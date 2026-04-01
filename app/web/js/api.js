// API layer — fetch wrapper, auth helpers

const AUTH_KEY_STORAGE = "anpr_api_key";

export function api(path) {
  return `${document.getElementById("apiBase").value.trim()}${path}`;
}

export function getApiKey() { return localStorage.getItem(AUTH_KEY_STORAGE) || ""; }
export function setApiKey(k) { if (k) localStorage.setItem(AUTH_KEY_STORAGE, k); else localStorage.removeItem(AUTH_KEY_STORAGE); }

/** Append ?api_key=<key> when a key is configured (for EventSource / MJPEG URLs). */
export function apiUrl(path) {
  const k = getApiKey();
  return k ? `${api(path)}${path.includes("?") ? "&" : "?"}api_key=${encodeURIComponent(k)}` : api(path);
}

export function showAuthOverlay(onSuccess) {
  const overlay = document.getElementById("auth-overlay");
  if (!overlay) return;
  overlay.classList.add("active");
  const btn = document.getElementById("auth-submit");
  const inp = document.getElementById("auth-key-input");
  const err = document.getElementById("auth-error");
  if (err) err.textContent = "";
  const handler = async () => {
    const key = (inp ? inp.value : "").trim();
    if (!key) return;
    try {
      const r = await fetch(api("/api/health"), { headers: { "X-Api-Key": key } });
      if (r.ok) {
        setApiKey(key);
        overlay.classList.remove("active");
        if (btn) btn.removeEventListener("click", handler);
        if (onSuccess) onSuccess();
      } else {
        if (err) err.textContent = "Неверный ключ";
      }
    } catch {
      if (err) err.textContent = "Ошибка соединения";
    }
  };
  if (btn) { btn.removeEventListener("click", handler); btn.addEventListener("click", handler); }
}

export async function jfetch(url, method = "GET", body = null) {
  const headers = { "Content-Type": "application/json" };
  const k = getApiKey();
  if (k) headers["X-Api-Key"] = k;
  const r = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : null });
  if (r.status === 401) {
    showAuthOverlay(() => jfetch(url, method, body));
    throw new Error("Требуется аутентификация");
  }
  if (!r.ok) throw new Error(await r.text());
  return r.status === 204 ? null : r.json();
}
