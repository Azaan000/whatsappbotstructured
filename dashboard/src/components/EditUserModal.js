import React, { useState, useRef } from "react";
import { api } from "../api/client";
import s from "../styles/Modal.module.css";

export default function EditUserModal({ user, onClose, onSaved }) {
  const [tags, setTags] = useState(user.tags || "");
  const [notes, setNotes] = useState(user.notes || "");
  const [saving, setSaving] = useState(false);
  // `user` already comes from the /users endpoint (models/user.py's
  // get_all_users), which includes first_seen — no need to refetch every
  // user in the system just to read one field we already have.
  const firstSeen = user.first_seen || null;
  const modalRef = useRef(null);

  const handleOverlay = (e) => {
    if (!modalRef.current?.contains(e.target)) onClose();
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.updateUser(user.phone, tags, notes);
      onSaved({ tags, notes });
      onClose();
    } catch {
      alert("Failed to update user");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={s.overlay} onMouseDown={handleOverlay}>
      <div className={s.modal} ref={modalRef}>
        <div className={s.header}>
          <h2>Edit user</h2>
          <button className={s.closeBtn} onClick={onClose}>×</button>
        </div>
        <div className={s.body}>
          {/* User info card */}
          <div style={{
            background: "rgba(255, 255, 255, 0.05)",
            border: "1px solid rgba(229, 169, 80, 0.2)",
            borderRadius: 12, padding: "14px 16px",
            marginBottom: 16, display: "flex", flexDirection: "column", gap: 6,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: "#f8fafc" }}>
                {user.name || user.phone}
              </span>
              {user.human_mode !== undefined && (
                <span style={{
                  fontSize: 11, padding: "3px 10px", borderRadius: 10, fontWeight: 600,
                  background: user.human_mode ? "rgba(245, 158, 11, 0.15)" : "rgba(16, 185, 129, 0.15)",
                  color: user.human_mode ? "#fcd34d" : "#6ee7b7",
                  border: user.human_mode ? "1px solid rgba(245, 158, 11, 0.3)" : "1px solid rgba(16, 185, 129, 0.3)",
                }}>
                  {user.human_mode ? "Human mode" : "AI mode"}
                </span>
              )}
            </div>
            {user.name && (
              <span style={{ fontSize: 11, color: "var(--color-gold-light)" }}>{user.phone}</span>
            )}
            <div style={{ display: "flex", gap: 16, marginTop: 2, flexWrap: "wrap" }}>
              {firstSeen && (
                <span style={{ fontSize: 11, color: "#94a3b8" }}>
                  📅 First contact: {new Date(firstSeen).toLocaleDateString([], {
                    day: "numeric", month: "long", year: "numeric",
                  })}
                </span>
              )}
              {user.last_seen && (
                <span style={{ fontSize: 11, color: "#94a3b8" }}>
                  🕐 Last seen: {new Date(user.last_seen).toLocaleDateString([], {
                    day: "numeric", month: "long", year: "numeric",
                  })}
                </span>
              )}
            </div>
            <span style={{ fontSize: 11, color: "#94a3b8" }}>
              📨 {user.total_messages || 0} total messages
            </span>
          </div>

          <div className={s.field}>
            <label>Tags (comma separated)</label>
            <input
              className={s.input}
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="e.g. VIP, lead, interested"
            />
          </div>
          <div className={s.field}>
            <label>Notes</label>
            <textarea
              className={s.textarea}
              rows={4}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Internal notes about this user..."
            />
          </div>
        </div>
        <div className={s.footer}>
          <button className={s.cancelBtn} onClick={onClose}>Cancel</button>
          <button className={s.primaryBtn} onClick={save} disabled={saving}>
            {saving ? "Saving..." : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}