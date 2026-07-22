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

export default function App() {
  const [users, setUsers] = useState([]);
  const [selectedPhone, setSelectedPhone] = useState(null);
  const [selectedUser, setSelectedUser] = useState(null);
  const [stats, setStats] = useState({});
  const [sending, setSending] = useState(false);
  const [typing, setTyping] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [unseenConsultPhones, setUnseenConsultPhones] = useState(new Set());
  const consultationCount = unseenConsultPhones.size;
  const typingTimerRef = useRef(null);
  const pendingTempIds = useRef(new Set());

  const [showBroadcast, setShowBroadcast] = useState(false);
  const [showAnalytics, setShowAnalytics] = useState(false);
  const [showConsultations, setShowConsultations] = useState(false);
  const [editingUser, setEditingUser] = useState(null);

  const {
    messages, setMessages, loading, unreadCounts, highlightedUsers,
    loadMessages, markAsRead, incrementUnread, appendMessage,
    updateMessageStatus, updateTempStatus, removeMessage, selectedPhoneRef,
  } = useMessages(selectedPhone);

  // ── Refresh analytics ─────────────────────────────────────────────────

  const refreshAnalytics = useCallback(async () => {
    try {
      const data = await api.getAnalytics();
      setStats(data);
    } catch {}
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
      setTyping(false);
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);

      if (data.direction === "bot" && data.source === "ai") {
        setTyping(true);
        typingTimerRef.current = setTimeout(() => setTyping(false), 1200);
      }

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
    if (selectedPhoneRef.current === data.phone)
      setSelectedUser((prev) => ({ ...prev, human_mode: data.human_mode }));
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
      setTyping(true);
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      typingTimerRef.current = setTimeout(() => setTyping(false), 3000);
    }
  }, [selectedPhoneRef]);

  const handleUserDeleted = useCallback((phone) => {
    setUsers((prev) => prev.filter((u) => u.phone !== phone));
    setUnseenConsultPhones((prev) => { const n = new Set(prev); n.delete(phone); return n; });
    const seen = getSeenConsults(); seen.delete(phone); saveSeenConsults(seen);
    if (selectedPhoneRef.current === phone) { setSelectedPhone(null); setSelectedUser(null); }
  }, [selectedPhoneRef]);

  const handleUserDeletedSocket = useCallback((data) => handleUserDeleted(data.phone), [handleUserDeleted]);

  const { connected } = useSocket({
    onNewUser: handleNewUser,
    onUserUpdate: handleUserUpdate,
    onNewMessage: handleNewMessage,
    onStatusUpdate: handleStatusUpdate,
    onModeChanged: handleModeChanged,
    onUserUpdated: handleUserUpdated,
    onUserTyping: handleUserTyping,
    onUserDeleted: handleUserDeletedSocket,
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
  }, [loadMessages, markAsRead]);

  // ── Send actions ──────────────────────────────────────────────────────

  const handleSend = useCallback(async (text) => {
    if (!selectedPhone || sending) return;
    setSending(true);
    const tempId = Date.now();
    const temp = {
      _id: tempId,
      message: text,
      direction: "bot",
      status: "sending",
      timestamp: new Date().toISOString(),
      message_type: "text",
      media_path: "",
      file_name: "",
    };
    pendingTempIds.current.add(tempId);
    appendMessage(temp);
    try {
      await api.sendMessage(selectedPhone, text);
      updateTempStatus(tempId, "sent");
    } catch {
      removeMessage(temp);
      alert("Failed to send message.");
    } finally {
      pendingTempIds.current.delete(tempId);
      setSending(false);
    }
  }, [selectedPhone, sending, appendMessage, removeMessage, updateTempStatus]);

  const handleSendFile = useCallback(async (file) => {
    if (!selectedPhone || sending) return;
    setSending(true);
    const tempId = Date.now();
    const temp = {
      _id: tempId,
      message: file.name,
      direction: "bot",
      status: "sending",
      timestamp: new Date().toISOString(),
      message_type: "file",
      file_name: file.name,
      media_path: "",
    };
    pendingTempIds.current.add(tempId);
    appendMessage(temp);
    try {
      await api.sendFile(selectedPhone, file);
      updateTempStatus(tempId, "sent");
    } catch {
      removeMessage(temp);
      alert("Failed to send file.");
    } finally {
      pendingTempIds.current.delete(tempId);
      setSending(false);
    }
  }, [selectedPhone, sending, appendMessage, removeMessage, updateTempStatus]);

  // ── Toggle / edit ─────────────────────────────────────────────────────

  const handleToggleMode = useCallback(async () => {
    if (!selectedPhone) return;
    try {
      const data = await api.toggleMode(selectedPhone);
      setSelectedUser((prev) => ({ ...prev, human_mode: data.human_mode }));
      setUsers((prev) => prev.map((u) =>
        u.phone === selectedPhone ? { ...u, human_mode: data.human_mode } : u
      ));
      await refreshAnalytics();
    } catch (e) { console.error("Toggle failed:", e); }
  }, [selectedPhone, refreshAnalytics]);

  const handleUserSaved = useCallback(({ tags, notes }) => {
    setSelectedUser((prev) => ({ ...prev, tags, notes }));
    setUsers((prev) => prev.map((u) =>
      u.phone === selectedPhone ? { ...u, tags, notes } : u
    ));
  }, [selectedPhone]);

  const handleMarkAllRead = useCallback(() => {
    users.forEach((u) => markAsRead(u.phone));
  }, [users, markAsRead]);

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>

      {loadError && (
        <div style={{ background: "#f44336", color: "#fff", padding: "8px 20px", fontSize: 13, textAlign: "center", flexShrink: 0 }}>
          Cannot connect to server. Make sure Flask is running on port 5000.
          <button onClick={() => window.location.reload()} style={{ marginLeft: 12, padding: "2px 10px", background: "#fff", color: "#f44336", border: "none", borderRadius: 4, cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
            Retry
          </button>
        </div>
      )}

      {/* Top bar */}
      <div style={barStyle}>
        <span style={{ fontSize: 16, fontWeight: 700, color: "#fff", letterSpacing: 0.3 }}>
          BizAdvise & LawAdvise
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button
            style={btnStyle("#fff", "#667eea")}
            onClick={async () => { await refreshAnalytics(); setShowAnalytics(true); }}
          >
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

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <Sidebar
          users={users}
          selectedPhone={selectedPhone}
          connected={connected}
          unreadCounts={unreadCounts}
          highlightedUsers={highlightedUsers}
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

      <div style={{ position: "fixed", bottom: 12, right: 12, background: connected ? "#4caf50" : "#f44336", color: "#fff", padding: "4px 10px", borderRadius: 20, fontSize: 11, display: "flex", alignItems: "center", gap: 5, boxShadow: "0 2px 6px rgba(0,0,0,0.2)", zIndex: 999 }}>
        <span style={{ width: 7, height: 7, background: "#fff", borderRadius: "50%", animation: "pulse 1.2s infinite", display: "inline-block" }} />
        {connected ? "Live" : "Reconnecting…"}
      </div>

      {showBroadcast && <BroadcastModal users={users} onClose={() => setShowBroadcast(false)} />}
      {showAnalytics && <AnalyticsModal stats={stats} onClose={() => setShowAnalytics(false)} />}
      {showConsultations && (
        <ConsultationsModal
          users={users}
          onClose={() => setShowConsultations(false)}
          onSelectUser={selectUser}
          onUserDeleted={handleUserDeleted}
        />
      )}
      {editingUser && (
        <EditUserModal
          user={editingUser}
          onClose={() => setEditingUser(null)}
          onSaved={handleUserSaved}
        />
      )}
    </div>
  );
}

const barStyle = {
  display: "flex",
  alignItems: "center",
  padding: "10px 20px",
  background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
  flexShrink: 0,
  boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
  gap: 12,
};

const btnStyle = (bg, color) => ({
  padding: "6px 14px", background: bg, color,
  border: "none", borderRadius: 20, cursor: "pointer",
  fontWeight: 600, fontSize: 12, whiteSpace: "nowrap",
});