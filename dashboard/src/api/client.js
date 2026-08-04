const BASE = process.env.REACT_APP_API_URL || "http://localhost:5000";

// Legacy shared-secret fallback (optional). Once every real user has
// their own login, this can be left unset — the per-user token below
// is the normal path now.
const SHARED_SECRET = process.env.REACT_APP_DASHBOARD_SECRET || "";

const TOKEN_KEY = "dashboard_token";
const USER_KEY = "dashboard_user";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function getStoredUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); }
  catch { return null; }
}

function setSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

// Called by App.js so that any 401 response anywhere (token expired,
// account deleted, etc.) can immediately drop the user back to the
// login screen instead of leaving them looking at a dead dashboard.
let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn || (() => {});
}

function authToken() {
  return getToken() || SHARED_SECRET;
}

function headers(extra = {}) {
  return {
    "Content-Type": "application/json",
    "X-Dashboard-Token": authToken(),
    ...extra,
  };
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: headers(),
    ...options,
  });
  if (res.status === 401) {
    clearSession();
    onUnauthorized();
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || "Request failed");
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // ── Auth ───────────────────────────────────────────────────────────
  register: async (username, password, displayName = "") => {
    const data = await request("/register", {
      method: "POST",
      body: JSON.stringify({ username, password, display_name: displayName }),
    });
    setSession(data.token, data.user);
    return data.user;
  },

  login: async (username, password) => {
    const data = await request("/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setSession(data.token, data.user);
    return data.user;
  },

  me: () => request("/me"),

  logout: () => clearSession(),

  deleteOwnAccount: (password) =>
    request("/account", {
      method: "DELETE",
      body: JSON.stringify({ password }),
    }),

  listDashboardUsers: () => request("/dashboard-users"),

  deleteDashboardUser: (id) =>
    request(`/dashboard-users/${id}`, { method: "DELETE" }),

  // ── Existing dashboard endpoints ──────────────────────────────────
  getUsers: () => request("/users"),

  getMessages: (phone, search = "") =>
    request(`/messages/${phone}${search ? `?search=${encodeURIComponent(search)}` : ""}`),

  sendMessage: (phone, message) =>
    request("/send", {
      method: "POST",
      body: JSON.stringify({ phone, message }),
    }),

  sendFile: (phone, file, caption = "") => {
    const form = new FormData();
    form.append("file", file);
    form.append("phone", phone);
    if (caption) form.append("caption", caption);
    return fetch(`${BASE}/send-file`, {
      method: "POST",
      headers: { "X-Dashboard-Token": authToken() },
      body: form,
    }).then(async (r) => {
      if (r.status === 401) { clearSession(); onUnauthorized(); }
      if (!r.ok) throw new Error("Failed to send file");
      return r.json();
    });
  },

  toggleMode: (phone) =>
    request(`/toggle/${phone}`, { method: "POST" }),

  updateUser: (phone, tags, notes) =>
    request("/update-user", {
      method: "POST",
      body: JSON.stringify({ phone, tags, notes }),
    }),

  deleteUser: (phone) =>
    request(`/delete-user/${phone}`, { method: "DELETE" }),

  getAnalytics: () => request("/analytics"),

  getConsultations: () => request("/consultations"),

  exportCsv: (phone = null) => {
    const params = new URLSearchParams({ token: authToken() });
    if (phone) params.append("phone", phone);
    window.open(`${BASE}/export/csv?${params.toString()}`, "_blank");
  },

  reloadKnowledge: () =>
    request("/reload-knowledge", { method: "POST" }),
};

export { BASE };