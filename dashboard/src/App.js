import React, { useEffect, useState, useCallback, useRef } from "react";
import "./styles/global.css";

import { api, getToken, setUnauthorizedHandler, clearSession } from "./api/client";
import { useSocket } from "./hooks/useSocket";
import { useMessages } from "./hooks/useMessages";

import Sidebar from "./components/Sidebar";
import ChatArea from "./components/ChatArea";
import BroadcastModal from "./components/BroadcastModal";
import AnalyticsModal from "./components/AnalyticsModal";
import EditUserModal from "./components/EditUserModal";
import ConsultationsModal from "./components/ConsultationsModal";
import Login from "./components/Login";
import AccountModal from "./components/AccountModal";
import { playNotificationSound, playMessageSound, unlockAudioOnFirstGesture, requestNotificationPermission, trace } from "./utils/notificationSound";

const CONSULT_KEYWORDS = [
  "consult", "book", "appointment", "talk to", "speak to",
  "contact", "lawyer", "legal expert", "schedule", "call me",
  "reach out", "get in touch", "book consultation",
  "talk to a lawyer", "talk to expert", "book a consultation"
];

function isConsultMessage(message) {
  const lower = (message || "").toLowerCase();
  return CONSULT_KEYWORDS.some((kw) => lower.includes(kw));
}

function getSeenConsults() {
  try { return new Set(JSON.parse(localStorage.getItem("seen_consults") || "[]")); }
  catch { return new Set(); }
}

function saveSeenConsults(set) {
  try { localStorage.setItem("seen_consults", JSON.stringify([...set])); } catch {}
}

function markConsultSeen(phone) {
  const seen = getSeenConsults();
  seen.add(phone);
  saveSeenConsults(seen);
}

function showBrowserNotification(title, body, requireInteraction = false) {
  if ("Notification" in window && Notification.permission === "granted") {
    const n = new Notification(title, {
      body,
      icon: "/favicon.ico",
      badge: "/favicon.ico",
      requireInteraction,
    });
    n.onclick = () => { window.focus(); n.close(); };
  }
}

