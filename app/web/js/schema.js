// Settings schema: allowed enum values come from GET /api/settings/schema
// (config/registry.py is the single owner). <select> elements listed in
// BINDINGS are filled from it, so a new log level or detection mode needs a
// change in the registry only; the RU labels below are presentation.
// Theme and style are not here: they moved device-local (appearance.js,
// class L) and the registry no longer validates them, so their <select>
// options are plain static HTML (app/web/index.html, #p_theme/#p_style).
import { api, jfetch } from './api.js';

let schema = null;

// [select element id, registry enum name]
const BINDINGS = [
  ["g_log_level", "log_level"],
  ["c_detection_mode", "detection_mode"],
  ["c_controller_direction_filter", "controller_direction_filter"],
  ["c_list_filter_mode", "list_filter_mode"],
  ["c_zone_channel_type", "zone_channel_type"],
  ["ctrlType", "controller_type"],
  ["ctrlR0Mode", "relay_mode"],
  ["ctrlR1Mode", "relay_mode"],
];

const LABELS = {
  controller_direction_filter: { both: "Оба направления", approaching: "Приближение", receding: "Удаление" },
  list_filter_mode: { all: "Все", whitelist: "Белые списки", custom: "Свои списки" },
  zone_channel_type: { entry: "Въезд", exit: "Выезд" },
  relay_mode: { pulse: "Импульс", pulse_timer: "Импульс с таймером" },
};

export function enumValues(name) {
  return schema && schema.enums ? (schema.enums[name] || null) : null;
}

// Value if the registry allows it (or the schema is not loaded yet), else fallback.
export function pickEnum(name, value, fallback) {
  const normalized = String(value || fallback).toLowerCase();
  const allowed = enumValues(name);
  return !allowed || allowed.includes(normalized) ? normalized : fallback;
}

// Display zones are IANA identifiers (not offsets): daylight saving is respected.
function fillTimezones(select, zones) {
  const previous = select.value;
  select.innerHTML = "";
  for (const zone of zones) {
    const option = document.createElement("option");
    option.value = zone;
    option.textContent = zone;
    select.appendChild(option);
  }
  if (previous && zones.includes(previous)) select.value = previous;
}

function fillSelect(select, name, values) {
  const previous = select.value;
  // Placeholder options (value="") are UI, not part of the domain: keep them.
  Array.from(select.options).forEach(o => { if (o.getAttribute("value") !== "") o.remove(); });
  const labels = LABELS[name] || {};
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labels[value] || value;
    select.appendChild(option);
  }
  if (previous && values.includes(previous)) select.value = previous;
}

export async function loadSettingsSchema() {
  schema = await jfetch(api("/api/settings/schema"));
  for (const [id, name] of BINDINGS) {
    const select = document.getElementById(id);
    const values = enumValues(name);
    if (select && values) fillSelect(select, name, values);
  }
  const zoneSelect = document.getElementById("g_timezone");
  if (zoneSelect && Array.isArray(schema.timezones)) fillTimezones(zoneSelect, schema.timezones);
  return schema;
}
