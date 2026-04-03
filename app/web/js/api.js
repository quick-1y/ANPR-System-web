// API layer — fetch wrapper, JWT auth helpers

const TOKEN_STORAGE = "anpr_token";

export function api(path) {
  return `${document.getElementById("apiBase").value.trim()}${path}`;
}

export function getToken() { return localStorage.getItem(TOKEN_STORAGE) || ""; }
export function setToken(t) { if (t) localStorage.setItem(TOKEN_STORAGE, t); else localStorage.removeItem(TOKEN_STORAGE); }

/** Append ?token=<jwt> when a token is configured (for EventSource / MJPEG URLs). */
export function apiUrl(path) {
  const t = getToken();
  return t ? `${api(path)}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(t)}` : api(path);
}

export async function loginRequest(loginStr, password) {
  const r = await fetch(api("/api/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ login: loginStr, password }),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.detail || "Неверный логин или пароль");
  }
  return r.json();
}

export async function getCurrentUser() {
  const t = getToken();
  const r = await fetch(api("/api/auth/me"), {
    headers: t ? { "Authorization": `Bearer ${t}` } : {},
  });
  if (!r.ok) throw new Error("Не авторизован");
  return r.json();
}

export function showLoginOverlay(onSuccess) {
  const overlay = document.getElementById("login-overlay");
  if (!overlay) return;
  overlay.classList.add("active");
  const btn = document.getElementById("login-submit");
  const loginInp = document.getElementById("login-input");
  const passInp = document.getElementById("login-password");
  const err = document.getElementById("login-error");
  if (err) err.textContent = "";
  if (loginInp) loginInp.value = "";
  if (passInp) passInp.value = "";

  const handler = async () => {
    const loginVal = (loginInp ? loginInp.value : "").trim();
    const passVal = passInp ? passInp.value : "";
    if (!loginVal || !passVal) {
      if (err) err.textContent = "Введите логин и пароль";
      return;
    }
    if (btn) btn.disabled = true;
    if (err) err.textContent = "";
    try {
      const data = await loginRequest(loginVal, passVal);
      setToken(data.access_token);
      overlay.classList.remove("active");
      cleanup();
      if (onSuccess) onSuccess(data.user);
    } catch (e) {
      if (err) err.textContent = e.message || "Ошибка входа";
    } finally {
      if (btn) btn.disabled = false;
    }
  };

  const keyHandler = (e) => { if (e.key === "Enter") handler(); };

  function cleanup() {
    if (btn) btn.removeEventListener("click", handler);
    if (loginInp) loginInp.removeEventListener("keydown", keyHandler);
    if (passInp) passInp.removeEventListener("keydown", keyHandler);
  }

  cleanup();
  if (btn) btn.addEventListener("click", handler);
  if (loginInp) loginInp.addEventListener("keydown", keyHandler);
  if (passInp) passInp.addEventListener("keydown", keyHandler);

  setTimeout(() => { if (loginInp) loginInp.focus(); }, 50);
}

export async function jfetch(url, method = "GET", body = null) {
  const headers = { "Content-Type": "application/json" };
  const t = getToken();
  if (t) headers["Authorization"] = `Bearer ${t}`;
  const r = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : null });
  if (r.status === 401) {
    setToken(null);
    showLoginOverlay(() => { location.reload(); });
    throw new Error("Требуется аутентификация");
  }
  if (!r.ok) throw new Error(await r.text());
  return r.status === 204 ? null : r.json();
}
