import { api, apiUrl, getApiKey, jfetch, showAuthOverlay } from "./js/api.js";
import {
  applyDebugPanelVisibility,
  cleanupDebugLogStream,
  initDebugModule,
  loadDebugLogHistory,
  setupDebugLogStream,
} from "./js/debug.js";
import {
  fillChannelFilter,
  formatDirection,
  handleLiveEventForJournal,
  initJournalBindings,
  initJournalModule,
  initJournalScroll,
  loadEventFeedHistory,
  loadJournal,
  normalizePlate,
  openEventDetails,
} from "./js/journal.js";
import { initListsBindings, initListsModule, loadLists } from "./js/lists.js";
import { initSettingsModule, loadGlobalSettings, saveGeneral } from "./js/settings.js";
import { state } from "./js/state.js";

let eventSource = null;
let streamReconnectTimer = null;
let debugSettingsCache = null;
let overlayRefreshTimer = null;
let eventFeedResizeObserver = null;
let eventFeedRenderScheduled = false;
let eventFeedRenderFrame = null;
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
    sysdata: "Системные данные",
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
  if (name === "vision") {
    refreshPreviewSnapshot();
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


function loadBarColor(pct) {
  if (pct < 50) return "#2ecc71";
  if (pct < 80) return "#f5a623";
  return "#e74c3c";
}

async function refreshSystemResources() {
  if (document.hidden) return;
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
    if (cpuBar) { cpuBar.style.width = `${cpu}%`; cpuBar.style.background = loadBarColor(cpu); }
    if (ramBar) { ramBar.style.width = `${ram}%`; ramBar.style.background = loadBarColor(ram); }
  } catch (_e) {}
}

async function checkServerHealth() {
  if (document.hidden) return;
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
  if (document.hidden) return;
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

function syncOverlayPolling() {
  const shouldPoll = Boolean((debugSettingsCache || {}).show_channel_metrics);
  if (shouldPoll && !overlayRefreshTimer) {
    refreshOverlayStates();
    overlayRefreshTimer = setInterval(refreshOverlayStates, 700);
  } else if (!shouldPoll && overlayRefreshTimer) {
    clearInterval(overlayRefreshTimer);
    overlayRefreshTimer = null;
  }
}

async function refreshOverlayStates() {
  if (document.hidden) return;
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
    if (!document.hidden) {
      scheduleVideoGridLayout();
      refreshChannels();
      refreshSystemResources();
      checkServerHealth();
    }
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
  const pd = plateData || {};
  const plateText = String(pd.plate_display || pd.plate || "").trim();
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
    plate_display: ev.plate_display || null,
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
    const displayPlate = item.plate_display || item.plate || "—";
    div.innerHTML = `${flagHtml(item.country)}<div class='ev-row-top'><span class='ev-plate'>${displayPlate}</span><span class='ev-direction badge ${direction.badgeClass}'>${direction.label}</span></div><div class='ev-row-bottom'><span class='ev-meta-channel'>${channelName}</span><span class='ev-meta-time'>${timeStr}</span><span class='ev-conf ${conf < 0.85 ? "warn" : ""}'>${conf.toFixed(2)}</span></div>`;
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
  handleLiveEventForJournal(ev);
}

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

let selectedChannelId = null;
let channelConfigRequestToken = 0;
let controllersCache = [];
let selectedControllerId = null;
let roiPoints = [];
let currentChannelCustomListIds = [];
const hotkeyMap = new Map();
let roiDrag = -1;
let previewBgImage = null;

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
function drawPreview() {
  const cv = document.getElementById("roiCanvas");
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (previewBgImage && previewBgImage.complete) {
    ctx.drawImage(previewBgImage, 0, 0, cv.width, cv.height);
  }
  // plate size boxes
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
  // ROI polygon
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
  roiPoints.forEach((p, i) => {
    ctx.fillStyle = "#9b8fff";
    ctx.beginPath();
    ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.font = "bold 9px sans-serif";
    ctx.fillText(String(i + 1), p.x + 7, p.y - 4);
  });
}
async function refreshPreviewSnapshot() {
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
      previewBgImage = img;
      drawPreview();
    };
    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      };
    img.src = objectUrl;
  } catch (err) {
  }
}
function renderROIPointsList() {
  const container = document.getElementById("roiPointsList");
  if (!container) return;
  container.innerHTML = "";
  roiPoints.forEach((p, i) => {
    const row = document.createElement("div");
    row.className = "roi-point-row";
    row.innerHTML =
      '<span class="roi-pt-label">Точка ' + (i + 1) + ":</span>" +
      ' x <input type="number" class="roi-pt-x" data-idx="' + i + '" value="' + Math.round(p.x) + '">' +
      ' y <input type="number" class="roi-pt-y" data-idx="' + i + '" value="' + Math.round(p.y) + '">' +
      '<button class="roi-pt-del" data-idx="' + i + '" title="Удалить">\u00d7</button>';
    container.appendChild(row);
  });
  container.querySelectorAll(".roi-pt-x").forEach((el) => {
    el.addEventListener("input", () => {
      const idx = Number(el.dataset.idx);
      const cv = document.getElementById("roiCanvas");
      roiPoints[idx].x = Math.max(0, Math.min(cv.width, Number(el.value) || 0));
      drawPreview();
    });
  });
  container.querySelectorAll(".roi-pt-y").forEach((el) => {
    el.addEventListener("input", () => {
      const idx = Number(el.dataset.idx);
      const cv = document.getElementById("roiCanvas");
      roiPoints[idx].y = Math.max(0, Math.min(cv.height, Number(el.value) || 0));
      drawPreview();
    });
  });
  container.querySelectorAll(".roi-pt-del").forEach((el) => {
    el.addEventListener("click", () => {
      roiPoints.splice(Number(el.dataset.idx), 1);
      renderROIPointsList();
      drawPreview();
    });
  });
}

