import React, { useState, useEffect } from "react";
import styles from "../styles/AccountModal.module.css";
import modalStyles from "../styles/Modal.module.css";
import { api } from "../api/client";

export default function AccountModal({ user, currentUser, onClose, onLoggedOut }) {
  const activeUser = user || currentUser;
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    loadUsers();
  }, []);

  const loadUsers = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.listDashboardUsers();
      setUsers(Array.isArray(data) ? data : data.users || []);
    } catch (err) {
      setError(err.message || "Failed to fetch account directory.");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteUser = async (targetUser) => {
    if (!window.confirm(`Delete dashboard account for ${targetUser.username || targetUser.display_name}?`)) {
      return;
    }

    setDeletingId(targetUser.id);
    try {
      await api.deleteDashboardUser(targetUser.id);
      setUsers((prev) => prev.filter((u) => u.id !== targetUser.id));
    } catch (err) {
      alert(err.message || "Failed to delete dashboard account.");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className={modalStyles.overlay}>
      <div className={`${modalStyles.content} ${modalStyles.wide}`}>
        <div className={styles.modalHeader}>
          <div>
            <h2 className={styles.title}>Account & User Directory</h2>
            <p className={styles.subtitle}>
              Logged in as: <strong>{activeUser?.display_name || activeUser?.username}</strong>
            </p>
          </div>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>

        {error && <div className={styles.errorMessage}>{error}</div>}

        <div className={styles.body}>
          {loading ? (
            <div className={styles.loaderState}>Loading user accounts...</div>
          ) : (
            <div className={styles.tableWrapper}>
              <table className={styles.userTable}>
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Username</th>
                    <th>Role</th>
                    <th style={{ textAlign: "right" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.length === 0 ? (
                    <tr>
                      <td colSpan="4" className={styles.emptyCell}>
                        No dashboard accounts found.
                      </td>
                    </tr>
                  ) : (
                    users.map((u) => {
                      const isSelf = activeUser?.id === u.id || activeUser?.username === u.username;

                      return (
                        <tr key={u.id || u.username}>
                          <td>
                            <div className={styles.userNameGroup}>
                              <div className={styles.avatarCircle}>
                                {(u.display_name || u.username || "U").charAt(0).toUpperCase()}
                              </div>
                              <div>
                                <div className={styles.userName}>
                                  {u.display_name || u.username}{" "}
                                  {isSelf && <span className={styles.youBadge}>(You)</span>}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td>
                            <div className={styles.contactDetails}>
                              <div>@{u.username}</div>
                            </div>
                          </td>
                          <td>
                            <span className={`${styles.roleBadge} ${styles.badgeAdmin}`}>
                              {u.role || "Agent"}
                            </span>
                          </td>
                          <td style={{ textAlign: "right" }}>
                            {!isSelf && (
                              <button
                                className={`${styles.actionBtn} ${styles.revokeBtn}`}
                                onClick={() => handleDeleteUser(u)}
                                disabled={deletingId === u.id}
                              >
                                {deletingId === u.id ? "Deleting..." : "Delete Account"}
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className={modalStyles.footer} style={{ display: "flex", justifyContent: "space-between" }}>
          {onLoggedOut && (
            <button
              className={styles.revokeBtn}
              style={{ padding: "8px 16px", borderRadius: 6, cursor: "pointer" }}
              onClick={onLoggedOut}
            >
              Log Out
            </button>
          )}
          <button className={styles.cancelBtn} onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}