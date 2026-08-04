import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import s from "../styles/Modal.module.css";

export default function AccountModal({ user, onClose, onLoggedOut }) {
  const modalRef = useRef(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);

  const [dashboardUsers, setDashboardUsers] = useState(null);
  const [usersError, setUsersError] = useState("");
  const [deletingUserId, setDeletingUserId] = useState(null);

  const handleOverlay = (e) => {
    if (!modalRef.current?.contains(e.target)) onClose();
  };

  useEffect(() => {
    if (!user?.is_admin) return;
    api.listDashboardUsers()
      .then((data) => setDashboardUsers(data.users))
      .catch((e) => setUsersError(e.message || "Failed to load users"));
  }, [user]);

  const deleteOwnAccount = async () => {
    setError("");
    setDeleting(true);
    try {
      await api.deleteOwnAccount(password);
      onLoggedOut();
    } catch (e) {
      setError(e.message || "Failed to delete account");
    } finally {
      setDeleting(false);
    }
  };

  const deleteOtherUser = async (id, username) => {
    if (!window.confirm(`Delete the account "${username}"? This can't be undone.`)) return;
    setDeletingUserId(id);
    try {
      await api.deleteDashboardUser(id);
      setDashboardUsers((prev) => prev.filter((u) => u.id !== id));
    } catch (e) {
      alert(e.message || "Failed to delete user");
    } finally {
      setDeletingUserId(null);
    }
  };

  return (
    <div className={s.overlay} onMouseDown={handleOverlay}>
      <div className={s.modal} ref={modalRef}>
        <div className={s.header}>
          <h2>My account</h2>
          <button className={s.closeBtn} onClick={onClose}>×</button>
        </div>

        <div className={s.body}>
          <div style={{
            background: "#f8f9fa", borderRadius: 10, padding: "12px 14px",
            marginBottom: 20, display: "flex", flexDirection: "column", gap: 4,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 14, fontWeight: 600, color: "#111" }}>
                {user.display_name || user.username}
              </span>
              {user.is_admin && (
                <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 10, fontWeight: 500, background: "#e8eefc", color: "#1a237e" }}>
                  Admin
                </span>
              )}
            </div>
            <span style={{ fontSize: 12, color: "#888" }}>@{user.username}</span>
          </div>

          {/* Admin: manage other users */}
          {user.is_admin && (
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#333", marginBottom: 8 }}>
                All dashboard accounts
              </div>
              {usersError && <div style={{ fontSize: 12, color: "var(--color-red-dark, #96000a)" }}>{usersError}</div>}
              {!dashboardUsers && !usersError && (
                <div style={{ fontSize: 12, color: "#999" }}>Loading…</div>
              )}
              {dashboardUsers && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 220, overflowY: "auto" }}>
                  {dashboardUsers.map((u) => (
                    <div key={u.id} style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      padding: "8px 10px", border: "1px solid #eee", borderRadius: 8, fontSize: 13,
                    }}>
                      <div>
                        <div style={{ fontWeight: 500 }}>
                          {u.display_name || u.username}
                          {u.is_admin && <span style={{ marginLeft: 6, fontSize: 10, color: "#1a237e" }}>(admin)</span>}
                          {u.id === user.id && <span style={{ marginLeft: 6, fontSize: 10, color: "#999" }}>(you)</span>}
                        </div>
                        <div style={{ fontSize: 11, color: "#999" }}>@{u.username}</div>
                      </div>
                      {u.id !== user.id && (
                        <button
                          onClick={() => deleteOtherUser(u.id, u.username)}
                          disabled={deletingUserId === u.id}
                          style={{
                            padding: "5px 10px", background: "#fdecea", color: "var(--color-red-dark, #96000a)",
                            border: "1px solid #f5c6c2", borderRadius: 6, cursor: "pointer", fontSize: 12,
                          }}
                        >
                          {deletingUserId === u.id ? "Deleting…" : "Delete"}
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Self delete-account */}
          <div style={{ borderTop: "1px solid #eee", paddingTop: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-red-dark, #96000a)", marginBottom: 6 }}>
              Danger zone
            </div>
            {!confirmingDelete ? (
              <button
                onClick={() => setConfirmingDelete(true)}
                style={{
                  padding: "8px 14px", background: "#fdecea", color: "var(--color-red-dark, #96000a)",
                  border: "1px solid #f5c6c2", borderRadius: 8, cursor: "pointer", fontSize: 13,
                }}
              >
                Delete my account
              </button>
            ) : (
              <div>
                <p style={{ fontSize: 12.5, color: "#666", marginTop: 0 }}>
                  This permanently deletes your login. Enter your password to confirm.
                </p>
                {error && (
                  <div style={{ fontSize: 12, color: "var(--color-red-dark, #96000a)", marginBottom: 8 }}>
                    {error}
                  </div>
                )}
                <input
                  className={s.input}
                  type="password"
                  placeholder="Current password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  style={{ marginBottom: 10 }}
                  autoFocus
                />
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={() => { setConfirmingDelete(false); setPassword(""); setError(""); }}
                    className={s.cancelBtn}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={deleteOwnAccount}
                    disabled={deleting || !password}
                    style={{
                      padding: "8px 16px", background: "var(--color-red, #ca000e)", color: "#fff",
                      border: "none", borderRadius: 8, cursor: "pointer", fontSize: 13,
                      opacity: deleting || !password ? 0.6 : 1,
                    }}
                  >
                    {deleting ? "Deleting…" : "Permanently delete"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className={s.footer}>
          <button className={s.cancelBtn} onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}