function canvasCoords(e, cv) {
  const r = cv.getBoundingClientRect();
  const scaleX = cv.width / r.width;
  const scaleY = cv.height / r.height;
  return {
    x: (e.clientX - r.left) * scaleX,
    y: (e.clientY - r.top) * scaleY,
  };
}

function setupVisionCanvas() {
  const cv = document.getElementById("roiCanvas");
  let moved = false;
  let downPoint = null;
  let psStartX = 0, psStartY = 0, psStartBox = null;

  cv.oncontextmenu = (e) => {
    e.preventDefault();
    const { x, y } = canvasCoords(e, cv);
    const idx = roiPoints.findIndex((p) => Math.hypot(p.x - x, p.y - y) < 10);
    if (idx >= 0) {
      roiPoints.splice(idx, 1);
      renderROIPointsList();
      drawPreview();
    }
  };

  cv.onmousedown = (e) => {
    const { x, y } = canvasCoords(e, cv);
    downPoint = { x, y };
    moved = false;

    // check plate-size boxes first (left button only)
    if (e.button === 0) {
      for (const key of ["min", "max"]) {
        const hit = hitTestPlateSizeBox(x, y, plateSizeBoxes[key]);
        if (hit) {
          plateSizeDrag = { key, hit };
          psStartX = x;
          psStartY = y;
          psStartBox = { ...plateSizeBoxes[key] };
          e.preventDefault();
          return;
        }
      }
    }

    // then ROI point drag
    roiDrag = roiPoints.findIndex((p) => Math.hypot(p.x - x, p.y - y) < 10);
  };

  cv.onmousemove = (e) => {
    const { x, y } = canvasCoords(e, cv);

    // plate size drag in progress
    if (plateSizeDrag) {
      const dx = x - psStartX, dy = y - psStartY;
      const box = plateSizeBoxes[plateSizeDrag.key];
      const hit = plateSizeDrag.hit;
      if (hit === "move") {
        box.x = psStartBox.x + dx;
        box.y = psStartBox.y + dy;
      } else {
        let nx = psStartBox.x, ny = psStartBox.y, nw = psStartBox.width, nh = psStartBox.height;
        if (hit.includes("l")) { nx = psStartBox.x + dx; nw = psStartBox.width - dx; }
        if (hit.includes("r")) { nw = psStartBox.width + dx; }
        if (hit.includes("t")) { ny = psStartBox.y + dy; nh = psStartBox.height - dy; }
        if (hit.includes("b")) { nh = psStartBox.height + dy; }
        if (nw < 4) { nw = 4; if (hit.includes("l")) nx = psStartBox.x + psStartBox.width - 4; }
        if (nh < 4) { nh = 4; if (hit.includes("t")) ny = psStartBox.y + psStartBox.height - 4; }
        box.x = nx; box.y = ny; box.width = nw; box.height = nh;
      }
      clampBoxInCanvas(box, cv);
      syncPlateSizeInputsFromBoxes();
      drawPreview();
      return;
    }

    // ROI point drag in progress
    if (roiDrag >= 0) {
      roiPoints[roiDrag] = { x, y };
      moved = true;
      drawPreview();
      return;
    }

    // hover cursor
    let cursor = "default";
    for (const key of ["min", "max"]) {
      const hit = hitTestPlateSizeBox(x, y, plateSizeBoxes[key]);
      if (hit) { cursor = getCursorForHit(hit); break; }
    }
    if (cursor === "default") {
      const nearPt = roiPoints.findIndex((p) => Math.hypot(p.x - x, p.y - y) < 10);
      if (nearPt >= 0) cursor = "grab";
    }
    cv.style.cursor = cursor;
  };

  cv.onmouseup = (e) => {
    const { x, y } = canvasCoords(e, cv);

    // finish plate size drag
    if (plateSizeDrag) {
      plateSizeDrag = null;
      enforcePlateSizeConstraints();
      drawPreview();
      return;
    }

    // finish ROI drag
    if (roiDrag >= 0) {
      roiDrag = -1;
      if (moved) {
        renderROIPointsList();
        return;
      }
    }

    if (e.button !== 0) return;
    if (downPoint && Math.hypot(downPoint.x - x, downPoint.y - y) > 4) return;

    // don't add ROI point if click was on an existing point
    const nearExisting = roiPoints.findIndex(
      (p) => Math.hypot(p.x - x, p.y - y) < 10,
    );
    if (nearExisting !== -1) return;

    // don't add ROI point if click was inside a plate-size box
    for (const key of ["min", "max"]) {
      if (hitTestPlateSizeBox(x, y, plateSizeBoxes[key]) === "move") return;
    }

    const insertAfter = findInsertSegmentIndex({ x, y });
    if (insertAfter === -1) return;
    roiPoints.splice(insertAfter + 1, 0, { x, y });
    renderROIPointsList();
    drawPreview();
  };

  cv.onmouseleave = () => {
    if (plateSizeDrag) {
      plateSizeDrag = null;
      enforcePlateSizeConstraints();
      drawPreview();
    }
  };
}

