// Video grid rendering, preview lifecycle, overlays, metrics
import { state, debugSettingsCache, overlayRefreshTimer, setOverlayRefreshTimer } from './state.js';
import { api, apiUrl, jfetch } from './api.js';
import { normalizeDirectionCode, formatDirection } from './ui.js';

function gridConfig(v) {
  if (v === "1x1") return [1, 1];
  if (v === "2x3") return [2, 3];
  if (v === "3x3") return [3, 3];
  return [2, 2];
}

// --- Channel display order ---
const CHANNEL_ORDER_KEY = "anpr_channel_order";

function loadChannelOrder() {
  try {
    const saved = JSON.parse(localStorage.getItem(CHANNEL_ORDER_KEY) || "[]");
    return Array.isArray(saved) ? saved.map(String) : [];
  } catch { return []; }
}

function saveChannelOrder() {
  try { localStorage.setItem(CHANNEL_ORDER_KEY, JSON.stringify(channelOrder)); } catch {}
}

let channelOrder = loadChannelOrder(); // string IDs in current display order

function syncChannelOrder() {
  const currentIds = state.channels.map(ch => String(ch.id));
  const before = channelOrder.join(",");
  channelOrder = channelOrder.filter(id => currentIds.includes(id));
  for (const id of currentIds) {
    if (!channelOrder.includes(id)) channelOrder.push(id);
  }
  if (channelOrder.join(",") !== before) saveChannelOrder();
}

function getOrderedChannels() {
  return channelOrder
    .map(id => state.channels.find(ch => String(ch.id) === id))
    .filter(Boolean);
}

// --- Expand state ---
let expandedChannelId = null;
let savedGridValue = null;

export function clearExpandMode() {
  if (!expandedChannelId) return;
  expandedChannelId = null;
  savedGridValue = null;
  const grid = document.getElementById("videoGrid");
  if (grid) grid.classList.remove("grid-expanded");
}

// --- Drag-and-drop state ---
let dragSourceId = null;
let dragTargetId = null;
let isDragging = false;
let dragStartX = 0;
let dragStartY = 0;
const DRAG_THRESHOLD = 8;

function cleanupDrag() {
  const grid = document.getElementById("videoGrid");
  if (grid) {
    grid.querySelectorAll(".drag-source, .drag-over").forEach(c => {
      c.classList.remove("drag-source", "drag-over");
    });
  }
  document.body.style.userSelect = "";
  document.body.style.cursor = "";
  dragSourceId = null;
  dragTargetId = null;
  isDragging = false;
}

function swapChannelOrder(idA, idB) {
  const ia = channelOrder.indexOf(String(idA));
  const ib = channelOrder.indexOf(String(idB));
  if (ia === -1 || ib === -1) return;
  [channelOrder[ia], channelOrder[ib]] = [channelOrder[ib], channelOrder[ia]];
  saveChannelOrder();
}

