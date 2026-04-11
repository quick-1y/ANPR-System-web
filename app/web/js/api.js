// API layer — fetch wrapper, JWT auth helpers

const TOKEN_STORAGE = "anpr_token";

export function api(path) {
  return `${document.getElementById("apiBase").value.trim()}${path}`;
}

export function getToken() { return localStorage.getItem(TOKEN_STORAGE) || ""; }
export function setToken(t) { if (t) localStorage.setItem(TOKEN_STORAGE, t); else localStorage.removeItem(TOKEN_STORAGE); }

/**
 * Check if the stored JWT is expired (decoded client-side, no network).
 * Returns true when the token is missing, malformed, or past its exp claim.
 */
export function isTokenExpired() {
  const token = getToken();
  if (!token) return true;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    // exp is in seconds; Date.now() is in milliseconds
    return Date.now() >= payload.exp * 1000;
  } catch (_e) {
    return true;
  }
}

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

/** Notify the server about logout (best-effort, for audit logging). */
export async function logoutRequest() {
  const t = getToken();
  try {
    await fetch(api("/api/auth/logout"), {
      method: "POST",
      headers: t
        ? { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" }
        : { "Content-Type": "application/json" },
    });
  } catch (_e) {
    // Ignore errors — client-side cleanup proceeds regardless
  }
}

export function showLoginOverlay(onSuccess) {
  const overlay = document.getElementById("login-overlay");
  if (!overlay) return;
  overlay.classList.add("active");
  const btn = document.getElementById("login-submit");
  const btnSpinner = document.getElementById("login-submit-spinner");
  const btnLabel = document.getElementById("login-submit-label");
  const loginInp = document.getElementById("login-input");
  const passInp = document.getElementById("login-password");
  const passToggle = document.getElementById("login-password-toggle");
  const capsHint = document.getElementById("login-caps-hint");
  const err = document.getElementById("login-error");
  let loading = false;

  const setLoading = (value) => {
    loading = value;
    if (btn) {
      btn.disabled = value;
      btn.classList.toggle("is-loading", value);
    }
    if (btnSpinner) btnSpinner.setAttribute("aria-hidden", value ? "false" : "true");
    if (btnLabel) btnLabel.textContent = value ? "Вход..." : "Войти";
  };

  const setCapsHint = (show) => {
    if (!capsHint) return;
    capsHint.classList.toggle("active", show);
  };

  const updateCapsState = (e) => {
    const isCapsOn = Boolean(e && e.getModifierState && e.getModifierState("CapsLock"));
    setCapsHint(isCapsOn);
  };

  const togglePasswordVisibility = () => {
    if (!passInp || !passToggle) return;
    const isHidden = passInp.type === "password";
    passInp.type = isHidden ? "text" : "password";
    passToggle.textContent = isHidden ? "Скрыть" : "Показать";
    passToggle.setAttribute("aria-label", isHidden ? "Скрыть пароль" : "Показать пароль");
    passInp.focus();
  };

  if (err) err.textContent = "";
  if (loginInp) loginInp.value = "";
  if (passInp) {
    passInp.value = "";
    passInp.type = "password";
  }
  if (passToggle) {
    passToggle.textContent = "Показать";
    passToggle.setAttribute("aria-label", "Показать пароль");
  }
  setCapsHint(false);
  setLoading(false);

  const handler = async () => {
    if (loading) return;
    const loginVal = (loginInp ? loginInp.value : "").trim();
    const passVal = passInp ? passInp.value : "";
    if (!loginVal || !passVal) {
      if (err) err.textContent = "Введите логин и пароль";
      return;
    }
    setLoading(true);
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
      setLoading(false);
    }
  };

  const keyHandler = (e) => {
    updateCapsState(e);
    if (e.key === "Enter") handler();
  };

  function cleanup() {
    if (btn) btn.removeEventListener("click", handler);
    if (loginInp) loginInp.removeEventListener("keydown", keyHandler);
    if (passInp) passInp.removeEventListener("keydown", keyHandler);
    if (passInp) passInp.removeEventListener("keyup", updateCapsState);
    if (passInp) passInp.removeEventListener("blur", handlePasswordBlur);
    if (passToggle) passToggle.removeEventListener("click", togglePasswordVisibility);
  }

  const handlePasswordBlur = () => setCapsHint(false);

  cleanup();
  if (btn) btn.addEventListener("click", handler);
  if (loginInp) loginInp.addEventListener("keydown", keyHandler);
  if (passInp) passInp.addEventListener("keydown", keyHandler);
  if (passInp) passInp.addEventListener("keyup", updateCapsState);
  if (passInp) passInp.addEventListener("blur", handlePasswordBlur);
  if (passToggle) passToggle.addEventListener("click", togglePasswordVisibility);

  setTimeout(() => { if (loginInp) loginInp.focus(); }, 50);
}

export async function jfetch(url, method = "GET", body = null) {
  // Pre-flight expiry check — avoids sending a request we know will fail
  if (isTokenExpired()) {
    setToken(null);
    showLoginOverlay(() => { location.reload(); });
    throw new Error("Токен авторизации истёк");
  }
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