/* ─── Plate Size visual editor ─────────────────────── */

function syncPlateSizeInputsFromBoxes() {
  setVal("c_min_w", Math.round(plateSizeBoxes.min.width));
  setVal("c_min_h", Math.round(plateSizeBoxes.min.height));
  setVal("c_max_w", Math.round(plateSizeBoxes.max.width));
  setVal("c_max_h", Math.round(plateSizeBoxes.max.height));
}

function syncPlateSizeBoxesFromInputs() {
  const cv = document.getElementById("roiCanvas");
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
  drawPreview();
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

function setupPlateSizeInputListeners() {
  ["c_min_w", "c_min_h", "c_max_w", "c_max_h"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      syncPlateSizeBoxesFromInputs();
      enforcePlateSizeConstraints();
      drawPreview();
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
  } catch (err) {
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
  setChk("c_adaptive_stride", c.adaptive_stride_enabled ?? true);
  setChk("c_size_filter", c.size_filter_enabled);
  setVal("c_min_w", c.min_plate_size?.width ?? 80);
  setVal("c_min_h", c.min_plate_size?.height ?? 20);
  setVal("c_max_w", c.max_plate_size?.width ?? 600);
  setVal("c_max_h", c.max_plate_size?.height ?? 240);
  setVal("c_best_shots", c.best_shots ?? 3);
  setVal("c_cooldown", c.cooldown_seconds ?? 5);
  setVal("c_ocr_conf", c.ocr_min_confidence ?? 0.6);
  setVal("c_max_ocr_attempts", c.max_ocr_attempts ?? 15);
  setVal("c_max_consecutive_empty_ocr", c.max_consecutive_empty_ocr ?? 5);
  setVal("c_preview_fps_limit", c.preview_fps_limit ?? 5);
  setChk("c_roi_enabled", c.roi_enabled);
  const cv = document.getElementById("roiCanvas");
  const unit = c.region?.unit || "px";
  roiPoints = (c.region?.points || []).map((p) => toCanvasPoint(p, unit, cv));
  if (!roiPoints.length) {
    roiPoints = defaultROIPointsForCanvas(cv);
  }
  renderROIPointsList();

  plateSizeBoxes = defaultPlateSizeOverlay(cv);
  clampBoxInCanvas(plateSizeBoxes.min, cv);
  clampBoxInCanvas(plateSizeBoxes.max, cv);
  drawPreview();
  refreshPreviewSnapshot();
}

async function saveChannel() {
  if (!selectedChannelId) return;
  const points = roiPoints;
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
    adaptive_stride_enabled: document.getElementById("c_adaptive_stride").checked,
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
    max_consecutive_empty_ocr: Number(val("c_max_consecutive_empty_ocr")),
    preview_fps_limit: Number(val("c_preview_fps_limit")),
    roi_enabled: document.getElementById("c_roi_enabled").checked,
    region: {
      unit: "percent",
      points: points.map((p) =>
        toPercentPoint(p, document.getElementById("roiCanvas")),
      ),
    },
  };
  await jfetch(
    api(`/api/channels/${selectedChannelId}/config`),
    "PUT",
    payload,
  );
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
  } catch (err) {
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
  } catch (err) {
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
  } catch (err) {
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
    showToast("Настройки сохранены");
  } catch (err) {
    alert(`Не удалось сохранить контроллер: ${err.message}`);
  }
}
async function testController(relay) {
  if (!selectedControllerId) return;
  await jfetch(api(`/api/controllers/${selectedControllerId}/test`), "POST", {
    relay_index: relay,
    is_on: true,
  });
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
    try {
      eventSource.close();
    } catch (_e) {}
    scheduleStreamReconnect();
  };
}
initDebugModule({ api, apiUrl, jfetch, scheduleVideoGridLayout });
initJournalModule({ api, jfetch, state, flagHtml });

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
initJournalBindings();
// ── Modal helpers ────────────────────────────────────
function openModal(id) { document.getElementById(id).classList.add("active"); }
function closeModal(id) { document.getElementById(id).classList.remove("active"); }
initListsModule({
  api,
  jfetch,
  state,
  openModal,
  closeModal,
  showToast,
  renderEventFeed,
  renderCustomListOptions,
  getCurrentChannelCustomListIds: () => currentChannelCustomListIds,
});
initSettingsModule({
  api,
  jfetch,
  applyTheme,
  applySidebarLocked,
  applyDebugPanelVisibility,
  syncOverlayPolling,
  scheduleVideoGridLayout,
  showToast,
  setDebugSettingsCache: (value) => {
    debugSettingsCache = value;
  },
  val,
  setVal,
  setChk,
});
initListsBindings();
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
document.getElementById("g_sidebar_locked").onchange = () => applySidebarLocked(document.getElementById("g_sidebar_locked").checked);
document.getElementById("themeToggleBtn").onclick = () => {
  const nextTheme = val("g_theme") === "light" ? "dark" : "light";
  setVal("g_theme", nextTheme);
  applyTheme(nextTheme);
};
document.getElementById("plateSizeResetBtn").onclick = () => {
  const cv = document.getElementById("roiCanvas");
  setVal("c_min_w", 80);
  setVal("c_min_h", 20);
  setVal("c_max_w", 600);
  setVal("c_max_h", 240);
  plateSizeBoxes = defaultPlateSizeOverlay(cv);
  syncPlateSizeInputsFromBoxes();
  drawPreview();
};
document.getElementById("roiRefreshBtn").onclick = refreshPreviewSnapshot;
document.getElementById("roiClearBtn").onclick = () => {
  const cv = document.getElementById("roiCanvas");
  roiPoints = defaultROIPointsForCanvas(cv);
  renderROIPointsList();
  drawPreview();
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
setInterval(refreshSystemResources, 10000);
checkServerHealth();
setInterval(checkServerHealth, 10000);
function cleanupStreamsAndTimers() {
  if (eventSource) {
    try {
      eventSource.close();
    } catch (_e) {}
    eventSource = null;
  }
  cleanupDebugLogStream();
  if (overlayRefreshTimer) {
    clearInterval(overlayRefreshTimer);
    overlayRefreshTimer = null;
  }
  if (eventFeedRenderFrame !== null) {
    cancelAnimationFrame(eventFeedRenderFrame);
    eventFeedRenderFrame = null;
    eventFeedRenderScheduled = false;
  }
}
window.addEventListener("beforeunload", cleanupStreamsAndTimers);
window.addEventListener("pagehide", cleanupStreamsAndTimers);
window.addEventListener("resize", () => scheduleEventFeedRender(true));

/* ─── Sidebar hover-expand ──────────────────────────── */
let sidebarLocked = false;
function applySidebarLocked(locked) {
  sidebarLocked = !!locked;
  const rail = document.getElementById("leftRail");
  if (sidebarLocked) {
    rail.classList.remove("rail-expanded");
  }
}
(function initSidebarHover() {
  const rail = document.getElementById("leftRail");

  rail.addEventListener("mouseenter", () => {
    if (sidebarLocked) return;
    rail.classList.add("rail-expanded");
  });

  rail.addEventListener("mouseleave", () => {
    rail.classList.remove("rail-expanded");
  });
})();

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
  setupVisionCanvas();
  setupPlateSizeInputListeners();
  switchChannelSettingsTab("channel");
  updateTopbarTitle();
  await refreshChannels();
  await hydrateChannelLastPlates();
  initJournalScroll();
  await loadEventFeedHistory();
  renderEventFeed();
  await loadLists();
  await loadJournal();
  await loadGlobalSettings();
  await refreshOverlayStates();
  await loadDebugLogHistory();
  setupDebugLogStream();
  await loadControllers();
  setupStream();
  setInterval(refreshChannels, 8000);
  syncOverlayPolling();
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
  adaptive_stride_enabled: "Когда активных треков нет, система может временно реже запускать детектор для экономии CPU.",
  size_filter_enabled: "Включить фильтрацию найденных номерных рамок по размеру (ширина и высота в пикселях). Отсекает слишком маленькие и слишком большие обнаружения.",
  min_plate_size: "Минимальная ширина и высота обнаруженной номерной рамки в пикселях. Рамки меньше этого размера отбрасываются до OCR. Помогает отфильтровать далёкие или нерелевантные объекты.",
  max_plate_size: "Максимальная ширина и высота обнаруженной номерной рамки в пикселях. Рамки больше этого размера отбрасываются. Помогает отфильтровать ложные детекции на крупных объектах.",
  best_shots: "Сколько лучших OCR-наблюдений накапливается на один трек для голосования. Из них выбирается консенсус — номер, набравший кворум и наибольший суммарный вес уверенности.ВНИМАНИЕ, количество бестшотов не должно быть равным или больше макс. OCR попыток.\n\nПо умолчанию 3.",
  cooldown_seconds: "Пауза (в секундах) между повторными событиями для одного и того же номера. Если номер уже был распознан менее N секунд назад — повторное событие не создаётся. Предотвращает дублирование при медленном проезде.",
  ocr_min_confidence: "Минимальный порог уверенности OCR (0.0–1.0). Результаты ниже порога не попадают в пул кандидатов трека и считаются нечитаемыми.\n\nПо умолчанию 0.6.",
  max_ocr_attempts: "Максимальное число OCR-попыток для одного трека. После исчерпания бюджета OCR для этого трека прекращается — кроп, предобработка и CRNN-инференс больше не выполняются.\n\nЕсли консенсус был достигнут раньше — трек финализируется досрочно.\nЕсли бюджет исчерпан без консенсуса — выбирается лучший кандидат по весу.\nЕсли кандидатов нет — генерируется одно событие «Нечитаемо».\n\nПо умолчанию 15.",
  max_consecutive_empty_ocr: "Если OCR несколько раз подряд не возвращает текст, трек можно завершить раньше, чтобы не тратить CPU. 0 — отключить.\n\nПо умолчанию 5.",
  preview_fps_limit: "Ограничение частоты кодирования JPEG для предпросмотра (preview). Не влияет на реальный FPS камеры — ограничивает только частоту обновления превью в браузере.\n\nПо умолчанию 5.",
  roi_enabled: "Включить зону интереса (Region of Interest). Когда включено, только обнаружения с центром bbox внутри ROI-полигона обрабатываются. Детекция YOLO по-прежнему работает по всему кадру, но результаты за пределами ROI отбрасываются.",
  controller_id: "Привязка аппаратного контроллера к этому каналу. При распознавании номера, прошедшего фильтр списков, на контроллер отправляется HTTP-команда для срабатывания выбранного реле.",
  controller_relay: "Какое из двух реле контроллера использовать для этого канала (Реле 1 или Реле 2). Режим работы реле (pulse / pulse_timer) настраивается в параметрах контроллера.",

  /* ── Общие настройки ── */
  g_grid: "Сетка раскладки видеопревью на главной странице. Определяет сколько камер отображается одновременно: 1×1, 2×2, 2×3 или 3×3.",
  g_theme: "Цветовая тема интерфейса. Тёмная тема снижает нагрузку на глаза при работе в условиях слабого освещения.",
  g_sidebar_locked: "Фиксирует левую навигационную панель в свёрнутом состоянии. Когда включено, панель не раскрывается при наведении курсора.",
  g_sl_enabled: "Включает мониторинг потери видеосигнала. Если от камеры не поступают кадры в течение заданного таймаута, система автоматически переподключает канал.",
  g_frame_timeout: "Время ожидания (в секундах) нового кадра от камеры. Если за это время кадр не получен, соединение считается потерянным и запускается повторное подключение.",
  g_retry_interval: "Пауза (в секундах) между попытками переподключения после потери сигнала. Слишком малое значение может создать лишнюю нагрузку на камеру.",
  g_periodic_enabled: "Принудительное переподключение всех каналов через заданный интервал. Помогает при нестабильных камерах, которые «зависают» без явной потери сигнала.",
  g_periodic_minutes: "Интервал (в минутах) между принудительными переподключениями. Рекомендуется 30–120 минут.",
  g_max_screenshots: "Максимальный общий объём (в мегабайтах) файлов в каталоге скриншотов. При превышении лимита самые старые файлы удаляются автоматически.",
  g_media_retention: "Сколько дней хранить медиафайлы (скриншоты, кропы номеров) на диске. Файлы старше указанного срока удаляются при очередном цикле автоочистки.",
  g_log_level: "Минимальный уровень записей в лог-файл.\n• ALL / DEBUG — максимальная детализация (для отладки).\n• INFO — штатная работа.\n• WARNING / ERROR / CRITICAL — только проблемы.",
  g_log_retention: "Сколько дней хранить файлы логов. Файлы старше указанного срока удаляются при ротации.",
  g_auto_cleanup: "Включает периодическую автоматическую очистку данных. При включении система удаляет:\n• старые события из базы данных (старше заданного срока);\n• связанные медиафайлы (кадры и кропы номеров);\n• осиротевшие медиафайлы на диске;\n• файлы сверх лимита хранения скриншотов.",
  g_cleanup_minutes: "Как часто (в минутах) запускать цикл автоочистки. Минимум — 1 минута. Рекомендуется 15–60 минут.",
  g_events_retention: "Сколько дней хранить записи событий в базе данных. События старше указанного срока удаляются вместе со связанными медиафайлами.",
  g_postgres_dsn: "Строка подключения к PostgreSQL. Задаётся через переменную окружения и не может быть изменена из интерфейса.",
  g_timezone: "Часовой пояс для отображения времени в интерфейсе. Этот параметр влияет только на представление времени в приложении и не изменяет системные часы сервера.",
  g_offset_minutes: "Дополнительная коррекция времени (в минутах) поверх выбранного часового пояса. Используйте, если системные часы сервера расходятся с реальным временем. Диапазон: от −720 до +720 минут.",
  g_countries: "Выберите страны, номера которых распознаются системой. Список формируется из конфигурационных файлов в каталоге номеров."
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

// ── Backup & Restore ─────────────────────────────────
let _backupBusy = false;

function setBackupBusy(busy) {
  _backupBusy = busy;
  ["dbBackupBtn", "dbRestoreBtn", "settingsBackupBtn", "settingsRestoreBtn"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = busy;
  });
}

