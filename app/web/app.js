const state = {
  channels: [],
  lists: [],
  selectedListId: null,
  allEvents: [],
  lastPlatesByChannelId: {},
  plateLookup: {},
  currentEntries: [],
};
let eventSource = null;
let streamReconnectTimer = null;
let debugLogSource = null;
let debugLogReconnectTimer = null;
let lastDebugLogId = 0;
let debugSettingsCache = null;
let overlayRefreshTimer = null;
let eventFeedResizeObserver = null;
let eventFeedRenderScheduled = false;
let eventFeedRenderFrame = null;
function api(path) {
  return `${document.getElementById("apiBase").value.trim()}${path}`;
}

// --- API key auth helpers ---
const AUTH_KEY_STORAGE = "anpr_api_key";
function getApiKey() { return localStorage.getItem(AUTH_KEY_STORAGE) || ""; }
function setApiKey(k) { if (k) localStorage.setItem(AUTH_KEY_STORAGE, k); else localStorage.removeItem(AUTH_KEY_STORAGE); }

/** Append ?api_key=<key> when a key is configured (for EventSource / MJPEG URLs). */
function apiUrl(path) {
  const k = getApiKey();
  return k ? `${api(path)}${path.includes("?") ? "&" : "?"}api_key=${encodeURIComponent(k)}` : api(path);
}

function showAuthOverlay(onSuccess) {
  const overlay = document.getElementById("auth-overlay");
  if (!overlay) return;
  overlay.classList.add("active");
  const btn = document.getElementById("auth-submit");
  const inp = document.getElementById("auth-key-input");
  const err = document.getElementById("auth-error");
  if (err) err.textContent = "";
  const handler = async () => {
    const key = (inp ? inp.value : "").trim();
    if (!key) return;
    try {
      const r = await fetch(api("/api/health"), { headers: { "X-Api-Key": key } });
      if (r.ok) {
        setApiKey(key);
        overlay.classList.remove("active");
        if (btn) btn.removeEventListener("click", handler);
        if (onSuccess) onSuccess();
      } else {
        if (err) err.textContent = "Неверный ключ";
      }
    } catch {
      if (err) err.textContent = "Ошибка соединения";
    }
  };
  if (btn) { btn.removeEventListener("click", handler); btn.addEventListener("click", handler); }
}

async function jfetch(url, method = "GET", body = null) {
  const headers = { "Content-Type": "application/json" };
  const k = getApiKey();
  if (k) headers["X-Api-Key"] = k;
  const r = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : null });
  if (r.status === 401) {
    showAuthOverlay(() => jfetch(url, method, body));
    throw new Error("Требуется аутентификация");
  }
  if (!r.ok) throw new Error(await r.text());
  return r.status === 204 ? null : r.json();
}
function flagByCountry(code) {
  const normalized = String(code || "")
    .trim()
    .toLowerCase();
  return normalized
    ? `/web/images/flags/${normalized}.png`
    : "/web/images/flags/eu.png";
}
function flagHtml(code) {
  const normalized = String(code || "")
    .trim()
    .toLowerCase();
  const src = flagByCountry(normalized || "eu");
  const fallback = flagByCountry("eu");
  return `<img class='ev-flag' src='${src}' alt='${normalized || "unknown"}' onerror="this.onerror=null;this.src='${fallback}'" />`;
}
function switchTab(name) {
  document
    .querySelectorAll(".ttab")
    .forEach((el) => el.classList.toggle("active", el.dataset.tab === name));
  document
    .querySelectorAll(".tab-pane")
    .forEach((p) => p.classList.remove("active"));
  document.getElementById(`tab-${name}`).classList.add("active");
  updateTopbarTitle();
  if (name === "obs") {
    scheduleVideoGridLayout();
    renderEventFeed(true);
  }
}
function switchSettings(name) {
  document
    .querySelectorAll(".snav-item")
    .forEach((el) => el.classList.toggle("active", el.dataset.sp === name));
  document
    .querySelectorAll(".settings-pane")
    .forEach((p) => p.classList.remove("active"));
  document.getElementById(`sp-${name}`).classList.add("active");
  updateTopbarTitle();
}
function getActiveTabName() {
  return document.querySelector(".ttab.active")?.dataset.tab || "obs";
}

function getActiveSettingsName() {
  return document.querySelector(".snav-item.active")?.dataset.sp || "general";
}

function updateTopbarTitle() {
  const titleNode = document.querySelector(".topbar-title");
  if (!titleNode) return;
  const tabLabels = {
    obs: "Наблюдение",
    journal: "Журнал",
    lists: "Списки",
    settings: "Настройки",
  };
  const settingsLabels = {
    general: "Общие",
    channels: "Каналы",
    controllers: "Контроллеры",
    debug: "Debug",
  };
  const activeTab = getActiveTabName();
  if (activeTab !== "settings") {
    titleNode.textContent = tabLabels[activeTab] || tabLabels.obs;
    return;
  }
  const activeSettings = getActiveSettingsName();
  titleNode.textContent = `${tabLabels.settings} / ${settingsLabels[activeSettings] || settingsLabels.general}`;
}
function switchChannelSettingsTab(name) {
  document
    .querySelectorAll(".ch-tab")
    .forEach((el) => el.classList.toggle("active", el.dataset.chTab === name));
  document
    .querySelectorAll(".ch-group")
    .forEach((el) => (el.style.display = "none"));
  const active = document.getElementById(`ch-group-${name}`);
  if (active) {
    active.style.display = "block";
  }
}

function syncChannelConfigVisibility() {
  const pane = document.getElementById("channelConfigPane");
  const empty = document.getElementById("channelConfigEmpty");
  const hasSelectedChannel = Boolean(selectedChannelId);
  if (pane) pane.style.display = hasSelectedChannel ? "block" : "none";
  if (empty) empty.style.display = hasSelectedChannel ? "none" : "flex";
}

function syncControllerConfigVisibility() {
  const pane = document.getElementById("controllerConfigPane");
  const empty = document.getElementById("controllerConfigEmpty");
  const hasSelectedController = Boolean(selectedControllerId);
  if (pane) pane.style.display = hasSelectedController ? "block" : "none";
  if (empty) empty.style.display = hasSelectedController ? "none" : "flex";
}


async function refreshSystemResources() {
  try {
    const resources = await jfetch(api("/api/system/resources"));
    const cpu = Math.round(Number(resources.cpu_percent) || 0);
    const ram = Math.round(Number(resources.ram_percent) || 0);
    const cpuStat = document.getElementById("cpuStat");
    const ramStat = document.getElementById("ramStat");
    const cpuBar = document.getElementById("cpuBar");
    const ramBar = document.getElementById("ramBar");
    if (cpuStat) cpuStat.textContent = `${cpu}%`;
    if (ramStat) ramStat.textContent = `${ram}%`;
    if (cpuBar) cpuBar.style.width = `${cpu}%`;
    if (ramBar) ramBar.style.width = `${ram}%`;
  } catch (_e) {}
}

async function checkServerHealth() {
  const dot = document.getElementById("serverDot");
  if (!dot) return;
  try {
    const k = getApiKey();
    const headers = k ? { "X-Api-Key": k } : {};
    const r = await fetch(api("/api/health"), { method: "GET", headers, signal: AbortSignal.timeout(4000) });
    dot.className = r.ok ? "server-dot live" : "server-dot off";
  } catch (_e) {
    dot.className = "server-dot off";
  }
}

async function refreshChannels() {
  state.channels = await jfetch(api("/api/channels"));
  renderVideoGrid();
  renderChannelsList();
  fillChannelFilter();
  if (!selectedChannelId && state.channels.length) {
    await selectChannel(state.channels[0].id);
  }
}
function gridConfig(v) {
  if (v === "1x1") return [1, 1];
  if (v === "2x3") return [2, 3];
  if (v === "3x3") return [3, 3];
  return [2, 2];
}
function statusTextForChannel(ch) {
  const running = (ch.metrics || {}).state === "running";
  const lastError = (ch.metrics || {}).last_error;
  return !running
    ? "Канал остановлен"
    : lastError
      ? `Ошибка: ${lastError}`
      : "Ожидание кадра...";
}

function buildNoSignalHtml(statusText) {
  return `
    <div class="cam-no-signal">
      <img class="cam-no-signal-icon" src="/web/assets/icons/nosignal.svg" alt="" />
      <p>${statusText}</p>
    </div>
  `;
}

function getCellPreviewSignal(cell, ch) {
  const metricReady = Boolean((ch.metrics || {}).preview_ready);
  const imageReady = cell?.dataset.previewLoaded === "1";
  return metricReady || imageReady;
}

function ensureNoSignalOverlay(cell) {
  if (!cell) return null;
  let overlay = cell.querySelector(".cam-no-signal");
  if (overlay) return overlay;
  const wrapper = cell.querySelector(".cam-media-wrapper");
  if (!wrapper) return null;
  wrapper.insertAdjacentHTML("beforeend", buildNoSignalHtml("Ожидание кадра..."));
  return cell.querySelector(".cam-no-signal");
}

function setNoSignalVisibility(cell, shouldShow, statusText) {
  const overlay = ensureNoSignalOverlay(cell);
  if (!overlay) return;
  const textNode = overlay.querySelector("p");
  if (textNode && statusText) textNode.textContent = statusText;
  const hidden = overlay.dataset.hidden === "1";
  if (shouldShow === !hidden) return;
  overlay.dataset.hidden = shouldShow ? "0" : "1";
  overlay.style.display = shouldShow ? "flex" : "none";
}

function bindPreviewLifecycle(cell, img) {
  if (!cell || !img || img.dataset.lifecycleBound === "1") return;
  img.dataset.lifecycleBound = "1";
  img.addEventListener("load", () => {
    cell.dataset.previewLoaded = "1";
    setNoSignalVisibility(cell, false, cell.dataset.statusText || "");
    const statusDot = cell.querySelector(".cam-status");
    if (statusDot) {
      statusDot.classList.add("live");
      statusDot.classList.remove("off");
    }
  });
  img.addEventListener("error", () => {
    cell.dataset.previewLoaded = "0";
    const statusDot = cell.querySelector(".cam-status");
    if (statusDot) {
      statusDot.classList.remove("live");
      statusDot.classList.add("off");
    }
    if (!Boolean((debugSettingsCache || {}).disable_video_output)) {
      setNoSignalVisibility(cell, true, cell.dataset.statusText || "Ожидание кадра...");
    }
  });
}

function ensurePreviewStream(img, channelId) {
  if (!img) return;
  const url = apiUrl(`/api/channels/${channelId}/preview.mjpg`);
  if (img.dataset.url !== url) {
    const cell = img.closest(".video-cell");
    if (cell) {
      cell.dataset.previewLoaded = "0";
      setNoSignalVisibility(cell, true, cell.dataset.statusText || "Ожидание кадра...");
    }
    img.dataset.url = url;
    img.src = url;
  }
}


function normalizeDirectionCode(direction) {
  const value = String(direction || "").trim().toUpperCase();
  return (!value || value === "UNKNOWN") ? "" : value;
}

function getPreviewDisplayRect(cell, overlayData) {
  const wrapper = cell.querySelector(".cam-media-wrapper");
  const preview = cell.querySelector(".cam-preview");
  if (!wrapper || !preview) return null;
  const wrapperW = wrapper.clientWidth;
  const wrapperH = wrapper.clientHeight;
  if (wrapperW <= 0 || wrapperH <= 0) return null;

  const frameSize = overlayData.frame_size || {};
  const frameW = Number(frameSize.width) || Number(preview.naturalWidth) || 0;
  const frameH = Number(frameSize.height) || Number(preview.naturalHeight) || 0;
  if (frameW <= 0 || frameH <= 0) {
    return { x: 0, y: 0, width: wrapperW, height: wrapperH };
  }

  const frameAspect = frameW / frameH;
  const wrapperAspect = wrapperW / wrapperH;
  let width = wrapperW;
  let height = wrapperH;
  if (frameAspect > wrapperAspect) {
    height = Math.round(wrapperW / frameAspect);
  } else {
    width = Math.round(wrapperH * frameAspect);
  }
  return {
    x: Math.floor((wrapperW - width) / 2),
    y: Math.floor((wrapperH - height) / 2),
    width,
    height,
  };
}



function applyMotionHighlight(cell, ch) {
  if (!cell) return;
  const motionActive = Boolean((ch?.metrics || {}).motion_active);
  cell.classList.toggle("motion-active", motionActive);
}

