// Event journal with pagination
import { state } from './state.js';
import { api, jfetch } from './api.js';
import { formatDirection, flagHtml, normalizePlate, esc } from './ui.js';
import { openEventDetails } from './events.js';

export const journalState = {
  items: [],
  cursor: null,
  hasMore: false,
  loading: false,
};
let journalObserver = null;

function buildJournalParams(cursor) {
  const params = new URLSearchParams();
  params.set("limit", "100");
  const plate = (document.getElementById("fltPlate").value || "").trim();
  const channelId = document.getElementById("fltChannel").value;
  const dateFrom = document.getElementById("fltDateFrom").value;
  const dateTo = document.getElementById("fltDateTo").value;
  if (plate) params.set("plate", plate);
  if (channelId) params.set("channel_id", channelId);
  if (dateFrom) params.set("start_ts", new Date(dateFrom).toISOString());
  if (dateTo) params.set("end_ts", new Date(dateTo).toISOString());
  if (cursor) {
    params.set("before_ts", cursor.ts);
    params.set("before_id", String(cursor.id));
  }
  return params;
}

export async function loadJournal() {
  journalState.items = [];
  journalState.cursor = null;
  journalState.hasMore = false;
  journalState.loading = false;
  document.getElementById("journalBody").innerHTML = "";
  await fetchJournalPage();
}

async function fetchJournalPage() {
  if (journalState.loading) return;
  journalState.loading = true;
  const params = buildJournalParams(journalState.cursor);
  try {
    const data = await jfetch(api(`/api/events?${params}`));
    const items = Array.isArray(data) ? data : (data.items || []);
    const hasMore = typeof data === "object" && !Array.isArray(data) ? !!data.has_more : false;
    journalState.items.push(...items);
    journalState.hasMore = hasMore;
    if (items.length > 0) {
      const last = items[items.length - 1];
      journalState.cursor = { ts: last.time, id: last.id };
    }
    appendJournalRows(items);
    updateJournalSentinel();
  } catch (err) {
  } finally {
    journalState.loading = false;
  }
}

export function makeJournalRow(ev) {
  const conf = Number(ev.confidence || 0);
  const direction = formatDirection(ev.direction);
  const ts = new Date(ev.time);
  const timeStr = ts.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }) +
    " " + ts.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const tr = document.createElement("tr");
  if (ev.id !== null && ev.id !== undefined) tr.dataset.eventId = String(ev.id);
  const listType = state.plateLookup[normalizePlate(ev.plate || "")];
  if (listType === "white") tr.classList.add("list-white");
  else if (listType === "black") tr.classList.add("list-black");
  else if (listType === "info") tr.classList.add("list-info");
  const srcText = ev.source || "";
  const ch = state.channels.find((c) => Number(c.id) === Number(ev.channel_id));
  const channelName = ch ? ch.name : (ev.channel || `CAM-${ev.channel_id || ""}`);
  let zoneCell = "";
  if (ev.zone_id !== null && ev.zone_id !== undefined) {
    const zid = Number(ev.zone_id);
    if (zid === 0) {
      zoneCell = "Вне парковки";
    } else if (zid > 0) {
      const zoneObj = state.zones.find((z) => Number(z.id) === zid);
      zoneCell = zoneObj ? zoneObj.name : String(zid);
    }
  }
  const entryCell = ev.time_entry ? new Date(ev.time_entry).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" }) : "";
  const exitCell = ev.time_exit ? new Date(ev.time_exit).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" }) : "";
  tr.innerHTML = `<td class="col-time">${timeStr}</td>` +
    `<td class="col-channel">${esc(channelName)}</td>` +
    `<td class="col-country">${flagHtml(ev.country)} ${esc(ev.country || "")}</td>` +
    `<td class="col-dir"><span class="badge ${direction.badgeClass}">${direction.label}</span></td>` +
    `<td class="col-plate plate-cell">${esc(ev.plate_display || ev.plate || "")}</td>` +
    `<td class="col-conf conf-cell" style="color:${conf < 0.85 ? "var(--warning)" : "var(--success)"}">${conf.toFixed(2)}</td>` +
    `<td class="col-source" title="${esc(srcText)}">${esc(srcText)}</td>` +
    `<td class="col-zone col-zone-name">${esc(zoneCell)}</td>` +
    `<td class="col-zone col-zone-time">${esc(entryCell)}</td>` +
    `<td class="col-zone col-zone-time">${esc(exitCell)}</td>`;
  tr.onclick = () => openEventDetails(ev);
  return tr;
}

function appendJournalRows(items) {
  const body = document.getElementById("journalBody");
  items.forEach((ev) => body.appendChild(makeJournalRow(ev)));
}

function updateJournalSentinel() {
  const sentinel = document.getElementById("journalSentinel");
  if (!sentinel) return;
  sentinel.style.display = journalState.hasMore ? "block" : "none";
}

export function initJournalBindings() {
  document.getElementById("btnFind").onclick = loadJournal;
  document.getElementById("btnReset").onclick = () => {
    document.getElementById("fltPlate").value = "";
    document.getElementById("fltChannel").value = "";
    document.getElementById("fltDateFrom").value = "";
    document.getElementById("fltDateTo").value = "";
    loadJournal();
  };
  document.getElementById("btnExport").onclick = () => {
    const params = new URLSearchParams();
    const plate = (document.getElementById("fltPlate").value || "").trim();
    const channelId = document.getElementById("fltChannel").value;
    const dateFrom = document.getElementById("fltDateFrom").value;
    const dateTo = document.getElementById("fltDateTo").value;
    if (plate) params.set("plate", plate);
    if (channelId) params.set("channel_id", channelId);
    if (dateFrom) params.set("start", new Date(dateFrom).toISOString());
    if (dateTo) params.set("end", new Date(dateTo).toISOString());
    const qs = params.toString();
    window.open(api(`/api/data/export/events.csv${qs ? "?" + qs : ""}`), "_blank");
  };
}

export function initJournalScroll() {
  const sentinel = document.getElementById("journalSentinel");
  if (!sentinel) return;
  if (journalObserver) journalObserver.disconnect();
  journalObserver = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting && journalState.hasMore && !journalState.loading) {
        fetchJournalPage();
      }
    },
    { root: document.getElementById("journalScroll"), threshold: 0.1 }
  );
  journalObserver.observe(sentinel);
}
