import React, { useState } from "react";
import { api } from "../api/client";
import s from "../styles/Auth.module.css";

export default function Login({ onAuthenticated }) {
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

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

  return (
    <div className={s.page}>
      <div className={s.card}>
        <h1 className={s.title}>BizAdvise & LawAdvise</h1>
        <p className={s.subtitle}>Staff dashboard</p>

        <div className={s.tabs}>
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
            {submitting
              ? mode === "login" ? "Logging in…" : "Creating account…"
              : mode === "login" ? "Log in" : "Create account"}
          </button>
        </form>
      </div>
    </div>
  );
}