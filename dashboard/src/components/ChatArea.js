import React, { useRef, useEffect, useState } from "react";
import s from "../styles/ChatArea.module.css";

function statusIcon(status) {
  return { sent: "✓", delivered: "✓✓", read: "✓✓✓", sending: "⋯", failed: "⚠" }[status] || "";
}
function statusColor(status) {
  return { read: "#0000FF", delivered: "#7393B3", sent: "#7393B3", failed: "#ff6b6b" }[status] || "#a0c4ff";
}
function typeIcon(type) {
  return { image: "🖼", audio: "🎵", document: "📄", video: "🎬", file: "📎" }[type] || null;
}
function formatDateLabel(timestamp) {
  if (!timestamp) return null;
  const date = new Date(timestamp);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const msgDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  if (msgDate.getTime() === today.getTime()) return "Today";
  if (msgDate.getTime() === yesterday.getTime()) return "Yesterday";
  return date.toLocaleDateString([], { day: "numeric", month: "long", year: "numeric" });
}
function isSameDay(ts1, ts2) {
  if (!ts1 || !ts2) return false;
  const a = new Date(ts1);
  const b = new Date(ts2);
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function DateSeparator({ label }) {
  return (
    <div className={s.dateSep}>
      <span className={s.dateSepLine} />
      <span className={s.dateSepLabel}>{label}</span>
      <span className={s.dateSepLine} />
    </div>
  );
}

// Typing bubble — only shown when USER is typing (incoming), not bot
function TypingBubble() {
  return (
    <div className={s.typingBubbleWrap}>
      <div className={s.typingDots}>
        <span className={s.dot} style={{ animationDelay: "0ms" }} />
        <span className={s.dot} style={{ animationDelay: "150ms" }} />
        <span className={s.dot} style={{ animationDelay: "300ms" }} />
      </div>
    </div>
  );
}

const seenKeys = new Set();

export default function ChatArea({
  user, messages, loading, typing, sending,
  onSend, onSendFile, onToggleMode, onEdit, onExport
}) {
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const [file, setFile] = useState(null);
  const [showTooltip, setShowTooltip] = useState(null);
  const endRef = useRef(null);
  const fileRef = useRef(null);
  const prevPhoneRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, typing]);

  useEffect(() => {
    if (user?.phone !== prevPhoneRef.current) {
      seenKeys.clear();
      prevPhoneRef.current = user?.phone;
    }
  }, [user?.phone]);

  const handleSend = () => {
    if (!text.trim() || sending) return;
    onSend(text);
    setText("");
  };

  const handleFile = () => {
    if (!file || sending) return;
    onSendFile(file);
    setFile(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const filtered = search
    ? messages.filter((m) => m.message?.toLowerCase().includes(search.toLowerCase()))
    : messages;

  if (!user) {
    return (
      <div className={s.empty}>
        <div className={s.emptyIllustration}>
          <svg width="120" height="120" viewBox="0 0 120 120" fill="none">
            <circle cx="60" cy="60" r="56" fill="#e8eaf6" />
            <rect x="28" y="38" width="64" height="44" rx="8" fill="#fff" />
            <rect x="36" y="50" width="32" height="6" rx="3" fill="#c5cae9" />
            <rect x="36" y="62" width="22" height="6" rx="3" fill="#e8eaf6" />
            <circle cx="84" cy="78" r="14" fill="#667eea" />
            <path d="M78 78h12M84 72v12" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" />
          </svg>
        </div>
        <div className={s.emptyTitle}>Welcome to the dashboard</div>
        <div className={s.emptySubtitle}>Select a chat from the sidebar to start messaging</div>
        <div className={s.emptyHint}>New users appear instantly when they message you</div>
      </div>
    );
  }

  // Action buttons config
  const actionBtns = [
    {
      key: "toggle",
      icon: user.human_mode ? "🤖" : "👤",
      label: user.human_mode ? "Switch to AI" : "Switch to Human",
      action: onToggleMode,
      color: user.human_mode ? "#0b5cff" : "#ff9800",
    },
    { key: "edit",   icon: "✏️",  label: "Edit user",  action: onEdit,   color: "#9c27b0" },
    { key: "export", icon: "⬇️", label: "Export chat", action: onExport, color: "#4caf50" },
  ];

  return (
    <div className={s.chat}>

      {/* ── Header ── */}
      <div className={s.header}>
        <div className={s.headerLeft}>
          <div className={s.headerAvatar} style={{ background: user.human_mode ? "#ff9800" : "#667eea" }}>
            {(user.name || user.phone).charAt(0).toUpperCase()}
          </div>
          <div>
            <div className={s.headerName}>
              {user.name || user.phone}
              {user.name && <span className={s.headerPhone}>({user.phone})</span>}
            </div>
            <div className={s.headerMeta}>
              <span className={s.modePill} style={{
                background: user.human_mode ? "#fff3e0" : "#e8f5e9",
                color: user.human_mode ? "#e65100" : "#2e7d32",
              }}>
                <span className={s.modePillDot} style={{ background: user.human_mode ? "#ff9800" : "#4caf50" }} />
                {user.human_mode ? "Human mode" : "AI mode"}
              </span>
              {user.tags && <span className={s.tagBadge}>{user.tags}</span>}
              <span className={s.msgCount}>{user.total_messages} messages</span>
            </div>
          </div>
        </div>

        {/* ── Action buttons with label underneath ── */}
        <div className={s.headerActions}>
          {actionBtns.map((btn) => (
            <button
              key={btn.key}
              className={s.actionBtn}
              onClick={btn.action}
              onMouseEnter={() => setShowTooltip(btn.key)}
              onMouseLeave={() => setShowTooltip(null)}
              style={{ "--btn-color": btn.color }}
            >
              <span className={s.actionBtnIcon}>{btn.icon}</span>
              <span className={`${s.actionBtnLabel} ${showTooltip === btn.key ? s.actionBtnLabelVisible : ""}`}>
                {btn.label}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* ── Search ── */}
      <div className={s.searchBar}>
        <input
          className={s.searchInput}
          placeholder="Search messages..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && <button className={s.clearBtn} onClick={() => setSearch("")}>✕</button>}
      </div>

      {/* ── Messages ── */}
      <div className={s.messages}>
        {loading && <div className={s.loading}>Loading...</div>}
        {!loading && filtered.length === 0 && (
          <div className={s.noMessages}>No messages yet.</div>
        )}

        {filtered.map((msg, i) => {
          const prevMsg = filtered[i - 1];
          const showDateSep = !isSameDay(prevMsg?.timestamp, msg.timestamp);
          const dateLabel = formatDateLabel(msg.timestamp);
          const icon = typeIcon(msg.message_type);
          const key = msg._id || msg.whatsapp_message_id || `${msg.timestamp}-${i}`;
          const isNew = !seenKeys.has(key);
          if (isNew) seenKeys.add(key);
          const isUser = msg.direction === "user";

          return (
            <React.Fragment key={key}>
              {showDateSep && dateLabel && <DateSeparator label={dateLabel} />}
              <div className={`${s.bubbleWrap} ${isUser ? s.bubbleWrapUser : s.bubbleWrapBot} ${isNew ? s.bubbleNew : ""}`}>
                <div className={`${s.bubble} ${isUser ? s.bubbleUser : s.bubbleBot}`}>
                  <div className={s.bubbleBody}>
                    {icon && <span className={s.typeIcon}>{icon}</span>}
                    {msg.file_name && <span className={s.fileName}>{msg.file_name}</span>}
                    <span>{msg.message || `[${msg.message_type} message]`}</span>
                  </div>
                </div>
                {/* Time always outside and below — fixed position regardless of text length */}
                <div className={`${s.bubbleTime} ${isUser ? s.bubbleTimeUser : s.bubbleTimeBot}`}>
                  {msg.timestamp && new Date(msg.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  {!isUser && (
                    <span style={{ marginLeft: 4, color: statusColor(msg.status), fontSize: 11, fontWeight: "bold" }}>
                      {statusIcon(msg.status)}
                    </span>
                  )}
                </div>
              </div>
            </React.Fragment>
          );
        })}

        {/* Typing bubble — left side, only for incoming (user typing) */}
        {typing && <TypingBubble />}
        <div ref={endRef} />
      </div>

      {/* ── Input ── */}
      <div className={s.inputArea}>
        <input
          type="file"
          ref={fileRef}
          className={s.fileInputHidden}
          accept="image/*,application/pdf,audio/*,.doc,.docx,.txt"
          onChange={(e) => setFile(e.target.files[0])}
        />
        <button className={s.attachBtn} onClick={() => fileRef.current?.click()} title="Attach file">
          📎
        </button>
        {file ? (
          <div className={s.filePreview}>
            <span className={s.filePreviewName}>{file.name}</span>
            <button className={s.filePreviewSend} onClick={handleFile} disabled={sending}>Send</button>
            <button className={s.filePreviewCancel} onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = ""; }}>✕</button>
          </div>
        ) : (
          <>
            <input
              className={s.textInput}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
              placeholder="Type a message..."
              disabled={sending}
            />
            <button className={s.sendBtn} onClick={handleSend} disabled={sending || !text.trim()}>
              {sending ? "..." : "Send"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}