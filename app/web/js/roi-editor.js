// ROI polygon editor — point management, rendering, canvas interaction
let _redraw = () => {};
export function setROIRedrawCallback(fn) { _redraw = fn; }

export let roiPoints = [];
let roiDrag = -1;

export function setRoiPoints(v) { roiPoints = v; }
export function getRoiDrag() { return roiDrag; }
export function setRoiDrag(v) { roiDrag = v; }

export function toCanvasPoint(point, unit, cv) {
  if (unit === "percent") {
    return {
      x: ((Number(point.x) || 0) * cv.width) / 100,
      y: ((Number(point.y) || 0) * cv.height) / 100,
    };
  }
  const legacyWidth = 640;
  const legacyHeight = 360;
  const pxX = Number(point.x) || 0;
  const pxY = Number(point.y) || 0;
  if (cv.width === legacyWidth && cv.height === legacyHeight) {
    return { x: pxX, y: pxY };
  }
  return {
    x: (pxX / legacyWidth) * cv.width,
    y: (pxY / legacyHeight) * cv.height,
  };
}

export function toPercentPoint(point, cv) {
  const x = Math.max(0, Math.min(cv.width, Number(point.x) || 0));
  const y = Math.max(0, Math.min(cv.height, Number(point.y) || 0));
  return {
    x: Number(((x / cv.width) * 100).toFixed(3)),
    y: Number(((y / cv.height) * 100).toFixed(3)),
  };
}

export function defaultROIPointsForCanvas(cv) {
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

export function findInsertSegmentIndex(point) {
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

export function renderROIPointsList() {
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
      _redraw();
    });
  });
  container.querySelectorAll(".roi-pt-y").forEach((el) => {
    el.addEventListener("input", () => {
      const idx = Number(el.dataset.idx);
      const cv = document.getElementById("roiCanvas");
      roiPoints[idx].y = Math.max(0, Math.min(cv.height, Number(el.value) || 0));
      _redraw();
    });
  });
  container.querySelectorAll(".roi-pt-del").forEach((el) => {
    el.addEventListener("click", () => {
      roiPoints.splice(Number(el.dataset.idx), 1);
      renderROIPointsList();
      _redraw();
    });
  });
}

export function canvasCoords(e, cv) {
  const r = cv.getBoundingClientRect();
  const scaleX = cv.width / r.width;
  const scaleY = cv.height / r.height;
  return {
    x: (e.clientX - r.left) * scaleX,
    y: (e.clientY - r.top) * scaleY,
  };
}

export function resetROIPoints() {
  const cv = document.getElementById("roiCanvas");
  roiPoints = defaultROIPointsForCanvas(cv);
  renderROIPointsList();
  _redraw();
}
