import React, { useState, useRef, useEffect, useMemo } from "react";
import { api } from "../api/client";
import m from "../styles/Modal.module.css";
import s from "../styles/Broadcast.module.css";

const BRAND_LABELS = { biz: "BizAdvise", law: "LawAdvise", "": "Organic / Unknown" };
const CONSULT_STATUS_LABELS = {
  new: "New", contacted: "Contacted", scheduled: "Scheduled",
  completed: "Completed", no_show: "No-show", none: "No consultation",
};
const CONFIRM_THRESHOLD = 20;
const CHAR_LIMIT = 4096;

function personalize(text, name) {
  return (text || "").replace(/\{\{\s*name\s*\}\}/gi, (name || "").trim() || "there");
}

function daysAgo(iso) {
  if (!iso) return Infinity;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return Infinity;
  return (Date.now() - then) / 86400000;
}

function badgeClass(status) {
  if (status === "completed") return s.badgeCompleted;
  if (status === "stopped") return s.badgeStopped;
  return s.badgeInProgress;
}

export default function BroadcastModal({ users, onClose }) {
  const [tab, setTab] = useState("new"); // 'new' | 'history'

  // ── Targeting ──────────────────────────────────────────────────────
  const [brandFilter, setBrandFilter] = useState(new Set());
  const [statusFilter, setStatusFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [activeDays, setActiveDays] = useState("");
  const [excluded, setExcluded] = useState(new Set());
  const [consultMap, setConsultMap] = useState({}); // phone -> latest consultation status
  const [recipientSearch, setRecipientSearch] = useState("");

  // ── Content ────────────────────────────────────────────────────────
  const [message, setMessage] = useState("");
  const [file, setFile] = useState(null);
  const fileInputRef = useRef(null);
  const [templates, setTemplates] = useState([]);
  const [templateName, setTemplateName] = useState("");
  const [savingTemplate, setSavingTemplate] = useState(false);

  // ── Sending mechanics ──────────────────────────────────────────────
  const [minDelayMs, setMinDelayMs] = useState(400);
  const [maxDelayMs, setMaxDelayMs] = useState(900);
  const [scheduleAt, setScheduleAt] = useState("");

  // ── Flow state ─────────────────────────────────────────────────────
  const [confirming, setConfirming] = useState(false);
  const [broadcasting, setBroadcasting] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [result, setResult] = useState(null); // { ok, fail, id, recipients: [{phone,name,status}], scheduled }
  const [retrying, setRetrying] = useState(false);
  const [uploadedFileMeta, setUploadedFileMeta] = useState(null); // { file_name, media_path, media_type }

  // ── History ────────────────────────────────────────────────────────
  const [history, setHistory] = useState(null);
  const [historyOpenId, setHistoryOpenId] = useState(null);
  const [historyDetail, setHistoryDetail] = useState({});

  const cancelRef = useRef(false);
  const modalRef = useRef(null);

  const handleOverlayClick = (e) => {
    if (!modalRef.current?.contains(e.target)) onClose();
  };

  useEffect(() => {
    api.getConsultations({ stage: "all" }).then((rows) => {
      const map = {};
      for (const c of rows || []) {
        const prev = map[c.phone];
        if (!prev || (c.updated_at || "") > (prev.updated_at || "")) {
          map[c.phone] = { status: c.status, updated_at: c.updated_at || c.created_at || "" };
        }
      }
      setConsultMap(map);
    }).catch(() => {});
    api.listBroadcastTemplates().then(setTemplates).catch(() => {});
  }, []);

  useEffect(() => {
    if (tab === "history" && history === null) {
      api.listBroadcasts(50).then(setHistory).catch(() => setHistory([]));
    }
  }, [tab, history]);

  // ── Filtering ──────────────────────────────────────────────────────
  const filteredUsers = useMemo(() => {
    const tagQ = tagFilter.trim().toLowerCase();
    const searchQ = recipientSearch.trim().toLowerCase();
    return (users || []).filter((u) => {
      if (brandFilter.size > 0 && !brandFilter.has(u.source || "")) return false;
      if (statusFilter) {
        const c = consultMap[u.phone];
        const st = c ? c.status : "none";
        if (statusFilter !== st) return false;
      }
      if (tagQ && !(u.tags || "").toLowerCase().includes(tagQ)) return false;
      if (activeDays !== "" && daysAgo(u.last_seen) > Number(activeDays)) return false;
      if (searchQ) {
        const hay = `${u.name || ""} ${u.phone || ""}`.toLowerCase();
        if (!hay.includes(searchQ)) return false;
      }
      return true;
    });
  }, [users, brandFilter, statusFilter, tagFilter, activeDays, consultMap, recipientSearch]);

  const recipients = useMemo(
    () => filteredUsers.filter((u) => !excluded.has(u.phone)),
    [filteredUsers, excluded]
  );

  const toggleBrand = (key) => {
    setBrandFilter((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  const toggleRecipient = (phone) => {
    setExcluded((prev) => {
      const next = new Set(prev);
      next.has(phone) ? next.delete(phone) : next.add(phone);
      return next;
    });
  };

  const selectAll = () => setExcluded(new Set());
  const selectNone = () => setExcluded(new Set(filteredUsers.map((u) => u.phone)));

  // ── Templates ──────────────────────────────────────────────────────
  const applyTemplate = (t) => setMessage(t.message);

  const saveTemplate = async () => {
    if (!templateName.trim() || !message.trim()) return;
    setSavingTemplate(true);
    try {
      await api.createBroadcastTemplate(templateName.trim(), message);
      setTemplates(await api.listBroadcastTemplates());
      setTemplateName("");
    } catch {
      // best-effort — keep the message the user already typed either way
    } finally {
      setSavingTemplate(false);
    }
  };

  const removeTemplate = async (id) => {
    try {
      await api.deleteBroadcastTemplate(id);
      setTemplates((prev) => prev.filter((t) => t.id !== id));
    } catch {}
  };

  // ── Sending ────────────────────────────────────────────────────────
  const jitter = () => {
    const min = Math.max(0, Number(minDelayMs) || 0);
    const max = Math.max(min, Number(maxDelayMs) || min);
    return min + Math.random() * (max - min);
  };

  const requestSend = () => {
    if ((!message.trim() && !file) || recipients.length === 0) return;
    if (!confirming && recipients.length > CONFIRM_THRESHOLD) {
      setConfirming(true);
      return;
    }
    send();
  };

  const send = async () => {
    setConfirming(false);
    setBroadcasting(true);
    cancelRef.current = false;

    try {
      let fileMeta = {};
      if (file) {
        const uploaded = await api.uploadBroadcastMedia(file);
        fileMeta = {
          file_name: uploaded.file_name,
          media_path: uploaded.media_path,
          media_type: uploaded.media_type,
        };
        setUploadedFileMeta(fileMeta);
      }

      const scheduledIso = scheduleAt ? new Date(scheduleAt).toISOString() : undefined;

      const { id } = await api.createBroadcast({
        message,
        recipients: recipients.map((u) => ({ phone: u.phone, name: u.name })),
        ...fileMeta,
        scheduled_at: scheduledIso,
        min_delay_ms: Number(minDelayMs) || 400,
        max_delay_ms: Number(maxDelayMs) || 900,
      });

      if (scheduledIso) {
        setBroadcasting(false);
        setResult({ scheduled: true, scheduledAt: scheduleAt, total: recipients.length, id });
        return;
      }

      setProgress({ current: 0, total: recipients.length });
      const statuses = recipients.map((u) => ({ phone: u.phone, name: u.name, status: "pending" }));
      let ok = 0, fail = 0;

      for (let i = 0; i < recipients.length; i++) {
        if (cancelRef.current) break;
        const u = recipients[i];
        setProgress({ current: i + 1, total: recipients.length });
        let sendOk = false;
        try {
          if (fileMeta.media_path) {
            await api.sendBroadcastMedia(
              u.phone, fileMeta.media_path, fileMeta.media_type,
              personalize(message, u.name)
            );
          } else {
            await api.sendMessage(u.phone, personalize(message, u.name));
          }
          sendOk = true;
          ok++;
        } catch {
          fail++;
        }
        const st = sendOk ? "sent" : "failed";
        statuses[i].status = st;
        api.updateBroadcastRecipient(id, u.phone, st).catch(() => {});
        if (i < recipients.length - 1) await new Promise((r) => setTimeout(r, jitter()));
      }

      const finalStatus = cancelRef.current ? "stopped" : "completed";
      await api.finishBroadcast(id, finalStatus).catch(() => {});

      setBroadcasting(false);
      setResult({ ok, fail, id, recipients: statuses, status: finalStatus });
    } catch (e) {
      setBroadcasting(false);
      setResult({ ok: 0, fail: recipients.length, error: e.message || "Broadcast failed" });
    }
  };

  const retryFailed = async () => {
    if (!result?.recipients || !result.id) return;
    const failedOnes = result.recipients.filter((r) => r.status === "failed");
    if (failedOnes.length === 0) return;
    setRetrying(true);
    const updated = [...result.recipients];
    let ok = result.ok, fail = result.fail;

    for (const r of failedOnes) {
      if (cancelRef.current) break;
      let sendOk = false;
      try {
        if (uploadedFileMeta?.media_path) {
          await api.sendBroadcastMedia(
            r.phone, uploadedFileMeta.media_path, uploadedFileMeta.media_type,
            personalize(message, r.name)
          );
        } else {
          await api.sendMessage(r.phone, personalize(message, r.name));
        }
        sendOk = true;
      } catch {}
      const idx = updated.findIndex((x) => x.phone === r.phone);
      const st = sendOk ? "sent" : "failed";
      if (idx !== -1) updated[idx] = { ...updated[idx], status: st };
      if (sendOk) { ok++; fail--; }
      await api.updateBroadcastRecipient(result.id, r.phone, st).catch(() => {});
      await new Promise((res) => setTimeout(res, jitter()));
    }
    await api.finishBroadcast(result.id, "completed").catch(() => {});
    setResult({ ...result, ok, fail, recipients: updated, status: "completed" });
    setRetrying(false);
  };

  const reset = () => {
    setResult(null);
    setConfirming(false);
    setProgress({ current: 0, total: 0 });
    setFile(null);
    setUploadedFileMeta(null);
    setMessage("");
    setScheduleAt("");
  };

  // ── History detail ─────────────────────────────────────────────────
  const openHistoryItem = async (id) => {
    if (historyOpenId === id) { setHistoryOpenId(null); return; }
    setHistoryOpenId(id);
    if (!historyDetail[id]) {
      try {
        const d = await api.getBroadcast(id);
        setHistoryDetail((prev) => ({ ...prev, [id]: d }));
      } catch {}
    }
  };

  const charCount = message.length;
  const overLimit = charCount > CHAR_LIMIT;

  return (
    <div className={m.overlay} onMouseDown={handleOverlayClick}>
      <div className={`${m.modal} ${m.wide}`} ref={modalRef}>
        <div className={m.header}>
          <h2>Broadcast</h2>
          <button className={m.closeBtn} onClick={onClose}>×</button>
        </div>

        <div className={s.tabs} style={{ padding: "0 20px" }}>
          <button
            className={`${s.tab} ${tab === "new" ? s.tabActive : ""}`}
            onClick={() => setTab("new")}
          >New broadcast</button>
          <button
            className={`${s.tab} ${tab === "history" ? s.tabActive : ""}`}
            onClick={() => setTab("history")}
          >History</button>
        </div>

        <div className={`${m.body} ${m.scrollable}`}>
          {tab === "new" && !result && (
            <>
              {/* ── Targeting ── */}
              <div className={s.section}>
                <div className={s.sectionTitle}>Targeting</div>
                <div className={s.filterRow} style={{ marginBottom: 8 }}>
                  {Object.entries(BRAND_LABELS).map(([key, label]) => (
                    <label key={key || "organic"} className={s.checkboxLabel}>
                      <input
                        type="checkbox"
                        checked={brandFilter.has(key)}
                        onChange={() => toggleBrand(key)}
                      />
                      {label}
                    </label>
                  ))}
                </div>
                <div className={s.filterRow}>
                  <select
                    className={s.filterSelect}
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                  >
                    <option value="">Any consultation status</option>
                    {Object.entries(CONSULT_STATUS_LABELS).map(([k, v]) => (
                      <option key={k} value={k}>{v}</option>
                    ))}
                  </select>
                  <input
                    className={s.filterInput}
                    placeholder="Filter by tag..."
                    value={tagFilter}
                    onChange={(e) => setTagFilter(e.target.value)}
                  />
                  <input
                    className={s.filterInput}
                    style={{ flex: "none", width: 170 }}
                    type="number"
                    min="0"
                    placeholder="Active in last N days"
                    value={activeDays}
                    onChange={(e) => setActiveDays(e.target.value)}
                  />
                </div>
              </div>

              {/* ── Recipients ── */}
              <div className={s.section}>
                <div className={s.recipientBar}>
                  <span>
                    <strong>{recipients.length}</strong> of {filteredUsers.length} matched will receive this
                    {excluded.size > 0 && ` (${excluded.size} deselected)`}
                  </span>
                  <span>
                    <button className={s.linkBtn} onClick={selectAll}>Select all</button>
                    <button className={s.linkBtn} onClick={selectNone}>Select none</button>
                  </span>
                </div>
                <input
                  className={s.filterInput}
                  style={{ width: "100%", boxSizing: "border-box", marginBottom: 8 }}
                  placeholder="Search matched recipients by name or phone..."
                  value={recipientSearch}
                  onChange={(e) => setRecipientSearch(e.target.value)}
                />
                <div className={s.recipientList}>
                  {filteredUsers.length === 0 ? (
                    <div className={s.emptyState}>No users match these filters.</div>
                  ) : (
                    filteredUsers.map((u) => (
                      <label key={u.phone} className={s.recipientItem}>
                        <input
                          type="checkbox"
                          checked={!excluded.has(u.phone)}
                          onChange={() => toggleRecipient(u.phone)}
                        />
                        <span className={s.recipientName}>{u.name || "Unnamed"}</span>
                        <span className={s.recipientPhone}>{u.phone}</span>
                      </label>
                    ))
                  )}
                </div>
              </div>

              {/* ── Content ── */}
              <div className={s.section}>
                <div className={s.sectionTitle}>Message</div>
                <textarea
                  className={m.textarea}
                  rows={5}
                  placeholder="Type your broadcast message... use {{name}} to personalize"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                />
                <div className={`${s.charCount} ${overLimit ? s.charCountOver : ""}`}>
                  {charCount} / {CHAR_LIMIT}
                </div>

                <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 10 }}>
                  <button
                    className={m.cancelBtn}
                    onClick={() => fileInputRef.current?.click()}
                    type="button"
                  >
                    📎 {file ? "Change attachment" : "Attach file"}
                  </button>
                  {file && (
                    <>
                      <span style={{ fontSize: 13, color: "#555" }}>{file.name}</span>
                      <button className={s.linkBtn} onClick={() => { setFile(null); setUploadedFileMeta(null); }}>Remove</button>
                    </>
                  )}
                  <input
                    ref={fileInputRef}
                    type="file"
                    style={{ display: "none" }}
                    onChange={(e) => { setFile(e.target.files?.[0] || null); setUploadedFileMeta(null); }}
                  />
                </div>

                <div className={s.templateRow}>
                  <select
                    className={s.filterSelect}
                    style={{ flex: 1 }}
                    value=""
                    onChange={(e) => {
                      const t = templates.find((t) => String(t.id) === e.target.value);
                      if (t) applyTemplate(t);
                    }}
                  >
                    <option value="">Load a saved template...</option>
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                  {templates.length > 0 && (
                    <select
                      className={s.filterSelect}
                      value=""
                      onChange={(e) => { if (e.target.value) removeTemplate(Number(e.target.value)); }}
                    >
                      <option value="">Delete a template...</option>
                      {templates.map((t) => (
                        <option key={t.id} value={t.id}>{t.name}</option>
                      ))}
                    </select>
                  )}
                </div>
                <div className={s.templateRow}>
                  <input
                    className={s.filterInput}
                    placeholder="Save current message as template..."
                    value={templateName}
                    onChange={(e) => setTemplateName(e.target.value)}
                  />
                  <button
                    className={m.cancelBtn}
                    disabled={!templateName.trim() || !message.trim() || savingTemplate}
                    onClick={saveTemplate}
                  >Save</button>
                </div>
              </div>

              {/* ── Sending mechanics ── */}
              <div className={s.section}>
                <div className={s.sectionTitle}>Sending</div>
                <div className={s.settingsGrid}>
                  <label className={m.field} style={{ marginBottom: 0 }}>
                    <span style={{ fontSize: 13, color: "#555" }}>Min delay between sends (ms)</span>
                    <input
                      className={m.input}
                      type="number"
                      min="0"
                      value={minDelayMs}
                      onChange={(e) => setMinDelayMs(e.target.value)}
                    />
                  </label>
                  <label className={m.field} style={{ marginBottom: 0 }}>
                    <span style={{ fontSize: 13, color: "#555" }}>Max delay between sends (ms)</span>
                    <input
                      className={m.input}
                      type="number"
                      min="0"
                      value={maxDelayMs}
                      onChange={(e) => setMaxDelayMs(e.target.value)}
                    />
                  </label>
                </div>
                <label className={m.field} style={{ marginTop: 12, marginBottom: 0 }}>
                  <span style={{ fontSize: 13, color: "#555" }}>Schedule for later (optional)</span>
                  <input
                    className={m.input}
                    type="datetime-local"
                    value={scheduleAt}
                    min={new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16)}
                    onChange={(e) => setScheduleAt(e.target.value)}
                  />
                </label>
              </div>

              {confirming && (
                <div className={s.confirmBox}>
                  You're about to send this to <strong>{recipients.length}</strong> people
                  {scheduleAt ? ` (scheduled for ${new Date(scheduleAt).toLocaleString()})` : ""}.
                  This can't be undone once sending starts. Send anyway?
                </div>
              )}

              {broadcasting && (
                <div className={s.section} style={{ marginTop: 0 }}>
                  <div className={m.progressWrap}>
                    <div className={m.progressBar}>
                      <div
                        className={m.progressFill}
                        style={{ width: `${(progress.current / progress.total) * 100}%` }}
                      />
                    </div>
                    <div className={m.progressText}>{progress.current} / {progress.total}</div>
                  </div>
                </div>
              )}
            </>
          )}

          {tab === "new" && result && (
            <div>
              {result.scheduled ? (
                <>
                  <p>Broadcast scheduled for <strong>{new Date(result.scheduledAt).toLocaleString()}</strong>.</p>
                  <p>Will send to {result.total} recipient(s) automatically — you can close this window.</p>
                </>
              ) : result.error ? (
                <p>Broadcast failed to start: {result.error}</p>
              ) : (
                <>
                  <p>Broadcast {result.status === "stopped" ? "stopped" : "complete"}.</p>
                  <p>Sent: {result.ok} &nbsp; Failed: {result.fail}</p>
                  {result.recipients && (
                    <div className={s.recipientList} style={{ maxHeight: 220, marginTop: 10 }}>
                      {result.recipients.map((r) => (
                        <div key={r.phone} className={s.recipientItem}>
                          <span className={s.recipientName}>{r.name || "Unnamed"}</span>
                          <span className={s.recipientPhone}>{r.phone}</span>
                          <span className={`${s.recipientStatus} ${
                            r.status === "sent" ? s.statusSent : r.status === "failed" ? s.statusFailed : s.statusPending
                          }`}>{r.status}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {result.fail > 0 && (
                    <button
                      className={m.primaryBtn}
                      style={{ marginTop: 12 }}
                      onClick={retryFailed}
                      disabled={retrying}
                    >{retrying ? "Retrying..." : `Retry ${result.fail} failed`}</button>
                  )}
                </>
              )}
              <div style={{ marginTop: 16, display: "flex", gap: 10 }}>
                <button className={m.cancelBtn} onClick={reset}>New broadcast</button>
                <button className={m.primaryBtn} onClick={onClose}>Close</button>
              </div>
            </div>
          )}

          {tab === "history" && (
            <div>
              {history === null ? (
                <div className={s.emptyState}>Loading...</div>
              ) : history.length === 0 ? (
                <div className={s.emptyState}>No broadcasts sent yet.</div>
              ) : (
                history.map((b) => (
                  <div key={b.id} className={s.historyItem}>
                    <div className={s.historyTop}>
                      <span>
                        {b.scheduled_at ? `Scheduled ${new Date(b.scheduled_at).toLocaleString()}` : new Date(b.created_at).toLocaleString()}
                        {b.created_by_name ? ` · ${b.created_by_name}` : ""}
                      </span>
                      <span className={`${s.badge} ${badgeClass(b.status)}`}>{b.status}</span>
                    </div>
                    <div className={s.historyMsg}>
                      {b.message || `📎 ${b.file_name}`}
                    </div>
                    <div className={s.historyStats}>
                      <span>Total: {b.total}</span>
                      <span>Sent: {b.sent}</span>
                      <span>Failed: {b.failed}</span>
                      <button className={s.linkBtn} onClick={() => openHistoryItem(b.id)}>
                        {historyOpenId === b.id ? "Hide details" : "View details"}
                      </button>
                    </div>
                    {historyOpenId === b.id && historyDetail[b.id] && (
                      <div className={s.recipientList} style={{ marginTop: 10, maxHeight: 200 }}>
                        {historyDetail[b.id].recipients.map((r) => (
                          <div key={r.phone} className={s.recipientItem}>
                            <span className={s.recipientName}>{r.name || "Unnamed"}</span>
                            <span className={s.recipientPhone}>{r.phone}</span>
                            <span className={`${s.recipientStatus} ${
                              r.status === "sent" ? s.statusSent : r.status === "failed" ? s.statusFailed : s.statusPending
                            }`}>{r.status}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {tab === "new" && !result && (
          <div className={m.footer}>
            {broadcasting ? (
              <button className={m.cancelBtn} onClick={() => { cancelRef.current = true; }}>Stop</button>
            ) : (
              <button className={m.cancelBtn} onClick={confirming ? () => setConfirming(false) : onClose}>
                {confirming ? "Back" : "Cancel"}
              </button>
            )}
            <button
              className={m.primaryBtn}
              onClick={requestSend}
              disabled={broadcasting || (!message.trim() && !file) || recipients.length === 0 || overLimit}
            >
              {broadcasting
                ? "Sending..."
                : confirming
                ? "Yes, send"
                : scheduleAt
                ? "Schedule broadcast"
                : "Send broadcast"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}