import React, { useEffect, useState, useCallback, useRef } from "react";
import "./styles/global.css";

import { api } from "./api/client";
import { useSocket } from "./hooks/useSocket";
import { useMessages } from "./hooks/useMessages";

import Sidebar from "./components/Sidebar";
import ChatArea from "./components/ChatArea";
import BroadcastModal from "./components/BroadcastModal";
import AnalyticsModal from "./components/AnalyticsModal";
import EditUserModal from "./components/EditUserModal";
import ConsultationsModal from "./components/ConsultationsModal";

// Set to true (or window.DEBUG_CONSULT = true in the browser console) to
// see the consultation-booked trace logs. Off by default in production.
const DEBUG_CONSULT = false;
const trace = (...args) => {
  if (DEBUG_CONSULT || window.DEBUG_CONSULT) console.log(...args);
};

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

// ── Shared AudioContext ──────────────────────────────────────────────────
// Browsers (Chrome/Safari) start every AudioContext in a "suspended" state
// until the page has received a real user gesture (click/keydown/tap).
// Creating a brand-new context on every notification — with no gesture
// behind it — means the tones schedule but never actually play, and it
// also leaks contexts (browsers cap you at ~4-6 concurrent ones).
// Fix: create ONE context up front, and unlock/resume it on the user's
// first interaction with the page.
let _audioCtx = null;
function getAudioContext() {
  if (!_audioCtx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    _audioCtx = new AC();
  }
  return _audioCtx;
}

function unlockAudioOnFirstGesture() {
  const unlock = () => {
    const ctx = getAudioContext();
    if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
    window.removeEventListener("click", unlock);
    window.removeEventListener("keydown", unlock);
  };
  window.addEventListener("click", unlock);
  window.addEventListener("keydown", unlock);
}

// Play a notification sound using Web Audio API — no file needed
function playNotificationSound() {
  try {
    const ctx = getAudioContext();
    trace("[TRACE 4] AudioContext state:", ctx?.state);
    if (!ctx) { trace("[TRACE 4] No AudioContext available (unsupported browser)"); return; }

    const schedule = () => {
      const playTone = (freq, start, duration, gain = 0.3) => {
        const osc = ctx.createOscillator();
        const gainNode = ctx.createGain();
        osc.connect(gainNode);
        gainNode.connect(ctx.destination);
        osc.frequency.value = freq;
        osc.type = "sine";
        gainNode.gain.setValueAtTime(0, ctx.currentTime + start);
        gainNode.gain.linearRampToValueAtTime(gain, ctx.currentTime + start + 0.02);
        gainNode.gain.linearRampToValueAtTime(0, ctx.currentTime + start + duration);
        osc.start(ctx.currentTime + start);
        osc.stop(ctx.currentTime + start + duration + 0.05);
      };
      // Three ascending tones — pleasant alert
      playTone(523, 0,    0.15);  // C5
      playTone(659, 0.18, 0.15);  // E5
      playTone(784, 0.36, 0.25);  // G5
    };

    if (ctx.state === "suspended") {
      // Still locked (no gesture yet this session) — try to resume and
      // play once it succeeds; if the browser refuses, fail silently
      // instead of throwing, so the browser notification/toast still fire.
      ctx.resume().then(schedule).catch(() => {});
    } else {
      schedule();
    }
  } catch (e) {
    console.log("Audio not available:", e);
  }
}

// Request browser notification permission once
function requestNotificationPermission() {
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
}

function showBrowserNotification(title, body) {
  if ("Notification" in window && Notification.permission === "granted") {
    const n = new Notification(title, {
      body,
      icon: "/favicon.ico",
      badge: "/favicon.ico",
      requireInteraction: true,  // stays until dismissed
    });
    n.onclick = () => { window.focus(); n.close(); };
  }
}