async function downloadBackup(url, fallbackName) {
  setBackupBusy(true);
  try {
    const headers = {};
    const k = getApiKey();
    if (k) headers["X-Api-Key"] = k;
    const resp = await fetch(api(url), { headers });
    if (resp.status === 401) {
      showAuthOverlay(() => downloadBackup(url, fallbackName));
      return;
    }
    if (!resp.ok) {
      let detail = "Ошибка скачивания";
      try { const j = await resp.json(); detail = j.detail || detail; } catch(_) {}
      showToast(detail, 4000);
      return;
    }
    const blob = await resp.blob();
    const cd = resp.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/);
    const filename = m ? m[1] : fallbackName;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 200);
    showToast("Файл скачан", 2000);
  } catch (err) {
    showToast("Ошибка: " + err.message, 4000);
  } finally {
    setBackupBusy(false);
  }
}

// DB backup download
document.getElementById("dbBackupBtn").onclick = () => downloadBackup("/api/data/backup/database", "anpr_db_backup.zip");

// Settings backup download
document.getElementById("settingsBackupBtn").onclick = () => downloadBackup("/api/data/backup/settings", "settings.yaml");

// DB restore flow
let _pendingDbFile = null;
document.getElementById("dbRestoreBtn").onclick = () => {
  document.getElementById("dbRestoreFileInput").value = "";
  document.getElementById("dbRestoreFileInput").click();
};
document.getElementById("dbRestoreFileInput").onchange = (e) => {
  const file = e.target.files[0];
  if (!file) return;
  _pendingDbFile = file;
  document.getElementById("dbRestoreFileName").textContent = file.name;
  openModal("dbRestoreModal");
};
document.getElementById("dbRestoreModalClose").onclick = () => { _pendingDbFile = null; closeModal("dbRestoreModal"); };
document.getElementById("dbRestoreCancel").onclick = () => { _pendingDbFile = null; closeModal("dbRestoreModal"); };
document.getElementById("dbRestoreModal").onclick = (e) => {
  if (e.target.id === "dbRestoreModal") { _pendingDbFile = null; closeModal("dbRestoreModal"); }
};
document.getElementById("dbRestoreConfirm").onclick = async () => {
  closeModal("dbRestoreModal");
  if (!_pendingDbFile) return;
  setBackupBusy(true);
  const confirmBtn = document.getElementById("dbRestoreConfirm");
  confirmBtn.disabled = true;
  try {
    const formData = new FormData();
    formData.append("file", _pendingDbFile);
    const headers = {};
    const k = getApiKey();
    if (k) headers["X-Api-Key"] = k;
    const resp = await fetch(api("/api/data/backup/database/restore"), {
      method: "POST", headers, body: formData,
    });
    if (resp.status === 401) {
      showAuthOverlay();
      return;
    }
    const result = await resp.json();
    if (resp.ok && result.status === "ok") {
      showToast("БД восстановлена. Приложение перезапускается...", 8000);
      // Wait for restart and reload page
      setTimeout(() => {
        const check = setInterval(async () => {
          try {
            const r = await fetch(api("/api/health"));
            if (r.ok) { clearInterval(check); location.reload(); }
          } catch(_) {}
        }, 2000);
        setTimeout(() => clearInterval(check), 120000);
      }, 3000);
    } else {
      showToast(result.detail || "Ошибка восстановления БД", 5000);
    }
  } catch (err) {
    showToast("Ошибка: " + err.message, 5000);
  } finally {
    _pendingDbFile = null;
    confirmBtn.disabled = false;
    setBackupBusy(false);
  }
};