export function setupVideoGridDragDrop() {
  const grid = document.getElementById("videoGrid");
  if (!grid) return;

  // Prevent native browser drag from interfering
  grid.addEventListener("dragstart", e => e.preventDefault());

  // Double-click to expand / restore
  grid.addEventListener("dblclick", e => {
    const cell = e.target.closest(".video-cell");
    if (!cell) return;
    const gridSelect = document.getElementById("gridSelect");
    if (expandedChannelId) {
      if (gridSelect && savedGridValue) gridSelect.value = savedGridValue;
      expandedChannelId = null;
      savedGridValue = null;
    } else {
      savedGridValue = gridSelect ? gridSelect.value : null;
      expandedChannelId = String(cell.dataset.channelId);
    }
    renderVideoGrid();
  });

  // Drag start — track mousedown on a cell
  grid.addEventListener("mousedown", e => {
    if (e.button !== 0) return;
    const cell = e.target.closest(".video-cell");
    if (!cell) return;
    dragSourceId = String(cell.dataset.channelId);
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    isDragging = false;
  });

  // Drag move — document-level to track outside grid
  document.addEventListener("mousemove", e => {
    if (!dragSourceId) return;
    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;
    if (!isDragging && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;

    if (!isDragging) {
      isDragging = true;
      document.body.style.userSelect = "none";
      document.body.style.cursor = "grabbing";
    }

    // Refresh source highlight
    grid.querySelectorAll(".drag-source, .drag-over").forEach(c => {
      c.classList.remove("drag-source", "drag-over");
    });
    const sourceCell = grid.querySelector(`.video-cell[data-channel-id="${dragSourceId}"]`);
    if (sourceCell) sourceCell.classList.add("drag-source");

    // Find target cell under cursor
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const overCell = el?.closest(".video-cell");
    if (overCell && grid.contains(overCell) && overCell.dataset.channelId !== dragSourceId) {
      overCell.classList.add("drag-over");
      dragTargetId = String(overCell.dataset.channelId);
    } else {
      dragTargetId = null;
    }
  });

  // Drag end — document-level to catch release anywhere
  document.addEventListener("mouseup", () => {
    if (!dragSourceId) return;
    if (isDragging && dragTargetId) {
      const targetCell = grid.querySelector(`.video-cell[data-channel-id="${dragTargetId}"]`);
      if (targetCell) {
        swapChannelOrder(dragSourceId, dragTargetId);
        renderVideoGrid();
      }
    }
    cleanupDrag();
  });

  // Cancel drag when cursor leaves the grid area
  grid.addEventListener("mouseleave", () => {
    if (isDragging) cleanupDrag();
  });
}

export function statusTextForChannel(ch) {
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

function renderDebugOverlay(cell, ch) {
  if (!cell || !ch) return;
  const chState = ch.debug_state || {};
  const overlayData = chState.overlay || {};
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
  const timings = (chState.stage_timings || {});
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

export function syncOverlayPolling() {
  const shouldPoll = Boolean((debugSettingsCache || {}).show_channel_metrics);
  if (shouldPoll && !overlayRefreshTimer) {
    refreshOverlayStates();
    setOverlayRefreshTimer(setInterval(refreshOverlayStates, 700));
  } else if (!shouldPoll && overlayRefreshTimer) {
    clearInterval(overlayRefreshTimer);
    setOverlayRefreshTimer(null);
  }
}

export async function refreshOverlayStates() {
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

export function renderVideoGrid() {
  const grid = document.getElementById("videoGrid");
  if (!grid) return;

  syncChannelOrder();

  const pool = getCellPool();

  // Purge pool entries for channels that no longer exist in state so we
  // don't accumulate stale nodes after channel deletion.
  const liveIds = new Set(state.channels.map(ch => String(ch.id)));
  Array.from(pool.children).forEach(cell => {
    if (!liveIds.has(cell.dataset.channelId || "")) cell.remove();
  });

  let visible;
  let cols, effectiveRows;

  const expandedCh = expandedChannelId
    ? state.channels.find(c => String(c.id) === expandedChannelId)
    : null;

  if (expandedCh) {
    visible = [expandedCh];
    cols = 1;
    effectiveRows = 1;
    grid.classList.add("grid-expanded");
  } else {
    if (expandedChannelId) { expandedChannelId = null; savedGridValue = null; } // channel gone
    const [presetRows, presetCols] = gridConfig(document.getElementById("gridSelect").value);
    cols = presetCols;
    visible = getOrderedChannels().slice(0, presetRows * cols);
    effectiveRows = visible.length > 0 ? Math.ceil(visible.length / cols) : 1;
    grid.classList.remove("grid-expanded");
  }

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

  // Move off-screen cells to the pool instead of removing them from the DOM.
  // This keeps each channel's <img> element attached to the document so the
  // browser never cancels its MJPEG connection — the stream stays alive and
  // resumes instantly when the cell is moved back into the grid.
  const visibleIds = new Set(visible.map((ch) => String(ch.id)));
  Array.from(grid.children).forEach((cell) => {
    if (!visibleIds.has(cell.dataset.channelId || "")) {
      pool.appendChild(cell);
    }
  });

  for (const ch of visible) {
    // 1. Check the live grid first.
    let cell = grid.querySelector(`.video-cell[data-channel-id='${ch.id}']`);
    if (cell) {
      updateVideoCell(cell, ch);
    } else {
      // 2. Try to restore a parked cell (MJPEG stream still alive in pool).
      cell = pool.querySelector(`.video-cell[data-channel-id='${ch.id}']`);
      if (cell) {
        updateVideoCell(cell, ch);
      } else {
        // 3. Truly new channel — create from scratch.
        cell = createVideoCell(ch);
      }
    }
    grid.appendChild(cell);
  }
}

let videoGridLayoutFrame = null;
let videoGridSecondPassFrame = null;
let videoGridResizeObserver = null;

// Hidden cell pool — keeps <img> elements attached to the document so the
// browser never cancels their MJPEG streams while channels are off-screen
// (e.g. during expand mode).  Cells are moved here instead of removed, then
// moved back to the grid when they become visible again.
function getCellPool() {
  let pool = document.getElementById("_anpr_cell_pool");
  if (!pool) {
    pool = document.createElement("div");
    pool.id = "_anpr_cell_pool";
    pool.style.cssText = "display:none;position:absolute;pointer-events:none;";
    document.body.appendChild(pool);
  }
  return pool;
}

export function scheduleVideoGridLayout(secondPass = false) {
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

export function setupVideoGridLayoutGuards(onVisibilityVisible) {
  window.addEventListener("resize", scheduleVideoGridLayout);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      scheduleVideoGridLayout();
      if (onVisibilityVisible) onVisibilityVisible();
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

// --- Event feed last plate support ---
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
