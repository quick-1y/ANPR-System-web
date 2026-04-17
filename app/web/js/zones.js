// Zones tab — list, create, settings panel, delete with confirmation
import { getZones, createZone, getZone, updateZone, deleteZone } from './api.js';
import { showToast, openModal, closeModal } from './ui.js';
import { state } from './state.js';

let _zones = [];
let _selectedZoneId = null;

// ── Public: called on tab activation ─────────────────────────────────

export async function loadZones() {
  try {
    _zones = await getZones();
  } catch (_e) {
    _zones = [];
  }
  state.zones = _zones;
  renderZoneList(_zones);
}

// ── Rendering ─────────────────────────────────────────────────────────

function renderZoneList(zones) {
  const container = document.getElementById("zonesList");
  if (!container) return;
  container.innerHTML = "";
  if (!zones.length) {
    container.innerHTML = '<div class="ch-item">Нет зон</div>';
    _hideSettingsPanel();
    return;
  }
  zones.forEach((z) => {
    const card = document.createElement("div");
    card.className = "zone-card" + (z.id === _selectedZoneId ? " active" : "");
    card.dataset.zoneId = z.id;
    card.innerHTML = `
      <div class="zone-card-name">${_esc(z.name)}</div>
      <div class="zone-card-stats">
        Вместимость: <b>${z.capacity}</b>&ensp;
        Занято: <b>${z.occupied}</b>&ensp;
        Свободно: <b>${z.free}</b>
      </div>
      <div class="zone-card-actions">
        <button class="btn btn-ghost btn-sm zone-settings-btn" data-zone-id="${z.id}">Настройки</button>
        <button class="btn btn-danger btn-sm zone-delete-btn" data-zone-id="${z.id}">Удалить</button>
      </div>`;
    container.appendChild(card);
  });

  container.querySelectorAll(".zone-settings-btn").forEach((btn) => {
    btn.onclick = () => openZoneSettings(parseInt(btn.dataset.zoneId));
  });
  container.querySelectorAll(".zone-delete-btn").forEach((btn) => {
    btn.onclick = () => _confirmDeleteZone(parseInt(btn.dataset.zoneId));
  });
}

// ── Settings panel ────────────────────────────────────────────────────

async function openZoneSettings(zoneId) {
  _selectedZoneId = zoneId;
  renderZoneList(_zones);
  const panel = document.getElementById("zonesSettingsPanel");
  if (!panel) return;
  panel.classList.remove("hidden");

  let detail;
  try {
    detail = await getZone(zoneId);
  } catch (_e) {
    showToast("Не удалось загрузить зону", "error");
    return;
  }

  const nameEl = document.getElementById("zoneSettingName");
  const capEl = document.getElementById("zoneSettingCapacity");
  const occEl = document.getElementById("zoneOccupancyInfo");
  const chEl = document.getElementById("zoneChannelsList");

  if (nameEl) nameEl.value = detail.name || "";
  if (capEl) capEl.value = detail.capacity ?? 0;
  if (occEl) occEl.textContent = `Занято: ${detail.occupied} / Вместимость: ${detail.capacity}`;

  if (chEl) {
    if (detail.channels && detail.channels.length) {
      chEl.innerHTML = detail.channels.map((ch) => `<div class="zone-channel-item">${_esc(ch.name)}</div>`).join("");
    } else {
      chEl.innerHTML = '<div class="zone-channel-item muted">Нет привязанных каналов</div>';
    }
  }

  const saveBtn = document.getElementById("saveZoneBtn");
  if (saveBtn) saveBtn.onclick = () => _saveZone(zoneId);
}

function _hideSettingsPanel() {
  _selectedZoneId = null;
  const panel = document.getElementById("zonesSettingsPanel");
  if (panel) panel.classList.add("hidden");
}

async function _saveZone(zoneId) {
  const name = (document.getElementById("zoneSettingName")?.value || "").trim();
  const capacity = parseInt(document.getElementById("zoneSettingCapacity")?.value || "0");
  if (!name) { showToast("Введите название зоны", "error"); return; }
  try {
    await updateZone(zoneId, { name, capacity });
    showToast("Зона сохранена");
    await loadZones();
    // Re-open panel to refresh occupancy display
    openZoneSettings(zoneId);
  } catch (_e) {
    showToast("Ошибка сохранения зоны", "error");
  }
}