// Settings restore flow
let _pendingSettingsFile = null;
document.getElementById("settingsRestoreBtn").onclick = () => {
  document.getElementById("settingsRestoreFileInput").value = "";
  document.getElementById("settingsRestoreFileInput").click();
};
document.getElementById("settingsRestoreFileInput").onchange = (e) => {
  const file = e.target.files[0];
  if (!file) return;
  _pendingSettingsFile = file;
  document.getElementById("settingsRestoreFileName").textContent = file.name;
  openModal("settingsRestoreModal");
};
document.getElementById("settingsRestoreModalClose").onclick = () => { _pendingSettingsFile = null; closeModal("settingsRestoreModal"); };
document.getElementById("settingsRestoreCancel").onclick = () => { _pendingSettingsFile = null; closeModal("settingsRestoreModal"); };
document.getElementById("settingsRestoreModal").onclick = (e) => {
  if (e.target.id === "settingsRestoreModal") { _pendingSettingsFile = null; closeModal("settingsRestoreModal"); }
};
document.getElementById("settingsRestoreConfirm").onclick = async () => {
  closeModal("settingsRestoreModal");
  if (!_pendingSettingsFile) return;
  setBackupBusy(true);
  const confirmBtn = document.getElementById("settingsRestoreConfirm");
  confirmBtn.disabled = true;
  try {
    const formData = new FormData();
    formData.append("file", _pendingSettingsFile);
    const headers = {};
    const k = getApiKey();
    if (k) headers["X-Api-Key"] = k;
    const resp = await fetch(api("/api/data/backup/settings/restore"), {
      method: "POST", headers, body: formData,
    });
    if (resp.status === 401) {
      showAuthOverlay();
      return;
    }
    const result = await resp.json();
    if (resp.ok && result.status === "ok") {
      showToast("Настройки восстановлены и применены", 3000);
      // Reload settings on page
      await loadGlobalSettings();
    } else {
      showToast(result.detail || "Ошибка восстановления настроек", 5000);
    }
  } catch (err) {
    showToast("Ошибка: " + err.message, 5000);
  } finally {
    _pendingSettingsFile = null;
    confirmBtn.disabled = false;
    setBackupBusy(false);
  }
};
