import React, { useEffect, useState, useRef, useMemo, useCallback } from "react";
import { api } from "../api/client";
import s from "../styles/Modal.module.css";
import c from "../styles/Consultations.module.css";
import { playNotificationSound } from "../utils/notificationSound";

const STATUS_OPTIONS = [
  { value: "new", label: "New" },
  { value: "contacted", label: "Contacted" },
  { value: "scheduled", label: "Scheduled" },
  { value: "completed", label: "Completed" },
  { value: "no_show", label: "No-show" },
];

const SORT_OPTIONS = [
  { value: "-created_at", label: "Newest first" },
  { value: "created_at", label: "Oldest first" },
  { value: "name", label: "Name A-Z" },
  { value: "status", label: "Status" },
];

// Converts an ISO 'YYYY-MM-DDTHH:MM:SSZ' string (UTC) to the local
// value a <input type="datetime-local"> expects, and back again.
function isoToLocalInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function localInputToIso(value) {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d)) return "";
  return d.toISOString().replace(/\.\d{3}Z$/, "Z");
}

export default function ConsultationsModal({ onClose, onSelectUser, users, onUserDeleted, latestBooking, currentUser }) {
  const [consultations, setConsultations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [confirmPhone, setConfirmPhone] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [justBookedPhone, setJustBookedPhone] = useState(null);
  const [dashboardUsers, setDashboardUsers] = useState([]);
  const [savingId, setSavingId] = useState(null);
  const modalRef = useRef(null);
  const mountedAtRef = useRef(Date.now());

  // ── Filters ────────────────────────────────────────────────────────
  const [stage, setStage] = useState("booked");       // booked | requested | all
  const [status, setStatus] = useState("");
  const [brand, setBrand] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [assignedTo, setAssignedTo] = useState("");    // "", "me", "unassigned", or a user id
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sort, setSort] = useState("-created_at");

  // Every distinct service seen, independent of the current service
  // filter, so the dropdown always lists every option (not just the
  // ones matching whatever's currently selected).
  const [allServices, setAllServices] = useState([]);

  const filters = useMemo(() => ({
    stage,
    status: status || undefined,
    brand: brand || undefined,
    service_id: serviceId || undefined,
    assigned_to: assignedTo || undefined,
    search: search || undefined,
    date_from: dateFrom ? `${dateFrom}T00:00:00Z` : undefined,
    date_to: dateTo ? `${dateTo}T23:59:59Z` : undefined,
    sort,
  }), [stage, status, brand, serviceId, assignedTo, search, dateFrom, dateTo, sort]);

  const refresh = useCallback(() => {
    setLoading(true);
    api.getConsultations(filters)
      .then((rows) => { setConsultations(rows); setError(null); })
      .catch((e) => setError(e.message || "Failed to load consultations"))
      .finally(() => setLoading(false));
  }, [filters]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    api.listDashboardUsers().then((data) => setDashboardUsers(data.users || [])).catch(() => {});
    // Unfiltered snapshot, just to populate the service dropdown with
    // every service that's ever come in, not only whatever's visible
    // under the current filters.
    api.getConsultations({ stage: "all" })
      .then((rows) => {
        const seen = new Map();
        rows.forEach((r) => { if (r.service_id) seen.set(r.service_id, r.service_label || r.service_id); });
        setAllServices([...seen.entries()].map(([value, label]) => ({ value, label })));
      })
      .catch(() => {});
  }, []);

  // Reacts live to a booking that comes in while this modal is already
  // open — a full refresh() plus a brief highlight/sound, instead of
  // requiring staff to close and reopen the modal to see it.
  useEffect(() => {
    if (!latestBooking) return;
    if (latestBooking.at <= mountedAtRef.current) return;

    playNotificationSound();
    setJustBookedPhone(latestBooking.phone);
    refresh();

    const t = setTimeout(() => setJustBookedPhone(null), 4000);
    return () => clearTimeout(t);
  }, [latestBooking, refresh]);

  const handleOverlay = (e) => {
    if (!modalRef.current?.contains(e.target)) onClose();
  };

  const handleClick = (phone) => {
    const user = users.find((u) => u.phone === phone);
    if (user) {
      onSelectUser(user);
      onClose();
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteUser(confirmPhone);
      setConsultations((prev) => prev.filter((item) => item.phone !== confirmPhone));
      onUserDeleted(confirmPhone);
      setConfirmPhone(null);
    } catch {
      alert("Failed to delete user.");
    } finally {
      setDeleting(false);
    }
  };

  const patchConsultation = async (id, patch) => {
    setSavingId(id);
    // Optimistic update so the control feels instant.
    setConsultations((prev) => prev.map((item) => (item.id === id ? { ...item, ...patch } : item)));
    try {
      const updated = await api.updateConsultation(id, patch);
      setConsultations((prev) => prev.map((item) => (item.id === id ? updated : item)));
    } catch (e) {
      alert(e.message || "Failed to update consultation.");
      refresh();
    } finally {
      setSavingId(null);
    }
  };

  const clearFilters = () => {
    setStage("booked"); setStatus(""); setBrand(""); setServiceId("");
    setAssignedTo(""); setSearch(""); setDateFrom(""); setDateTo("");
    setSort("-created_at");
  };
  const filtersActive = status || brand || serviceId || assignedTo || search || dateFrom || dateTo || stage !== "booked";

  return (
    <div className={s.overlay} onMouseDown={handleOverlay}>
      <div className={`${s.modal} ${s.wide}`} ref={modalRef}>
        <div className={s.header}>
          <h2>📋 Consultations</h2>
          <button className={s.closeBtn} onClick={onClose}>×</button>
        </div>

        <div className={c.filterBar}>
          <input
            className={c.searchInput}
            placeholder="Search name, phone, or mobile…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className={c.filterRow}>
            <div className={c.segmented}>
              {[
                { value: "booked", label: "Queue" },
                { value: "requested", label: "Dropped off" },
                { value: "all", label: "All" },
              ].map((opt) => (
                <button
                  key={opt.value}
                  className={`${c.segmentBtn} ${stage === opt.value ? c.segmentBtnActive : ""}`}
                  onClick={() => setStage(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            <select className={c.filterSelect} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>

            <select className={c.filterSelect} value={brand} onChange={(e) => setBrand(e.target.value)}>
              <option value="">Biz &amp; Law</option>
              <option value="biz">BizAdvise</option>
              <option value="law">LawAdvise</option>
            </select>

            <select className={c.filterSelect} value={serviceId} onChange={(e) => setServiceId(e.target.value)}>
              <option value="">All services</option>
              {allServices.map((sv) => <option key={sv.value} value={sv.value}>{sv.label}</option>)}
            </select>

            <select className={c.filterSelect} value={assignedTo} onChange={(e) => setAssignedTo(e.target.value)}>
              <option value="">Everyone</option>
              {currentUser?.id && <option value="me">My consultations</option>}
              <option value="unassigned">Unassigned</option>
              {dashboardUsers.map((u) => (
                <option key={u.id} value={u.id}>{u.display_name || u.username}</option>
              ))}
            </select>

            <input type="date" className={c.dateInput} value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} title="From date" />
            <input type="date" className={c.dateInput} value={dateTo} onChange={(e) => setDateTo(e.target.value)} title="To date" />

            <select className={c.filterSelect} value={sort} onChange={(e) => setSort(e.target.value)}>
              {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>

            {filtersActive && (
              <button className={c.clearBtn} onClick={clearFilters}>Clear filters</button>
            )}
          </div>
        </div>

        <div className={`${s.body} ${s.scrollable}`}>
          {loading && <div className={c.loading}>Loading...</div>}
          {!loading && error && <div className={c.empty}>⚠️ {error}</div>}

          {!loading && !error && consultations.length === 0 && (
            <div className={c.empty}>
              {filtersActive ? "No consultations match these filters." : "No consultation requests yet."}
            </div>
          )}

          {!loading && !error && consultations.length > 0 && (
            <>
              <div className={c.count}>
                {consultations.length} consultation{consultations.length !== 1 ? "s" : ""}
              </div>
              <div className={c.list}>
                {consultations.map((item) => (
                  <div
                    key={item.id}
                    className={`${c.card} ${item.phone === justBookedPhone ? c.justBooked : ""} ${item.is_stale ? c.stale : ""}`}
                  >
                    <div className={c.cardLeft}>
                      <div className={c.avatar}>
                        {(item.name || item.phone).charAt(0).toUpperCase()}
                      </div>
                    </div>

                    <div className={c.cardBody}>
                      <div className={c.nameRow}>
                        <span className={c.name} onClick={() => handleClick(item.phone)}>
                          {item.name || item.phone}
                        </span>
                        {item.name && <span className={c.phone}>{item.phone}</span>}
                        {item.service_label && (
                          <span className={`${c.tag} ${item.brand === "biz" ? c.tagBiz : item.brand === "law" ? c.tagLaw : ""}`}>
                            {item.service_label}
                          </span>
                        )}
                        {item.stage === "requested" && (
                          <span className={c.tagMuted} title="Started the booking flow but never finished it">
                            Dropped off
                          </span>
                        )}
                        {item.is_stale && (
                          <span className={c.staleBadge} title="Still New after 24+ hours">⏰ Stale</span>
                        )}
                      </div>

                      {item.stage === "booked" ? (
                        <div className={c.details}>
                          <span>📞 {item.mobile}</span>
                          <span>🕐 {item.best_time}</span>
                        </div>
                      ) : (
                        <div className={c.details}>
                          <span className={c.detailsMuted}>No contact info collected yet</span>
                        </div>
                      )}

                      <div className={c.meta}>
                        <span>Requested {new Date(item.created_at).toLocaleString()}</span>
                        {item.updated_at && item.updated_at !== item.created_at && (
                          <span>Updated {new Date(item.updated_at).toLocaleString()}</span>
                        )}
                      </div>

                      {item.stage === "booked" && (
                        <div className={c.controls}>
                          <select
                            className={`${c.statusSelect} ${c["status_" + item.status]}`}
                            value={item.status}
                            disabled={savingId === item.id}
                            onChange={(e) => patchConsultation(item.id, { status: e.target.value })}
                          >
                            {STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                          </select>

                          <select
                            className={c.assignSelect}
                            value={item.assigned_to ?? ""}
                            disabled={savingId === item.id}
                            onChange={(e) => patchConsultation(item.id, { assigned_to: e.target.value ? Number(e.target.value) : null })}
                          >
                            <option value="">Unassigned</option>
                            {dashboardUsers.map((u) => (
                              <option key={u.id} value={u.id}>{u.display_name || u.username}</option>
                            ))}
                          </select>

                          <input
                            type="datetime-local"
                            className={c.scheduleInput}
                            value={isoToLocalInput(item.scheduled_at)}
                            disabled={savingId === item.id}
                            title="Scheduled callback time"
                            onChange={(e) => patchConsultation(item.id, { scheduled_at: localInputToIso(e.target.value) })}
                          />
                        </div>
                      )}
                    </div>

                    <div className={c.cardRight}>
                      <button className={c.openBtn} onClick={() => handleClick(item.phone)}>
                        Open Chat →
                      </button>
                      <button
                        className={c.deleteBtn}
                        onClick={() => setConfirmPhone(item.phone)}
                        title="Delete user"
                      >
                        🗑 Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Confirm delete */}
      {confirmPhone && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 2000,
        }}>
          <div style={{
            background: "#fff", borderRadius: 12, padding: 24,
            width: 320, boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
          }}>
            <h3 style={{ marginBottom: 8, color: "#333" }}>Delete user?</h3>
            <p style={{ fontSize: 13, color: "#666", marginBottom: 20 }}>
              This will permanently delete <strong>{confirmPhone}</strong> and all their messages. This cannot be undone.
            </p>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button
                onClick={() => setConfirmPhone(null)}
                style={{ padding: "8px 16px", background: "#f5f5f5", border: "1px solid #ddd", borderRadius: 8, cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                style={{ padding: "8px 16px", background: "#f44336", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer" }}
              >
                {deleting ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}