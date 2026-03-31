let api = null;
let jfetch = null;
let applyTheme = null;
let applySidebarLocked = null;
let applyDebugPanelVisibility = null;
let syncOverlayPolling = null;
let scheduleVideoGridLayout = null;
let showToast = null;
let setDebugSettingsCache = null;
let val = null;
let setVal = null;
let setChk = null;

export function initSettingsModule(deps) {
  api = deps.api;
  jfetch = deps.jfetch;
  applyTheme = deps.applyTheme;
  applySidebarLocked = deps.applySidebarLocked;
  applyDebugPanelVisibility = deps.applyDebugPanelVisibility;
  syncOverlayPolling = deps.syncOverlayPolling;
  scheduleVideoGridLayout = deps.scheduleVideoGridLayout;
  showToast = deps.showToast;
  setDebugSettingsCache = deps.setDebugSettingsCache;
  val = deps.val;
  setVal = deps.setVal;
  setChk = deps.setChk;
}

async function renderCountryToggles(enabledCodes) {
  const container = document.getElementById("g_countries_list");
  if (!container) return;
  let countries = [];
  try {
    countries = await jfetch(api("/api/countries"));
  } catch (_e) {
    container.innerHTML = '<span style="color:var(--text3);font-size:12px">Не удалось загрузить список стран</span>';
    return;
  }
  const enabled = new Set((enabledCodes || []).map((c) => c.toUpperCase()));
  container.innerHTML = "";
  for (const c of countries) {
    const row = document.createElement("div");
    row.className = "s-row";
    row.style.paddingLeft = "0";
    const label = document.createElement("div");
    label.className = "s-row-label";
    label.style.flex = "1";
    label.innerHTML = '<span class="s-row-name">' + c.name + '</span> <span style="color:var(--text3);font-size:11px;margin-left:4px">' + c.code + "</span>";
    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.dataset.countryCode = c.code;
    toggle.checked = enabled.has(c.code.toUpperCase());
    row.appendChild(label);
    row.appendChild(toggle);
    container.appendChild(row);
  }
}

function getEnabledCountryCodes() {
  const toggles = document.querySelectorAll("#g_countries_list input[type='checkbox']");
  const codes = [];
  toggles.forEach((t) => {
    if (t.checked) codes.push(t.dataset.countryCode);
  });
  return codes;
}

export async function loadGlobalSettings() {
  const g = await jfetch(api("/api/settings"));
  setVal("g_grid", g.grid);
  setVal("g_theme", g.theme);
  applyTheme(g.theme);
  setChk("g_sidebar_locked", g.sidebar_locked);
  applySidebarLocked(!!g.sidebar_locked);
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
  setVal("g_postgres_dsn", g.storage.postgres_dsn);
  setVal("g_log_level", g.logging.level);
  setVal("g_log_retention", g.logging.retention_days);
  setVal("g_timezone", g.time.timezone);
  setVal("g_offset_minutes", g.time.offset_minutes);
  await renderCountryToggles(g.plates.enabled_countries || []);
  setChk("d_metrics", g.debug.show_channel_metrics);
  setChk("d_log", g.debug.log_panel_enabled);
  setChk("d_video_off", g.debug.disable_video_output);
  const debugSettingsCache = g.debug || {};
  setDebugSettingsCache(debugSettingsCache);
  applyDebugPanelVisibility(debugSettingsCache);
}

export async function saveGeneral() {
  applyTheme(val("g_theme"));
  const payload = {
    grid: val("g_grid"),
    theme: val("g_theme"),
    sidebar_locked: document.getElementById("g_sidebar_locked").checked,
    reconnect: {
      signal_loss: {
        enabled: document.getElementById("g_sl_enabled").checked,
        frame_timeout_seconds: Number(val("g_frame_timeout")),
        retry_interval_seconds: Number(val("g_retry_interval")),
      },
      periodic: {
        enabled: document.getElementById("g_periodic_enabled").checked,
        interval_minutes: Number(val("g_periodic_minutes")),
      },
    },
    storage: {
      auto_cleanup_enabled: document.getElementById("g_auto_cleanup").checked,
      cleanup_interval_minutes: Number(val("g_cleanup_minutes")),
      events_retention_days: Number(val("g_events_retention")),
      media_retention_days: Number(val("g_media_retention")),
      max_screenshots_mb: Number(val("g_max_screenshots")),
      postgres_dsn: val("g_postgres_dsn"),
    },
    logging: {
      level: val("g_log_level"),
      retention_days: Number(val("g_log_retention")),
    },
    time: {
      timezone: val("g_timezone"),
      offset_minutes: Number(val("g_offset_minutes")),
    },
    plates: {
      enabled_countries: getEnabledCountryCodes(),
    },
    debug: {
      show_channel_metrics: document.getElementById("d_metrics").checked,
      log_panel_enabled: document.getElementById("d_log").checked,
      disable_video_output: document.getElementById("d_video_off").checked,
    },
  };
  const updated = await jfetch(api("/api/settings"), "PUT", payload);
  const debugSettingsCache = (updated || {}).debug || payload.debug;
  setDebugSettingsCache(debugSettingsCache);
  setChk("d_video_off", Boolean(debugSettingsCache.disable_video_output));
  setChk("d_metrics", Boolean(debugSettingsCache.show_channel_metrics));
  setChk("d_log", Boolean(debugSettingsCache.log_panel_enabled));
  document.querySelectorAll(".cam-preview").forEach((img) => {
    img.dataset.url = "";
    if (debugSettingsCache.disable_video_output) {
      img.removeAttribute("src");
    }
  });
  applyDebugPanelVisibility(debugSettingsCache);
  syncOverlayPolling();
  scheduleVideoGridLayout(true);
  applySidebarLocked(document.getElementById("g_sidebar_locked").checked);
  showToast("Настройки сохранены");
}
