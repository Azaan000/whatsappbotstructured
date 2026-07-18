import React, { useEffect, useState, useRef } from "react";
import { api } from "../api/client";
import s from "../styles/Modal.module.css";
import c from "../styles/Consultations.module.css";

export default function ConsultationsModal({ onClose, onSelectUser, users }) {
  const [consultations, setConsultations] = useState([]);
  const [loading, setLoading] = useState(true);
  const modalRef = useRef(null);

  useEffect(() => {
    api.getConsultations()
      .then(setConsultations)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const handleOverlay = (e) => {
    if (!modalRef.current?.contains(e.target)) onClose();
  };

  const handleClick = (phone) => {
    // Find full user object and open their chat
    const user = users.find((u) => u.phone === phone);
    if (user) {
      onSelectUser(user);
      onClose();
    }
  };

  return (
    <div className={s.overlay} onMouseDown={handleOverlay}>
      <div className={`${s.modal} ${s.wide}`} ref={modalRef}>
        <div className={s.header}>
          <h2>📋 Consultation Requests</h2>
          <button className={s.closeBtn} onClick={onClose}>×</button>
        </div>
        <div className={`${s.body} ${s.scrollable}`}>
          {loading && <div className={c.loading}>Loading...</div>}

          {!loading && consultations.length === 0 && (
            <div className={c.empty}>
              No consultation requests yet.
            </div>
          )}

          {!loading && consultations.length > 0 && (
            <>
              <div className={c.count}>
                {consultations.length} user{consultations.length !== 1 ? "s" : ""} requested a consultation
              </div>
              <div className={c.list}>
                {consultations.map((item) => (
                  <div
                    key={item.phone}
                    className={c.card}
                    onClick={() => handleClick(item.phone)}
                  >
                    <div className={c.cardLeft}>
                      <div className={c.avatar}>
                        {(item.name || item.phone).charAt(0).toUpperCase()}
                      </div>
                    </div>
                    <div className={c.cardBody}>
                      <div className={c.nameRow}>
                        <span className={c.name}>
                          {item.name || item.phone}
                        </span>
                        {item.name && (
                          <span className={c.phone}>{item.phone}</span>
                        )}
                        {item.tags && (
                          <span className={c.tag}>{item.tags}</span>
                        )}
                      </div>
                      <div className={c.lastMsg}>
                        "{item.last_consult_message}"
                      </div>
                      <div className={c.meta}>
                        <span>🕐 {new Date(item.last_request).toLocaleString()}</span>
                        <span>📨 {item.consult_count} request{item.consult_count !== 1 ? "s" : ""}</span>
                      </div>
                    </div>
                    <div className={c.cardRight}>
                      <button className={c.openBtn}>Open Chat →</button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}