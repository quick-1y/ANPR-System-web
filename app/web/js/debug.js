// Debug panels, log stream
import { debugLogSource, debugLogReconnectTimer, lastDebugLogId, debugSettingsCache, setDebugLogSource, setDebugLogReconnectTimer, setLastDebugLogId, streamReconnectTimer, eventSource, setStreamReconnectTimer, setEventSource, isSuperAdmin } from './state.js';
import { api, apiUrl, jfetch } from './api.js';
import { scheduleVideoGridLayout } from './channels.js';
import { handleIncomingEvent } from './events.js';

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

export function applyDebugPanelVisibility() {
  const panel = document.getElementById("obsDebugPanel");
  if (!panel) return;
  if (!isSuperAdmin()) {
    panel.style.display = "none";
    scheduleVideoGridLayout(true);
    return;
  }
  const btn = document.getElementById("toggleDebugPanelBtn");
  const enabled = Boolean((debugSettingsCache || {}).log_panel_enabled);
  panel.style.display = enabled ? "flex" : "none";
  scheduleVideoGridLayout(true);
  if (!enabled) return;
  if (!panel.dataset.collapsed) panel.dataset.collapsed = "0";
  if (btn) btn.textContent = panel.dataset.collapsed === "1" ? "Развернуть" : "Свернуть";
}

function scheduleDebugLogReconnect(delayMs = 2000) {
  if (debugLogReconnectTimer) return;
  setDebugLogReconnectTimer(setTimeout(() => {
    setDebugLogReconnectTimer(null);
    setupDebugLogStream();
  }, delayMs));
}

export async function loadDebugLogHistory() {
  try {
    const payload = await jfetch(api("/api/debug/logs?limit=150"));
    const items = Array.isArray(payload.items) ? payload.items : [];
    items.reverse().forEach((item) => {
      setLastDebugLogId(Math.max(lastDebugLogId, Number(item.id || 0)));
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
  setDebugLogSource(new EventSource(apiUrl(`/api/debug/logs/stream?last_id=${lastDebugLogId}`)));
  debugLogSource.onmessage = (evt) => {
    try {
      const item = JSON.parse(evt.data);
      setLastDebugLogId(Math.max(lastDebugLogId, Number(item.id || 0)));
      const prefix = `[${item.level}] ${item.service}/${item.logger}${item.channel_id ? ` #${item.channel_id}` : ""}`;
      prependDebugLine(item.message, mapLogClass(item.level), item.timestamp, prefix);
    } catch (_e) {}
  };
  debugLogSource.onerror = () => {
    try { debugLogSource.close(); } catch (_e) {}
    scheduleDebugLogReconnect();
  };
}

function scheduleStreamReconnect(delayMs = 3000) {
  if (streamReconnectTimer) return;
  setStreamReconnectTimer(setTimeout(() => {
    setStreamReconnectTimer(null);
    setupStream();
  }, delayMs));
}

export function setupStream() {
  if (streamReconnectTimer) {
    clearTimeout(streamReconnectTimer);
    setStreamReconnectTimer(null);
  }
  if (eventSource) {
    try { eventSource.close(); } catch (_e) {}
  }
  setEventSource(new EventSource(apiUrl("/api/events/stream")));
  eventSource.onmessage = (m) => {
    try { handleIncomingEvent(JSON.parse(m.data)); } catch (_e) {}
  };
  eventSource.onerror = () => {
    try { eventSource.close(); } catch (_e) {}
    scheduleStreamReconnect();
  };
}
