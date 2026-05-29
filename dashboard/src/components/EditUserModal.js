import React, { useState, useRef } from "react";
import { api } from "../api/client";
import s from "../styles/Modal.module.css";

export default function EditUserModal({ user, onClose, onSaved }) {
  const [tags, setTags] = useState(user.tags || "");
  const [notes, setNotes] = useState(user.notes || "");
  const [saving, setSaving] = useState(false);
  const modalRef = useRef(null);

  const handleOverlay = (e) => { if (!modalRef.current?.contains(e.target)) onClose(); };

  const save = async () => {
    setSaving(true);
    try {
      await api.updateUser(user.phone, tags, notes);
      onSaved({ tags, notes });
      onClose();
    } catch (e) {
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
          <div className={s.field}>
            <label>Phone</label>
            <p><strong>{user.phone}</strong></p>
          </div>
          <div className={s.field}>
            <label>Tags (comma separated)</label>
            <input
              className={s.input}
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="e.g. VIP, lead"
            />
          </div>
          <div className={s.field}>
            <label>Notes</label>
            <textarea
              className={s.textarea}
              rows={4}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Internal notes..."
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
