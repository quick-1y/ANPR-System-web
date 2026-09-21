// The single owner of displayed date/time (roadmap 7.5, model 4.9).
//
// Everything shown to the user is rendered in ONE zone with one explicit locale:
// the zone an administrator chose for the instance, or — until one is chosen —
// this computer's own zone (the default; it is not labelled). The workstation clock is
// never trusted: "now" is server time plus a measured offset.
//
// No imports and no DOM access at load time, so it runs (and is tested) in Node.

export const LOCALE = "ru-RU";

const state = {
  zone: null,          // IANA id actually used for rendering
  source: "client",    // "server" = an administrator chose the zone; "client" = this computer's own zone
  configured: null,    // did an administrator choose the instance zone? (null = unknown)
  offsetMs: 0,         // serverNow - Date.now()
};
const zoneListeners = new Set();

export function browserZone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch (_e) { return "UTC"; }
}

function isValidZone(zone) {
  try { new Intl.DateTimeFormat(LOCALE, { timeZone: zone }); return true; } catch (_e) { return false; }
}

export function getZoneInfo() {
  const zone = state.zone || browserZone();
  // A label exists only for a zone an administrator explicitly chose. The
  // default (this computer's time) is not labelled.
  const label = state.source === "server" ? zone : "";
  return { zone, source: state.source, configured: state.configured, label };
}

// Adopt the zone the server reported. A missing/invalid zone means the
// client's own zone. Listeners run only when the outcome changed.
export function configureZone({ zone = null, configured = null } = {}) {
  const usable = zone && isValidZone(zone) ? zone : null;
  const next = { zone: usable || browserZone(), source: usable ? "server" : "client", configured: usable ? configured : null };
  const changed = next.zone !== state.zone || next.source !== state.source || next.configured !== state.configured;
  Object.assign(state, next);
  if (changed) zoneListeners.forEach((listener) => { try { listener(getZoneInfo()); } catch (_e) { /* one bad view must not block the others */ } });
}

export function onZoneChange(listener) {
  zoneListeners.add(listener);
  return () => zoneListeners.delete(listener);
}

// ── Server clock ─────────────────────────────────────────────────────

export function setServerTime({ serverUtc, sentAt, receivedAt }) {
  const serverMs = Date.parse(serverUtc);
  if (!Number.isFinite(serverMs)) return;
  // The server stamped its answer roughly halfway through the round trip.
  state.offsetMs = serverMs - (sentAt + receivedAt) / 2;
}

export function serverNow() {
  return new Date(Date.now() + state.offsetMs);
}

// One request gives the clock offset AND the zone. On failure the interface
// keeps working: last offset stays, the zone falls back to the client's.
export async function syncServerTime(fetchTime) {
  const sentAt = Date.now();
  try {
    const body = await fetchTime();
    setServerTime({ serverUtc: body.server_utc, sentAt, receivedAt: Date.now() });
    configureZone({ zone: body.display_timezone, configured: body.timezone_configured });
    return body;
  } catch (_e) {
    configureZone({ zone: null });
    return null;
  }
}

export function startServerTimeSync(fetchTime, intervalMs = 5 * 60 * 1000) {
  syncServerTime(fetchTime);
  return setInterval(() => syncServerTime(fetchTime), intervalMs);
}

// ── Formatting (always explicit timeZone + locale) ───────────────────

const formatterCache = new Map();
function formatter(kind) {
  const zone = getZoneInfo().zone;
  const key = `${kind}|${zone}`;
  let f = formatterCache.get(key);
  if (!f) {
    const base = { timeZone: zone, hourCycle: "h23" };
    const options = kind === "date"
      ? { ...base, day: "2-digit", month: "2-digit", year: "numeric" }
      : { ...base, hour: "2-digit", minute: "2-digit", second: "2-digit" };
    f = new Intl.DateTimeFormat(LOCALE, options);
    formatterCache.set(key, f);
  }
  return f;
}

function toDate(value) {
  if (value === null || value === undefined || value === "") return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value) {
  const d = toDate(value);
  return d ? formatter("date").format(d) : "—";
}

export function formatTime(value) {
  const d = toDate(value);
  return d ? formatter("time").format(d) : "—";
}

export function formatDateTime(value) {
  const d = toDate(value);
  return d ? `${formatter("date").format(d)}, ${formatter("time").format(d)}` : "—";
}

// ── Wall time in the display zone <-> UTC (journal filters) ──────────

function zoneOffsetMs(utcMs, zone) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(new Date(utcMs));
  const v = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  const wallAsUtc = Date.UTC(+v.year, +v.month - 1, +v.day, +v.hour, +v.minute, +v.second);
  return wallAsUtc - Math.floor(utcMs / 1000) * 1000;
}

// "2026-09-21T08:00" typed in a <input type="datetime-local"> means 08:00 in
// the DISPLAY zone, not in the browser's: convert it to a UTC instant for the API.
export function wallTimeToUtcIso(local, zone = getZoneInfo().zone) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(String(local || "").trim());
  if (!m) return null;
  const wallAsUtc = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0));
  let instant = wallAsUtc - zoneOffsetMs(wallAsUtc, zone);
  instant = wallAsUtc - zoneOffsetMs(instant, zone); // second pass settles DST boundaries
  return new Date(instant).toISOString();
}

export function utcToWallTime(value, zone = getZoneInfo().zone) {
  const d = toDate(value);
  if (!d) return "";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  }).formatToParts(d);
  const v = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${v.year}-${v.month}-${v.day}T${v.hour}:${v.minute}`;
}
