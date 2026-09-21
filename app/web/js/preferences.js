// Personal preferences (class U): GET/PATCH /api/me/preferences.
// Open to every signed-in user — no tab or role permission is involved. The
// server is the source of truth; the cache in state.js only mirrors its last answer.
import { api, jfetch } from './api.js';
import { setPreferencesCache, getPreference, getPreferenceEntry } from './state.js';
import { setChk, showToast } from './ui.js';

export async function loadPreferences() {
  const body = await jfetch(api("/api/me/preferences"));
  setPreferencesCache(body.preferences || {}, body.display_timezone || "UTC");
  return body;
}

// Save a (partial) set of preferences; on failure the caller gets the error and
// the cache is left as it was, so the UI can revert instead of silently diverging.
export async function savePreferences(patch) {
  const body = await jfetch(api("/api/me/preferences"), "PATCH", patch);
  setPreferencesCache(body.preferences || {}, body.display_timezone || "UTC");
  return body;
}

export async function savePreference(key, value) {
  await savePreferences({ [key]: value });
  return getPreference(key);
}

// [checkbox id, preference key]. These controls live in the settings pane but
// are personal: they save on toggle, independent of the "Save" button and of
// any tab permission.
const CONTROLS = [
  ["p_sidebar_locked", "sidebar_locked"],
  ["d_metrics", "channel_metrics_visible"],
  ["d_log", "debug_panel_enabled"],
];

export function syncPreferenceControls() {
  for (const [id, key] of CONTROLS) setChk(id, Boolean(getPreference(key)));
  const zone = document.getElementById("p_timezone");
  if (zone) zone.value = getPreference("timezone") || "auto";
  for (const [id, key] of [["p_theme", "theme"], ["p_style", "style"]]) {
    const el = document.getElementById(id);
    if (el && getPreference(key)) el.value = getPreference(key);
  }
  const notes = { theme: "p_theme_source", style: "p_style_source" };
  const labels = { user: "личная настройка", instance: "задано администратором", default: "по умолчанию" };
  for (const [key, id] of Object.entries(notes)) {
    const el = document.getElementById(id);
    const entry = getPreferenceEntry(key);
    if (el) el.textContent = entry ? labels[entry.source] || "" : "";
  }
}

export function bindPreferenceControls(afterChange) {
  for (const [id, key] of CONTROLS) {
    const element = document.getElementById(id);
    if (!element) continue;
    element.onchange = async () => {
      try {
        await savePreference(key, element.checked);
      } catch (_e) {
        element.checked = Boolean(getPreference(key));  // revert: never diverge silently
        showToast("Не удалось сохранить личную настройку", 4000);
        return;
      }
      afterChange(key);
    };
  }
}
