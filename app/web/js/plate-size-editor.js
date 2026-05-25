// Plate size editor — min/max box rendering, hit testing, drag, input sync
import { val, setVal } from './ui.js';

let _redraw = () => {};
export function setPlateSizeRedrawCallback(fn) { _redraw = fn; }

export let plateSizeBoxes = {
  min: { x: 200, y: 130, width: 80, height: 20 },
  max: { x: 200, y: 130, width: 400, height: 100 },
};
let plateSizeDrag = null;

export function setPlateSizeBoxes(v) { plateSizeBoxes = v; }
export function getPlateSizeDrag() { return plateSizeDrag; }
export function setPlateSizeDrag(v) { plateSizeDrag = v; }

export function syncPlateSizeInputsFromBoxes() {
  setVal("c_min_w", Math.round(plateSizeBoxes.min.width));
  setVal("c_min_h", Math.round(plateSizeBoxes.min.height));
  setVal("c_max_w", Math.round(plateSizeBoxes.max.width));
  setVal("c_max_h", Math.round(plateSizeBoxes.max.height));
}

export function syncPlateSizeBoxesFromInputs() {
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
  _redraw();
}

export function clampBoxInCanvas(box, cv) {
  box.width = Math.max(1, Math.min(box.width, cv.width));
  box.height = Math.max(1, Math.min(box.height, cv.height));
  box.x = Math.max(0, Math.min(box.x, cv.width - box.width));
  box.y = Math.max(0, Math.min(box.y, cv.height - box.height));
}

export function defaultPlateSizeOverlay(cv) {
  const minW = Number(val("c_min_w")) || 80;
  const minH = Number(val("c_min_h")) || 20;
  const maxW = Number(val("c_max_w")) || 400;
  const maxH = Number(val("c_max_h")) || 100;
  return {
    min: { x: (cv.width - minW) / 2, y: (cv.height - minH) / 2 + 40, width: minW, height: minH },
    max: { x: (cv.width - maxW) / 2, y: (cv.height - maxH) / 2 - 20, width: maxW, height: maxH },
  };
}

export function hitTestPlateSizeBox(x, y, box) {
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

export function getCursorForHit(hit) {
  if (!hit) return "default";
  if (hit === "move") return "grab";
  if (hit === "tl" || hit === "br") return "nwse-resize";
  if (hit === "tr" || hit === "bl") return "nesw-resize";
  if (hit === "l" || hit === "r") return "ew-resize";
  if (hit === "t" || hit === "b") return "ns-resize";
  return "default";
}

export function enforcePlateSizeConstraints() {
  const minB = plateSizeBoxes.min;
  const maxB = plateSizeBoxes.max;
  if (minB.width > maxB.width) { minB.width = maxB.width; }
  if (minB.height > maxB.height) { minB.height = maxB.height; }
  syncPlateSizeInputsFromBoxes();
}

export function setupPlateSizeInputListeners() {
  ["c_min_w", "c_min_h", "c_max_w", "c_max_h"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      syncPlateSizeBoxesFromInputs();
      enforcePlateSizeConstraints();
      _redraw();
    });
  });
}

export function resetPlateSizeBoxes() {
  const cv = document.getElementById("roiCanvas");
  setVal("c_min_w", 80);
  setVal("c_min_h", 20);
  setVal("c_max_w", 400);
  setVal("c_max_h", 100);
  plateSizeBoxes = defaultPlateSizeOverlay(cv);
  syncPlateSizeInputsFromBoxes();
  _redraw();
}
