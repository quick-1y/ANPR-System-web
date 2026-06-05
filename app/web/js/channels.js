// Channel config state, CRUD, hotkeys, vision canvas orchestration
import { state } from './state.js';
import { api, apiUrl, jfetch, getZones } from './api.js';
import { val, setVal, setChk, showToast, openModal, closeModal } from './ui.js';

// --- Sub-module imports ---
import {
  statusTextForChannel, renderVideoGrid, scheduleVideoGridLayout,
  setupVideoGridLayoutGuards, syncOverlayPolling, refreshOverlayStates,
  updateChannelLastPlate,
} from './video-grid.js';
import {
  roiPoints, setRoiPoints, getRoiDrag, setRoiDrag, setROIRedrawCallback,
  toCanvasPoint, toPercentPoint, defaultROIPointsForCanvas,
  findInsertSegmentIndex, canvasCoords, renderROIPointsList, resetROIPoints,
} from './roi-editor.js';
import {
  plateSizeBoxes, setPlateSizeBoxes, getPlateSizeDrag, setPlateSizeDrag,
  setPlateSizeRedrawCallback, syncPlateSizeInputsFromBoxes,
  syncPlateSizeBoxesFromInputs, clampBoxInCanvas, defaultPlateSizeOverlay,
  hitTestPlateSizeBox, getCursorForHit, enforcePlateSizeConstraints,
  setupPlateSizeInputListeners, resetPlateSizeBoxes,
} from './plate-size-editor.js';

// --- Re-exports for backwards compatibility ---
// Other modules import from channels.js; these re-exports keep those imports working.
export {
  statusTextForChannel, renderVideoGrid, scheduleVideoGridLayout,
  setupVideoGridLayoutGuards, setupVideoGridDragDrop, syncOverlayPolling,
  refreshOverlayStates, updateChannelLastPlate, clearExpandMode,
} from './video-grid.js';
export {
  roiPoints, defaultROIPointsForCanvas, renderROIPointsList, resetROIPoints,
} from './roi-editor.js';
export {
  defaultPlateSizeOverlay, setupPlateSizeInputListeners, resetPlateSizeBoxes,
} from './plate-size-editor.js';

// --- Channel config state ---
export let selectedChannelId = null;
let channelConfigRequestToken = 0;
export let controllersCache = [];
export let selectedControllerId = null;
let currentChannelCustomListIds = [];
export const hotkeyMap = new Map();
let previewBgImage = null;

// Setters for module-scoped lets
export function setSelectedChannelId(v) { selectedChannelId = v; }
export function setControllersCache(v) { controllersCache = v; }
export function setSelectedControllerId(v) { selectedControllerId = v; }

// --- Vision canvas: drawPreview composes ROI + plate-size rendering ---
export function drawPreview() {
  const cv = document.getElementById("roiCanvas");
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (previewBgImage && previewBgImage.complete) {
    ctx.drawImage(previewBgImage, 0, 0, cv.width, cv.height);
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
    ctx.font = "600 13px system-ui, -apple-system, Segoe UI, sans-serif";
    ctx.fillText(label + " " + Math.round(b.width) + "\u00d7" + Math.round(b.height), b.x + 4, b.y - 4);
  });
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
    ctx.font = "600 12px system-ui, -apple-system, Segoe UI, sans-serif";
    ctx.fillText(String(i + 1), p.x + 7, p.y - 4);
  });
}

// Wire redraw callbacks so sub-modules can trigger drawPreview
setROIRedrawCallback(drawPreview);
setPlateSizeRedrawCallback(drawPreview);

