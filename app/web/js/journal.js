const journalState = {
  items: [],
  cursor: null,
  hasMore: false,
  loading: false,
};

let journalObserver = null;
let api = null;
let jfetch = null;
let state = null;
let flagHtml = null;

export function initJournalModule(deps) {
  api = deps.api;
  jfetch = deps.jfetch;
  state = deps.state;
  flagHtml = deps.flagHtml;
}

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

export function normalizePlate(plate) {
  return (plate || "").toUpperCase().replace(/\s/g, "");
}

export function formatDirection(directionValue) {
  const normalized = String(directionValue || "").toUpperCase();
  const isApproaching =
    normalized === "IN" ||
    normalized === "APPROACHING" ||
    normalized === "APPROACH";
  const isReceding =
    normalized === "OUT" ||
    normalized === "RECEDING" ||
    normalized === "RECEDE";

  if (isApproaching) {
    return {
      badgeClass: "badge-in",
      label: "→ Приближение",
      plain: "Приближение",
    };
  }

  if (isReceding) {
    return {
      badgeClass: "badge-out",
      label: "← Отдаление",
      plain: "Отдаление",
    };
  }

  return {
    badgeClass: "badge-out",
    label: "—",
    plain: "—",
  };
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

export function closeEventModal() {
  document.getElementById("eventModal").classList.remove("active");
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
  const ts = payload.timestamp
    ? new Date(payload.timestamp).toLocaleString()
    : "—";
  const rows = [
    ["Дата/время", ts],
    ["Канал", payload.channel || `CAM-${payload.channel_id || ""}`],
    ["Страна", payload.country || "—"],
    ["Гос. номер", payload.plate_display || payload.plate || "—"],
    ["Уверенность", Number(payload.confidence || 0).toFixed(2)],
    ["Направление", formatDirection(payload.direction).plain],
    ["Источник", payload.source || "—"],
  ];

  let listHtml = "";
  const plate = payload.plate;
  if (plate) {
    try {
      const entry = await jfetch(api(`/api/lists/entry-by-plate?plate=${encodeURIComponent(plate)}`));
      if (entry) {
        let info = {};
        try { info = JSON.parse(entry.comment || "{}"); } catch (_e) {}
        const typeLabels = { white: "Белый список", info: "Информационный список", black: "Черный список" };
        const listRows = [
          ["Список", `${entry.list_name}\u2002·\u2002${typeLabels[entry.list_type] || entry.list_type}`],
          ["Имя", info.first_name || "—"],
          ["Фамилия", info.last_name || "—"],
          ["Отчество", info.patronymic || "—"],
          ["Телефон", info.phone || "—"],
          ["Марка авто", info.car_make || "—"],
        ];
        listHtml = `<div class="event-meta-divider">Данные из списка</div>` +
          listRows.map((r) => `<div class="event-meta-row"><span>${r[0]}</span><b>${r[1]}</b></div>`).join("");
      }
    } catch (_e) {
      // 404 = plate not in any list; no section shown
    }
  }

  const meta = document.getElementById("eventMeta");
  meta.innerHTML = rows
    .map((r) => `<div class="event-meta-row"><span>${r[0]}</span><b>${r[1]}</b></div>`)
    .join("") + listHtml;
  if (id > 0) {
    setModalImage("eventFrameImg", api(`/api/events/item/${id}/media/frame`));
    setModalImage("eventPlateImg", api(`/api/events/item/${id}/media/plate`));
  } else {
    setModalImage("eventFrameImg", null);
    setModalImage("eventPlateImg", null);
  }
  document.getElementById("eventModal").classList.add("active");
}

function makeJournalRow(ev) {
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
    `<td class="col-source" title="${srcText.replace(/\"/g, "&quot;")}">${srcText}</td>`;
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

export async function loadJournal() {
  journalState.items = [];
  journalState.cursor = null;
  journalState.hasMore = false;
  journalState.loading = false;
  document.getElementById("journalBody").innerHTML = "";
  await fetchJournalPage();
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

export async function loadEventFeedHistory() {
  const data = await jfetch(api("/api/events?limit=50"));
  const items = Array.isArray(data) ? data : (data.items || []);
  state.allEvents = items;
}

export function handleLiveEventForJournal(ev) {
  const needle = (document.getElementById("fltPlate").value || "").trim().toUpperCase();
  const channelId = document.getElementById("fltChannel").value;
  const plateMatch = !needle || String(ev.plate || "").toUpperCase().includes(needle);
  const chanMatch = !channelId || String(ev.channel_id || "") === channelId;
  if (!plateMatch || !chanMatch) return;
  journalState.items.unshift(ev);
  const body = document.getElementById("journalBody");
  const row = makeJournalRow(ev);
  body.insertBefore(row, body.firstChild);
}

export function fillChannelFilter() {
  const sel = document.getElementById("fltChannel");
  const cur = sel.value;
  sel.innerHTML = '<option value="">Все каналы</option>';
  state.channels.forEach((c) => {
    const o = document.createElement("option");
    o.value = String(c.id);
    o.textContent = c.name || `CAM-${String(c.id).padStart(2, "0")}`;
    sel.appendChild(o);
  });
  sel.value = cur;
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
  document.getElementById("eventModalClose").onclick = closeEventModal;
  document.getElementById("eventModal").onclick = (e) => {
    if (e.target.id === "eventModal") closeEventModal();
  };
}
