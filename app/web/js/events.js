let deps = null;

let eventSource = null;
let streamReconnectTimer = null;
let eventFeedResizeObserver = null;
let eventFeedRenderScheduled = false;
let eventFeedRenderFrame = null;
let initialized = false;

function trimEventFeedOverflow(feed) {
  if (!feed) return;
  while (feed.lastElementChild && feed.scrollHeight > feed.clientHeight) {
    feed.removeChild(feed.lastElementChild);
  }
}

function getActiveTabName() {
  return document.querySelector(".ttab.active")?.dataset.tab || "obs";
}

export function scheduleEventFeedRender(forceRebuild = true) {
  if (eventFeedRenderScheduled) return;
  eventFeedRenderScheduled = true;
  eventFeedRenderFrame = requestAnimationFrame(() => {
    eventFeedRenderScheduled = false;
    eventFeedRenderFrame = null;
    if (getActiveTabName() !== "obs") return;
    const feed = document.getElementById("eventFeed");
    if (!feed || feed.clientHeight <= 0) return;
    renderEventFeed(forceRebuild);
  });
}

export function setupEventFeedLayoutGuards() {
  if (typeof ResizeObserver !== "function") return;
  const obsRight = document.querySelector("#tab-obs .obs-right");
  const feed = document.getElementById("eventFeed");
  if (!obsRight && !feed) return;
  eventFeedResizeObserver = new ResizeObserver(() => {
    scheduleEventFeedRender(true);
  });
  if (obsRight) eventFeedResizeObserver.observe(obsRight);
  if (feed) eventFeedResizeObserver.observe(feed);
}

function resolveChannelIdFromEvent(ev) {
  const directId = Number(ev.channel_id);
  if (Number.isFinite(directId) && directId > 0) return directId;
  const byName = deps.state.channels.find((c) => String(c.name) === String(ev.channel));
  return byName ? Number(byName.id) : null;
}

export function updateChannelLastPlate(channelId, plateData) {
  const id = Number(channelId);
  if (!Number.isFinite(id) || id <= 0) return;
  const plateNode = document.getElementById(`plate-${id}`);
  if (!plateNode) return;
  const pd = plateData || {};
  const plateText = String(pd.plate_display || pd.plate || "").trim();
  const wasVisible = plateNode.style.display === "block";
  const prevText = plateNode.textContent;
  if (plateText) {
    if (!wasVisible || prevText !== plateText) {
      plateNode.textContent = plateText;
      plateNode.style.display = "block";
      plateNode.style.animation = "none";
      void plateNode.offsetWidth;
      plateNode.style.animation = "";
    }
  } else {
    plateNode.style.display = "none";
    plateNode.textContent = "";
  }
}

function applyLastPlate(ev) {
  const channelId = resolveChannelIdFromEvent(ev);
  if (!channelId) return;
  const payload = {
    plate: ev.plate || "",
    plate_display: ev.plate_display || null,
    timestamp: ev.timestamp || null,
    country: ev.country || null,
    confidence: ev.confidence ?? null,
    direction: ev.direction || null,
  };
  deps.state.lastPlatesByChannelId[channelId] = payload;
  updateChannelLastPlate(channelId, payload);
}

export async function hydrateChannelLastPlates() {
  const rows = await deps.jfetch(deps.api("/api/channels/last-plates"));
  deps.state.lastPlatesByChannelId = rows || {};
  Object.entries(deps.state.lastPlatesByChannelId).forEach(([channelId, payload]) => {
    updateChannelLastPlate(Number(channelId), payload);
  });
}

export async function loadInitialEventFeed() {
  await deps.loadEventFeedHistory();
  renderEventFeed();
}