function refreshVideoCellOverlayState(cell, ch) {
  if (!cell || !ch) return;
  const statusText = statusTextForChannel(ch);
  cell.dataset.statusText = statusText;

  if (Boolean((debugSettingsCache || {}).disable_video_output)) {
    const statusDot = cell.querySelector(".cam-status");
    if (statusDot) {
      statusDot.classList.remove("live");
      statusDot.classList.add("off");
    }
    removeCellPreviewImg(cell);
    setNoSignalVisibility(cell, true, "Видеопоток отключён настройками отладки");
    applyMotionHighlight(cell, ch);
    renderDebugOverlay(cell, ch);
    return;
  }

  const hasPreviewSignal = getCellPreviewSignal(cell, ch);
  const statusDot = cell.querySelector(".cam-status");
  if (statusDot) {
    statusDot.classList.toggle("live", hasPreviewSignal);
    statusDot.classList.toggle("off", !hasPreviewSignal);
  }
  setNoSignalVisibility(cell, !hasPreviewSignal, statusText);
  applyMotionHighlight(cell, ch);
  renderDebugOverlay(cell, ch);
}

async function refreshOverlayStates() {
  try {
    const payload = await jfetch(api("/api/debug/channels"));
    const channels = Array.isArray(payload.channels) ? payload.channels : [];
    const byId = new Map(channels.map((row) => [Number(row.channel_id), row]));
    state.channels.forEach((ch) => {
      const row = byId.get(Number(ch.id));
      if (!row) return;
      if (row.metrics) ch.metrics = row.metrics;
      if (row.debug_state) ch.debug_state = row.debug_state;
      const cell = document.querySelector(`.video-cell[data-channel-id='${ch.id}']`);
      if (cell) refreshVideoCellOverlayState(cell, ch);
    });
  } catch (_e) {}
}

function renderDebugOverlay(cell, ch) {
  if (!cell || !ch) return;
  const state = ch.debug_state || {};
  const overlayData = state.overlay || {};
  const bbox = Array.isArray(overlayData.bbox_norm) ? overlayData.bbox_norm : null;
  const overlayLayer = cell.querySelector(".cam-overlay-layer");
  if (!overlayLayer) return;
  const box = overlayLayer.querySelector(".cam-detection-box");
  const ocrEl = overlayLayer.querySelector(".cam-ocr-label");
  const dirEl = overlayLayer.querySelector(".cam-direction-label");
  if (!box || !ocrEl || !dirEl) return;

  const showMetrics = Boolean((debugSettingsCache || {}).show_channel_metrics);
  const displayRect = getPreviewDisplayRect(cell, overlayData);
  if (!bbox || bbox.length < 4 || !displayRect || !showMetrics) {
    box.style.display = "none";
    ocrEl.style.display = "none";
    dirEl.style.display = "none";
  } else {
    const [x1, y1, x2, y2] = bbox.map((v) => Math.max(0, Math.min(1, Number(v) || 0)));
    const boxW = Math.max(0, x2 - x1) * displayRect.width;
    const boxH = Math.max(0, y2 - y1) * displayRect.height;
    if (boxW <= 0 || boxH <= 0) {
      box.style.display = "none";
      ocrEl.style.display = "none";
      dirEl.style.display = "none";
    } else {
      const left = displayRect.x + x1 * displayRect.width;
      const top = displayRect.y + y1 * displayRect.height;
      box.style.display = "block";
      box.style.left = `${left}px`;
      box.style.top = `${top}px`;
      box.style.width = `${boxW}px`;
      box.style.height = `${boxH}px`;

      const ocrText = String(overlayData.ocr_text || "").trim();
      const directionCode = normalizeDirectionCode(overlayData.direction);
      const labelGap = 4;
      const ocrHeight = 22;
      const dirHeight = 20;
      const hasSpaceAbove = top >= (ocrHeight + labelGap + 2);
      const ocrTop = hasSpaceAbove ? -(ocrHeight + labelGap) : (boxH + labelGap);
      const dirTop = hasSpaceAbove ? (boxH + labelGap) : (boxH + labelGap + ocrHeight + labelGap);

      if (ocrText) {
        ocrEl.textContent = ocrText;
        ocrEl.style.display = "block";
        ocrEl.style.top = `${ocrTop}px`;
      } else {
        ocrEl.style.display = "none";
      }

      if (directionCode) {
        dirEl.textContent = formatDirection(directionCode).plain;
        dirEl.style.display = "block";
        dirEl.style.top = `${dirTop}px`;
      } else {
        dirEl.style.display = "none";
      }

      const maxBottom = displayRect.y + displayRect.height;
      const directionBottom = top + dirTop + dirHeight;
      if (directionBottom > maxBottom && dirEl.style.display !== "none") {
        dirEl.style.top = `${Math.max(boxH + 2, boxH - dirHeight)}px`;
      }
    }
  }

  const metricsWidget = cell.querySelector(".cam-metrics-widget");
  if (!metricsWidget) return;
  metricsWidget.style.display = showMetrics ? "grid" : "none";
  if (!showMetrics) return;
  const metrics = ch.metrics || {};
  const timings = (state.stage_timings || {});
  const compact = cell.clientWidth < 360 || cell.clientHeight < 230;
  const tiny = cell.clientWidth < 250 || cell.clientHeight < 170;
  const primaryRows = [
    `State: ${metrics.state || "unknown"}`,
    `FPS: ${(Number(metrics.fps) || 0).toFixed(2)} · Lat: ${(Number(metrics.latency_ms) || 0).toFixed(1)}ms`,
    `Rec/TO: ${(Number(metrics.reconnect_count) || 0)}/${(Number(metrics.timeout_count) || 0)}`,
  ];
  const secondaryRows = [
    `Empty/Fail: ${(Number(metrics.empty_frames) || 0)}/${(Number(metrics.failed_frames) || 0)}`,
    `Skip D/M: ${(Number(metrics.detector_skipped_frames) || 0)}/${(Number(metrics.motion_skipped_frames) || 0)}`,
    `D/O/P: ${(Number(timings.detection_ms) || 0).toFixed(1)}/${(Number(timings.ocr_ms) || 0).toFixed(1)}/${(Number(timings.postprocess_ms) || 0).toFixed(1)}ms`,
  ];
  metricsWidget.classList.toggle("compact", compact);
  metricsWidget.classList.toggle("tiny", tiny);
  const rows = tiny ? primaryRows.slice(0, 2) : (compact ? primaryRows : primaryRows.concat(secondaryRows));
  metricsWidget.innerHTML = rows.map((row) => `<div>${row}</div>`).join("");
}

function removeCellPreviewImg(cell) {
  const img = cell.querySelector(".cam-preview");
  if (!img) return;
  img.removeAttribute("src");
  img.dataset.url = "";
  img.remove();
}

function ensureCellPreviewImg(cell, channelId) {
  let img = cell.querySelector(".cam-preview");
  if (!img) {
    const wrapper = cell.querySelector(".cam-media-wrapper");
    if (!wrapper) return null;
    img = document.createElement("img");
    img.className = "cam-preview";
    img.id = `v-${channelId}`;
    img.alt = `preview CAM-${channelId}`;
    const overlayLayer = wrapper.querySelector(".cam-overlay-layer");
    wrapper.insertBefore(img, overlayLayer || null);
  }
  bindPreviewLifecycle(cell, img);
  return img;
}

function createVideoCell(ch) {
  const statusText = statusTextForChannel(ch);
  const videoDisabled = Boolean((debugSettingsCache || {}).disable_video_output);
  const cell = document.createElement("div");
  cell.className = "video-cell";
  cell.dataset.channelId = String(ch.id);
  cell.dataset.previewLoaded = "0";
  cell.dataset.statusText = statusText;
  cell.innerHTML = `
    <div class='video-cell-bg'></div>
    <div class='cam-media-wrapper'>
      <div class='cam-overlay-layer'>
        <div class='cam-detection-box'>
          <div class='cam-ocr-label'></div>
          <div class='cam-direction-label'></div>
        </div>
      </div>
    </div>
    <div class='cam-label'>${ch.name}</div>
    <div class='cam-status off'></div>
    <div class='cam-metrics-widget'></div>
    <div class='cam-plate' id='plate-${ch.id}'></div>`;
  ensureNoSignalOverlay(cell);
  if (!videoDisabled) {
    const preview = ensureCellPreviewImg(cell, ch.id);
    const hasPreviewSignal = getCellPreviewSignal(cell, ch);
    setNoSignalVisibility(cell, !hasPreviewSignal, statusText);
    const statusDot = cell.querySelector(".cam-status");
    if (statusDot) {
      statusDot.classList.toggle("live", hasPreviewSignal);
      statusDot.classList.toggle("off", !hasPreviewSignal);
    }
    ensurePreviewStream(preview, ch.id);
  }
  refreshVideoCellOverlayState(cell, ch);
  updateChannelLastPlate(ch.id, state.lastPlatesByChannelId[ch.id]);
  return cell;
}

function updateVideoCell(cell, ch) {
  const statusText = statusTextForChannel(ch);
  cell.dataset.statusText = statusText;
  const label = cell.querySelector(".cam-label");
  if (label) label.textContent = ch.name;
  if (!Boolean((debugSettingsCache || {}).disable_video_output)) {
    const preview = ensureCellPreviewImg(cell, ch.id);
    const hasPreviewSignal = getCellPreviewSignal(cell, ch);
    const statusDot = cell.querySelector(".cam-status");
    if (statusDot) {
      statusDot.classList.toggle("live", hasPreviewSignal);
      statusDot.classList.toggle("off", !hasPreviewSignal);
    }
    setNoSignalVisibility(cell, !hasPreviewSignal, statusText);
    ensurePreviewStream(preview, ch.id);
  }
  refreshVideoCellOverlayState(cell, ch);
  updateChannelLastPlate(ch.id, state.lastPlatesByChannelId[ch.id]);
}

function computeVideoGridRowHeight(grid, rows, cols) {
  if (!grid || rows <= 0 || cols <= 0) return null;
  const style = window.getComputedStyle(grid);
  const gap = Number.parseFloat(style.rowGap || style.gap || "0") || 0;
  const width = grid.clientWidth;
  const height = grid.clientHeight;
  if (width <= 0 || height <= 0) return null;

  const availableWidth = width - gap * (cols - 1);
  const availableHeight = height - gap * (rows - 1);
  if (availableWidth <= 0 || availableHeight <= 0) return null;

  const byWidth = (availableWidth / cols) * (9 / 16);
  const byHeight = availableHeight / rows;
  const rowHeight = Math.floor(Math.min(byWidth, byHeight));
  return rowHeight > 0 ? rowHeight : null;
}

function renderVideoGrid() {
  const grid = document.getElementById("videoGrid");
  if (!grid) return;
  const [presetRows, cols] = gridConfig(document.getElementById("gridSelect").value);
  const visible = state.channels.slice(0, presetRows * cols);
  const effectiveRows = visible.length > 0 ? Math.ceil(visible.length / cols) : 1;

  grid.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
  const stableRowHeight = computeVideoGridRowHeight(grid, effectiveRows, cols);
  grid.style.gridTemplateRows = stableRowHeight
    ? `repeat(${effectiveRows}, ${stableRowHeight}px)`
    : `repeat(${effectiveRows}, minmax(0, 1fr))`;
  const countEl = document.getElementById("channelsCount");
  const newCount = `${state.channels.length} канала`;
  if (countEl && countEl.textContent !== newCount) {
    countEl.textContent = newCount;
    countEl.style.animation = "none";
    void countEl.offsetHeight;
    countEl.style.animation = "count-bump 0.3s ease-out";
  }

  const visibleIds = new Set(visible.map((ch) => String(ch.id)));
  Array.from(grid.children).forEach((cell) => {
    if (!visibleIds.has(cell.dataset.channelId || "")) {
      cell.remove();
    }
  });

  for (const ch of visible) {
    let cell = grid.querySelector(`.video-cell[data-channel-id='${ch.id}']`);
    if (!cell) {
      cell = createVideoCell(ch);
    } else {
      updateVideoCell(cell, ch);
    }
    grid.appendChild(cell);
  }
}

