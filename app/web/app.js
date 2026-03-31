import { api, apiUrl, getApiKey, jfetch, showAuthOverlay } from "./js/api.js";
import {
  applyDebugPanelVisibility,
  cleanupDebugLogStream,
  initDebugModule,
  loadDebugLogHistory,
  setupDebugLogStream,
} from "./js/debug.js";
import {
  hasHotkeyBinding,
  hasSelectedController,
  initControllersBindings,
  initControllersModule,
  loadControllers,
  renderChannelControllerOptions,
  triggerHotkey,
  updateChannelControllerBindingState,
} from "./js/controllers.js";
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
import {
  cleanupEventRuntime,
  hydrateChannelLastPlates,
  initEventsModule,
  loadInitialEventFeed,
  renderEventFeed,
  setupEventFeedLayoutGuards,
  setupEventStream,
  updateChannelLastPlate,
} from "./js/events.js";
import { initHelpModule } from "./js/help.js";
import { initListsBindings, initListsModule, loadLists } from "./js/lists.js";
import { initSettingsModule, loadGlobalSettings, saveGeneral } from "./js/settings.js";
import { state } from "./js/state.js";
import {
  closeModal,
  initUI,
  openModal,
  showToast,
  switchSettings,
  switchTab,
  updateTopbarTitle,
} from "./js/ui.js";

let debugSettingsCache = null;
let overlayRefreshTimer = null;
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
  const hasController = hasSelectedController();
  if (pane) pane.style.display = hasController ? "block" : "none";
  if (empty) empty.style.display = hasController ? "none" : "flex";
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

let selectedChannelId = null;
let channelConfigRequestToken = 0;
let roiPoints = [];
let currentChannelCustomListIds = [];
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
initDebugModule({ api, apiUrl, jfetch, scheduleVideoGridLayout });
initJournalModule({ api, jfetch, state, flagHtml });
initEventsModule({
  api,
  apiUrl,
  jfetch,
  state,
  flagHtml,
  formatDirection,
  normalizePlate,
  openEventDetails,
  handleLiveEventForJournal,
  loadEventFeedHistory,
});
initHelpModule();

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
initUI({
  onObsTabActivated: () => {
    scheduleVideoGridLayout();
    renderEventFeed(true);
  },
});
initJournalBindings();
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
initControllersModule({
  api,
  jfetch,
  val,
  setVal,
  showToast,
  openModal,
  closeModal,
  syncControllerConfigVisibility,
});
document.getElementById("saveGeneralBtn").onclick = saveGeneral;
document.getElementById("saveChannelBtn").onclick = saveChannel;
document.getElementById("deleteChannelBtn").onclick = deleteChannel;
document.getElementById("createChannelBtn").onclick = createChannel;
initControllersBindings();

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
  if (!hotkey || !hasHotkeyBinding(hotkey)) return;
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
  cleanupEventRuntime();
  cleanupDebugLogStream();
  if (overlayRefreshTimer) {
    clearInterval(overlayRefreshTimer);
    overlayRefreshTimer = null;
  }
}
window.addEventListener("beforeunload", cleanupStreamsAndTimers);
window.addEventListener("pagehide", cleanupStreamsAndTimers);

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
  await loadInitialEventFeed();
  await loadLists();
  await loadJournal();
  await loadGlobalSettings();
  await refreshOverlayStates();
  await loadDebugLogHistory();
  setupDebugLogStream();
  await loadControllers();
  setupEventStream();
  setInterval(refreshChannels, 8000);
  syncOverlayPolling();
})();

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
