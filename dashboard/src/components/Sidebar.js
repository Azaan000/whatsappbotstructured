import React, { useState } from "react";
import { api } from "../api/client";
import s from "../styles/Sidebar.module.css";

export default function Sidebar({
  users, selectedPhone, connected, unreadCounts,
  highlightedUsers, onSelect, onExportAll, onUserDeleted,
}) {
  const [confirmPhone, setConfirmPhone] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async (e, phone) => {
    e.stopPropagation();
    setConfirmPhone(phone);
  };

  const confirmDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteUser(confirmPhone);
      onUserDeleted(confirmPhone);
    } catch (err) {
      alert("Failed to delete user.");
    } finally {
      setDeleting(false);
      setConfirmPhone(null);
    }
  };

  return (
    <aside className={s.sidebar}>
      <div className={s.titleRow}>
        <h2 className={s.title}>WhatsApp Dashboard</h2>
      </div>
      <div className={s.meta}>
        {users.length} chats &nbsp;·&nbsp;
        <span style={{ color: connected ? "#4caf50" : "#f44336" }}>
          {connected ? "Live" : "Reconnecting..."}
        </span>
      </div>

      <button className={s.exportBtn} onClick={onExportAll}>
        Export all conversations
      </button>

      <div className={s.list}>
        {users.length === 0 && (
          <p className={s.empty}>No users yet. Waiting for messages...</p>
        )}
        {users.map((user) => {
          const isUnread = highlightedUsers.has(user.phone);
          const count = unreadCounts[user.phone] || 0;
          const active = selectedPhone === user.phone;
          return (
            <div
              key={user.phone}
              className={`${s.user} ${active ? s.active : ""} ${isUnread && !active ? s.unread : ""}`}
              onClick={() => onSelect(user)}
            >
              <div className={s.row}>
                <div>
                  {user.name && <div className={s.name}>{user.name}</div>}
                  <span className={s.phone}>{user.phone}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  {count > 0 && <span className={s.badge}>{count}</span>}
                  <button
                    className={s.deleteBtn}
                    onClick={(e) => handleDelete(e, user.phone)}
                    title="Delete user"
                  >
                    🗑
                  </button>
                </div>
              </div>
              <div className={s.stats}>
                {user.total_messages} msgs
                {user.tags && <span className={s.tag}>{user.tags}</span>}
              </div>
              <div className={`${s.last} ${isUnread && !active ? s.lastUnread : ""}`}>
                {user.last || "No messages yet"}
              </div>
              <div className={s.time}>
                {user.last_seen && new Date(user.last_seen).toLocaleTimeString()}
              </div>
              <div className={s.mode} style={{ color: user.human_mode ? "#ff9800" : "#4caf50" }}>
                {user.human_mode ? "Human mode" : "AI mode"}
              </div>
            </div>
          );
        })}
      </div>

      {/* Confirm delete dialog */}
      {confirmPhone && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 2000,
        }}>
          <div style={{
            background: "#fff", borderRadius: 12, padding: 24,
            width: 320, boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
          }}>
            <h3 style={{ marginBottom: 8, color: "#333" }}>Delete user?</h3>
            <p style={{ fontSize: 13, color: "#666", marginBottom: 20 }}>
              This will permanently delete <strong>{confirmPhone}</strong> and all their messages from the database. This cannot be undone.
            </p>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button
                onClick={() => setConfirmPhone(null)}
                style={{ padding: "8px 16px", background: "#f5f5f5", border: "1px solid #ddd", borderRadius: 8, cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                style={{ padding: "8px 16px", background: "#f44336", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer" }}
              >
                {deleting ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}