let videoGridLayoutFrame = null;
let videoGridSecondPassFrame = null;
let videoGridResizeObserver = null;
function scheduleVideoGridLayout(secondPass = false) {
  if (videoGridLayoutFrame !== null) return;
  videoGridLayoutFrame = requestAnimationFrame(() => {
    videoGridLayoutFrame = null;
    const obsTab = document.getElementById("tab-obs");
    if (!obsTab || !obsTab.classList.contains("active")) return;
    renderVideoGrid();
    if (secondPass && videoGridSecondPassFrame === null) {
      videoGridSecondPassFrame = requestAnimationFrame(() => {
        videoGridSecondPassFrame = null;
        renderVideoGrid();
      });
    }
  });
}

function setupVideoGridLayoutGuards() {
  window.addEventListener("resize", scheduleVideoGridLayout);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) scheduleVideoGridLayout();
  });
  if (typeof ResizeObserver !== "function") return;
  const obsLeft = document.querySelector("#tab-obs .obs-left");
  const grid = document.getElementById("videoGrid");
  if (!obsLeft && !grid) return;
  videoGridResizeObserver = new ResizeObserver(() => {
    scheduleVideoGridLayout(true);
  });
  if (obsLeft) videoGridResizeObserver.observe(obsLeft);
  if (grid) videoGridResizeObserver.observe(grid);
}

function trimEventFeedOverflow(feed) {
  if (!feed) return;
  while (feed.lastElementChild && feed.scrollHeight > feed.clientHeight) {
    feed.removeChild(feed.lastElementChild);
  }
}