function Dashboard({ authUser, onLogout }) {
  const [users, setUsers] = useState([]);
  const [selectedPhone, setSelectedPhone] = useState(null);
  const [selectedUser, setSelectedUser] = useState(null);
  const [stats, setStats] = useState({});
  const [sending, setSending] = useState(false);
  const [typing, setTyping] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [waTokenError, setWaTokenError] = useState(null);
  const [unseenConsultPhones, setUnseenConsultPhones] = useState(new Set());
  const [bookedConsultPhones, setBookedConsultPhones] = useState(new Set());
  const [consultToast, setConsultToast] = useState(null);
  const consultationCount = unseenConsultPhones.size;
  const typingTimerRef = useRef(null);
  const toastTimerRef = useRef(null);
  const pendingTempIds = useRef(new Set());
  const usersRef = useRef([]);

  useEffect(() => { usersRef.current = users; }, [users]);

  useEffect(() => {
    requestNotificationPermission();
    unlockAudioOnFirstGesture();
  }, []);

  const [showBroadcast, setShowBroadcast] = useState(false);
  const [showAnalytics, setShowAnalytics] = useState(false);
  const [showConsultations, setShowConsultations] = useState(false);
  const [showAccount, setShowAccount] = useState(false);
  const [latestBooking, setLatestBooking] = useState(null);
  const [editingUser, setEditingUser] = useState(null);

  const {
    messages, setMessages, loading, unreadCounts, highlightedUsers,
    loadMessages, markAsRead, seedUnreadCounts, incrementUnread, appendMessage,
    updateMessageStatus, updateTempStatus, removeMessage, selectedPhoneRef,
  } = useMessages(selectedPhone);

  const refreshAnalytics = useCallback(async () => {
    try { const data = await api.getAnalytics(); setStats(data); } catch {}
  }, []);

  // ── Socket handlers ───────────────────────────────────────────────────

  const handleNewUser = useCallback((data) => {
    setUsers((prev) => prev.find((u) => u.phone === data.phone) ? prev : [data, ...prev]);
    incrementUnread(data.phone);
  }, [incrementUnread]);

  const handleUserUpdate = useCallback((data) => {
    setUsers((prev) => prev.map((u) => u.phone === data.phone ? { ...u, ...data } : u));
    if (selectedPhoneRef.current === data.phone)
      setSelectedUser((prev) => ({ ...prev, ...data }));
    // mark_read() on the backend broadcasts { phone, unread_count: 0 }
    // whenever ANY dashboard tab/instance reads this chat — apply that
    // here so every other open tab clears the badge too, instead of
    // only the tab that actually opened the chat.
    if (data.unread_count === 0) markAsRead(data.phone);
  }, [selectedPhoneRef, markAsRead]);

  const handleNewMessage = useCallback((data) => {
    setUsers((prev) => prev.map((u) =>
      u.phone === data.phone
        ? { ...u, last: data.message?.substring(0, 50), total_messages: (u.total_messages || 0) + 1, last_seen: data.timestamp }
        : u
    ));

    if (data.direction === "user") {
      playMessageSound();
      incrementUnread(data.phone);

      if (document.hidden || selectedPhoneRef.current !== data.phone) {
        const sender = usersRef.current.find((u) => u.phone === data.phone);
        const senderName = sender?.name || data.phone;
        const preview = data.message || (data.message_type && data.message_type !== "text" ? `[${data.message_type}]` : "New message");
        showBrowserNotification(`💬 ${senderName}`, preview);
      }

      if (isConsultMessage(data.message) && selectedPhoneRef.current !== data.phone) {
        const seen = getSeenConsults();
        seen.delete(data.phone);
        saveSeenConsults(seen);
        setUnseenConsultPhones((prev) => new Set(prev).add(data.phone));
      }
    }

    if (selectedPhoneRef.current === data.phone) {
      if (data.direction === "user" || data.source === "ai") {
        appendMessage({
          message: data.message,
          direction: data.direction,
          status: data.status,
          timestamp: data.timestamp,
          message_type: data.message_type || "text",
          file_name: data.file_name || "",
          media_path: data.media_path || "",
          whatsapp_message_id: data.whatsapp_message_id || "",
        });
      }

      if (data.direction === "bot") {
        setTyping(false);
        if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      }

      if (data.direction === "bot" && data.source !== "ai" && data.whatsapp_message_id) {
        updateMessageStatus(data.whatsapp_message_id, data.status);
      }

      if (data.direction === "user") markAsRead(data.phone);
    }
  }, [selectedPhoneRef, incrementUnread, appendMessage, markAsRead, updateMessageStatus]);

  const handleStatusUpdate = useCallback((data) => {
    updateMessageStatus(data.whatsapp_message_id, data.status);
  }, [updateMessageStatus]);

  const handleModeChanged = useCallback((data) => {
    setUsers((prev) => prev.map((u) =>
      u.phone === data.phone ? { ...u, human_mode: data.human_mode } : u
    ));
    if (selectedPhoneRef.current === data.phone) {
      setSelectedUser((prev) => ({ ...prev, human_mode: data.human_mode }));
      if (data.human_mode) {
        setTyping(false);
        if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      }
    }
    refreshAnalytics();
  }, [selectedPhoneRef, refreshAnalytics]);

  const handleUserUpdated = useCallback((data) => {
    setUsers((prev) => prev.map((u) =>
      u.phone === data.phone ? { ...u, tags: data.tags, notes: data.notes } : u
    ));
    if (selectedPhoneRef.current === data.phone)
      setSelectedUser((prev) => ({ ...prev, tags: data.tags, notes: data.notes }));
  }, [selectedPhoneRef]);

  const handleUserTyping = useCallback((data) => {
    if (selectedPhoneRef.current === data.phone && data.typing) {
      const currentUser = usersRef.current.find((u) => u.phone === data.phone);
      const isAiMode = currentUser ? !currentUser.human_mode : true;
      if (isAiMode) {
        setTyping(true);
        if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
        typingTimerRef.current = setTimeout(() => setTyping(false), 8000);
      }
    }
  }, [selectedPhoneRef]);

  const handleUserDeleted = useCallback((phone) => {
    setUsers((prev) => prev.filter((u) => u.phone !== phone));
    setUnseenConsultPhones((prev) => { const n = new Set(prev); n.delete(phone); return n; });
    setBookedConsultPhones((prev) => { const n = new Set(prev); n.delete(phone); return n; });
    const seen = getSeenConsults(); seen.delete(phone); saveSeenConsults(seen);
    if (selectedPhoneRef.current === phone) { setSelectedPhone(null); setSelectedUser(null); }
  }, [selectedPhoneRef]);

  const handleUserDeletedSocket = useCallback((data) => handleUserDeleted(data.phone), [handleUserDeleted]);

  const handleWaTokenError = useCallback((data) => {
    setWaTokenError(data.message);
  }, []);

  const handleConsultationBooked = useCallback((data) => {
    trace("[TRACE 2] handleConsultationBooked received:", data);
    const { phone, name, mobile, best_time } = data;
    const isViewingThisChat = selectedPhoneRef.current === phone;

    playNotificationSound();

    showBrowserNotification(
      "📋 New Consultation Booked!",
      `${name || phone} — ${mobile} — Best time: ${best_time}`,
      true
    );

    if (isViewingThisChat) {
      markConsultSeen(phone);
    } else {
      setBookedConsultPhones((prev) => new Set(prev).add(phone));
      const seen = getSeenConsults();
      seen.delete(phone);
      saveSeenConsults(seen);
      setUnseenConsultPhones((prev) => new Set(prev).add(phone));
    }

    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setConsultToast({ phone, name, mobile, best_time });
    toastTimerRef.current = setTimeout(() => setConsultToast(null), 8000);

    setLatestBooking({ phone, name, mobile, best_time, at: Date.now() });
  }, [selectedPhoneRef]);

  const { connected } = useSocket({
    onNewUser: handleNewUser,
    onUserUpdate: handleUserUpdate,
    onNewMessage: handleNewMessage,
    onStatusUpdate: handleStatusUpdate,
    onModeChanged: handleModeChanged,
    onUserUpdated: handleUserUpdated,
    onUserTyping: handleUserTyping,
    onUserDeleted: handleUserDeletedSocket,
    onWaTokenError: handleWaTokenError,
    onConsultationBooked: handleConsultationBooked,
  });

  // ── Initial load ──────────────────────────────────────────────────────

  useEffect(() => {
    const load = async () => {
      try {
        const [usersData, statsData, consults] = await Promise.all([
          api.getUsers(), api.getAnalytics(), api.getConsultations(),
        ]);
        setUsers(usersData);
        seedUnreadCounts(usersData);
        setStats(statsData);
        const seen = getSeenConsults();
        setUnseenConsultPhones(new Set(consults.map((c) => c.phone).filter((p) => !seen.has(p))));
        setLoadError(false);
      } catch (e) { console.error("Initial load failed:", e); setLoadError(true); }
    };
    load();
  }, []);

  useEffect(() => {
    const id = setInterval(refreshAnalytics, 30000);
    return () => clearInterval(id);
  }, [refreshAnalytics]);

  // ── User selection ────────────────────────────────────────────────────

  const selectUser = useCallback((user) => {
    setSelectedPhone(user.phone);
    setSelectedUser(user);
    loadMessages(user.phone);
    markAsRead(user.phone);
    // Persist the read state server-side so it survives logging out/back
    // in and stays correct if the dashboard is open elsewhere too.
    api.markRead(user.phone).catch((e) => console.error("markRead:", e));
    setTyping(false);
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    markConsultSeen(user.phone);
    setUnseenConsultPhones((prev) => { const n = new Set(prev); n.delete(user.phone); return n; });
    setBookedConsultPhones((prev) => { const n = new Set(prev); n.delete(user.phone); return n; });
  }, [loadMessages, markAsRead]);

  // ── Send actions ──────────────────────────────────────────────────────

  const handleSend = useCallback(async (text) => {
    if (!selectedPhone || sending) return;
    setSending(true);
    const tempId = Date.now();
    const temp = { _id: tempId, message: text, direction: "bot", status: "sending", timestamp: new Date().toISOString(), message_type: "text", media_path: "", file_name: "" };
    pendingTempIds.current.add(tempId);
    appendMessage(temp);
    try {
      const result = await api.sendMessage(selectedPhone, text);
      updateTempStatus(tempId, "sent", { whatsapp_message_id: result?.message_id || "" });
    }
    catch { removeMessage(temp); alert("Failed to send message."); }
    finally { pendingTempIds.current.delete(tempId); setSending(false); }
  }, [selectedPhone, sending, appendMessage, removeMessage, updateTempStatus]);

  const handleSendFile = useCallback(async (file) => {
    if (!selectedPhone || sending) return;
    setSending(true);
    const tempId = Date.now();
    const temp = { _id: tempId, message: file.name, direction: "bot", status: "sending", timestamp: new Date().toISOString(), message_type: "file", file_name: file.name, media_path: "" };
    pendingTempIds.current.add(tempId);
    appendMessage(temp);
    try {
      const result = await api.sendFile(selectedPhone, file);
      updateTempStatus(tempId, "sent", { whatsapp_message_id: result?.message_id || "" });
    }
    catch { removeMessage(temp); alert("Failed to send file."); }
    finally { pendingTempIds.current.delete(tempId); setSending(false); }
  }, [selectedPhone, sending, appendMessage, removeMessage, updateTempStatus]);

  // ── Toggle / edit ─────────────────────────────────────────────────────

  const handleToggleMode = useCallback(async () => {
    if (!selectedPhone) return;
    try {
      const data = await api.toggleMode(selectedPhone);
      setSelectedUser((prev) => ({ ...prev, human_mode: data.human_mode }));
      setUsers((prev) => prev.map((u) => u.phone === selectedPhone ? { ...u, human_mode: data.human_mode } : u));
      if (data.human_mode) { setTyping(false); if (typingTimerRef.current) clearTimeout(typingTimerRef.current); }
      await refreshAnalytics();
    } catch (e) { console.error("Toggle failed:", e); }
  }, [selectedPhone, refreshAnalytics]);

  const handleUserSaved = useCallback(({ tags, notes }) => {
    setSelectedUser((prev) => ({ ...prev, tags, notes }));
    setUsers((prev) => prev.map((u) => u.phone === selectedPhone ? { ...u, tags, notes } : u));
  }, [selectedPhone]);

  const handleMarkAllRead = useCallback(() => {
    users.forEach((u) => {
      markAsRead(u.phone);
      api.markRead(u.phone).catch((e) => console.error("markRead:", e));
    });
  }, [users, markAsRead]);

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>

      {/* Server error banner */}
      {loadError && (
        <div style={{ background: "#f44336", color: "#fff", padding: "8px 20px", fontSize: 13, textAlign: "center", flexShrink: 0 }}>
          Cannot connect to server. Make sure Flask is running on port 5000.
          <button onClick={() => window.location.reload()} style={{ marginLeft: 12, padding: "2px 10px", background: "#fff", color: "#f44336", border: "none", borderRadius: 4, cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
            Retry
          </button>
        </div>
      )}

      {/* WhatsApp token error banner */}
      {waTokenError && (
        <div style={{ background: "#ff6f00", color: "#fff", padding: "10px 20px", fontSize: 13, display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0, gap: 12 }}>
          <span>⚠️ {waTokenError}</span>
          <button onClick={() => setWaTokenError(null)} style={{ background: "rgba(255,255,255,0.25)", border: "none", color: "#fff", borderRadius: 6, padding: "3px 10px", cursor: "pointer", fontSize: 12 }}>
            Dismiss
          </button>
        </div>
      )}

      {/* Top bar */}
      <div style={barStyle} className="topBar">
        <span className="brandTitleShimmer" style={{ fontSize: 16, fontWeight: 700, letterSpacing: 0.3 }}>
          BizAdvise & LawAdvise
        </span>
        <div className="topBarActions" style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button className="topBarBtn" style={btnStyle("rgba(255, 255, 255, 0.07)", "#f8fafc", "1px solid rgba(255, 255, 255, 0.12)")} onClick={async () => { await refreshAnalytics(); setShowAnalytics(true); }}>
            📊 <span className="topBarBtnLabel">Analytics</span>
          </button>
          <button
            className="topBarBtn"
            style={{ ...btnStyle("rgba(225, 29, 72, 0.18)", "#fda4af", "1px solid rgba(225, 29, 72, 0.4)"), display: "flex", alignItems: "center", gap: 6 }}
            onClick={() => setShowConsultations(true)}
          >
            📋 <span className="topBarBtnLabel">Consultations</span>
            {consultationCount > 0 && (
              <span style={{ background: "var(--color-red)", color: "#fff", borderRadius: "50%", width: 18, height: 18, fontSize: 10, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 0 10px rgba(225, 29, 72, 0.6)" }}>
                {consultationCount}
              </span>
            )}
          </button>
          <button className="topBarBtn" style={btnStyle("rgba(229, 169, 80, 0.15)", "#f6c87a", "1px solid rgba(229, 169, 80, 0.45)")} onClick={() => setShowBroadcast(true)}>
            📢 <span className="topBarBtnLabel">Broadcast</span>
          </button>
          <button className="topBarBtn" style={btnStyle("rgba(22, 47, 86, 0.55)", "#93c5fd", "1px solid rgba(59, 130, 246, 0.3)")} onClick={() => api.reloadKnowledge()}>
            🔄 <span className="topBarBtnLabel">Reload KB</span>
          </button>
          <button className="topBarBtn" style={btnStyle("rgba(255, 255, 255, 0.07)", "#f8fafc", "1px solid rgba(229, 169, 80, 0.3)")} onClick={() => setShowAccount(true)}>
            👤 <span className="topBarBtnLabel">{authUser?.display_name || authUser?.username}</span>
          </button>
          <button className="topBarBtn" style={btnStyle("rgba(255, 255, 255, 0.04)", "#94a3b8", "1px solid rgba(255, 255, 255, 0.08)")} onClick={onLogout}>
            <span className="topBarBtnLabel">Log out</span>
          </button>
        </div>
      </div>

      {/* Main layout — on mobile widths, only one of Sidebar/ChatArea is visible
          at a time (WhatsApp-style), controlled by the .mobileChatOpen class. */}
      <div className={`mainLayout${selectedPhone ? " mobileChatOpen" : ""}`} style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <div className="sidebarPane">
          <Sidebar
            users={users}
            selectedPhone={selectedPhone}
            connected={connected}
            unreadCounts={unreadCounts}
            highlightedUsers={highlightedUsers}
            bookedConsultPhones={bookedConsultPhones}
            onSelect={selectUser}
            onExportAll={() => api.exportCsv()}
            onUserDeleted={handleUserDeleted}
            onMarkAllRead={handleMarkAllRead}
          />
        </div>
        <div className="chatPane">
          <ChatArea
            user={selectedUser}
            messages={messages}
            loading={loading}
            typing={typing}
            sending={sending}
            onSend={handleSend}
            onSendFile={handleSendFile}
            onToggleMode={handleToggleMode}
            onEdit={() => setEditingUser(selectedUser)}
            onExport={() => api.exportCsv(selectedPhone)}
            onBack={() => { setSelectedPhone(null); setSelectedUser(null); }}
          />
        </div>
      </div>

      {/* Connection status indicator */}
      <div style={{
        position: "fixed", bottom: 12, right: 12,
        background: "rgba(10, 16, 28, 0.88)",
        backdropFilter: "blur(12px)",
        border: connected ? "1px solid rgba(16, 185, 129, 0.45)" : "1px solid rgba(239, 68, 68, 0.45)",
        color: connected ? "#6ee7b7" : "#fca5a5",
        padding: "5px 12px", borderRadius: 20, fontSize: 11, fontWeight: 600,
        display: "flex", alignItems: "center", gap: 8,
        boxShadow: connected ? "0 4px 16px rgba(0,0,0,0.5), 0 0 14px rgba(16, 185, 129, 0.25)" : "0 4px 16px rgba(0,0,0,0.5), 0 0 14px rgba(239, 68, 68, 0.25)",
        zIndex: 999
      }}>
        <span style={{ position: "relative", display: "inline-flex", width: 8, height: 8 }}>
          <span style={{
            position: "absolute", inset: 0, borderRadius: "50%",
            background: connected ? "#10b981" : "#ef4444",
            animation: "radarWave 2s cubic-bezier(0, 0, 0.2, 1) infinite"
          }} />
          <span style={{
            position: "relative", width: 8, height: 8, borderRadius: "50%",
            background: connected ? "#10b981" : "#ef4444",
            boxShadow: connected ? "0 0 8px #10b981" : "0 0 8px #ef4444"
          }} />
        </span>
        {connected ? "Live System" : "Reconnecting…"}
      </div>

      {/* ── Consultation booked toast ── */}
      {consultToast && (
        <div style={{
          position: "fixed", bottom: 60, right: 16,
          background: "rgba(13, 20, 36, 0.92)",
          backdropFilter: "blur(16px)",
          color: "#f8fafc",
          border: "1px solid rgba(229, 169, 80, 0.4)",
          borderRadius: 14, padding: "16px 20px",
          boxShadow: "0 12px 40px rgba(0,0,0,0.65), 0 0 24px rgba(229, 169, 80, 0.2)",
          zIndex: 1000, maxWidth: 330,
          animation: "slideInRight 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
          display: "flex", flexDirection: "column", gap: 8,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: "var(--color-gold-light)" }}>📋 Consultation Booked!</span>
            <button
              onClick={() => { setConsultToast(null); clearTimeout(toastTimerRef.current); }}
              style={{ background: "none", border: "none", color: "rgba(255,255,255,0.6)", cursor: "pointer", fontSize: 16, lineHeight: 1, padding: 0, flexShrink: 0 }}
            >×</button>
          </div>
          <div style={{ fontSize: 12, color: "#cbd5e1", lineHeight: 1.5 }}>
            <div style={{ fontWeight: 600, color: "#fff" }}>{consultToast.name || consultToast.phone}</div>
            <div>📞 {consultToast.mobile}</div>
            <div>🕐 Best time: {consultToast.best_time}</div>
          </div>
          <button
            onClick={() => {
              const user = users.find((u) => u.phone === consultToast.phone);
              if (user) selectUser(user);
              setConsultToast(null);
            }}
            style={{
              marginTop: 4, padding: "7px 14px",
              background: "linear-gradient(135deg, #e5a950 0%, #d97706 100%)",
              color: "#070e1b", border: "none", borderRadius: 8,
              cursor: "pointer", fontSize: 12, fontWeight: 700,
              alignSelf: "flex-start",
              boxShadow: "0 2px 10px rgba(229, 169, 80, 0.35)",
            }}
          >
            Open Chat →
          </button>
        </div>
      )}

      {showBroadcast && <BroadcastModal users={users} onClose={() => setShowBroadcast(false)} />}
      {showAnalytics && <AnalyticsModal stats={stats} onClose={() => setShowAnalytics(false)} />}
      {showConsultations && <ConsultationsModal users={users} onClose={() => setShowConsultations(false)} onSelectUser={selectUser} onUserDeleted={handleUserDeleted} latestBooking={latestBooking} currentUser={authUser} />}
      {editingUser && <EditUserModal user={editingUser} onClose={() => setEditingUser(null)} onSaved={handleUserSaved} />}
      {showAccount && (
        <AccountModal
          user={authUser}
          onClose={() => setShowAccount(false)}
          onLoggedOut={onLogout}
        />
      )}
    </div>
  );
}

const barStyle = {
  display: "flex", alignItems: "center", padding: "10px 20px",
  background: "linear-gradient(180deg, rgba(13, 22, 38, 0.96) 0%, rgba(7, 13, 23, 0.98) 100%)",
  backdropFilter: "blur(16px)",
  borderBottom: "1px solid rgba(229, 169, 80, 0.28)",
  boxShadow: "0 4px 20px rgba(0, 0, 0, 0.5), 0 1px 0 rgba(229, 169, 80, 0.25)",
  flexShrink: 0, gap: 12, position: "relative", zIndex: 10,
};

const btnStyle = (bg, color, border = "1px solid rgba(255, 255, 255, 0.1)") => ({
  padding: "6px 14px", background: bg, color,
  border: border, borderRadius: 20, cursor: "pointer",
  fontWeight: 600, fontSize: 12, whiteSpace: "nowrap",
  transition: "all 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
  boxShadow: "0 2px 8px rgba(0, 0, 0, 0.25)",
  display: "inline-flex", alignItems: "center", gap: 6,
});

// ── Top-level App Component ──────────────────────────────────────────────

export default function App() {
  const [authUser, setAuthUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);

  const logout = useCallback(() => {
    clearSession();
    setAuthUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setAuthUser(null));
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    const token = getToken();
    if (!token) { setCheckingSession(false); return; }
    api.me()
      .then((data) => setAuthUser(data.user))
      .catch(() => clearSession())
      .finally(() => setCheckingSession(false));
  }, []);

  if (checkingSession) {
    return (
      <div style={{ height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: "#888", fontSize: 14 }}>
        Loading…
      </div>
    );
  }

  if (!authUser) {
    return <Login onAuthenticated={setAuthUser} />;
  }

  return <Dashboard authUser={authUser} onLogout={logout} />;
}