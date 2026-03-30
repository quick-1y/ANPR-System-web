let debugLogSource = null;
let debugLogReconnectTimer = null;
let lastDebugLogId = 0;

let api = null;
let apiUrl = null;
let jfetch = null;
let scheduleVideoGridLayout = null;

function mapLogClass(level) {
  const v = String(level || "INFO").toUpperCase();
  if (v === "CRITICAL") return "crit";
  if (v === "ERROR") return "err";
  if (v === "WARNING") return "warn";
  if (v === "DEBUG") return "dbg";
  return "ok";
}

function prependDebugLine(text, type = "info", timestamp = null, meta = "") {
  const log = document.getElementById("debugLog");
  if (!log) return;
  const line = document.createElement("div");
  line.className = `log-line ${type}`;
  const ts = timestamp ? new Date(timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
  line.innerHTML = `<span class='log-ts'>${ts}</span>${meta ? ` <span class='log-meta'>${meta}</span>` : ""} ${text}`;
  log.prepend(line);
  while (log.children.length > 300) log.removeChild(log.lastElementChild);
}

function scheduleDebugLogReconnect(delayMs = 2000) {
  if (debugLogReconnectTimer) return;
  debugLogReconnectTimer = setTimeout(() => {
    debugLogReconnectTimer = null;
    setupDebugLogStream();
  }, delayMs);
}

export function initDebugModule(deps) {
  api = deps.api;
  apiUrl = deps.apiUrl;
  jfetch = deps.jfetch;
  scheduleVideoGridLayout = deps.scheduleVideoGridLayout;

  const toggleDebugPanelBtn = document.getElementById("toggleDebugPanelBtn");
  if (!toggleDebugPanelBtn) return;
  toggleDebugPanelBtn.onclick = () => {
    const panel = document.getElementById("obsDebugPanel");
    if (!panel) return;
    const collapsed = panel.dataset.collapsed === "1";
    panel.dataset.collapsed = collapsed ? "0" : "1";
    toggleDebugPanelBtn.textContent = collapsed ? "Свернуть" : "Развернуть";
    if (scheduleVideoGridLayout) scheduleVideoGridLayout(true);
  };
}

export function applyDebugPanelVisibility(debugSettingsCache) {
  const panel = document.getElementById("obsDebugPanel");
  const btn = document.getElementById("toggleDebugPanelBtn");
  if (!panel) return;
  const enabled = Boolean((debugSettingsCache || {}).log_panel_enabled);
  panel.style.display = enabled ? "flex" : "none";
  if (scheduleVideoGridLayout) scheduleVideoGridLayout(true);
  if (!enabled) return;
  if (!panel.dataset.collapsed) panel.dataset.collapsed = "0";
  if (btn) {
    btn.textContent = panel.dataset.collapsed === "1" ? "Развернуть" : "Свернуть";
  }
}

export async function loadDebugLogHistory() {
  try {
    const payload = await jfetch(api("/api/debug/logs?limit=150"));
    const items = Array.isArray(payload.items) ? payload.items : [];
    items.reverse().forEach((item) => {
      lastDebugLogId = Math.max(lastDebugLogId, Number(item.id || 0));
      const prefix = `[${item.level}] ${item.service}/${item.logger}${item.channel_id ? ` #${item.channel_id}` : ""}`;
      prependDebugLine(item.message, mapLogClass(item.level), item.timestamp, prefix);
    });
  } catch (err) {
    prependDebugLine(`[WARN] не удалось загрузить историю логов: ${err.message}`, "warn");
  }
}

export function setupDebugLogStream() {
  if (debugLogSource) {
    try { debugLogSource.close(); } catch (_e) {}
  }
  debugLogSource = new EventSource(apiUrl(`/api/debug/logs/stream?last_id=${lastDebugLogId}`));
  debugLogSource.onmessage = (evt) => {
    try {
      const item = JSON.parse(evt.data);
      lastDebugLogId = Math.max(lastDebugLogId, Number(item.id || 0));
      const prefix = `[${item.level}] ${item.service}/${item.logger}${item.channel_id ? ` #${item.channel_id}` : ""}`;
      prependDebugLine(item.message, mapLogClass(item.level), item.timestamp, prefix);
    } catch (_e) {}
  };
  debugLogSource.onerror = () => {
    try { debugLogSource.close(); } catch (_e) {}
    scheduleDebugLogReconnect();
  };
}

export function cleanupDebugLogStream() {
  if (!debugLogSource) return;
  try {
    debugLogSource.close();
  } catch (_e) {}
  debugLogSource = null;
}