function scheduleEventFeedRender(forceRebuild = true) {
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

function setupEventFeedLayoutGuards() {
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
  const byName = state.channels.find((c) => String(c.name) === String(ev.channel));
  return byName ? Number(byName.id) : null;
}

function updateChannelLastPlate(channelId, plateData) {
  const id = Number(channelId);
  if (!Number.isFinite(id) || id <= 0) return;
  const plateNode = document.getElementById(`plate-${id}`);
  if (!plateNode) return;
  const plateText = String((plateData || {}).plate || "").trim();
  const wasVisible = plateNode.style.display === "block";
  const prevText = plateNode.textContent;
  if (plateText) {
    // Анимация только при смене номера
    if (!wasVisible || prevText !== plateText) {
      plateNode.textContent = plateText;
      plateNode.style.display = "block";
      plateNode.style.animation = "none";
      void plateNode.offsetWidth; // reflow
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
    timestamp: ev.timestamp || null,
    country: ev.country || null,
    confidence: ev.confidence ?? null,
    direction: ev.direction || null,
  };
  state.lastPlatesByChannelId[channelId] = payload;
  updateChannelLastPlate(channelId, payload);
}

async function hydrateChannelLastPlates() {
  const rows = await jfetch(api('/api/channels/last-plates'));
  state.lastPlatesByChannelId = rows || {};
  Object.entries(state.lastPlatesByChannelId).forEach(([channelId, payload]) => {
    updateChannelLastPlate(Number(channelId), payload);
  });
}

function renderEventFeed(forceRebuild = false) {
  const feed = document.getElementById("eventFeed");
  if (!feed) return;

  const events = state.allEvents;
  if (!events.length) { feed.innerHTML = ""; return; }

  function makeItem(item, isNew) {
    const conf = Number(item.confidence || 0);
    const direction = formatDirection(item.direction);
    const key = String(item.id ?? item.timestamp ?? "");
    const channelName = item.channel || `CAM-${item.channel_id || ""}`;
    const timeStr = new Date(item.timestamp || Date.now()).toLocaleTimeString();
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
    div.innerHTML = `${flagHtml(item.country)}<div class='ev-row-top'><span class='ev-plate'>${item.plate || "—"}</span><span class='ev-direction badge ${direction.badgeClass}'>${direction.label}</span></div><div class='ev-row-bottom'><span class='ev-meta-channel'>${channelName}</span><span class='ev-meta-time'>${timeStr}</span><span class='ev-conf ${conf < 0.85 ? "warn" : ""}'>${conf.toFixed(2)}</span></div>`;
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

  // Инкрементальное: только новые события сверху
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
  state.allEvents.unshift(ev);
  if (state.allEvents.length > 500) state.allEvents.pop();
  renderEventFeed();
  // Prepend new live event to journal if it matches active filters
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
  addDebug(
    `[INFO] event: ${ev.plate || "-"} conf=${Number(ev.confidence || 0).toFixed(2)}`,
    "ok",
  );
}
async function loadEventFeedHistory() {
  const data = await jfetch(api("/api/events?limit=50"));
  const items = Array.isArray(data) ? data : (data.items || []);
  state.allEvents = items;
  renderEventFeed();
}

const journalState = {
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

async function loadJournal() {
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
    addDebug(`[WARN] loadJournal: ${err.message}`, "warn");
  } finally {
    journalState.loading = false;
  }
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
    `<td class="col-plate plate-cell">${ev.plate || ""}</td>` +
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

function initJournalScroll() {
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

function formatDirection(directionValue) {
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

let editingEntryId = null;

function showToast(message, duration = 2000) {
  const existing = document.getElementById("appToast");
  if (existing) existing.remove();
  const toast = document.createElement("div");
  toast.id = "appToast";
  toast.className = "app-toast";
  toast.textContent = message;
  document.body.appendChild(toast);
  requestAnimationFrame(() => {
    requestAnimationFrame(() => toast.classList.add("app-toast-visible"));
  });
  setTimeout(() => {
    toast.classList.remove("app-toast-visible");
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

function normalizePlate(plate) {
  return (plate || "").toUpperCase().replace(/\s/g, "");
}

async function refreshPlateLookup() {
  try {
    const plates = await jfetch(api("/api/lists/plates"));
    const priority = { white: 1, info: 2, black: 3 };
    const lookup = {};
    (plates || []).forEach(({ plate, list_type }) => {
      if (!lookup[plate] || (priority[list_type] || 0) > (priority[lookup[plate]] || 0)) {
        lookup[plate] = list_type;
      }
    });
    state.plateLookup = lookup;
  } catch (_e) {
    state.plateLookup = {};
  }
}

async function loadLists() {
  state.lists = await jfetch(api("/api/lists"));
  renderLists();
  renderCustomListOptions(currentChannelCustomListIds);
  await refreshPlateLookup();
  renderEventFeed(true);
}

function syncListMainVisibility() {
  const hasSelection = !!state.selectedListId && state.lists.length > 0;
  const header = document.getElementById("listsMainHeader");
  const dataWrap = document.getElementById("listsDataWrap");
  const emptyState = document.getElementById("listsEmptyState");
  if (header) header.style.display = hasSelection ? "" : "none";
  if (dataWrap) dataWrap.style.display = hasSelection ? "" : "none";
  if (emptyState) emptyState.style.display = hasSelection ? "none" : "";
}

function listTypeDot(type) {
  if (type === "black") return "dot-black";
  if (type === "info") return "dot-info";
  return "dot-white";
}

function renderLists() {
  const items = document.getElementById("listItems");
  items.innerHTML = "";
  state.lists.forEach((l, idx) => {
    const isActive = l.id === state.selectedListId || (!state.selectedListId && idx === 0);
    if (!state.selectedListId && idx === 0) state.selectedListId = l.id;
    const div = document.createElement("div");
    div.className = `list-item type-${l.type}${isActive ? " active" : ""}`;
    div.innerHTML = `<div class='list-item-dot ${listTypeDot(l.type)}'></div><div class='list-item-name'>${l.name}</div><div class='list-item-count'>${l.entries_count ?? "…"}</div>`;
    div.onclick = () => {
      state.selectedListId = l.id;
      renderLists();
      loadEntries(l.id);
    };
    items.appendChild(div);
  });
  syncListMainVisibility();
  if (state.selectedListId) loadEntries(state.selectedListId);
}

async function loadEntries(listId) {
  const rows = await jfetch(api(`/api/lists/${listId}/entries`));
  state.currentEntries = rows;
  const list = state.lists.find((x) => x.id === listId);
  document.getElementById("listTitle").textContent = list ? list.name : "—";
  const body = document.getElementById("entriesBody");
  body.innerHTML = "";
  rows.forEach((r) => {
    let info = {};
    try { info = JSON.parse(r.comment || "{}"); } catch (_e) {}
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class='plate-cell'>${r.plate}</td><td>${info.first_name || ""}</td><td>${info.last_name || ""}</td><td>${info.patronymic || ""}</td><td>${info.phone || ""}</td><td>${info.car_make || ""}</td><td class="col-actions"><button class="entry-edit-btn">Изменить</button></td>`;
    tr.querySelector(".entry-edit-btn").onclick = () => openEditEntryModal(r);
    body.appendChild(tr);
  });
}

function openEditEntryModal(entry) {
  editingEntryId = entry.id;
  let info = {};
  try { info = JSON.parse(entry.comment || "{}"); } catch (_e) {}
  document.getElementById("addEntryModalTitle").textContent = "Изменить запись";
  document.getElementById("entryLastName").value = info.last_name || "";
  document.getElementById("entryFirstName").value = info.first_name || "";
  document.getElementById("entryPatronymic").value = info.patronymic || "";
  document.getElementById("entryPhone").value = info.phone || "";
  document.getElementById("entryCarMake").value = info.car_make || "";
  document.getElementById("entryPlate").value = entry.plate || "";
  document.getElementById("addEntryError").textContent = "";
  openModal("addEntryModal");
  setTimeout(() => document.getElementById("entryLastName").focus(), 50);
}

function exportCurrentListCSV() {
  if (!state.selectedListId) return;
  const list = state.lists.find((l) => l.id === state.selectedListId);
  const headers = ["Гос. номер", "Имя", "Фамилия", "Отчество", "Телефон", "Марка авто"];
  const lines = [headers.join(",")];
  (state.currentEntries || []).forEach((r) => {
    let info = {};
    try { info = JSON.parse(r.comment || "{}"); } catch (_e) {}
    const cells = [r.plate, info.first_name || "", info.last_name || "", info.patronymic || "", info.phone || "", info.car_make || ""]
      .map((v) => `"${String(v).replace(/"/g, '""')}"`);
    lines.push(cells.join(","));
  });
  const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${list ? list.name : "list"}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

let selectedChannelId = null;
let channelConfigRequestToken = 0;
let controllersCache = [];
let selectedControllerId = null;
let roiPoints = [];
let currentChannelCustomListIds = [];
const hotkeyMap = new Map();
let roiDrag = -1;
let roiBgImage = null;

let plateSizeBgImage = null;
let plateSizeBoxes = {
  min: { x: 200, y: 130, width: 80, height: 20 },
  max: { x: 100, y: 60, width: 600, height: 240 },
};
let plateSizeDrag = null;

function val(id) {
  return document.getElementById(id).value;
}
function setVal(id, v) {
  document.getElementById(id).value = v ?? "";
}
function setChk(id, v) {
  document.getElementById(id).checked = !!v;
}
function parseIds(raw) {
  return String(raw || "")
    .split(",")
    .map((x) => Number(x.trim()))
    .filter((x) => Number.isFinite(x));
}

function applyTheme(theme) {
  const normalized = String(theme || "dark").toLowerCase() === "light" ? "light" : "dark";
  document.body.setAttribute("data-theme", normalized);
  try {
    localStorage.setItem("anpr_theme", normalized);
  } catch (_e) {}
}

async function loadGlobalSettings() {
  const g = await jfetch(api("/api/settings"));
  setVal("g_grid", g.grid);
  setVal("g_theme", g.theme);
  applyTheme(g.theme);
  setChk("g_sl_enabled", g.reconnect.signal_loss.enabled);
  setVal("g_frame_timeout", g.reconnect.signal_loss.frame_timeout_seconds);
  setVal("g_retry_interval", g.reconnect.signal_loss.retry_interval_seconds);
  setChk("g_periodic_enabled", g.reconnect.periodic.enabled);
  setVal("g_periodic_minutes", g.reconnect.periodic.interval_minutes);
  setVal("g_screenshots_dir", g.storage.screenshots_dir);
  setVal("g_logs_dir", g.storage.logs_dir);
  setChk("g_auto_cleanup", g.storage.auto_cleanup_enabled);
  setVal("g_cleanup_minutes", g.storage.cleanup_interval_minutes);
  setVal("g_events_retention", g.storage.events_retention_days);
  setVal("g_media_retention", g.storage.media_retention_days);
  setVal("g_max_screenshots", g.storage.max_screenshots_mb);
  setVal("g_export_dir", g.storage.export_dir);
  setVal("g_postgres_dsn", g.storage.postgres_dsn);
  setVal("g_log_level", g.logging.level);
  setVal("g_log_retention", g.logging.retention_days);
  setVal("g_timezone", g.time.timezone);
  setVal("g_offset_minutes", g.time.offset_minutes);
  setVal("g_plates_dir", g.plates.config_dir);
  setVal("g_countries", (g.plates.enabled_countries || []).join(","));
  setChk("d_metrics", g.debug.show_channel_metrics);
  setChk("d_log", g.debug.log_panel_enabled);
  setChk("d_video_off", g.debug.disable_video_output);
  debugSettingsCache = g.debug || {};
  applyDebugPanelVisibility();
}

async function saveGeneral() {
  applyTheme(val("g_theme"));
  const payload = {
    grid: val("g_grid"),
    theme: val("g_theme"),
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
      screenshots_dir: val("g_screenshots_dir"),
      logs_dir: val("g_logs_dir"),
      auto_cleanup_enabled: document.getElementById("g_auto_cleanup").checked,
      cleanup_interval_minutes: Number(val("g_cleanup_minutes")),
      events_retention_days: Number(val("g_events_retention")),
      media_retention_days: Number(val("g_media_retention")),
      max_screenshots_mb: Number(val("g_max_screenshots")),
      export_dir: val("g_export_dir"),
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
      config_dir: val("g_plates_dir"),
      enabled_countries: parseIds("").length
        ? []
        : String(val("g_countries"))
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
    },
    debug: {
      show_channel_metrics: document.getElementById("d_metrics").checked,
      log_panel_enabled: document.getElementById("d_log").checked,
      disable_video_output: document.getElementById("d_video_off").checked,
    },
  };
  const updated = await jfetch(api("/api/settings"), "PUT", payload);
  debugSettingsCache = (updated || {}).debug || payload.debug;
  setChk("d_video_off", Boolean(debugSettingsCache.disable_video_output));
  setChk("d_metrics", Boolean(debugSettingsCache.show_channel_metrics));
  setChk("d_log", Boolean(debugSettingsCache.log_panel_enabled));
  document.querySelectorAll(".cam-preview").forEach((img) => {
    img.dataset.url = "";
    if (debugSettingsCache.disable_video_output) {
      img.removeAttribute("src");
    }
  });
  applyDebugPanelVisibility();
  scheduleVideoGridLayout(true);
  addDebug("[OK] global settings saved", "ok");
  showToast("Настройки сохранены");
}

function renderChannelsList() {
  const box = document.getElementById("channelsList");
  box.innerHTML = "";
  if (!state.channels.length) {
    selectedChannelId = null;
    syncChannelConfigVisibility();
    box.innerHTML = '<div class="ch-item">Нет каналов</div>';
    return;
  }
  const selectedNum = Number(selectedChannelId);
  state.channels.forEach((c) => {
    const run = (c.metrics || {}).state === "running";
    const row = document.createElement("div");
    row.className = `ch-item ${Number(c.id) === selectedNum ? "active" : ""}`;
    row.innerHTML = `<div class='ch-item-dot ${run ? "" : "off"}'></div> ${c.name}`;
    row.onclick = () => selectChannel(c.id);
    box.appendChild(row);
  });
  if (selectedChannelId != null && !state.channels.some((c) => Number(c.id) === selectedNum)) {
    selectedChannelId = null;
  }
  syncChannelConfigVisibility();
}

function toCanvasPoint(point, unit, cv) {
  if (unit === "percent") {
    return {
      x: ((Number(point.x) || 0) * cv.width) / 100,
      y: ((Number(point.y) || 0) * cv.height) / 100,
    };
  }
  return { x: Number(point.x) || 0, y: Number(point.y) || 0 };
}
function toPercentPoint(point, cv) {
  const x = Math.max(0, Math.min(cv.width, Number(point.x) || 0));
  const y = Math.max(0, Math.min(cv.height, Number(point.y) || 0));
  return {
    x: Number(((x / cv.width) * 100).toFixed(3)),
    y: Number(((y / cv.height) * 100).toFixed(3)),
  };
}

function defaultROIPointsForCanvas(cv) {
  return [
    { x: 0, y: 0 },
    { x: cv.width, y: 0 },
    { x: cv.width, y: cv.height },
    { x: 0, y: cv.height },
  ];
}

function pointToSegmentDistance(point, start, end) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  if (dx === 0 && dy === 0) {
    return Math.hypot(point.x - start.x, point.y - start.y);
  }
  const t = Math.max(
    0,
    Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / (dx * dx + dy * dy)),
  );
  const projectionX = start.x + t * dx;
  const projectionY = start.y + t * dy;
  return Math.hypot(point.x - projectionX, point.y - projectionY);
}

function findInsertSegmentIndex(point) {
  if (roiPoints.length < 2) return -1;
  const threshold = 8;
  let bestIndex = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let i = 0; i < roiPoints.length; i += 1) {
    const start = roiPoints[i];
    const end = roiPoints[(i + 1) % roiPoints.length];
    const distance = pointToSegmentDistance(point, start, end);
    if (distance <= threshold && distance < bestDistance) {
      bestDistance = distance;
      bestIndex = i;
    }
  }
  return bestIndex;
}
function drawROI() {
  const cv = document.getElementById("roiCanvas");
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (roiBgImage && roiBgImage.complete) {
    ctx.drawImage(roiBgImage, 0, 0, cv.width, cv.height);
  }
  ctx.fillStyle = "rgba(124,107,250,0.15)";
  ctx.strokeStyle = "#9b8fff";
  ctx.lineWidth = 2;
  if (roiPoints.length >= 2) {
    ctx.beginPath();
    roiPoints.forEach((p, i) => {
      if (i === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    if (roiPoints.length >= 3) {
      ctx.closePath();
      ctx.fill();
    }
    ctx.stroke();
  }
  roiPoints.forEach((p) => {
    ctx.fillStyle = "#9b8fff";
    ctx.beginPath();
    ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
    ctx.fill();
  });
}
async function refreshROISnapshot() {
  if (!selectedChannelId) return;
  const channelId = selectedChannelId;
  try {
    const res = await fetch(
      apiUrl(`/api/channels/${channelId}/snapshot.jpg?t=${Date.now()}`),
      { cache: "no-store" },
    );
    if (!res.ok) {
      throw new Error(`snapshot status ${res.status}`);
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(objectUrl);
      if (Number(selectedChannelId) !== Number(channelId)) return;
      roiBgImage = img;
      drawROI();
    };
    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      addDebug("[WARN] ROI snapshot decode failed", "warn");
    };
    img.src = objectUrl;
  } catch (err) {
    addDebug(`[WARN] ROI snapshot unavailable: ${err.message}`, "warn");
  }
}
function setupROI() {
  const cv = document.getElementById("roiCanvas");
  let moved = false;
  let downPoint = null;
  cv.oncontextmenu = (e) => {
    e.preventDefault();
    const r = cv.getBoundingClientRect();
    const x = e.clientX - r.left,
      y = e.clientY - r.top;
    const idx = roiPoints.findIndex((p) => Math.hypot(p.x - x, p.y - y) < 10);
    if (idx >= 0) {
      roiPoints.splice(idx, 1);
      drawROI();
      setVal("c_roi_points", JSON.stringify(roiPoints));
    }
  };
  cv.onmousedown = (e) => {
    const r = cv.getBoundingClientRect();
    const x = e.clientX - r.left,
      y = e.clientY - r.top;
    downPoint = { x, y };
    moved = false;
    roiDrag = roiPoints.findIndex((p) => Math.hypot(p.x - x, p.y - y) < 10);
  };
  cv.onmousemove = (e) => {
    if (roiDrag < 0) return;
    const r = cv.getBoundingClientRect();
    const x = e.clientX - r.left,
      y = e.clientY - r.top;
    roiPoints[roiDrag] = { x, y };
    moved = true;
    drawROI();
  };
  cv.onmouseup = (e) => {
    const r = cv.getBoundingClientRect();
    const x = e.clientX - r.left,
      y = e.clientY - r.top;
    if (roiDrag >= 0) {
      roiDrag = -1;
      if (moved) {
        setVal("c_roi_points", JSON.stringify(roiPoints));
        return;
      }
    }
    if (e.button !== 0) return;
    if (downPoint && Math.hypot(downPoint.x - x, downPoint.y - y) > 4) return;
    const nearExisting = roiPoints.findIndex(
      (p) => Math.hypot(p.x - x, p.y - y) < 10,
    );
    if (nearExisting !== -1) return;
    const insertAfter = findInsertSegmentIndex({ x, y });
    if (insertAfter === -1) return;
    roiPoints.splice(insertAfter + 1, 0, { x, y });
    drawROI();
    setVal("c_roi_points", JSON.stringify(roiPoints));
  };
}

/* ─── Plate Size visual editor ─────────────────────── */

function drawPlateSizeBoxes() {
  const cv = document.getElementById("plateSizeCanvas");
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (plateSizeBgImage && plateSizeBgImage.complete) {
    ctx.drawImage(plateSizeBgImage, 0, 0, cv.width, cv.height);
  }
  const boxes = [
    { key: "max", color: "#f59e0b", fill: "rgba(245,158,11,0.12)", label: "MAX" },
    { key: "min", color: "#3b82f6", fill: "rgba(59,130,246,0.15)", label: "MIN" },
  ];
  boxes.forEach(({ key, color, fill, label }) => {
    const b = plateSizeBoxes[key];
    ctx.fillStyle = fill;
    ctx.fillRect(b.x, b.y, b.width, b.height);
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.strokeRect(b.x, b.y, b.width, b.height);
    ctx.fillStyle = color;
    ctx.font = "bold 11px sans-serif";
    ctx.fillText(label + " " + Math.round(b.width) + "\u00d7" + Math.round(b.height), b.x + 4, b.y - 4);
  });
}

function syncPlateSizeInputsFromBoxes() {
  setVal("c_min_w", Math.round(plateSizeBoxes.min.width));
  setVal("c_min_h", Math.round(plateSizeBoxes.min.height));
  setVal("c_max_w", Math.round(plateSizeBoxes.max.width));
  setVal("c_max_h", Math.round(plateSizeBoxes.max.height));
}

function syncPlateSizeBoxesFromInputs() {
  const cv = document.getElementById("plateSizeCanvas");
  const minW = Math.max(1, Number(val("c_min_w")) || 1);
  const minH = Math.max(1, Number(val("c_min_h")) || 1);
  const maxW = Math.max(1, Number(val("c_max_w")) || 1);
  const maxH = Math.max(1, Number(val("c_max_h")) || 1);
  plateSizeBoxes.min.width = Math.min(minW, cv.width);
  plateSizeBoxes.min.height = Math.min(minH, cv.height);
  plateSizeBoxes.max.width = Math.min(maxW, cv.width);
  plateSizeBoxes.max.height = Math.min(maxH, cv.height);
  clampBoxInCanvas(plateSizeBoxes.min, cv);
  clampBoxInCanvas(plateSizeBoxes.max, cv);
  drawPlateSizeBoxes();
}

function clampBoxInCanvas(box, cv) {
  box.width = Math.max(1, Math.min(box.width, cv.width));
  box.height = Math.max(1, Math.min(box.height, cv.height));
  box.x = Math.max(0, Math.min(box.x, cv.width - box.width));
  box.y = Math.max(0, Math.min(box.y, cv.height - box.height));
}

function defaultPlateSizeOverlay(cv) {
  const minW = Number(val("c_min_w")) || 80;
  const minH = Number(val("c_min_h")) || 20;
  const maxW = Number(val("c_max_w")) || 600;
  const maxH = Number(val("c_max_h")) || 240;
  return {
    min: { x: (cv.width - minW) / 2, y: (cv.height - minH) / 2 + 40, width: minW, height: minH },
    max: { x: (cv.width - maxW) / 2, y: (cv.height - maxH) / 2 - 20, width: maxW, height: maxH },
  };
}

async function refreshPlateSizeSnapshot() {
  if (!selectedChannelId) return;
  const channelId = selectedChannelId;
  try {
    const res = await fetch(
      apiUrl(`/api/channels/${channelId}/snapshot.jpg?t=${Date.now()}`),
      { cache: "no-store" },
    );
    if (!res.ok) throw new Error(`snapshot status ${res.status}`);
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(objectUrl);
      if (Number(selectedChannelId) !== Number(channelId)) return;
      plateSizeBgImage = img;
      drawPlateSizeBoxes();
    };
    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      addDebug("[WARN] plate-size snapshot decode failed", "warn");
    };
    img.src = objectUrl;
  } catch (err) {
    addDebug(`[WARN] plate-size snapshot unavailable: ${err.message}`, "warn");
  }
}

function hitTestPlateSizeBox(x, y, box) {
  const E = 7;
  const inX = x >= box.x - E && x <= box.x + box.width + E;
  const inY = y >= box.y - E && y <= box.y + box.height + E;
  if (!inX || !inY) return null;

  const nearL = Math.abs(x - box.x) <= E;
  const nearR = Math.abs(x - (box.x + box.width)) <= E;
  const nearT = Math.abs(y - box.y) <= E;
  const nearB = Math.abs(y - (box.y + box.height)) <= E;

  if (nearT && nearL) return "tl";
  if (nearT && nearR) return "tr";
  if (nearB && nearL) return "bl";
  if (nearB && nearR) return "br";
  if (nearL) return "l";
  if (nearR) return "r";
  if (nearT) return "t";
  if (nearB) return "b";

  if (x >= box.x && x <= box.x + box.width && y >= box.y && y <= box.y + box.height) {
    return "move";
  }
  return null;
}

function getCursorForHit(hit) {
  if (!hit) return "default";
  if (hit === "move") return "grab";
  if (hit === "tl" || hit === "br") return "nwse-resize";
  if (hit === "tr" || hit === "bl") return "nesw-resize";
  if (hit === "l" || hit === "r") return "ew-resize";
  if (hit === "t" || hit === "b") return "ns-resize";
  return "default";
}

function setupPlateSizeEditor() {
  const cv = document.getElementById("plateSizeCanvas");
  let startX = 0, startY = 0;
  let startBox = null;

  cv.onmousedown = (e) => {
    if (e.button !== 0) return;
    const r = cv.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;

    for (const key of ["min", "max"]) {
      const hit = hitTestPlateSizeBox(x, y, plateSizeBoxes[key]);
      if (hit) {
        plateSizeDrag = { key, hit };
        startX = x;
        startY = y;
        startBox = { ...plateSizeBoxes[key] };
        e.preventDefault();
        return;
      }
    }
  };

  cv.onmousemove = (e) => {
    const r = cv.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;

    if (!plateSizeDrag) {
      let cursor = "default";
      for (const key of ["min", "max"]) {
        const hit = hitTestPlateSizeBox(x, y, plateSizeBoxes[key]);
        if (hit) { cursor = getCursorForHit(hit); break; }
      }
      cv.style.cursor = cursor;
      return;
    }

    const dx = x - startX, dy = y - startY;
    const box = plateSizeBoxes[plateSizeDrag.key];
    const hit = plateSizeDrag.hit;

    if (hit === "move") {
      box.x = startBox.x + dx;
      box.y = startBox.y + dy;
    } else {
      let nx = startBox.x, ny = startBox.y, nw = startBox.width, nh = startBox.height;
      if (hit.includes("l")) { nx = startBox.x + dx; nw = startBox.width - dx; }
      if (hit.includes("r")) { nw = startBox.width + dx; }
      if (hit.includes("t")) { ny = startBox.y + dy; nh = startBox.height - dy; }
      if (hit.includes("b")) { nh = startBox.height + dy; }
      if (nw < 4) { nw = 4; if (hit.includes("l")) nx = startBox.x + startBox.width - 4; }
      if (nh < 4) { nh = 4; if (hit.includes("t")) ny = startBox.y + startBox.height - 4; }
      box.x = nx; box.y = ny; box.width = nw; box.height = nh;
    }

    clampBoxInCanvas(box, cv);
    syncPlateSizeInputsFromBoxes();
    drawPlateSizeBoxes();
  };

  cv.onmouseup = () => {
    if (plateSizeDrag) {
      plateSizeDrag = null;
      enforcePlateSizeConstraints();
      drawPlateSizeBoxes();
    }
  };

  cv.onmouseleave = () => {
    if (plateSizeDrag) {
      plateSizeDrag = null;
      enforcePlateSizeConstraints();
      drawPlateSizeBoxes();
    }
  };

  ["c_min_w", "c_min_h", "c_max_w", "c_max_h"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      syncPlateSizeBoxesFromInputs();
      enforcePlateSizeConstraints();
      drawPlateSizeBoxes();
    });
  });
}

function enforcePlateSizeConstraints() {
  const minB = plateSizeBoxes.min;
  const maxB = plateSizeBoxes.max;
  if (minB.width > maxB.width) { minB.width = maxB.width; }
  if (minB.height > maxB.height) { minB.height = maxB.height; }
  syncPlateSizeInputsFromBoxes();
}

function hotkeyFromEvent(event) {
  const key = String(event.key || "").trim().toUpperCase();
  if (!key || key === "CONTROL" || key === "SHIFT" || key === "ALT") return "";
  const parts = [];
  if (event.ctrlKey) parts.push("CTRL");
  if (event.altKey) parts.push("ALT");
  if (event.shiftKey) parts.push("SHIFT");
  parts.push(key);
  return parts.join("+");
}

function isEditingTarget(target) {
  if (!target) return false;
  const tag = String(target.tagName || "").toLowerCase();
  if (["input", "textarea", "select"].includes(tag)) return true;
  return Boolean(target.closest("[contenteditable='true']"));
}

function updateRelayTimerState(relayIndex) {
  const modeEl = document.getElementById(`ctrlR${relayIndex}Mode`);
  const timerEl = document.getElementById(`ctrlR${relayIndex}Timer`);
  if (!modeEl || !timerEl) return;
  const isPulseTimer = modeEl.value === "pulse_timer";
  timerEl.disabled = !isPulseTimer;
  if (!isPulseTimer) {
    timerEl.value = "1";
  }
}

function updateChannelControllerBindingState() {
  const hasController = Boolean(val("c_controller_id"));
  const relayEl = document.getElementById("c_controller_relay");
  relayEl.disabled = !hasController;
  if (!hasController) {
    setVal("c_controller_relay", 0);
  }
}

function renderCustomListOptions(selectedIds = []) {
  const box = document.getElementById("c_list_ids_select");
  if (!box) return;
  const selected = new Set((selectedIds || []).map((id) => Number(id)));
  box.innerHTML = "";
  const selectableLists = state.lists.filter((list) => String(list.type || "").toLowerCase() !== "black");
  selectableLists.forEach((list) => {
    const item = document.createElement("label");
    item.style.display = "flex";
    item.style.alignItems = "center";
    item.style.gap = "6px";
    item.style.marginBottom = "4px";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = String(list.id);
    checkbox.checked = selected.has(Number(list.id));

    const caption = document.createElement("span");
    const typeRaw = String(list.type || "").toLowerCase();
    let listType = "Белый список";
    if (typeRaw === "info") listType = "Информационный список";
    caption.textContent = `${list.name} (${listType})`;

    item.appendChild(checkbox);
    item.appendChild(caption);
    box.appendChild(item);
  });
}


function getSelectedCustomListIds() {
  const box = document.getElementById("c_list_ids_select");
  if (!box) return [];
  return Array.from(box.querySelectorAll("input[type='checkbox']:checked"))
    .map((el) => Number(el.value))
    .filter((id) => Number.isFinite(id) && id > 0);
}

function updateCustomListsVisibility() {
  const block = document.getElementById("c_custom_lists_block");
  const hint = document.getElementById("c_custom_lists_hint");
  if (!block || !hint) return;
  const isCustom = val("c_list_filter_mode") === "custom";
  block.style.display = isCustom ? "flex" : "none";
  hint.style.display = isCustom ? "flex" : "none";
}

function renderChannelControllerOptions(selectedId = "") {
  const select = document.getElementById("c_controller_id");
  const current = String(selectedId ?? "");
  select.innerHTML = "";
  const noneOption = document.createElement("option");
  noneOption.value = "";
  noneOption.textContent = "Без контроллера";
  select.appendChild(noneOption);
  controllersCache.forEach((controller) => {
    const option = document.createElement("option");
    option.value = String(controller.id);
    option.textContent = controller.name || `Контроллер ${controller.id}`;
    select.appendChild(option);
  });
  select.value = current;
  if (select.value !== current) {
    select.value = "";
  }
  updateChannelControllerBindingState();
}

function rebuildHotkeyMap() {
  hotkeyMap.clear();
  const pending = new Map();
  const duplicates = new Set();
  controllersCache.forEach((controller) => {
    (controller.relays || []).forEach((relay, relayIndex) => {
      const hotkey = String(relay.hotkey || "").trim().toUpperCase();
      if (!hotkey) return;
      const binding = {
        controllerId: controller.id,
        relayIndex,
        controllerName: controller.name || `Контроллер ${controller.id}`,
      };
      if (!pending.has(hotkey)) {
        pending.set(hotkey, [binding]);
      } else {
        pending.get(hotkey).push(binding);
        duplicates.add(hotkey);
      }
    });
  });
  duplicates.forEach((hotkey) => {
    addDebug(`[ERR] duplicate hotkey detected: ${hotkey}. Хоткей отключен до устранения конфликта`, "err");
  });
  pending.forEach((bindings, hotkey) => {
    if (duplicates.has(hotkey)) return;
    hotkeyMap.set(hotkey, bindings[0]);
  });
}

async function triggerHotkey(hotkey) {
  const binding = hotkeyMap.get(hotkey);
  if (!binding) return;
  try {
    const res = await jfetch(api(`/api/controllers/${binding.controllerId}/test`), "POST", {
      relay_index: binding.relayIndex,
      is_on: true,
    });
    addDebug(`[OK] hotkey ${hotkey}: ${binding.controllerName}, реле ${binding.relayIndex + 1}, статус=${res.status}`, "ok");
  } catch (err) {
    addDebug(`[ERR] hotkey ${hotkey}: ${err.message}`, "err");
  }
}

async function selectChannel(id) {
  selectedChannelId = id;
  syncChannelConfigVisibility();
  switchChannelSettingsTab("channel");
  const requestToken = ++channelConfigRequestToken;
  renderChannelsList();
  const c = await jfetch(api(`/api/channels/${id}/config`));
  if (
    requestToken !== channelConfigRequestToken ||
    Number(selectedChannelId) !== Number(id)
  ) {
    return;
  }
  setVal("c_name", c.name);
  setVal("c_source", c.source);
  renderChannelControllerOptions(c.controller_id ?? "");
  setVal("c_controller_relay", c.controller_relay ?? 0);
  updateChannelControllerBindingState();
  setVal("c_list_filter_mode", c.list_filter_mode || "all");
  currentChannelCustomListIds = (c.list_filter_list_ids || []).map((id) => Number(id)).filter((id) => Number.isFinite(id) && id > 0);
  renderCustomListOptions(currentChannelCustomListIds);
  updateCustomListsVisibility();
  setVal("c_detection_mode", c.detection_mode || "motion");
  setVal("c_motion_threshold", c.motion_threshold ?? 0.01);
  setVal("c_motion_frame_stride", c.motion_frame_stride ?? 1);
  setVal("c_motion_activation", c.motion_activation_frames ?? 3);
  setVal("c_motion_release", c.motion_release_frames ?? 6);
  setVal("c_detector_stride", c.detector_frame_stride ?? 2);
  setChk("c_size_filter", c.size_filter_enabled);
  setVal("c_min_w", c.min_plate_size?.width ?? 80);
  setVal("c_min_h", c.min_plate_size?.height ?? 20);
  setVal("c_max_w", c.max_plate_size?.width ?? 600);
  setVal("c_max_h", c.max_plate_size?.height ?? 240);
  setVal("c_best_shots", c.best_shots ?? 3);
  setVal("c_cooldown", c.cooldown_seconds ?? 5);
  setVal("c_ocr_conf", c.ocr_min_confidence ?? 0.6);
  setVal("c_max_ocr_attempts", c.max_ocr_attempts ?? 15);
  setChk("c_roi_enabled", c.roi_enabled);
  const cv = document.getElementById("roiCanvas");
  const unit = c.region?.unit || "px";
  roiPoints = (c.region?.points || []).map((p) => toCanvasPoint(p, unit, cv));
  if (!roiPoints.length) {
    roiPoints = defaultROIPointsForCanvas(cv);
  }
  setVal("c_roi_points", JSON.stringify(roiPoints));
  drawROI();
  refreshROISnapshot();

  const psCv = document.getElementById("plateSizeCanvas");
  const overlay = c.plate_size_overlay;
  if (overlay && overlay.min_box && overlay.max_box) {
    plateSizeBoxes.min = { ...overlay.min_box };
    plateSizeBoxes.max = { ...overlay.max_box };
  } else {
    plateSizeBoxes = defaultPlateSizeOverlay(psCv);
  }
  clampBoxInCanvas(plateSizeBoxes.min, psCv);
  clampBoxInCanvas(plateSizeBoxes.max, psCv);
  drawPlateSizeBoxes();
  refreshPlateSizeSnapshot();
}

async function saveChannel() {
  if (!selectedChannelId) return;
  let points = roiPoints;
  try {
    points = JSON.parse(val("c_roi_points"));
  } catch (_e) {}
  if (
    document.getElementById("c_roi_enabled").checked &&
    points.length > 0 &&
    points.length < 3
  ) {
    alert("Для замкнутой ROI-области нужно минимум 3 точки");
    return;
  }
  const selectedCustomListIds = getSelectedCustomListIds();
  currentChannelCustomListIds = selectedCustomListIds;

  const payload = {
    name: val("c_name"),
    source: val("c_source"),
    controller_id: val("c_controller_id") ? Number(val("c_controller_id")) : null,
    controller_relay: val("c_controller_id") ? Number(val("c_controller_relay")) : 0,
    list_filter_mode: val("c_list_filter_mode"),
    list_filter_list_ids: val("c_list_filter_mode") === "custom" ? selectedCustomListIds : [],
    detection_mode: val("c_detection_mode"),
    motion_threshold: Number(val("c_motion_threshold")),
    motion_frame_stride: Number(val("c_motion_frame_stride")),
    motion_activation_frames: Number(val("c_motion_activation")),
    motion_release_frames: Number(val("c_motion_release")),
    detector_frame_stride: Number(val("c_detector_stride")),
    size_filter_enabled: document.getElementById("c_size_filter").checked,
    min_plate_size: {
      width: Number(val("c_min_w")),
      height: Number(val("c_min_h")),
    },
    max_plate_size: {
      width: Number(val("c_max_w")),
      height: Number(val("c_max_h")),
    },
    best_shots: Number(val("c_best_shots")),
    cooldown_seconds: Number(val("c_cooldown")),
    ocr_min_confidence: Number(val("c_ocr_conf")),
    max_ocr_attempts: Number(val("c_max_ocr_attempts")),
    roi_enabled: document.getElementById("c_roi_enabled").checked,
    region: {
      unit: "percent",
      points: points.map((p) =>
        toPercentPoint(p, document.getElementById("roiCanvas")),
      ),
    },
    plate_size_overlay: {
      min_box: { x: Math.round(plateSizeBoxes.min.x), y: Math.round(plateSizeBoxes.min.y), width: Math.round(plateSizeBoxes.min.width), height: Math.round(plateSizeBoxes.min.height) },
      max_box: { x: Math.round(plateSizeBoxes.max.x), y: Math.round(plateSizeBoxes.max.y), width: Math.round(plateSizeBoxes.max.width), height: Math.round(plateSizeBoxes.max.height) },
    },
  };
  await jfetch(
    api(`/api/channels/${selectedChannelId}/config`),
    "PUT",
    payload,
  );
  addDebug(`[OK] channel ${selectedChannelId} saved`, "ok");
  await refreshChannels();
  showToast("Настройки сохранены");
}
async function createChannel() {
  document.getElementById("newChannelName").value = "";
  document.getElementById("newChannelName").placeholder = "Введите название";
  openModal("createChannelModal");
  setTimeout(() => document.getElementById("newChannelName").focus(), 50);
}
async function _doCreateChannel(name) {
  try {
    await jfetch(api("/api/channels"), "POST", {
      name: name || "Канал",
      source: "0",
      enabled: true,
      roi_enabled: true,
      region: { unit: "percent", points: [] },
    });
    await refreshChannels();
    if (state.channels.length) {
      selectedChannelId = state.channels[state.channels.length - 1].id;
      await selectChannel(selectedChannelId);
    }
    addDebug("[OK] channel created", "ok");
  } catch (err) {
    addDebug(`[ERR] ${err.message}`, "err");
    alert(`Не удалось создать канал: ${err.message}`);
  }
}
async function deleteChannel() {
  if (!selectedChannelId) return;
  const ch = state.channels.find((c) => c.id === selectedChannelId);
  const label = ch ? ch.name : `#${selectedChannelId}`;
  document.getElementById("deleteChannelNameLabel").textContent = label;
  openModal("deleteChannelModal");
}
async function _doDeleteChannel() {
  await jfetch(api(`/api/channels/${selectedChannelId}`), "DELETE");
  selectedChannelId = null;
  roiPoints = [];
  await refreshChannels();
  addDebug("[OK] channel deleted", "ok");
}


function setControllerFormDisabled(disabled) {
  [
    "ctrlName",
    "ctrlType",
    "ctrlAddress",
    "ctrlPassword",
    "ctrlR0Mode",
    "ctrlR0Timer",
    "ctrlR0Hotkey",
    "ctrlR1Mode",
    "ctrlR1Timer",
    "ctrlR1Hotkey",
    "testRelay0Btn",
    "testRelay1Btn",
    "saveControllerBtn",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = !!disabled;
  });
}