export default function App() {
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

  // Request browser notification permission on first load, and unlock
  // the shared AudioContext as soon as the user interacts with the page
  // (required by browser autoplay policy for the notification sound).
  useEffect(() => {
    requestNotificationPermission();
    unlockAudioOnFirstGesture();
  }, []);

  const [showBroadcast, setShowBroadcast] = useState(false);
  const [showAnalytics, setShowAnalytics] = useState(false);
  const [showConsultations, setShowConsultations] = useState(false);
  const [editingUser, setEditingUser] = useState(null);

  const {
    messages, setMessages, loading, unreadCounts, highlightedUsers,
    loadMessages, markAsRead, incrementUnread, appendMessage,
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
  }, [selectedPhoneRef]);

  const handleNewMessage = useCallback((data) => {
    setUsers((prev) => prev.map((u) =>
      u.phone === data.phone
        ? { ...u, last: data.message?.substring(0, 50), total_messages: (u.total_messages || 0) + 1, last_seen: data.timestamp }
        : u
    ));

    if (data.direction === "user") {
      incrementUnread(data.phone);
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

      if (data.direction === "bot" && data.source === "ai") {
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
        typingTimerRef.current = setTimeout(() => setTyping(false), 15000);
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

    // 1. Play sound
    trace("[TRACE 3] calling playNotificationSound()");
    playNotificationSound();

    // 2. Browser notification
    showBrowserNotification(
      "📋 New Consultation Booked!",
      `${name || phone} — ${mobile} — Best time: ${best_time}`
    );

    // 3. Highlight user red in sidebar
    setBookedConsultPhones((prev) => new Set(prev).add(phone));

    // 4. Mark as unseen consultation
    const seen = getSeenConsults();
    seen.delete(phone);
    saveSeenConsults(seen);
    setUnseenConsultPhones((prev) => new Set(prev).add(phone));

    // 5. Show in-app toast
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setConsultToast({ phone, name, mobile, best_time });
    toastTimerRef.current = setTimeout(() => setConsultToast(null), 8000);
  }, []);

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
    setTyping(false);
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    markConsultSeen(user.phone);
    setUnseenConsultPhones((prev) => { const n = new Set(prev); n.delete(user.phone); return n; });
    // Clear red highlight when chat is opened
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
    try { await api.sendMessage(selectedPhone, text); updateTempStatus(tempId, "sent"); }
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
    try { await api.sendFile(selectedPhone, file); updateTempStatus(tempId, "sent"); }
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
    users.forEach((u) => markAsRead(u.phone));
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
      <div style={barStyle}>
        <span style={{ fontSize: 16, fontWeight: 700, color: "#fff", letterSpacing: 0.3 }}>
          BizAdvise & LawAdvise
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button style={btnStyle("#fff", "#667eea")} onClick={async () => { await refreshAnalytics(); setShowAnalytics(true); }}>
            📊 Analytics
          </button>
          <button
            style={{ ...btnStyle("#e53935", "#fff"), display: "flex", alignItems: "center", gap: 6 }}
            onClick={() => setShowConsultations(true)}
          >
            📋 Consultations
            {consultationCount > 0 && (
              <span style={{ background: "#fff", color: "#e53935", borderRadius: "50%", width: 18, height: 18, fontSize: 10, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>
                {consultationCount}
              </span>
            )}
          </button>
          <button style={btnStyle("#ff9800", "#fff")} onClick={() => setShowBroadcast(true)}>
            📢 Broadcast
          </button>
          <button style={btnStyle("#4caf50", "#fff")} onClick={() => api.reloadKnowledge()}>
            🔄 Reload KB
          </button>
        </div>
      </div>

      {/* Main layout */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
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
        />
      </div>

      {/* Connection dot */}
      <div style={{ position: "fixed", bottom: 12, right: 12, background: connected ? "#4caf50" : "#f44336", color: "#fff", padding: "4px 10px", borderRadius: 20, fontSize: 11, display: "flex", alignItems: "center", gap: 5, boxShadow: "0 2px 6px rgba(0,0,0,0.2)", zIndex: 999 }}>
        <span style={{ width: 7, height: 7, background: "#fff", borderRadius: "50%", animation: "pulse 1.2s infinite", display: "inline-block" }} />
        {connected ? "Live" : "Reconnecting…"}
      </div>

      {/* ── Consultation booked toast ── */}
      {consultToast && (
        <div style={{
          position: "fixed", bottom: 60, right: 16,
          background: "#1a237e", color: "#fff",
          borderRadius: 14, padding: "14px 18px",
          boxShadow: "0 8px 32px rgba(0,0,0,0.28)",
          zIndex: 1000, maxWidth: 320,
          animation: "slideInRight 0.3s ease-out",
          display: "flex", flexDirection: "column", gap: 6,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>📋 Consultation Booked!</span>
            <button
              onClick={() => { setConsultToast(null); clearTimeout(toastTimerRef.current); }}
              style={{ background: "none", border: "none", color: "rgba(255,255,255,0.7)", cursor: "pointer", fontSize: 16, lineHeight: 1, padding: 0, flexShrink: 0 }}
            >×</button>
          </div>
          <div style={{ fontSize: 12, color: "rgba(255,255,255,0.85)", lineHeight: 1.5 }}>
            <div><strong>{consultToast.name || consultToast.phone}</strong></div>
            <div>📞 {consultToast.mobile}</div>
            <div>🕐 Best time: {consultToast.best_time}</div>
          </div>
          <button
            onClick={() => {
              const user = users.find((u) => u.phone === consultToast.phone);
              if (user) selectUser(user);
              setConsultToast(null);
            }}
            style={{ marginTop: 4, padding: "6px 12px", background: "#fff", color: "#1a237e", border: "none", borderRadius: 8, cursor: "pointer", fontSize: 12, fontWeight: 600, alignSelf: "flex-start" }}
          >
            Open Chat →
          </button>
        </div>
      )}

      {showBroadcast && <BroadcastModal users={users} onClose={() => setShowBroadcast(false)} />}
      {showAnalytics && <AnalyticsModal stats={stats} onClose={() => setShowAnalytics(false)} />}
      {showConsultations && <ConsultationsModal users={users} onClose={() => setShowConsultations(false)} onSelectUser={selectUser} onUserDeleted={handleUserDeleted} />}
      {editingUser && <EditUserModal user={editingUser} onClose={() => setEditingUser(null)} onSaved={handleUserSaved} />}
    </div>
  );
}

const barStyle = {
  display: "flex", alignItems: "center", padding: "10px 20px",
  background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
  flexShrink: 0, boxShadow: "0 2px 8px rgba(0,0,0,0.15)", gap: 12,
};
const btnStyle = (bg, color) => ({
  padding: "6px 14px", background: bg, color,
  border: "none", borderRadius: 20, cursor: "pointer",
  fontWeight: 600, fontSize: 12, whiteSpace: "nowrap",
});