export function renderEventFeed(forceRebuild = false) {
  const feed = document.getElementById("eventFeed");
  if (!feed) return;

  const events = deps.state.allEvents;
  if (!events.length) {
    feed.innerHTML = "";
    return;
  }

  function makeItem(item, isNew) {
    const conf = Number(item.confidence || 0);
    const direction = deps.formatDirection(item.direction);
    const key = String(item.id ?? item.timestamp ?? "");
    const channelName = item.channel || `CAM-${item.channel_id || ""}`;
    const timeStr = new Date(item.timestamp || Date.now()).toLocaleTimeString();
    const div = document.createElement("div");
    const normalizedPlate = deps.normalizePlate(item.plate);
    const listType = deps.state.plateLookup[normalizedPlate];
    let cls = isNew ? "ev-item ev-new" : "ev-item";
    if (listType === "white") cls += " list-white";
    else if (listType === "black") cls += " list-black";
    else if (listType === "info") cls += " list-info";
    div.className = cls;
    div.dataset.evKey = key;
    div.setAttribute("role", "button");
    div.setAttribute("tabindex", "0");
    const displayPlate = item.plate_display || item.plate || "—";
    div.innerHTML = `${deps.flagHtml(item.country)}<div class='ev-row-top'><span class='ev-plate'>${displayPlate}</span><span class='ev-direction badge ${direction.badgeClass}'>${direction.label}</span></div><div class='ev-row-bottom'><span class='ev-meta-channel'>${channelName}</span><span class='ev-meta-time'>${timeStr}</span><span class='ev-conf ${conf < 0.85 ? "warn" : ""}'>${conf.toFixed(2)}</span></div>`;
    div.onclick = () => deps.openEventDetails(item);
    div.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        deps.openEventDetails(item);
      }
    };
    if (isNew) {
      div.addEventListener("animationend", () => div.classList.remove("ev-new"), { once: true });
    }
    return div;
  }

  const existingEls = Array.from(feed.children);
  const existingKeys = new Set(existingEls.map((el) => el.dataset.evKey).filter(Boolean));
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
    const key = String(ev.id ?? ev.timestamp ?? "");
    if (existingKeys.has(key)) break;
    newItems.push(ev);
  }
  if (!newItems.length) return;

  for (let i = newItems.length - 1; i >= 0; i--) {
    feed.prepend(makeItem(newItems[i], true));
  }
  trimEventFeedOverflow(feed);
}

function pushEvent(ev) {
  applyLastPlate(ev);
  deps.state.allEvents.unshift(ev);
  if (deps.state.allEvents.length > 500) deps.state.allEvents.pop();
  renderEventFeed();
  deps.handleLiveEventForJournal(ev);
}

function scheduleStreamReconnect(delayMs = 3000) {
  if (streamReconnectTimer) return;
  streamReconnectTimer = setTimeout(() => {
    streamReconnectTimer = null;
    setupEventStream();
  }, delayMs);
}

export async function setupEventStream() {
  if (streamReconnectTimer) {
    clearTimeout(streamReconnectTimer);
    streamReconnectTimer = null;
  }
  if (eventSource) {
    try {
      eventSource.close();
    } catch (_e) {}
  }
  eventSource = new EventSource(deps.apiUrl("/api/events/stream"));
  eventSource.onmessage = (m) => {
    try {
      pushEvent(JSON.parse(m.data));
    } catch (_e) {}
  };
  eventSource.onerror = () => {
    try {
      eventSource.close();
    } catch (_e) {}
    scheduleStreamReconnect();
  };
}

export function cleanupEventRuntime() {
  if (eventSource) {
    try {
      eventSource.close();
    } catch (_e) {}
    eventSource = null;
  }
  if (streamReconnectTimer) {
    clearTimeout(streamReconnectTimer);
    streamReconnectTimer = null;
  }
  if (eventFeedRenderFrame !== null) {
    cancelAnimationFrame(eventFeedRenderFrame);
    eventFeedRenderFrame = null;
    eventFeedRenderScheduled = false;
  }
  if (eventFeedResizeObserver) {
    eventFeedResizeObserver.disconnect();
    eventFeedResizeObserver = null;
  }
}

export function initEventsModule(moduleDeps) {
  deps = moduleDeps;
  if (initialized) return;
  initialized = true;
  window.addEventListener("resize", () => scheduleEventFeedRender(true));
}
