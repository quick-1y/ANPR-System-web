// Global settings panel, country toggles
import { setDebugSettingsCache, isSuperAdmin, isVideoOutputDisabled } from './state.js';
import { syncPreferenceControls } from './device-prefs.js';
import { api, jfetch } from './api.js';
import { val, setVal, setChk, showToast } from './ui.js';
import { syncServerTime } from './datetime.js';
import { fetchServerTime } from './server-time.js';
import { scheduleVideoGridLayout, syncOverlayPolling } from './channels.js';
import { applyDebugPanelVisibility } from './debug.js';

export async function renderCountryToggles(enabledCodes) {
  const container = document.getElementById("g_countries_list");
  if (!container) return;
  let countries = [];
  try { countries = await jfetch(api("/api/countries")); }
  catch (_e) { container.innerHTML = '<span style="color:var(--text3);font-size:var(--font-sm)">Не удалось загрузить список стран</span>'; return; }
  const enabled = new Set((enabledCodes || []).map(c => c.toUpperCase()));
  container.innerHTML = "";
  for (const c of countries) {
    const row = document.createElement("div");
    row.className = "s-row"; row.style.paddingLeft = "0";
    const label = document.createElement("div");
    label.className = "s-row-label"; label.style.flex = "1";
    label.innerHTML = '<span class="s-row-name">' + c.name + '</span> <span style="color:var(--text3);font-size:var(--font-xs);margin-left:4px">' + c.code + '</span>';
    const toggle = document.createElement("input");
    toggle.type = "checkbox"; toggle.dataset.countryCode = c.code; toggle.checked = enabled.has(c.code.toUpperCase());
    row.appendChild(label); row.appendChild(toggle); container.appendChild(row);
  }
}

function getEnabledCountryCodes() {
  const toggles = document.querySelectorAll("#g_countries_list input[type='checkbox']");
  const codes = [];
  toggles.forEach(t => { if (t.checked) codes.push(t.dataset.countryCode); });
  return codes;
}

let timezoneTouched = false;

function setTimezoneSelect(zone) {
  const select = document.getElementById("g_timezone");
  if (!select) return;
  if (zone && !Array.from(select.options).some(o => o.value === zone)) {
    const option = document.createElement("option");
    option.value = zone; option.textContent = zone;
    select.appendChild(option);
  }
  select.value = zone;
  select.onchange = () => { timezoneTouched = true; };
}

export async function loadGlobalSettings() {
  const g = await jfetch(api("/api/settings"));
  setChk("g_sl_enabled", g.reconnect.signal_loss.enabled);
  setVal("g_frame_timeout", g.reconnect.signal_loss.frame_timeout_seconds);
  setVal("g_retry_interval", g.reconnect.signal_loss.retry_interval_seconds);
  setChk("g_periodic_enabled", g.reconnect.periodic.enabled);
  setVal("g_periodic_minutes", g.reconnect.periodic.interval_minutes);
  setChk("g_auto_cleanup", g.storage.auto_cleanup_enabled);
  setVal("g_cleanup_minutes", g.storage.cleanup_interval_minutes);
  setVal("g_events_retention", g.storage.events_retention_days);
  setVal("g_media_retention", g.storage.media_retention_days);
  setVal("g_max_screenshots", g.storage.max_screenshots_mb);
  setVal("g_token_ttl", g.auth.token_ttl_minutes);
  setVal("g_rl_attempts", g.auth.login_rate_limit_attempts);
  setVal("g_rl_window", g.auth.login_rate_limit_window_seconds);
  setVal("g_log_level", g.logging.level); setVal("g_log_retention", g.logging.retention_days);
  if (g.interface) {
  }
  // display_timezone is an app_settings key; it is sent back only when the
  // administrator touched the select, so "never configured" stays distinguishable
  // from an explicit choice (including an explicit UTC).
  setTimezoneSelect(g.interface.display_timezone);
  timezoneTouched = false;
  const note = document.getElementById("tzNotConfiguredNote");
  if (note) note.hidden = Boolean(g.interface.timezone_configured);
  await renderCountryToggles(g.plates.enabled_countries || []);
  if (g.debug) {
    setChk("d_video_off", g.debug.video_output_enabled === false);
    setDebugSettingsCache(g.debug || {});
  }
  syncPreferenceControls();
  applyDebugPanelVisibility();
}

export async function saveGeneral() {
  const payload = {
    reconnect: {
      signal_loss: { enabled: document.getElementById("g_sl_enabled").checked, frame_timeout_seconds: Number(val("g_frame_timeout")), retry_interval_seconds: Number(val("g_retry_interval")) },
      periodic: { enabled: document.getElementById("g_periodic_enabled").checked, interval_minutes: Number(val("g_periodic_minutes")) },
    },
    storage: { auto_cleanup_enabled: document.getElementById("g_auto_cleanup").checked, cleanup_interval_minutes: Number(val("g_cleanup_minutes")), events_retention_days: Number(val("g_events_retention")), media_retention_days: Number(val("g_media_retention")), max_screenshots_mb: Number(val("g_max_screenshots")) },
    logging: { level: val("g_log_level"), retention_days: Number(val("g_log_retention")) },
    interface: { display_timezone: timezoneTouched ? val("g_timezone") : null },
    plates: { enabled_countries: getEnabledCountryCodes() },
    auth: { token_ttl_minutes: Number(val("g_token_ttl")), login_rate_limit_attempts: Number(val("g_rl_attempts")), login_rate_limit_window_seconds: Number(val("g_rl_window")) },
  };
  // Server-side debug flag: superadmin only. Personal display flags (sidebar,
  // metrics overlay, log panel) are device-local (class L) and save on
  // toggle themselves — see device-prefs.js.
  if (isSuperAdmin()) payload.debug = { video_output_enabled: !document.getElementById("d_video_off").checked };
  const updated = await jfetch(api("/api/settings"), "PUT", payload);
  if (isSuperAdmin()) {
    setDebugSettingsCache((updated || {}).debug || payload.debug);
    setChk("d_video_off", isVideoOutputDisabled());
  }
  document.querySelectorAll(".cam-preview").forEach((img) => {
    img.dataset.url = "";
    if (isVideoOutputDisabled()) img.removeAttribute("src");
  });
  applyDebugPanelVisibility();
  syncOverlayPolling();
  scheduleVideoGridLayout(true);
  timezoneTouched = false;
  const note = document.getElementById("tzNotConfiguredNote");
  if (note && updated && updated.interface) note.hidden = Boolean(updated.interface.timezone_configured);
  // The zone may have changed what everyone sees.
  await syncServerTime(fetchServerTime);
  const restart = (updated || {}).requires_restart || [];
  showToast(restart.length
    ? "Настройки сохранены. Обработчик перезапущен для применения: " + restart.join(", ")
    : "Настройки сохранены", restart.length ? 5000 : 2000);
}