function fillControllerForm(c) {
  if (!c) {
    setVal("ctrlName", "");
    setVal("ctrlType", "DTWONDER2CH");
    setVal("ctrlAddress", "");
    setVal("ctrlPassword", "0");
    setVal("ctrlR0Mode", "pulse");
    setVal("ctrlR0Timer", 1);
    setVal("ctrlR0Hotkey", "");
    setVal("ctrlR1Mode", "pulse");
    setVal("ctrlR1Timer", 1);
    setVal("ctrlR1Hotkey", "");
    setControllerFormDisabled(true);
    return;
  }
  setVal("ctrlName", c.name);
  setVal("ctrlType", c.type);
  setVal("ctrlAddress", c.address);
  setVal("ctrlPassword", c.password);
  setVal("ctrlR0Mode", c.relays?.[0]?.mode || "pulse");
  setVal("ctrlR0Timer", c.relays?.[0]?.timer_seconds || 1);
  setVal("ctrlR0Hotkey", c.relays?.[0]?.hotkey || "");
  setVal("ctrlR1Mode", c.relays?.[1]?.mode || "pulse");
  setVal("ctrlR1Timer", c.relays?.[1]?.timer_seconds || 1);
  setVal("ctrlR1Hotkey", c.relays?.[1]?.hotkey || "");
  setControllerFormDisabled(false);
  updateRelayTimerState(0);
  updateRelayTimerState(1);
}
function renderControllerItems() {
  const box = document.getElementById("controllerItems");
  box.innerHTML = "";
  if (!controllersCache.length) {
    box.innerHTML = '<div class="ch-item">Нет контроллеров</div>';
    setControllerFormDisabled(true);
    syncControllerConfigVisibility();
    return;
  }
  controllersCache.forEach((c) => {
    const row = document.createElement("div");
    row.className = `ch-item ${c.id === selectedControllerId ? "active" : ""}`;
    row.textContent = c.name;
    row.onclick = () => selectController(c.id);
    box.appendChild(row);
  });
}
function selectController(id) {
  selectedControllerId = id;
  syncControllerConfigVisibility();
  const item = controllersCache.find((c) => c.id === id);
  fillControllerForm(item || null);
  renderControllerItems();
}
async function loadControllers() {
  controllersCache = await jfetch(api("/api/controllers"));
  if (controllersCache.length) {
    if (
      !selectedControllerId ||
      !controllersCache.some((c) => c.id === selectedControllerId)
    ) {
      selectedControllerId = controllersCache[0].id;
    }
    selectController(selectedControllerId);
  } else {
    selectedControllerId = null;
    fillControllerForm(null);
    renderControllerItems();
  }
  syncControllerConfigVisibility();
  rebuildHotkeyMap();
  renderChannelControllerOptions(val("c_controller_id"));
  renderControllerItems();
}
function controllerPayload() {
  return {
    name: val("ctrlName"),
    type: val("ctrlType") || "DTWONDER2CH",
    address: val("ctrlAddress"),
    password: val("ctrlPassword") || "0",
    relays: [
      {
        mode: val("ctrlR0Mode") || "pulse",
        timer_seconds: val("ctrlR0Mode") === "pulse_timer" ? Math.max(1, Number(val("ctrlR0Timer") || 1)) : 1,
        hotkey: (val("ctrlR0Hotkey") || "").trim().toUpperCase(),
      },
      {
        mode: val("ctrlR1Mode") || "pulse",
        timer_seconds: val("ctrlR1Mode") === "pulse_timer" ? Math.max(1, Number(val("ctrlR1Timer") || 1)) : 1,
        hotkey: (val("ctrlR1Hotkey") || "").trim().toUpperCase(),
      },
    ],
  };
}
async function createController() {
  document.getElementById("newControllerName").value = "";
  document.getElementById("newControllerName").placeholder = "Введите название";
  openModal("createControllerModal");
  setTimeout(() => document.getElementById("newControllerName").focus(), 50);
}
async function _doCreateController(name) {
  const body = controllerPayload();
  body.name = name || "Контроллер";
  try {
    await jfetch(api("/api/controllers"), "POST", body);
    await loadControllers();
    if (controllersCache.length) {
      selectedControllerId = controllersCache[controllersCache.length - 1].id;
      selectController(selectedControllerId);
    }
    addDebug("[OK] controller created", "ok");
  } catch (err) {
    addDebug(`[ERR] ${err.message}`, "err");
    alert(`Не удалось создать контроллер: ${err.message}`);
  }
}
async function deleteController() {
  if (!selectedControllerId) return;
  const ctrl = controllersCache.find((c) => c.id === selectedControllerId);
  const label = ctrl ? ctrl.name : `#${selectedControllerId}`;
  document.getElementById("deleteControllerNameLabel").textContent = label;
  openModal("deleteControllerModal");
}
async function _doDeleteController() {
  try {
    await jfetch(api(`/api/controllers/${selectedControllerId}`), "DELETE");
    await loadControllers();
    addDebug("[OK] controller deleted", "ok");
  } catch (err) {
    addDebug(`[ERR] ${err.message}`, "err");
    alert(err.message);
  }
}
async function saveController() {
  if (!selectedControllerId) return;
  try {
    await jfetch(
      api(`/api/controllers/${selectedControllerId}`),
      "PUT",
      controllerPayload(),
    );
    await loadControllers();
    addDebug("[OK] controller updated", "ok");
    showToast("Настройки сохранены");
  } catch (err) {
    addDebug(`[ERR] ${err.message}`, "err");
    alert(`Не удалось сохранить контроллер: ${err.message}`);
  }
}
async function deleteController() {
  if (!selectedControllerId) return;
  if (!confirm("Удалить выбранный контроллер?")) return;
  try {
    await jfetch(api(`/api/controllers/${selectedControllerId}`), "DELETE");
    await loadControllers();
    addDebug("[OK] controller deleted", "ok");
  } catch (err) {
    addDebug(`[ERR] ${err.message}`, "err");
    alert(err.message);
  }
}
async function testController(relay) {
  if (!selectedControllerId) return;
  await jfetch(api(`/api/controllers/${selectedControllerId}/test`), "POST", {
    relay_index: relay,
    is_on: true,
  });
  addDebug(`[OK] relay ${relay + 1} test sent`, "ok");
}

