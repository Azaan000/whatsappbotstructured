import React, { useEffect, useState, useCallback } from "react";
import "./styles/global.css";

import { api } from "./api/client";
import { useSocket } from "./hooks/useSocket";
import { useMessages } from "./hooks/useMessages";

import Sidebar from "./components/Sidebar";
import ChatArea from "./components/ChatArea";
import BroadcastModal from "./components/BroadcastModal";
import AnalyticsModal from "./components/AnalyticsModal";
import EditUserModal from "./components/EditUserModal";

export default function App() {
  const [users, setUsers] = useState([]);
  const [selectedPhone, setSelectedPhone] = useState(null);
  const [selectedUser, setSelectedUser] = useState(null);
  const [stats, setStats] = useState({});
  const [sending, setSending] = useState(false);
  const [typing, setTyping] = useState(false);

  const [showBroadcast, setShowBroadcast] = useState(false);
  const [showAnalytics, setShowAnalytics] = useState(false);
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
    }

    if (selectedPhoneRef.current === data.phone) {
      // Only show typing for AI replies
      if (data.direction === "bot" && data.source === "ai") {
        setTyping(true);
        setTimeout(() => setTyping(false), 1200);
      }

      // Only append user messages and AI replies
      // Dashboard sends are added optimistically so skip them
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
    if (selectedPhoneRef.current === data.phone) {
      updateMessageStatus(data.whatsapp_message_id, data.status);
    }
  }, [selectedPhoneRef, updateMessageStatus]);

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

  const { connected } = useSocket({
    onNewUser: handleNewUser,
    onUserUpdate: handleUserUpdate,
    onNewMessage: handleNewMessage,
    onStatusUpdate: handleStatusUpdate,
    onModeChanged: handleModeChanged,
    onUserUpdated: handleUserUpdated,
  });

  // ── Initial load ─────────────────────────────────────────────────────────

  useEffect(() => {
    const load = async () => {
      try {
        const [usersData, statsData] = await Promise.all([
          api.getUsers(),
          api.getAnalytics(),
        ]);
        setUsers(usersData);
        setStats(statsData);
      } catch (e) {
        console.error("Initial load failed:", e);
      }
    };
    load();
  }, []);

  // Poll analytics every 30s
  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const data = await api.getAnalytics();
        setStats(data);
      } catch {}
    }, 30000);
    return () => clearInterval(id);
  }, []);

  // ── User selection ───────────────────────────────────────────────────────

  const selectUser = useCallback((user) => {
    setSelectedPhone(user.phone);
    setSelectedUser(user);
    loadMessages(user.phone);
    markAsRead(user.phone);
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
      setMessages((prev) =>
        prev.map((m) => (m._id === temp._id ? { ...m, status: "sent" } : m))
      );
    } catch {
      removeMessage(temp);
      alert("Failed to send message.");
    } finally {
      setSending(false);
    }
  }, [selectedPhone, sending, appendMessage, removeMessage, setMessages]);

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
      setMessages((prev) =>
        prev.map((m) => (m._id === temp._id ? { ...m, status: "sent" } : m))
      );
    } catch {
      removeMessage(temp);
      alert("Failed to send file.");
    } finally {
      setSending(false);
    }
  }, [selectedPhone, sending, appendMessage, removeMessage, setMessages]);

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

      {/* Top bar */}
      <div style={barStyle}>
        <span>Users: {stats.total_users || 0}</span>
        <span>Messages: {stats.total_messages || 0}</span>
        <span>AI: {stats.ai_users || 0}</span>
        <span>Human: {stats.human_users || 0}</span>
        <span>Today: {stats.messages_today || 0}</span>
        <span>Avg response: {stats.avg_response_time || 0} min</span>
        <button style={btnStyle("#667eea")} onClick={() => setShowAnalytics(true)}>Analytics</button>
        <button style={btnStyle("#ff9800")} onClick={() => setShowBroadcast(true)}>Broadcast</button>
        <button style={btnStyle("#4caf50")} onClick={() => api.reloadKnowledge()}>Reload knowledge</button>
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