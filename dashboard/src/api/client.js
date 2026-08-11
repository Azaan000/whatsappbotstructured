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
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "null");
  } catch {
    return null;
  }
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

  setDashboardUserAdmin: (id, isAdmin) =>
    request(`/dashboard-users/${id}/admin`, {
      method: "PUT",
      body: JSON.stringify({ is_admin: isAdmin }),
    }),

  // ── Dashboard endpoints ───────────────────────────────────────────
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
      if (r.status === 401) {
        clearSession();
        onUnauthorized();
      }
      if (!r.ok) throw new Error("Failed to send file");
      return r.json();
    });
  },

  toggleMode: (phone) =>
    request(`/toggle/${phone}`, { method: "POST" }),

  // Persists "read up to here" server-side (see /mark-read/<phone> in
  // backend/routes/chat.py) so the unread badge survives a re-login and
  // stays in sync if the dashboard is open in more than one tab/device.
  markRead: (phone) =>
    request(`/mark-read/${phone}`, { method: "POST" }),

  updateUser: (phone, tags, notes) =>
    request("/update-user", {
      method: "POST",
      body: JSON.stringify({ phone, tags, notes }),
    }),

  deleteUser: (phone) =>
    request(`/delete-user/${phone}`, { method: "DELETE" }),

  getAnalytics: () => request("/analytics"),

  getConsultations: (filters = {}) => {
    const params = new URLSearchParams(
      Object.entries(filters).filter(([, v]) => v !== undefined && v !== null && v !== "")
    );
    const qs = params.toString();
    return request(`/consultations${qs ? `?${qs}` : ""}`);
  },

  updateConsultation: (id, patch) =>
    request(`/consultations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  getConsultationFunnel: (brand = "") =>
    request(`/consultations/funnel${brand ? `?brand=${encodeURIComponent(brand)}` : ""}`),

  exportCsv: (phone = null) => {
    const params = new URLSearchParams({ token: authToken() });
    if (phone) params.append("phone", phone);
    window.open(`${BASE}/export/csv?${params.toString()}`, "_blank");
  },

  reloadKnowledge: () =>
    request("/reload-knowledge", { method: "POST" }),

  // ── Broadcasts ────────────────────────────────────────────────────
  listBroadcasts: (limit = 50) => request(`/broadcasts?limit=${limit}`),

  getBroadcast: (id) => request(`/broadcasts/${id}`),

  createBroadcast: (payload) =>
    request("/broadcasts", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateBroadcastRecipient: (id, phone, status) =>
    request(`/broadcasts/${id}/recipient`, {
      method: "PATCH",
      body: JSON.stringify({ phone, status }),
    }),

  finishBroadcast: (id, status = "completed") =>
    request(`/broadcasts/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),

  uploadBroadcastMedia: (file) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/broadcasts/upload`, {
      method: "POST",
      headers: { "X-Dashboard-Token": authToken() },
      body: form,
    }).then(async (r) => {
      if (r.status === 401) {
        clearSession();
        onUnauthorized();
      }
      if (!r.ok) throw new Error("Failed to upload file");
      return r.json();
    });
  },

  // Sends a file already stored via uploadBroadcastMedia to one
  // recipient, reusing that single stored copy — unlike sendFile,
  // which re-uploads and re-saves a fresh copy to disk on every call
  // (fine for one-off sends, wasteful/duplicative in a broadcast loop).
  sendBroadcastMedia: (phone, mediaPath, mediaType, caption = "") =>
    request("/broadcasts/send-media", {
      method: "POST",
      body: JSON.stringify({ phone, media_path: mediaPath, media_type: mediaType, caption }),
    }),

  listBroadcastTemplates: () => request("/broadcast-templates"),

  createBroadcastTemplate: (name, message) =>
    request("/broadcast-templates", {
      method: "POST",
      body: JSON.stringify({ name, message }),
    }),

  deleteBroadcastTemplate: (id) =>
    request(`/broadcast-templates/${id}`, { method: "DELETE" }),
};

export { BASE };