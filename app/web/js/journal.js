// Event journal with pagination
import { state } from './state.js';
import { api, jfetch } from './api.js';
import { formatDirection, flagHtml, normalizePlate } from './ui.js';
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
      journalState.cursor = { ts: last.timestamp, id: last.id };
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
  const ts = new Date(ev.timestamp);
  const timeStr = ts.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }) +
    " " + ts.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const tr = document.createElement("tr");
  const listType = state.plateLookup[normalizePlate(ev.plate || "")];
  if (listType === "white") tr.classList.add("list-white");
  else if (listType === "black") tr.classList.add("list-black");
  else if (listType === "info") tr.classList.add("list-info");
  const srcText = ev.source || "";
  tr.innerHTML = `<td class="col-time">${timeStr}</td>` +
    `<td class="col-channel">${ev.channel || `CAM-${ev.channel_id || ""}`}</td>` +
    `<td class="col-country">${flagHtml(ev.country)} ${ev.country || ""}</td>` +
    `<td class="col-dir"><span class="badge ${direction.badgeClass}">${direction.label}</span></td>` +
    `<td class="col-plate plate-cell">${ev.plate_display || ev.plate || ""}</td>` +
    `<td class="col-conf conf-cell" style="color:${conf < 0.85 ? "var(--warning)" : "var(--success)"}">${conf.toFixed(2)}</td>` +
    `<td class="col-source" title="${srcText.replace(/"/g, "&quot;")}">${srcText}</td>`;
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