export async function refreshPreviewSnapshot() {
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

// --- Vision canvas: setupVisionCanvas orchestrates ROI + plate-size mouse handling ---
export function setupVisionCanvas() {
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
    if (e.button === 0) {
      for (const key of ["min", "max"]) {
        const hit = hitTestPlateSizeBox(x, y, plateSizeBoxes[key]);
        if (hit) {
          setPlateSizeDrag({ key, hit });
          psStartX = x;
          psStartY = y;
          psStartBox = { ...plateSizeBoxes[key] };
          e.preventDefault();
          return;
        }
      }
    }
    setRoiDrag(roiPoints.findIndex((p) => Math.hypot(p.x - x, p.y - y) < 10));
  };

  cv.onmousemove = (e) => {
    const { x, y } = canvasCoords(e, cv);
    if (getPlateSizeDrag()) {
      const drag = getPlateSizeDrag();
      const dx = x - psStartX, dy = y - psStartY;
      const box = plateSizeBoxes[drag.key];
      const hit = drag.hit;
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
    if (getRoiDrag() >= 0) {
      roiPoints[getRoiDrag()] = { x, y };
      moved = true;
      drawPreview();
      return;
    }
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
    if (getPlateSizeDrag()) {
      setPlateSizeDrag(null);
      enforcePlateSizeConstraints();
      drawPreview();
      return;
    }
    if (getRoiDrag() >= 0) {
      const wasMoved = moved;
      setRoiDrag(-1);
      if (wasMoved) {
        renderROIPointsList();
        return;
      }
    }
    if (e.button !== 0) return;
    if (downPoint && Math.hypot(downPoint.x - x, downPoint.y - y) > 4) return;
    const nearExisting = roiPoints.findIndex(
      (p) => Math.hypot(p.x - x, p.y - y) < 10,
    );
    if (nearExisting !== -1) return;
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
    if (getPlateSizeDrag()) {
      setPlateSizeDrag(null);
      enforcePlateSizeConstraints();
      drawPreview();
    }
  };
}

// --- Channel list rendering ---
export function renderChannelsList() {
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

export function syncChannelConfigVisibility() {
  const pane = document.getElementById("channelConfigPane");
  const empty = document.getElementById("channelConfigEmpty");
  const hasSelectedChannel = Boolean(selectedChannelId);
  if (pane) pane.style.display = hasSelectedChannel ? "block" : "none";
  if (empty) empty.style.display = hasSelectedChannel ? "none" : "flex";
}

export function syncControllerConfigVisibility() {
  const pane = document.getElementById("controllerConfigPane");
  const empty = document.getElementById("controllerConfigEmpty");
  const hasSelectedController = Boolean(selectedControllerId);
  if (pane) pane.style.display = hasSelectedController ? "block" : "none";
  if (empty) empty.style.display = hasSelectedController ? "none" : "flex";
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

// --- Hotkey system ---
export function hotkeyFromEvent(event) {
  const key = String(event.key || "").trim().toUpperCase();
  if (!key || key === "CONTROL" || key === "SHIFT" || key === "ALT") return "";
  const parts = [];
  if (event.ctrlKey) parts.push("CTRL");
  if (event.altKey) parts.push("ALT");
  if (event.shiftKey) parts.push("SHIFT");
  parts.push(key);
  return parts.join("+");
}

export function isEditingTarget(target) {
  if (!target) return false;
  const tag = String(target.tagName || "").toLowerCase();
  if (["input", "textarea", "select"].includes(tag)) return true;
  return Boolean(target.closest("[contenteditable='true']"));
}

export function rebuildHotkeyMap() {
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
  pending.forEach((bindings, hotkey) => {
    if (duplicates.has(hotkey)) return;
    hotkeyMap.set(hotkey, bindings[0]);
  });
}

export async function triggerHotkey(hotkey) {
  const binding = hotkeyMap.get(hotkey);
  if (!binding) return;
  try {
    await jfetch(api(`/api/controllers/${binding.controllerId}/test`), "POST", {
      relay_index: binding.relayIndex,
      is_on: true,
    });
  } catch (err) {
  }
}

// --- Channel config helpers ---
export function updateRelayTimerState(relayIndex) {
  const modeEl = document.getElementById(`ctrlR${relayIndex}Mode`);
  const timerEl = document.getElementById(`ctrlR${relayIndex}Timer`);
  if (!modeEl || !timerEl) return;
  const isPulseTimer = modeEl.value === "pulse_timer";
  timerEl.disabled = !isPulseTimer;
  if (!isPulseTimer) {
    timerEl.value = "1";
  }
}

export function updateChannelControllerBindingState() {
  const hasController = Boolean(val("c_controller_id"));
  const relayEl = document.getElementById("c_controller_relay");
  relayEl.disabled = !hasController;
  if (!hasController) {
    setVal("c_controller_relay", 0);
  }
}

export function renderCustomListOptions(selectedIds = []) {
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

export function updateCustomListsVisibility() {
  const block = document.getElementById("c_custom_lists_block");
  const hint = document.getElementById("c_custom_lists_hint");
  if (!block || !hint) return;
  const isCustom = val("c_list_filter_mode") === "custom";
  block.style.display = isCustom ? "flex" : "none";
  hint.style.display = isCustom ? "flex" : "none";
}

function renderChannelZoneSelect(selectId, zones, selectedValue) {
  const select = document.getElementById(selectId);
  if (!select) return;
  const currentStr = (selectedValue !== null && selectedValue !== undefined) ? String(selectedValue) : "";
  select.innerHTML = '<option value="">Не задано</option><option value="0">Вне парковки</option>';
  (zones || []).forEach((z) => {
    const option = document.createElement("option");
    option.value = String(z.id);
    option.textContent = z.name;
    select.appendChild(option);
  });
  select.value = currentStr;
  if (select.value !== currentStr) select.value = "";
  updateZoneChannelTypeState();
}

export function updateZoneChannelTypeState() {
  const beforeSelect = document.getElementById("c_zone_before_id");
  const afterSelect = document.getElementById("c_zone_after_id");
  const typeSelect = document.getElementById("c_zone_channel_type");
  if (!beforeSelect || !afterSelect || !typeSelect) return;
  const hasBoth = beforeSelect.value !== "" && afterSelect.value !== "";
  typeSelect.disabled = !hasBoth;
  if (!hasBoth) typeSelect.value = "";
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

export function switchChannelSettingsTab(name) {
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

// --- Channel CRUD ---
export async function refreshChannels() {
  if (document.hidden) return;
  state.channels = await jfetch(api("/api/channels"));
  renderVideoGrid();
  renderChannelsList();
  fillChannelFilter();
  if (!selectedChannelId && state.channels.length) {
    await selectChannel(state.channels[0].id);
  }
}

export async function selectChannel(id) {
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
  setVal("c_controller_direction_filter", c.controller_direction_filter || "both");
  setVal("c_list_filter_mode", c.list_filter_mode || "all");
  currentChannelCustomListIds = (c.list_filter_list_ids || []).map((id) => Number(id)).filter((id) => Number.isFinite(id) && id > 0);
  renderCustomListOptions(currentChannelCustomListIds);
  updateCustomListsVisibility();
  const zoneBeforeVal = (c.zone_before_id !== null && c.zone_before_id !== undefined) ? c.zone_before_id : "";
  const zoneAfterVal = (c.zone_after_id !== null && c.zone_after_id !== undefined) ? c.zone_after_id : "";
  try {
    const zones = await getZones();
    renderChannelZoneSelect("c_zone_before_id", zones, zoneBeforeVal);
    renderChannelZoneSelect("c_zone_after_id", zones, zoneAfterVal);
  } catch (_e) {
    renderChannelZoneSelect("c_zone_before_id", [], zoneBeforeVal);
    renderChannelZoneSelect("c_zone_after_id", [], zoneAfterVal);
  }
  const typeEl = document.getElementById("c_zone_channel_type");
  if (typeEl) typeEl.value = c.zone_channel_type || "";
  updateZoneChannelTypeState();
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
  setVal("c_max_w", c.max_plate_size?.width ?? 400);
  setVal("c_max_h", c.max_plate_size?.height ?? 100);
  setVal("c_best_shots", c.best_shots ?? 3);
  setVal("c_cooldown", c.cooldown_seconds ?? 5);
  setVal("c_ocr_conf", c.ocr_min_confidence ?? 0.6);
  setVal("c_max_ocr_attempts", c.max_ocr_attempts ?? 15);
  setVal("c_max_consecutive_empty_ocr", c.max_consecutive_empty_ocr ?? 5);
  setVal("c_preview_fps_limit", c.preview_fps_limit ?? 5);
  setChk("c_roi_enabled", c.roi_enabled);
  const cv = document.getElementById("roiCanvas");
  const unit = c.region?.unit || "px";
  setRoiPoints((c.region?.points || []).map((p) => toCanvasPoint(p, unit, cv)));
  if (!roiPoints.length) {
    setRoiPoints(defaultROIPointsForCanvas(cv));
  }
  renderROIPointsList();
  setPlateSizeBoxes(defaultPlateSizeOverlay(cv));
  clampBoxInCanvas(plateSizeBoxes.min, cv);
  clampBoxInCanvas(plateSizeBoxes.max, cv);
  drawPreview();
  refreshPreviewSnapshot();
}

export async function saveChannel() {
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
    controller_direction_filter: val("c_controller_direction_filter"),
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
    zone_before_id: val("c_zone_before_id") !== "" ? Number(val("c_zone_before_id")) : null,
    zone_after_id: val("c_zone_after_id") !== "" ? Number(val("c_zone_after_id")) : null,
    zone_channel_type: (val("c_zone_before_id") !== "" && val("c_zone_after_id") !== "") ? (val("c_zone_channel_type") || null) : null,
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

export async function createChannel() {
  document.getElementById("newChannelName").value = "";
  document.getElementById("newChannelName").placeholder = "Введите название";
  openModal("createChannelModal");
  setTimeout(() => document.getElementById("newChannelName").focus(), 50);
}

export async function _doCreateChannel(name) {
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

export async function deleteChannel() {
  if (!selectedChannelId) return;
  const ch = state.channels.find((c) => c.id === selectedChannelId);
  const label = ch ? ch.name : `#${selectedChannelId}`;
  document.getElementById("deleteChannelNameLabel").textContent = label;
  openModal("deleteChannelModal");
}

export async function _doDeleteChannel() {
  await jfetch(api(`/api/channels/${selectedChannelId}`), "DELETE");
  selectedChannelId = null;
  setRoiPoints([]);
  await refreshChannels();
}