function mapLogClass(level) {
  const v = String(level || "INFO").toUpperCase();
  if (v === "ERROR" || v === "CRITICAL") return "err";
  if (v === "WARNING") return "warn";
  if (v === "DEBUG") return "ok";
  return "info";
}

function prependDebugLine(text, type = "info", timestamp = null, meta = "") {
  const log = document.getElementById("debugLog");
  if (!log) return;
  const line = document.createElement("div");
  line.className = `log-line ${type}`;
  const ts = timestamp ? new Date(timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
  line.innerHTML = `<span class='log-ts'>${ts}</span>${meta ? ` <span class='log-meta'>${meta}</span>` : ""} ${text}`;
  log.prepend(line);
  while (log.children.length > 300) log.removeChild(log.lastElementChild);
}

function addDebug(msg, type = "info") {
  prependDebugLine(msg, type, null, "[UI]");
}

function applyDebugPanelVisibility() {
  const panel = document.getElementById("obsDebugPanel");
  const btn = document.getElementById("toggleDebugPanelBtn");
  if (!panel) return;
  const enabled = Boolean((debugSettingsCache || {}).log_panel_enabled);
  panel.style.display = enabled ? "flex" : "none";
  scheduleVideoGridLayout(true);
  if (!enabled) return;
  if (!panel.dataset.collapsed) panel.dataset.collapsed = "0";
  if (btn) {
    btn.textContent = panel.dataset.collapsed === "1" ? "Развернуть" : "Свернуть";
  }
}

function scheduleDebugLogReconnect(delayMs = 2000) {
  if (debugLogReconnectTimer) return;
  debugLogReconnectTimer = setTimeout(() => {
    debugLogReconnectTimer = null;
    setupDebugLogStream();
  }, delayMs);
}

async function loadDebugLogHistory() {
  try {
    const payload = await jfetch(api("/api/debug/logs?limit=150"));
    const items = Array.isArray(payload.items) ? payload.items : [];
    items.reverse().forEach((item) => {
      lastDebugLogId = Math.max(lastDebugLogId, Number(item.id || 0));
      const prefix = `[${item.level}] ${item.service}/${item.logger}${item.channel_id ? ` #${item.channel_id}` : ""}`;
      prependDebugLine(item.message, mapLogClass(item.level), item.timestamp, prefix);
    });
  } catch (err) {
    prependDebugLine(`[WARN] не удалось загрузить историю логов: ${err.message}`, "warn");
  }
}

function setupDebugLogStream() {
  if (debugLogSource) {
    try { debugLogSource.close(); } catch (_e) {}
  }
  debugLogSource = new EventSource(apiUrl(`/api/debug/logs/stream?last_id=${lastDebugLogId}`));
  debugLogSource.onmessage = (evt) => {
    try {
      const item = JSON.parse(evt.data);
      lastDebugLogId = Math.max(lastDebugLogId, Number(item.id || 0));
      const prefix = `[${item.level}] ${item.service}/${item.logger}${item.channel_id ? ` #${item.channel_id}` : ""}`;
      prependDebugLine(item.message, mapLogClass(item.level), item.timestamp, prefix);
    } catch (_e) {}
  };
  debugLogSource.onerror = () => {
    try { debugLogSource.close(); } catch (_e) {}
    scheduleDebugLogReconnect();
  };
}
function scheduleStreamReconnect(delayMs = 3000) {
  if (streamReconnectTimer) return;
  streamReconnectTimer = setTimeout(() => {
    streamReconnectTimer = null;
    setupStream();
  }, delayMs);
}

async function setupStream() {
  if (streamReconnectTimer) {
    clearTimeout(streamReconnectTimer);
    streamReconnectTimer = null;
  }
  if (eventSource) {
    try {
      eventSource.close();
    } catch (_e) {}
  }
  eventSource = new EventSource(apiUrl("/api/events/stream"));
  eventSource.onmessage = (m) => {
    try {
      pushEvent(JSON.parse(m.data));
    } catch (_e) {}
  };
  eventSource.onerror = () => {
    addDebug("[WARN] stream reconnect", "warn");
    try {
      eventSource.close();
    } catch (_e) {}
    scheduleStreamReconnect();
  };
}
function fillChannelFilter() {
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
function closeEventModal() {
  document.getElementById("eventModal").classList.remove("active");
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
async function openEventDetails(ev) {
  const id = Number(ev.id || 0);
  let payload = ev;
  if (id > 0) {
    try {
      payload = await jfetch(api(`/api/events/item/${id}`));
    } catch (err) {
      addDebug(
        `[WARN] event details fallback for id=${id}: ${err.message}`,
        "warn",
      );
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
    ["Гос. номер", payload.plate || "—"],
    ["Уверенность", Number(payload.confidence || 0).toFixed(2)],
    ["Направление", formatDirection(payload.direction).plain],
    ["Источник", payload.source || "—"],
  ];

  // Look up matched list entry for this plate
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

const toggleDebugPanelBtn = document.getElementById("toggleDebugPanelBtn");
if (toggleDebugPanelBtn) {
  toggleDebugPanelBtn.onclick = () => {
    const panel = document.getElementById("obsDebugPanel");
    if (!panel) return;
    const collapsed = panel.dataset.collapsed === "1";
    panel.dataset.collapsed = collapsed ? "0" : "1";
    toggleDebugPanelBtn.textContent = collapsed ? "Свернуть" : "Развернуть";
    scheduleVideoGridLayout(true);
  };
}

document
  .querySelectorAll(".ttab")
  .forEach((el) => (el.onclick = () => switchTab(el.dataset.tab)));
document
  .querySelectorAll(".snav-item")
  .forEach((el) => (el.onclick = () => switchSettings(el.dataset.sp)));
document
  .querySelectorAll(".ch-tab")
  .forEach(
    (el) => (el.onclick = () => switchChannelSettingsTab(el.dataset.chTab)),
  );
document.getElementById("gridSelect").onchange = () => scheduleVideoGridLayout(true);
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
// ── Modal helpers ────────────────────────────────────
function openModal(id) { document.getElementById(id).classList.add("active"); }
function closeModal(id) { document.getElementById(id).classList.remove("active"); }

// ── Create List Modal ────────────────────────────────
document.getElementById("addListBtn").onclick = () => {
  document.getElementById("newListName").value = "";
  openModal("createListModal");
  setTimeout(() => document.getElementById("newListName").focus(), 50);
};
document.getElementById("createListModalClose").onclick = () => closeModal("createListModal");
document.getElementById("createListCancel").onclick = () => closeModal("createListModal");
document.getElementById("createListConfirm").onclick = async () => {
  const name = document.getElementById("newListName").value.trim();
  if (!name) { document.getElementById("newListName").focus(); return; }
  await jfetch(api("/api/lists"), "POST", { name, type: "white" });
  closeModal("createListModal");
  await loadLists();
};
document.getElementById("createListModal").onclick = (e) => {
  if (e.target.id === "createListModal") closeModal("createListModal");
};
document.getElementById("newListName").onkeydown = (e) => {
  if (e.key === "Enter") document.getElementById("createListConfirm").click();
};

// ── Add / Edit Entry Modal ───────────────────────────
document.getElementById("addEntryBtn").onclick = () => {
  if (!state.selectedListId) return;
  editingEntryId = null;
  document.getElementById("addEntryModalTitle").textContent = "Добавить запись";
  ["entryLastName","entryFirstName","entryPatronymic","entryPhone","entryCarMake","entryPlate"].forEach(id => {
    document.getElementById(id).value = "";
  });
  document.getElementById("addEntryError").textContent = "";
  openModal("addEntryModal");
  setTimeout(() => document.getElementById("entryLastName").focus(), 50);
};
document.getElementById("addEntryModalClose").onclick = () => closeModal("addEntryModal");
document.getElementById("addEntryCancel").onclick = () => closeModal("addEntryModal");
document.getElementById("addEntryConfirm").onclick = async () => {
  const firstName = document.getElementById("entryFirstName").value.trim();
  const plate = document.getElementById("entryPlate").value.trim();
  const errEl = document.getElementById("addEntryError");
  if (!firstName || !plate) {
    errEl.textContent = "Поля «Имя» и «Гос. номер автомобиля» обязательны.";
    return;
  }
  errEl.textContent = "";
  const comment = JSON.stringify({
    last_name: document.getElementById("entryLastName").value.trim(),
    first_name: firstName,
    patronymic: document.getElementById("entryPatronymic").value.trim(),
    phone: document.getElementById("entryPhone").value.trim(),
    car_make: document.getElementById("entryCarMake").value.trim(),
  });
  try {
    if (editingEntryId !== null) {
      await jfetch(api(`/api/lists/${state.selectedListId}/entries/${editingEntryId}`), "PUT", { plate, comment });
    } else {
      await jfetch(api(`/api/lists/${state.selectedListId}/entries`), "POST", { plate, comment });
    }
  } catch (_e) {
    errEl.textContent = editingEntryId !== null
      ? "Не удалось обновить: возможно, номер уже существует."
      : "Не удалось сохранить: возможно, номер уже существует.";
    return;
  }
  editingEntryId = null;
  closeModal("addEntryModal");
  await loadEntries(state.selectedListId);
  await refreshPlateLookup();
  renderEventFeed(true);
};
document.getElementById("addEntryModal").onclick = (e) => {
  if (e.target.id === "addEntryModal") { editingEntryId = null; closeModal("addEntryModal"); }
};

// ── Export List ──────────────────────────────────────
document.getElementById("exportListBtn").onclick = exportCurrentListCSV;

// ── List Settings Modal ──────────────────────────────
document.getElementById("listSettingsBtn").onclick = () => {
  if (!state.selectedListId) return;
  const list = state.lists.find((l) => l.id === state.selectedListId);
  if (!list) return;
  document.getElementById("settingsListName").value = list.name;
  document.getElementById("settingsListType").value = list.type || "white";
  openModal("listSettingsModal");
  setTimeout(() => document.getElementById("settingsListName").focus(), 50);
};
document.getElementById("listSettingsModalClose").onclick = () => closeModal("listSettingsModal");
document.getElementById("listSettingsCancel").onclick = () => closeModal("listSettingsModal");
document.getElementById("listSettingsConfirm").onclick = async () => {
  const name = document.getElementById("settingsListName").value.trim();
  const type = document.getElementById("settingsListType").value;
  if (!name || !state.selectedListId) return;
  await jfetch(api(`/api/lists/${state.selectedListId}`), "PUT", { name, type });
  closeModal("listSettingsModal");
  await loadLists();
};
document.getElementById("listSettingsModal").onclick = (e) => {
  if (e.target.id === "listSettingsModal") closeModal("listSettingsModal");
};

// ── Delete List Modal ────────────────────────────────
document.getElementById("deleteListBtn").onclick = () => {
  if (!state.selectedListId) return;
  const list = state.lists.find((l) => l.id === state.selectedListId);
  if (!list) return;
  document.getElementById("deleteListNameLabel").textContent = list.name;
  openModal("deleteListModal");
};
document.getElementById("deleteListCancel").onclick = () => closeModal("deleteListModal");
document.getElementById("deleteListConfirm").onclick = async () => {
  if (!state.selectedListId) return;
  await jfetch(api(`/api/lists/${state.selectedListId}`), "DELETE");
  closeModal("deleteListModal");
  state.selectedListId = null;
  state.currentEntries = [];
  document.getElementById("listTitle").textContent = "—";
  document.getElementById("entriesBody").innerHTML = "";
  await loadLists();
};
document.getElementById("deleteListModal").onclick = (e) => {
  if (e.target.id === "deleteListModal") closeModal("deleteListModal");
};
document.getElementById("eventModalClose").onclick = closeEventModal;
document.getElementById("eventModal").onclick = (e) => {
  if (e.target.id === "eventModal") closeEventModal();
};
document.getElementById("saveGeneralBtn").onclick = saveGeneral;
document.getElementById("saveChannelBtn").onclick = saveChannel;
document.getElementById("deleteChannelBtn").onclick = deleteChannel;
document.getElementById("createChannelBtn").onclick = createChannel;
document.getElementById("createControllerBtn").onclick = createController;
document.getElementById("saveControllerBtn").onclick = saveController;
document.getElementById("deleteControllerBtn").onclick = deleteController;

// ── Create Channel Modal ─────────────────────────────
document.getElementById("createChannelModalClose").onclick = () => closeModal("createChannelModal");
document.getElementById("createChannelCancel").onclick = () => closeModal("createChannelModal");
document.getElementById("createChannelModal").onclick = (e) => {
  if (e.target.id === "createChannelModal") closeModal("createChannelModal");
};
document.getElementById("newChannelName").onkeydown = (e) => {
  if (e.key === "Enter") document.getElementById("createChannelConfirm").click();
};
document.getElementById("createChannelConfirm").onclick = async () => {
  const name = document.getElementById("newChannelName").value.trim() || "Канал";
  closeModal("createChannelModal");
  await _doCreateChannel(name);
};

// ── Delete Channel Modal ─────────────────────────────
document.getElementById("deleteChannelCancel").onclick = () => closeModal("deleteChannelModal");
document.getElementById("deleteChannelModal").onclick = (e) => {
  if (e.target.id === "deleteChannelModal") closeModal("deleteChannelModal");
};
document.getElementById("deleteChannelConfirm").onclick = async () => {
  closeModal("deleteChannelModal");
  await _doDeleteChannel();
};

// ── Create Controller Modal ──────────────────────────
document.getElementById("createControllerModalClose").onclick = () => closeModal("createControllerModal");
document.getElementById("createControllerCancel").onclick = () => closeModal("createControllerModal");
document.getElementById("createControllerModal").onclick = (e) => {
  if (e.target.id === "createControllerModal") closeModal("createControllerModal");
};
document.getElementById("newControllerName").onkeydown = (e) => {
  if (e.key === "Enter") document.getElementById("createControllerConfirm").click();
};
document.getElementById("createControllerConfirm").onclick = async () => {
  const name = document.getElementById("newControllerName").value.trim() || "Контроллер";
  closeModal("createControllerModal");
  await _doCreateController(name);
};

// ── Delete Controller Modal ──────────────────────────
document.getElementById("deleteControllerCancel").onclick = () => closeModal("deleteControllerModal");
document.getElementById("deleteControllerModal").onclick = (e) => {
  if (e.target.id === "deleteControllerModal") closeModal("deleteControllerModal");
};
document.getElementById("deleteControllerConfirm").onclick = async () => {
  closeModal("deleteControllerModal");
  await _doDeleteController();
};
document.getElementById("testRelay0Btn").onclick = () => testController(0);
document.getElementById("testRelay1Btn").onclick = () => testController(1);
document.getElementById("ctrlR0Mode").onchange = () => updateRelayTimerState(0);
document.getElementById("ctrlR1Mode").onchange = () => updateRelayTimerState(1);
document.getElementById("c_controller_id").onchange = updateChannelControllerBindingState;
document.getElementById("c_list_filter_mode").onchange = updateCustomListsVisibility;
document.getElementById("saveDebugBtn").onclick = saveGeneral;
document.getElementById("g_theme").onchange = () => applyTheme(val("g_theme"));
document.getElementById("themeToggleBtn").onclick = () => {
  const nextTheme = val("g_theme") === "light" ? "dark" : "light";
  setVal("g_theme", nextTheme);
  applyTheme(nextTheme);
};
document.getElementById("plateSizeRefreshBtn").onclick = refreshPlateSizeSnapshot;
document.getElementById("plateSizeResetBtn").onclick = () => {
  const cv = document.getElementById("plateSizeCanvas");
  plateSizeBoxes = defaultPlateSizeOverlay(cv);
  syncPlateSizeInputsFromBoxes();
  drawPlateSizeBoxes();
};
document.getElementById("roiRefreshBtn").onclick = refreshROISnapshot;
document.getElementById("roiClearBtn").onclick = () => {
  const cv = document.getElementById("roiCanvas");
  roiPoints = defaultROIPointsForCanvas(cv);
  setVal("c_roi_points", JSON.stringify(roiPoints));
  drawROI();
};


document.addEventListener("keydown", (event) => {
  if (event.repeat || isEditingTarget(event.target)) return;
  const hotkey = hotkeyFromEvent(event);
  if (!hotkey || !hotkeyMap.has(hotkey)) return;
  event.preventDefault();
  triggerHotkey(hotkey);
});

function updateTopbarDateTime() {
  const dateEl = document.getElementById("topbarDate");
  const timeEl = document.getElementById("topbarTime");
  if (!dateEl && !timeEl) return;
  const now = new Date();
  if (dateEl) dateEl.textContent = now.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
  if (timeEl) timeEl.textContent = now.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
updateTopbarDateTime();
setInterval(updateTopbarDateTime, 1000);

refreshSystemResources();
setInterval(refreshSystemResources, 2000);
checkServerHealth();
setInterval(checkServerHealth, 10000);
window.addEventListener("beforeunload", () => {
  if (eventSource) {
    try {
      eventSource.close();
    } catch (_e) {}
    eventSource = null;
  }
  if (debugLogSource) {
    try {
      debugLogSource.close();
    } catch (_e) {}
    debugLogSource = null;
  }
  if (overlayRefreshTimer) {
    clearInterval(overlayRefreshTimer);
    overlayRefreshTimer = null;
  }
  if (eventFeedRenderFrame !== null) {
    cancelAnimationFrame(eventFeedRenderFrame);
    eventFeedRenderFrame = null;
    eventFeedRenderScheduled = false;
  }
});
window.addEventListener("pagehide", () => {
  if (eventSource) {
    try {
      eventSource.close();
    } catch (_e) {}
    eventSource = null;
  }
  if (debugLogSource) {
    try {
      debugLogSource.close();
    } catch (_e) {}
    debugLogSource = null;
  }
  if (overlayRefreshTimer) {
    clearInterval(overlayRefreshTimer);
    overlayRefreshTimer = null;
  }
  if (eventFeedRenderFrame !== null) {
    cancelAnimationFrame(eventFeedRenderFrame);
    eventFeedRenderFrame = null;
    eventFeedRenderScheduled = false;
  }
});
window.addEventListener("resize", () => scheduleEventFeedRender(true));
(async function init() {
  const apiBaseEl = document.getElementById("apiBase");
  if (apiBaseEl) apiBaseEl.value = window.location.origin;
  try {
    applyTheme(localStorage.getItem("anpr_theme") || "dark");
  } catch (_e) {
    applyTheme("dark");
  }
  syncChannelConfigVisibility();
  syncControllerConfigVisibility();
  setupVideoGridLayoutGuards();
  setupEventFeedLayoutGuards();
  setupROI();
  setupPlateSizeEditor();
  switchChannelSettingsTab("channel");
  updateTopbarTitle();
  await refreshChannels();
  await hydrateChannelLastPlates();
  initJournalScroll();
  await loadEventFeedHistory();
  await loadLists();
  await loadJournal();
  await loadGlobalSettings();
  await refreshOverlayStates();
  await loadDebugLogHistory();
  setupDebugLogStream();
  await loadControllers();
  setupStream();
  addDebug("[INFO] UI initialized");
  setInterval(refreshChannels, 8000);
  overlayRefreshTimer = setInterval(refreshOverlayStates, 700);
})();

/* ─── Parameter help popover system ─────────────────── */
const PARAM_HELP = {
  name: "Отображаемое имя канала. Используется в журнале событий, заголовках превью и при сохранении медиафайлов.",
  source: "Адрес видеопотока. Поддерживаются RTSP, HTTP, локальные файлы и индексы камер (0, 1, …). Канал открывает этот источник через OpenCV VideoCapture.",
  list_filter_mode: "Определяет, при каких номерах срабатывает реле контроллера.\n• «Все» — реле для любого номера (кроме чёрного списка).\n• «Белые списки» — только номера из списков типа white.\n• «Свои списки» — только номера из выбранных ниже списков.\nЧёрный список блокирует срабатывание всегда.",
  list_filter_list_ids: "Выбор конкретных списков номеров, которые разрешают срабатывание реле в режиме «Свои списки». Чёрный список применяется автоматически в любом режиме.",
  detection_mode: "Режим запуска детектора YOLO.\n• «always» — детектор работает на каждом кадре (с учётом шага инференса).\n• «motion» — детектор запускается только при обнаружении движения в кадре. Экономит CPU при пустых сценах.",
  motion_threshold: "Доля пикселей, изменившихся между кадрами, при которой считается, что в кадре есть движение. Значение 0.01 = 1% пикселей. Меньше — выше чувствительность, больше ложных срабатываний.",
  motion_frame_stride: "Через сколько кадров проводить анализ движения. При stride=2 движение проверяется на каждом 2-м кадре. Промежуточные кадры пропускаются, но состояние motion сохраняется.",
  motion_activation_frames: "Сколько подряд проанализированных кадров с движением нужно, чтобы активировать состояние motion и начать запуск детектора YOLO. Защита от разовых шумов.",
  motion_release_frames: "Сколько подряд проанализированных кадров без движения нужно, чтобы деактивировать состояние motion и прекратить запуск детектора. Защита от преждевременной остановки при кратковременной паузе.",
  detector_frame_stride: "Через сколько кадров (прошедших motion gate) запускать YOLO-детекцию и трекинг. При stride=2 — каждый второй кадр. Снижает нагрузку CPU/GPU за счёт частоты обнаружения.",
  size_filter_enabled: "Включить фильтрацию найденных номерных рамок по размеру (ширина и высота в пикселях). Отсекает слишком маленькие и слишком большие обнаружения.",
  min_plate_size: "Минимальная ширина и высота обнаруженной номерной рамки в пикселях. Рамки меньше этого размера отбрасываются до OCR. Помогает отфильтровать далёкие или нерелевантные объекты.",
  max_plate_size: "Максимальная ширина и высота обнаруженной номерной рамки в пикселях. Рамки больше этого размера отбрасываются. Помогает отфильтровать ложные детекции на крупных объектах.",
  best_shots: "Сколько лучших OCR-наблюдений накапливается на один трек для голосования. Из них выбирается консенсус — номер, набравший кворум и наибольший суммарный вес уверенности. По умолчанию 3.",
  cooldown_seconds: "Пауза (в секундах) между повторными событиями для одного и того же номера. Если номер уже был распознан менее N секунд назад — повторное событие не создаётся. Предотвращает дублирование при медленном проезде.",
  ocr_min_confidence: "Минимальный порог уверенности OCR (0.0–1.0). Результаты ниже порога не попадают в пул кандидатов трека и считаются нечитаемыми. По умолчанию 0.6.",
  max_ocr_attempts: "Максимальное число OCR-попыток для одного трека. После исчерпания бюджета OCR для этого трека прекращается — кроп, предобработка и CRNN-инференс больше не выполняются.\n\nЕсли консенсус был достигнут раньше — трек финализируется досрочно.\nЕсли бюджет исчерпан без консенсуса — выбирается лучший кандидат по весу.\nЕсли кандидатов нет — генерируется одно событие «Нечитаемо».\n\nПо умолчанию 15.",
  roi_enabled: "Включить зону интереса (Region of Interest). Когда включено, только обнаружения с центром bbox внутри ROI-полигона обрабатываются. Детекция YOLO по-прежнему работает по всему кадру, но результаты за пределами ROI отбрасываются.",
  roi_points: "JSON-представление точек ROI-полигона. Координаты в пикселях канваса. Минимум 3 точки для замкнутой области. Редактируйте визуально на канвасе выше или вручную.",
  controller_id: "Привязка аппаратного контроллера к этому каналу. При распознавании номера, прошедшего фильтр списков, на контроллер отправляется HTTP-команда для срабатывания выбранного реле.",
  controller_relay: "Какое из двух реле контроллера использовать для этого канала (Реле 1 или Реле 2). Режим работы реле (pulse / pulse_timer) настраивается в параметрах контроллера."
};

let _activeHelpPopover = null;

function _closeHelpPopover() {
  if (_activeHelpPopover) {
    _activeHelpPopover.remove();
    _activeHelpPopover = null;
  }
}

function _showHelpPopover(btn) {
  _closeHelpPopover();
  const key = btn.getAttribute("data-help");
  const text = PARAM_HELP[key];
  if (!text) return;

  const pop = document.createElement("div");
  pop.className = "param-help-popover";
  pop.innerHTML =
    '<div class="param-help-popover-title">' +
    btn.closest(".s-row-label").querySelector(".s-row-name").textContent +
    "</div>" +
    text.replace(/\n/g, "<br>");
  document.body.appendChild(pop);

  const r = btn.getBoundingClientRect();
  let top = r.bottom + 6;
  let left = r.left;
  pop.style.left = left + "px";
  pop.style.top = top + "px";
  requestAnimationFrame(() => {
    const pr = pop.getBoundingClientRect();
    if (pr.right > window.innerWidth - 8) pop.style.left = Math.max(8, window.innerWidth - pr.width - 8) + "px";
    if (pr.bottom > window.innerHeight - 8) pop.style.top = Math.max(8, r.top - pr.height - 6) + "px";
  });

  _activeHelpPopover = pop;
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest(".param-help-btn");
  if (btn) {
    e.preventDefault();
    e.stopPropagation();
    if (_activeHelpPopover && _activeHelpPopover._helpBtn === btn) {
      _closeHelpPopover();
    } else {
      _showHelpPopover(btn);
      if (_activeHelpPopover) _activeHelpPopover._helpBtn = btn;
    }
    return;
  }
  if (_activeHelpPopover && !e.target.closest(".param-help-popover")) {
    _closeHelpPopover();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") _closeHelpPopover();
});
