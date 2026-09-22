// Personal UI toggles (class L / device state): sidebar pin, debug panel,
// channel metrics overlay. Device-local only — no server, no cross-
// workstation sync, same rule as theme/style (appearance.js) and grid layout
// (video-grid.js). A missing/blocked localStorage just means every toggle
// starts at its default (off).
import { setChk } from './ui.js';

const KEYS = {
  sidebar_locked: "anpr_sidebar_locked",
  debug_panel_enabled: "anpr_debug_panel_enabled",
  channel_metrics_visible: "anpr_channel_metrics_visible",
};

export function getPreference(key) {
  try { return localStorage.getItem(KEYS[key]) === "1"; } catch (_e) { return false; }
}

export function setPreference(key, value) {
  try { localStorage.setItem(KEYS[key], value ? "1" : "0"); } catch (_e) { /* device state only */ }
}

// [checkbox id, preference key]
const CONTROLS = [
  ["d_metrics", "channel_metrics_visible"],
  ["d_log", "debug_panel_enabled"],
];

export function syncPreferenceControls() {
  for (const [id, key] of CONTROLS) setChk(id, getPreference(key));
}

export function bindPreferenceControls(afterChange) {
  for (const [id, key] of CONTROLS) {
    const element = document.getElementById(id);
    if (!element) continue;
    element.onchange = () => {
      setPreference(key, element.checked);
      afterChange(key);
    };
  }
}

// ── Sidebar pin ─────────────────────────────────────────────────────────
// Pinned = the rail stays collapsed on hover. Control lives inside the
// sidebar itself.

export function syncSidebarPin() {
  const button = document.getElementById("railPinBtn");
  if (!button) return;
  const pinned = getPreference("sidebar_locked");
  button.classList.toggle("is-pinned", pinned);
  button.setAttribute("aria-pressed", pinned ? "true" : "false");
  const label = pinned ? "Панель закреплена свёрнутой" : "Закрепить панель";
  button.title = pinned ? "Открепить панель" : "Закрепить панель свёрнутой";
  const text = document.getElementById("railPinLabel");
  if (text) text.textContent = label;
}

export function bindSidebarPin(afterChange) {
  const button = document.getElementById("railPinBtn");
  if (!button) return;
  button.onclick = () => {
    const wanted = !getPreference("sidebar_locked");
    setPreference("sidebar_locked", wanted);
    syncSidebarPin();
    afterChange(wanted);
  };
}
