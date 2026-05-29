import React, { useRef, useEffect, useState } from "react";
import s from "../styles/ChatArea.module.css";

function statusIcon(status) {
  return { sent: "✓", delivered: "✓✓", read: "✓✓✓", sending: "⋯", failed: "⚠" }[status] || "";
}
function statusColor(status) {
  return { read: "#FFFFFF", delivered: "#FFFFFF", sent: "#666" }[status] || "#999";
}
function typeIcon(type) {
  return { image: "🖼", audio: "🎵", document: "📄", video: "🎬", file: "📎" }[type] || "💬";
}

export default function ChatArea({ user, messages, loading, typing, sending, onSend, onSendFile, onToggleMode, onEdit, onExport }) {
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const [file, setFile] = useState(null);
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
      {/* Header */}
      <div className={s.header}>
        <div>
          <h3 className={s.headerPhone}>
            {user.name || user.phone}
            {user.name && (
              <span style={{ fontSize: 12, color: "#999", marginLeft: 8 }}>
                ({user.phone})
              </span>
            )}
          </h3>
          <div className={s.headerMeta}>
            <span style={{ color: user.human_mode ? "#ff9800" : "#0b5cff", fontSize: 12 }}>
              {user.human_mode ? "Human mode" : "AI mode"}
            </span>
            {user.tags && <span className={s.tagBadge}>{user.tags}</span>}
            <span className={s.msgCount}>{user.total_messages} messages</span>
          </div>
        </div>
        <div className={s.headerBtns}>
          <button className={s.btnPrimary} onClick={onToggleMode}>
            {user.human_mode ? "Switch to AI" : "Switch to Human"}
          </button>
          <button className={s.btnWarn} onClick={onEdit}>Edit</button>
          <button className={s.btnSuccess} onClick={onExport}>Export</button>
        </div>
      </div>

      {/* Search */}
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

      {/* Messages */}
      <div className={s.messages}>
        {loading && <div className={s.loading}>Loading...</div>}
        {!loading && filtered.length === 0 && (
          <div className={s.noMessages}>No messages yet.</div>
        )}
        {filtered.map((msg, i) => (
          <div
            key={msg.id || i}
            className={`${s.bubble} ${msg.direction === "user" ? s.bubbleUser : s.bubbleBot}`}
          >
            <div className={s.bubbleBody}>
              <span className={s.typeIcon}>{typeIcon(msg.message_type)}</span>
              {msg.file_name && <span className={s.fileName}>{msg.file_name}</span>}
              <span>{msg.message || `[${msg.message_type} message]`}</span>
            </div>
            <div className={s.bubbleMeta}>
              {msg.timestamp && new Date(msg.timestamp).toLocaleTimeString()}
              {msg.direction === "bot" && (
                <span style={{ marginLeft: 4, color: statusColor(msg.status) }}>
                  {statusIcon(msg.status)}
                </span>
              )}
            </div>
          </div>
        ))}
        {typing && (
          <div className={`${s.bubble} ${s.bubbleBot} ${s.typingBubble}`}>
            typing...
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className={s.inputArea}>
        <input
          type="file"
          ref={fileRef}
          className={s.fileInput}
          accept="image/*,application/pdf,audio/*,.doc,.docx,.txt"
          onChange={(e) => setFile(e.target.files[0])}
        />
        {file && (
          <button className={s.sendFileBtn} onClick={handleFile} disabled={sending}>
            Send: {file.name}
          </button>
        )}
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
      </div>
    </div>
  );
}