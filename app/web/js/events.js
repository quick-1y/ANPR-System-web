// Event feed, event streaming, event details modal
import { state, eventFeedRenderScheduled, eventFeedRenderFrame, setEventFeedRenderScheduled, setEventFeedRenderFrame, setEventFeedResizeObserver } from './state.js';
import { api, apiUrl, jfetch } from './api.js';
import { getActiveTabName, formatDirection, flagHtml, normalizePlate, openModal, closeModal } from './ui.js';
import { updateChannelLastPlate } from './channels.js';
import { journalState, makeJournalRow } from './journal.js';

function trimEventFeedOverflow(feed) {
  if (!feed) return;
  while (feed.lastElementChild && feed.scrollHeight > feed.clientHeight) {
    feed.removeChild(feed.lastElementChild);
  }
}

export function scheduleEventFeedRender(forceRebuild = true) {
  if (eventFeedRenderScheduled) return;
  setEventFeedRenderScheduled(true);
  setEventFeedRenderFrame(requestAnimationFrame(() => {
    setEventFeedRenderScheduled(false);
    setEventFeedRenderFrame(null);
    if (getActiveTabName() !== "obs") return;
    const feed = document.getElementById("eventFeed");
    if (!feed || feed.clientHeight <= 0) return;
    renderEventFeed(forceRebuild);
  }));
}

export function setupEventFeedLayoutGuards() {
  if (typeof ResizeObserver !== "function") return;
  const obsRight = document.querySelector("#tab-obs .obs-right");
  const feed = document.getElementById("eventFeed");
  if (!obsRight && !feed) return;
  const observer = new ResizeObserver(() => {
    scheduleEventFeedRender(true);
  });
  if (obsRight) observer.observe(obsRight);
  if (feed) observer.observe(feed);
  setEventFeedResizeObserver(observer);
}

function resolveChannelIdFromEvent(ev) {
  const directId = Number(ev.channel_id);
  if (Number.isFinite(directId) && directId > 0) return directId;
  const byName = state.channels.find((c) => String(c.name) === String(ev.channel));
  return byName ? Number(byName.id) : null;
}

function applyLastPlate(ev) {
  const channelId = resolveChannelIdFromEvent(ev);
  if (!channelId) return;
  const payload = {
    plate: ev.plate || "",
    plate_display: ev.plate_display || null,
    time: ev.time || null,
    country: ev.country || null,
    confidence: ev.confidence ?? null,
    direction: ev.direction || null,
  };
  state.lastPlatesByChannelId[channelId] = payload;
  updateChannelLastPlate(channelId, payload);
}

export async function hydrateChannelLastPlates() {
  const rows = await jfetch(api('/api/channels/last-plates'));
  state.lastPlatesByChannelId = rows || {};
  Object.entries(state.lastPlatesByChannelId).forEach(([channelId, payload]) => {
    updateChannelLastPlate(Number(channelId), payload);
  });
}

export function renderEventFeed(forceRebuild = false) {
  const feed = document.getElementById("eventFeed");
  if (!feed) return;

  const events = state.allEvents;
  if (!events.length) { feed.innerHTML = ""; return; }

  function makeItem(item, isNew) {
    const conf = Number(item.confidence || 0);
    const direction = formatDirection(item.direction);
    const key = String(item.id ?? item.time ?? "");
    const chObj = state.channels.find((c) => Number(c.id) === Number(item.channel_id));
    const channelName = chObj ? chObj.name : (item.channel || `CAM-${item.channel_id || ""}`);
    const timeStr = new Date(item.time || Date.now()).toLocaleTimeString();
    const div = document.createElement("div");
    const normalizedPlate = normalizePlate(item.plate);
    const listType = state.plateLookup[normalizedPlate];
    let cls = isNew ? "ev-item ev-new" : "ev-item";
    if (listType === "white") cls += " list-white";
    else if (listType === "black") cls += " list-black";
    else if (listType === "info") cls += " list-info";
    div.className = cls;
    div.dataset.evKey = key;
    div.setAttribute("role", "button");
    div.setAttribute("tabindex", "0");
    const displayPlate = item.plate_display || item.plate || "—";
    const flagContainer = document.createElement('span');
    flagContainer.innerHTML = flagHtml(item.country);
    div.appendChild(flagContainer);
    const rowTop = document.createElement('div');
    rowTop.className = 'ev-row-top';
    const plateSpan = document.createElement('span');
    plateSpan.className = 'ev-plate';
    plateSpan.textContent = displayPlate;
    const dirSpan = document.createElement('span');
    dirSpan.className = `ev-direction badge ${direction.badgeClass}`;
    dirSpan.textContent = direction.label;
    rowTop.appendChild(plateSpan);
    rowTop.appendChild(dirSpan);
    const rowBottom = document.createElement('div');
    rowBottom.className = 'ev-row-bottom';
    const chanSpan = document.createElement('span');
    chanSpan.className = 'ev-meta-channel';
    chanSpan.textContent = channelName;
    const timeSpan = document.createElement('span');
    timeSpan.className = 'ev-meta-time';
    timeSpan.textContent = timeStr;
    const confSpan = document.createElement('span');
    confSpan.className = `ev-conf${conf < 0.85 ? ' warn' : ''}`;
    confSpan.textContent = conf.toFixed(2);
    rowBottom.appendChild(chanSpan);
    rowBottom.appendChild(timeSpan);
    rowBottom.appendChild(confSpan);
    div.appendChild(rowTop);
    div.appendChild(rowBottom);
    div.onclick = () => openEventDetails(item);
    div.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openEventDetails(item); }
    };
    if (isNew) {
      div.addEventListener("animationend", () => div.classList.remove("ev-new"), { once: true });
    }
    return div;
  }

  const existingEls = Array.from(feed.children);
  const existingKeys = new Set(existingEls.map(el => el.dataset.evKey).filter(Boolean));
  const needsFullRebuild = forceRebuild || existingKeys.size === 0;

  if (needsFullRebuild) {
    feed.innerHTML = "";
    for (const item of events) {
      feed.appendChild(makeItem(item, false));
      if (feed.scrollHeight > feed.clientHeight) {
        feed.removeChild(feed.lastElementChild);
        break;
      }
    }
    trimEventFeedOverflow(feed);
    return;
  }

  const newItems = [];
  for (const ev of events) {
    const key = String(ev.id ?? ev.time ?? "");
    if (existingKeys.has(key)) break;
    newItems.push(ev);
  }
  if (!newItems.length) return;

  for (let i = newItems.length - 1; i >= 0; i--) {
    feed.prepend(makeItem(newItems[i], true));
  }
  trimEventFeedOverflow(feed);
}

