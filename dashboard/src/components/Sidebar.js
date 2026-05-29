import React from "react";
import s from "../styles/Sidebar.module.css";

export default function Sidebar({ users, selectedPhone, connected, unreadCounts, highlightedUsers, onSelect, onExportAll }) {
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
                {count > 0 && <span className={s.badge}>{count}</span>}
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
    </aside>
  );
}
