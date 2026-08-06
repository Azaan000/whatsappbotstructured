import React, { useState, useRef } from "react";
import { api } from "../api/client";
import s from "../styles/Auth.module.css";
import bizLogo from "../assets/logos/bizadvise-logo.png";
import lawLogo from "../assets/logos/lawadvise-logo.png";

export default function Login({ onAuthenticated }) {
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const cardWrapRef = useRef(null);

  const switchMode = (next) => {
    setMode(next);
    setError("");
  };

  const submit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    setError("");
    setSubmitting(true);
    try {
      const user =
        mode === "login"
          ? await api.login(username.trim(), password)
          : await api.register(username.trim(), password, displayName.trim());
      onAuthenticated(user);
    } catch (err) {
      setError(err.message || "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  // Subtle mouse-tilt on the card — skipped for reduced-motion users and
  // touch devices (no mousemove there anyway). Applied via ref so it
  // doesn't trigger a re-render on every pixel of mouse movement.
  const handleMouseMove = (e) => {
    const el = cardWrapRef.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const rect = el.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width - 0.5;
    const y = (e.clientY - rect.top) / rect.height - 0.5;
    el.style.transform = `rotateY(${x * 6}deg) rotateX(${-y * 6}deg)`;
  };
  const handleMouseLeave = () => {
    const el = cardWrapRef.current;
    if (el) el.style.transform = "rotateY(0deg) rotateX(0deg)";
  };

  return (
    <div className={s.page} onMouseMove={handleMouseMove} onMouseLeave={handleMouseLeave}>
      <span className={s.glowThird} aria-hidden="true" />
      <span className={`${s.spark} ${s.spark1}`} aria-hidden="true" />
      <span className={`${s.spark} ${s.spark2}`} aria-hidden="true" />
      <span className={`${s.spark} ${s.spark3}`} aria-hidden="true" />
      <span className={`${s.spark} ${s.spark4}`} aria-hidden="true" />
      <span className={`${s.spark} ${s.spark5}`} aria-hidden="true" />
      <span className={`${s.spark} ${s.spark6}`} aria-hidden="true" />
      <span className={`${s.spark} ${s.spark7}`} aria-hidden="true" />

      <div className={s.cardWrap} ref={cardWrapRef}>
        <div className={s.card}>
          {/* Brand header — both logos converging behind a pulsing gold
              ring, then the shimmering title, on the same navy panel
              used throughout the dashboard. */}
          <div className={s.brandHeader}>
            <div className={s.logoRow}>
              <img src={bizLogo} alt="BizAdvise Consulting" className={`${s.logoCircle} ${s.logoLeft}`} />
              <span className={s.logoDivider} />
              <img src={lawLogo} alt="LawAdvise Consulting" className={`${s.logoCircle} ${s.logoRight}`} />
            </div>
            <h1 className={s.title}>BizAdvise & LawAdvise</h1>
            <p className={s.subtitle}>Staff dashboard</p>
          </div>

          <div className={s.formBody}>
            <div className={s.tabs}>
              <span
                className={`${s.tabThumb} ${mode === "register" ? s.tabThumbRegister : ""}`}
                aria-hidden="true"
              />
              <button
                type="button"
                className={`${s.tab} ${mode === "login" ? s.tabActive : ""}`}
                onClick={() => switchMode("login")}
              >
                Log in
              </button>
              <button
                type="button"
                className={`${s.tab} ${mode === "register" ? s.tabActive : ""}`}
                onClick={() => switchMode("register")}
              >
                Create account
              </button>
            </div>

            {error && <div className={s.error}>{error}</div>}

            <form onSubmit={submit}>
              {mode === "register" && (
                <div className={s.field}>
                  <label>Display name (optional)</label>
                  <input
                    className={s.input}
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="e.g. Jordan"
                    autoComplete="name"
                  />
                </div>
              )}

              <div className={s.field}>
                <label>Username</label>
                <input
                  className={s.input}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="username"
                  autoComplete="username"
                  required
                />
                {mode === "register" && (
                  <div className={s.hint}>3-32 characters: letters, numbers, underscore, dot</div>
                )}
              </div>

              <div className={s.field}>
                <label>Password</label>
                <input
                  className={s.input}
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  required
                />
                {mode === "register" && (
                  <div className={s.hint}>At least 8 characters</div>
                )}
              </div>

              <button className={s.submitBtn} type="submit" disabled={submitting}>
                <span className={s.submitLabel}>
                  {submitting && <span className={s.spinner} aria-hidden="true" />}
                  {submitting
                    ? mode === "login" ? "Logging in…" : "Creating account…"
                    : mode === "login" ? "Log in" : "Create account"}
                </span>
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}