export function pushEvent(ev) {
  applyLastPlate(ev);
  state.allEvents.unshift(ev);
  if (state.allEvents.length > 500) state.allEvents.pop();
  renderEventFeed();
  const needle = (document.getElementById("fltPlate").value || "").trim().toUpperCase();
  const channelId = document.getElementById("fltChannel").value;
  const plateMatch = !needle || String(ev.plate || "").toUpperCase().includes(needle);
  const chanMatch = !channelId || String(ev.channel_id || "") === channelId;
  if (plateMatch && chanMatch) {
    journalState.items.unshift(ev);
    const body = document.getElementById("journalBody");
    const row = makeJournalRow(ev);
    body.insertBefore(row, body.firstChild);
  }
}

export async function loadEventFeedHistory() {
  const data = await jfetch(api("/api/events?limit=50"));
  const items = Array.isArray(data) ? data : (data.items || []);
  state.allEvents = items;
  renderEventFeed();
}

// --- Event details modal ---
export function closeEventModal() {
  closeModal("eventModal");
}

function setModalImage(id, url) {
  const img = document.getElementById(id);
  if (!url) {
    img.removeAttribute("src");
    img.alt = "Нет изображения";
    return;
  }
  img.src = url;
}

function _makeMetaRow(label, value) {
  const row = document.createElement('div');
  row.className = 'event-meta-row';
  const labelEl = document.createElement('span');
  labelEl.textContent = label;
  const valueEl = document.createElement('b');
  valueEl.textContent = value;
  row.appendChild(labelEl);
  row.appendChild(valueEl);
  return row;
}

export async function openEventDetails(ev) {
  const id = Number(ev.id || 0);
  let payload = ev;
  if (id > 0) {
    try {
      payload = await jfetch(api(`/api/events/item/${id}`));
    } catch (err) {
      payload = ev;
    }
  }
  const ts = payload.time
    ? new Date(payload.time).toLocaleString()
    : "—";
  const chObj = state.channels.find((c) => Number(c.id) === Number(payload.channel_id));
  const channelName = chObj ? chObj.name : (payload.channel || `CAM-${payload.channel_id || ""}`);
  const rows = [
    ["Дата/время", ts],
    ["Канал", channelName],
    ["Страна", payload.country || "—"],
    ["Гос. номер", payload.plate_display || payload.plate || "—"],
    ["Уверенность", Number(payload.confidence || 0).toFixed(2)],
    ["Направление", formatDirection(payload.direction).plain],
    ["Источник", payload.source || "—"],
  ];
  if (payload.zone_id !== null && payload.zone_id !== undefined) {
    const zid = Number(payload.zone_id);
    let zoneName;
    if (zid === 0) {
      zoneName = "Вне парковки";
    } else if (zid > 0) {
      const zoneObj = state.zones.find((z) => Number(z.id) === zid);
      zoneName = zoneObj ? zoneObj.name : String(zid);
    }
    if (zoneName !== undefined) {
      rows.push(["Зона", zoneName]);
      if (payload.time_entry) rows.push(["Въезд", new Date(payload.time_entry).toLocaleString()]);
      if (payload.time_exit) rows.push(["Выезд", new Date(payload.time_exit).toLocaleString()]);
    }
  }

  const meta = document.getElementById("eventMeta");
  meta.innerHTML = "";
  rows.forEach(([label, value]) => meta.appendChild(_makeMetaRow(label, value)));

  const entry = payload.client_id
    ? await jfetch(api(`/api/clients/${payload.client_id}`)).catch(() => null)
    : null;
  if (entry) {
    const typeLabels = { white: "Белый список", info: "Информационный список", black: "Черный список" };
    const divider = document.createElement('div');
    divider.className = 'event-meta-divider';
    divider.textContent = 'Данные из списка';
    meta.appendChild(divider);
    const listRows = [
      ["Список", `${entry.list_name || "—"}\u2002·\u2002${typeLabels[entry.list_type] || entry.list_type || "—"}`],
      ["Имя", entry.first_name || "—"],
      ["Фамилия", entry.last_name || "—"],
      ["Отчество", entry.middle_name || "—"],
      ["Телефон", entry.phone || "—"],
      ["Марка авто", entry.car || "—"],
      ["Комментарий", entry.comment || "—"],
    ];
    listRows.forEach(([label, value]) => meta.appendChild(_makeMetaRow(label, value)));
  }
  if (id > 0) {
    setModalImage("eventFrameImg", apiUrl(`/api/events/item/${id}/media/frame`));
    setModalImage("eventPlateImg", apiUrl(`/api/events/item/${id}/media/plate`));
  } else {
    setModalImage("eventFrameImg", null);
    setModalImage("eventPlateImg", null);
  }
  openModal("eventModal");
}
