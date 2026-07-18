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

export default function App() {
  const [users, setUsers] = useState([]);
  const [selectedPhone, setSelectedPhone] = useState(null);
  const [selectedUser, setSelectedUser] = useState(null);
  const [stats, setStats] = useState({});
  const [sending, setSending] = useState(false);
  const [typing, setTyping] = useState(false);
  const [loadError, setLoadError] = useState(false);

  // Consultation tracking
  const [unseenConsultPhones, setUnseenConsultPhones] = useState(new Set());
  const consultationCount = unseenConsultPhones.size;

  const typingTimerRef = useRef(null);

  const [showBroadcast, setShowBroadcast] = useState(false);
  const [showAnalytics, setShowAnalytics] = useState(false);
  const [showConsultations, setShowConsultations] = useState(false);
  const [editingUser, setEditingUser] = useState(null);

  const {
    messages,
    setMessages,
    loading,
    unreadCounts,
    highlightedUsers,
    loadMessages,
    markAsRead,
    incrementUnread,
    appendMessage,
    updateMessageStatus,
    updateTempStatus,
    removeMessage,
    selectedPhoneRef,
  } = useMessages(selectedPhone);

  // ── Socket handlers ──────────────────────────────────────────────────────

  const handleNewUser = useCallback((data) => {
    setUsers((prev) =>
      prev.find((u) => u.phone === data.phone) ? prev : [data, ...prev]
    );
    incrementUnread(data.phone);
  }, [incrementUnread]);

  const handleUserUpdate = useCallback((data) => {
    setUsers((prev) =>
      prev.map((u) => (u.phone === data.phone ? { ...u, ...data } : u))
    );
    if (selectedPhoneRef.current === data.phone) {
      setSelectedUser((prev) => ({ ...prev, ...data }));
    }
  }, [selectedPhoneRef]);

  const handleNewMessage = useCallback((data) => {
    setUsers((prev) =>
      prev.map((u) =>
        u.phone === data.phone
          ? {
              ...u,
              last: data.message?.substring(0, 50),
              total_messages: (u.total_messages || 0) + 1,
              last_seen: data.timestamp,
            }
          : u
      )
    );

    if (data.direction === "user") {
      incrementUnread(data.phone);

      // If message is a consultation request and chat is not currently open
      if (
        isConsultMessage(data.message) &&
        selectedPhoneRef.current !== data.phone
      ) {
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
          message_type: data.message_type,
          file_name: data.file_name,
        });
      }

      if (data.direction === "user") markAsRead(data.phone);
    }
  }, [selectedPhoneRef, incrementUnread, appendMessage, markAsRead]);

  const handleStatusUpdate = useCallback((data) => {
    updateMessageStatus(data.whatsapp_message_id, data.status);
  }, [updateMessageStatus]);

  const handleModeChanged = useCallback((data) => {
    setUsers((prev) =>
      prev.map((u) =>
        u.phone === data.phone ? { ...u, human_mode: data.human_mode } : u
      )
    );
    if (selectedPhoneRef.current === data.phone) {
      setSelectedUser((prev) => ({ ...prev, human_mode: data.human_mode }));
    }
  }, [selectedPhoneRef]);

  const handleUserUpdated = useCallback((data) => {
    setUsers((prev) =>
      prev.map((u) =>
        u.phone === data.phone
          ? { ...u, tags: data.tags, notes: data.notes }
          : u
      )
    );
    if (selectedPhoneRef.current === data.phone) {
      setSelectedUser((prev) => ({
        ...prev,
        tags: data.tags,
        notes: data.notes,
      }));
    }
  }, [selectedPhoneRef]);

  const handleUserTyping = useCallback((data) => {
    if (selectedPhoneRef.current === data.phone && data.typing) {
      setTyping(true);
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      typingTimerRef.current = setTimeout(() => setTyping(false), 3000);
    }
  }, [selectedPhoneRef]);

  const { connected } = useSocket({
    onNewUser: handleNewUser,
    onUserUpdate: handleUserUpdate,
    onNewMessage: handleNewMessage,
    onStatusUpdate: handleStatusUpdate,
    onModeChanged: handleModeChanged,
    onUserUpdated: handleUserUpdated,
    onUserTyping: handleUserTyping,
  });

  // ── Initial load ─────────────────────────────────────────────────────────

  useEffect(() => {
    const load = async () => {
      try {
        const [usersData, statsData, consults] = await Promise.all([
          api.getUsers(),
          api.getAnalytics(),
          api.getConsultations(),
        ]);
        setUsers(usersData);
        setStats(statsData);
        // On initial load all consultation requests are "unseen"
        setUnseenConsultPhones(new Set(consults.map((c) => c.phone)));
        setLoadError(false);
      } catch (e) {
        console.error("Initial load failed:", e);
        setLoadError(true);
      }
    };
    load();
  }, []);

  // Poll every 30s
  useEffect(() => {
    const fetchStats = async () => {
      try {
        const data = await api.getAnalytics();
        setStats(data);
      } catch {}
    };
    const id = setInterval(fetchStats, 30000);
    return () => clearInterval(id);
  }, []);

  // ── User selection ───────────────────────────────────────────────────────

  const selectUser = useCallback((user) => {
    setSelectedPhone(user.phone);
    setSelectedUser(user);
    loadMessages(user.phone);
    markAsRead(user.phone);
    setTyping(false);
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);

    // Mark consultation as seen when opening the chat
    setUnseenConsultPhones((prev) => {
      const next = new Set(prev);
      next.delete(user.phone);
      return next;
    });
  }, [loadMessages, markAsRead]);

  // ── Send actions ─────────────────────────────────────────────────────────

  const handleSend = useCallback(async (text) => {
    if (!selectedPhone || sending) return;
    setSending(true);

    const temp = {
      _id: Date.now(),
      message: text,
      direction: "bot",
      status: "sending",
      timestamp: new Date().toISOString(),
      message_type: "text",
    };
    appendMessage(temp);

    try {
      await api.sendMessage(selectedPhone, text);
      updateTempStatus(temp._id, "sent");
    } catch {
      removeMessage(temp);
      alert("Failed to send message.");
    } finally {
      setSending(false);
    }
  }, [selectedPhone, sending, appendMessage, removeMessage, updateTempStatus]);

  const handleSendFile = useCallback(async (file) => {
    if (!selectedPhone || sending) return;
    setSending(true);

    const temp = {
      _id: Date.now(),
      message: file.name,
      direction: "bot",
      status: "sending",
      timestamp: new Date().toISOString(),
      message_type: "file",
      file_name: file.name,
    };
    appendMessage(temp);

    try {
      await api.sendFile(selectedPhone, file);
      updateTempStatus(temp._id, "sent");
    } catch {
      removeMessage(temp);
      alert("Failed to send file.");
    } finally {
      setSending(false);
    }
  }, [selectedPhone, sending, appendMessage, removeMessage, updateTempStatus]);

  // ── Toggle / edit ────────────────────────────────────────────────────────

  const handleToggleMode = useCallback(async () => {
    if (!selectedPhone) return;
    try {
      const data = await api.toggleMode(selectedPhone);
      setSelectedUser((prev) => ({ ...prev, human_mode: data.human_mode }));
      setUsers((prev) =>
        prev.map((u) =>
          u.phone === selectedPhone
            ? { ...u, human_mode: data.human_mode }
            : u
        )
      );
    } catch (e) {
      console.error("Toggle failed:", e);
    }
  }, [selectedPhone]);

  const handleUserSaved = useCallback(({ tags, notes }) => {
    setSelectedUser((prev) => ({ ...prev, tags, notes }));
    setUsers((prev) =>
      prev.map((u) =>
        u.phone === selectedPhone ? { ...u, tags, notes } : u
      )
    );
  }, [selectedPhone]);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>

      {loadError && (
        <div style={{
          background: "#f44336", color: "#fff",
          padding: "8px 20px", fontSize: 13, textAlign: "center", flexShrink: 0,
        }}>
          Cannot connect to server. Make sure Flask is running on port 5000.
          <button
            onClick={() => window.location.reload()}
            style={{
              marginLeft: 12, padding: "2px 10px",
              background: "#fff", color: "#f44336",
              border: "none", borderRadius: 4, cursor: "pointer",
              fontSize: 12, fontWeight: 600,
            }}
          >
            Retry
          </button>
        </div>
      )}

      {/* Top bar */}
      <div style={barStyle}>
        <span>Users: {stats.total_users || 0}</span>
        <span>Messages: {stats.total_messages || 0}</span>
        <span>AI: {stats.ai_users || 0}</span>
        <span>Human: {stats.human_users || 0}</span>
        <span>Today: {stats.messages_today || 0}</span>
        <span>Avg response: {stats.avg_response_time || 0} min</span>
        <button style={btnStyle("#667eea")} onClick={() => setShowAnalytics(true)}>
          Analytics
        </button>
        <button
          style={{
            ...btnStyle("#e53935"),
            display: "flex", alignItems: "center", gap: 6,
          }}
          onClick={() => setShowConsultations(true)}
        >
          📋 Consultations
          {consultationCount > 0 && (
            <span style={{
              background: "#fff", color: "#e53935",
              borderRadius: "50%", width: 18, height: 18,
              fontSize: 10, fontWeight: 700,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              {consultationCount}
            </span>
          )}
        </button>
        <button style={btnStyle("#ff9800")} onClick={() => setShowBroadcast(true)}>
          Broadcast
        </button>
        <button style={btnStyle("#4caf50")} onClick={() => api.reloadKnowledge()}>
          Reload knowledge
        </button>
      </div>

      {/* Main layout */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <Sidebar
          users={users}
          selectedPhone={selectedPhone}
          connected={connected}
          unreadCounts={unreadCounts}
          highlightedUsers={highlightedUsers}
          onSelect={selectUser}
          onExportAll={() => api.exportCsv()}
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
      <div style={{
        position: "fixed", bottom: 12, right: 12,
        background: connected ? "#4caf50" : "#f44336",
        color: "#fff", padding: "4px 10px", borderRadius: 20,
        fontSize: 11, display: "flex", alignItems: "center", gap: 5,
        boxShadow: "0 2px 6px rgba(0,0,0,0.2)", zIndex: 999,
      }}>
        <span style={{
          width: 7, height: 7, background: "#fff",
          borderRadius: "50%", animation: "pulse 1.2s infinite",
          display: "inline-block",
        }} />
        {connected ? "Live" : "Reconnecting…"}
      </div>

      {/* Modals */}
      {showBroadcast && (
        <BroadcastModal users={users} onClose={() => setShowBroadcast(false)} />
      )}
      {showAnalytics && (
        <AnalyticsModal stats={stats} onClose={() => setShowAnalytics(false)} />
      )}
      {showConsultations && (
        <ConsultationsModal
          users={users}
          onClose={() => setShowConsultations(false)}
          onSelectUser={selectUser}
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
  display: "flex", gap: 18, padding: "10px 24px",
  background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
  color: "#fff", fontSize: 13, alignItems: "center",
  flexWrap: "wrap", flexShrink: 0,
  boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
};

const btnStyle = (bg) => ({
  padding: "5px 14px",
  background: bg === "#667eea" ? "#fff" : bg,
  color: bg === "#667eea" ? "#667eea" : "#fff",
  border: "none", borderRadius: 20, cursor: "pointer",
  fontWeight: 600, fontSize: 12,
});