import React, { useRef, useEffect, useState } from "react";
import s from "../styles/ChatArea.module.css";

function statusIcon(status) {
  return { sent: "✓", delivered: "✓✓", read: "✓✓✓", sending: "⋯", failed: "⚠" }[status] || "";
}
function statusColor(status) {
  return { read: "#ffffff", delivered: "#c8e6ff", sent: "#a0c4ff", failed: "#ff6b6b" }[status] || "#a0c4ff";
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

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, typing]);

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
        <div className={s.emptyIcon}>💬</div>
        <div>Select a chat to start messaging</div>
        <div className={s.emptySub}>New users appear instantly in the sidebar</div>
      </div>
    );
  }

  return (
    <div className={s.chat}>

      {/* ── Header ── */}
      <div className={s.header}>
        <div className={s.headerLeft}>
          {/* Avatar */}
          <div className={s.headerAvatar} style={{ background: user.human_mode ? "#ff9800" : "#667eea" }}>
            {(user.name || user.phone).charAt(0).toUpperCase()}
          </div>
          {/* Name + meta */}
          <div>
            <div className={s.headerName}>
              {user.name || user.phone}
              {user.name && (
                <span className={s.headerPhone}>({user.phone})</span>
              )}
            </div>
            <div className={s.headerMeta}>
              <span
                className={s.modePill}
                style={{
                  background: user.human_mode ? "#fff3e0" : "#e8f5e9",
                  color: user.human_mode ? "#e65100" : "#2e7d32",
                }}
              >
                <span
                  className={s.modePillDot}
                  style={{ background: user.human_mode ? "#ff9800" : "#4caf50" }}
                />
                {user.human_mode ? "Human mode" : "AI mode"}
              </span>
              {user.tags && <span className={s.tagBadge}>{user.tags}</span>}
              <span className={s.msgCount}>{user.total_messages} messages</span>
            </div>
          </div>
        </div>

        {/* ── Icon buttons ── */}
        <div className={s.headerActions}>
          {/* Toggle mode */}
          <div className={s.iconBtnWrap}>
            <button
              className={s.iconBtn}
              onClick={onToggleMode}
              onMouseEnter={() => setShowTooltip("toggle")}
              onMouseLeave={() => setShowTooltip(null)}
              title={user.human_mode ? "Switch to AI mode" : "Switch to Human mode"}
            >
              {user.human_mode ? "🤖" : "👤"}
            </button>
            {showTooltip === "toggle" && (
              <div className={s.tooltip}>
                {user.human_mode ? "Switch to AI" : "Switch to Human"}
              </div>
            )}
          </div>

          {/* Edit */}
          <div className={s.iconBtnWrap}>
            <button
              className={s.iconBtn}
              onClick={onEdit}
              onMouseEnter={() => setShowTooltip("edit")}
              onMouseLeave={() => setShowTooltip(null)}
              title="Edit user"
            >
              ✏️
            </button>
            {showTooltip === "edit" && (
              <div className={s.tooltip}>Edit user</div>
            )}
          </div>

          {/* Export */}
          <div className={s.iconBtnWrap}>
            <button
              className={s.iconBtn}
              onClick={onExport}
              onMouseEnter={() => setShowTooltip("export")}
              onMouseLeave={() => setShowTooltip(null)}
              title="Export chat"
            >
              ⬇️
            </button>
            {showTooltip === "export" && (
              <div className={s.tooltip}>Export chat</div>
            )}
          </div>
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
        {search && (
          <button className={s.clearBtn} onClick={() => setSearch("")}>✕</button>
        )}
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

          return (
            <React.Fragment key={msg._id || msg.whatsapp_message_id || i}>
              {showDateSep && dateLabel && <DateSeparator label={dateLabel} />}
              <div className={`${s.bubble} ${msg.direction === "user" ? s.bubbleUser : s.bubbleBot}`}>
                <div className={s.bubbleBody}>
                  {icon && <span className={s.typeIcon}>{icon}</span>}
                  {msg.file_name && <span className={s.fileName}>{msg.file_name}</span>}
                  <span>{msg.message || `[${msg.message_type} message]`}</span>
                </div>
                <div className={s.bubbleMeta}>
                  {msg.timestamp && new Date(msg.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  {msg.direction === "bot" && (
                    <span style={{ marginLeft: 4, color: statusColor(msg.status), fontSize: 12, fontWeight: "bold" }}>
                      {statusIcon(msg.status)}
                    </span>
                  )}
                </div>
              </div>
            </React.Fragment>
          );
        })}

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
        <button
          className={s.attachBtn}
          onClick={() => fileRef.current?.click()}
          title="Attach file"
        >
          📎
        </button>
        {file && (
          <div className={s.filePreview}>
            <span className={s.filePreviewName}>{file.name}</span>
            <button className={s.filePreviewSend} onClick={handleFile} disabled={sending}>
              Send
            </button>
            <button className={s.filePreviewCancel} onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = ""; }}>
              ✕
            </button>
          </div>
        )}
        {!file && (
          <>
            <input
              className={s.textInput}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
              placeholder="Type a message..."
              disabled={sending}
            />
            <button
              className={s.sendBtn}
              onClick={handleSend}
              disabled={sending || !text.trim()}
            >
              {sending ? "..." : "Send"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}