// ── Create zone ───────────────────────────────────────────────────────

export function openCreateZoneModal() {
  const nameEl = document.getElementById("newZoneName");
  const capEl = document.getElementById("newZoneCapacity");
  if (nameEl) nameEl.value = "";
  if (capEl) capEl.value = "0";
  openModal("createZoneModal");
  setTimeout(() => { if (nameEl) nameEl.focus(); }, 50);
}

export async function doCreateZone() {
  const name = (document.getElementById("newZoneName")?.value || "").trim();
  const capacity = parseInt(document.getElementById("newZoneCapacity")?.value || "0");
  if (!name) { document.getElementById("newZoneName")?.focus(); return; }
  try {
    const created = await createZone({ name, capacity });
    closeModal("createZoneModal");
    await loadZones();
    openZoneSettings(created.id);
  } catch (_e) {
    showToast("Ошибка создания зоны", "error");
  }
}

// ── Delete zone ───────────────────────────────────────────────────────

async function _confirmDeleteZone(zoneId) {
  let detail;
  try {
    detail = await getZone(zoneId);
  } catch (_e) {
    showToast("Не удалось проверить зону", "error");
    return;
  }

  const infoEl = document.getElementById("deleteZoneInfo");
  if (infoEl) {
    if (detail.channels && detail.channels.length) {
      const names = detail.channels.map((ch) => _esc(ch.name)).join(", ");
      infoEl.innerHTML = `<b>${_esc(detail.name)}</b><br>Привязанные каналы будут отвязаны: ${names}`;
    } else {
      infoEl.innerHTML = `<b>${_esc(detail.name)}</b>`;
    }
  }

  const confirmBtn = document.getElementById("deleteZoneConfirm");
  if (confirmBtn) confirmBtn.onclick = () => _doDeleteZone(zoneId);
  openModal("deleteZoneModal");
}

async function _doDeleteZone(zoneId) {
  try {
    await deleteZone(zoneId);
    closeModal("deleteZoneModal");
    if (_selectedZoneId === zoneId) _hideSettingsPanel();
    await loadZones();
    showToast("Зона удалена");
  } catch (_e) {
    showToast("Ошибка удаления зоны", "error");
  }
}

// ── Init ──────────────────────────────────────────────────────────────

export function initZonesTab() {
  const createBtn = document.getElementById("createZoneBtn");
  if (createBtn) createBtn.onclick = openCreateZoneModal;

  const modalClose = document.getElementById("createZoneModalClose");
  if (modalClose) modalClose.onclick = () => closeModal("createZoneModal");
  const modalCancel = document.getElementById("createZoneCancel");
  if (modalCancel) modalCancel.onclick = () => closeModal("createZoneModal");
  const modalConfirm = document.getElementById("createZoneConfirm");
  if (modalConfirm) modalConfirm.onclick = doCreateZone;
  const createZoneModal = document.getElementById("createZoneModal");
  if (createZoneModal) createZoneModal.onclick = (e) => { if (e.target.id === "createZoneModal") closeModal("createZoneModal"); };
  const newZoneNameEl = document.getElementById("newZoneName");
  if (newZoneNameEl) newZoneNameEl.onkeydown = (e) => { if (e.key === "Enter") doCreateZone(); };

  const deleteCancel = document.getElementById("deleteZoneCancel");
  if (deleteCancel) deleteCancel.onclick = () => closeModal("deleteZoneModal");
  const deleteZoneModal = document.getElementById("deleteZoneModal");
  if (deleteZoneModal) deleteZoneModal.onclick = (e) => { if (e.target.id === "deleteZoneModal") closeModal("deleteZoneModal"); };

  const closePanelBtn = document.getElementById("closeZoneSettingsBtn");
  if (closePanelBtn) closePanelBtn.onclick = _hideSettingsPanel;
}

// ── Helpers ───────────────────────────────────────────────────────────

function _esc(str) {
  return String(str ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
