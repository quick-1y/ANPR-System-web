// Zones tab — dashboard-like zones list + detail panel with edit/delete actions.
import { getZones, createZone, getZone, updateZone, deleteZone } from './api.js';
import { showToast, openModal, closeModal } from './ui.js';
import { state } from './state.js';

let _zones = [];
let _selectedZoneId = null;

export async function loadZones() {
  try {
    _zones = await getZones();
  } catch (_e) {
    _zones = [];
  }
  state.zones = _zones;
  if (_zones.length && !_zones.some((z) => z.id === _selectedZoneId)) {
    _selectedZoneId = _zones[0].id;
  }
  if (!_zones.length) _selectedZoneId = null;
  renderZoneList(_zones);
  await renderZoneDetail();
}

function renderZoneList(zones) {
  const container = document.getElementById('zonesList');
  if (!container) return;
  container.innerHTML = '';
  if (!zones.length) {
    const item = document.createElement('div');
    item.className = 'zone-card';
    item.textContent = 'Нет зон';
    container.appendChild(item);
    return;
  }

  zones.forEach((z) => {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = `zone-card${z.id === _selectedZoneId ? ' active' : ''}`;
    card.onclick = async () => {
      _selectedZoneId = z.id;
      renderZoneList(_zones);
      await renderZoneDetail();
    };

    const name = document.createElement('div');
    name.className = 'zone-card-name';
    name.textContent = z.name;

    const meta = document.createElement('div');
    meta.className = 'zone-card-meta';
    const type = _zoneType(z.capacity);
    if (z.capacity > 0) {
      meta.textContent = `${type}  ${z.occupied} / ${z.capacity}`;
    } else {
      meta.textContent = `${type}  Без лимита`;
    }

    const bar = document.createElement('div');
    bar.className = 'zone-card-bar';
    const fill = document.createElement('div');
    fill.className = `zone-card-bar-fill ${_loadClass(z.occupied, z.capacity)}`.trim();
    fill.style.width = `${_percent(z.occupied, z.capacity)}%`;
    bar.appendChild(fill);

    card.appendChild(name);
    card.appendChild(meta);
    card.appendChild(bar);
    container.appendChild(card);
  });
}

async function renderZoneDetail() {
  const empty = document.getElementById('zoneEmptyState');
  const detailWrap = document.getElementById('zoneDetailWrap');
  if (!_selectedZoneId) {
    if (empty) empty.classList.remove('hidden');
    if (detailWrap) detailWrap.classList.add('hidden');
    return;
  }

  let detail;
  try {
    detail = await getZone(_selectedZoneId);
  } catch (_e) {
    showToast('Не удалось загрузить данные зоны', 'error');
    return;
  }

  if (empty) empty.classList.add('hidden');
  if (detailWrap) detailWrap.classList.remove('hidden');

  const cap = Number(detail.capacity || 0);
  const occupied = Number(detail.occupied || 0);
  const free = Math.max(0, Number(detail.free || 0));
  const percent = _percent(occupied, cap);
  const today = occupied;

  _setText('zoneDetailTitle', detail.name || '—');
  _setText('zoneDetailType', _zoneType(cap));
  _setText('zoneStatOccupied', `${occupied}${cap > 0 ? ` / ${cap}` : ''}`);
  _setText('zoneStatOccupiedSub', cap > 0 ? `${Math.max(0, occupied - free)} за час` : 'контроль');
  _setText('zoneStatFree', `${free}`);
  _setText('zoneStatLoad', cap > 0 ? `${percent}% загрузки` : 'без лимита');
  _setText('zoneStatToday', String(today));
  _setText('zoneOccupancyInfo', `Занято: ${occupied} / Вместимость: ${cap || 'без лимита'}`);

  const channelsList = document.getElementById('zoneChannelsList');
  if (channelsList) {
    channelsList.innerHTML = '';
    if (!detail.channels || !detail.channels.length) {
      const row = document.createElement('div');
      row.className = 'zone-linked-row';
      row.textContent = 'Нет привязанных камер';
      channelsList.appendChild(row);
    } else {
      detail.channels.forEach((channel, idx) => {
        const row = document.createElement('div');
        row.className = 'zone-linked-row';

        const left = document.createElement('div');
        const name = document.createElement('div');
        name.className = 'zone-linked-name';
        name.textContent = channel.name || `Канал ${channel.id}`;
        const meta = document.createElement('div');
        meta.className = 'zone-linked-meta';
        meta.textContent = `cam-${String(channel.id).padStart(2, '0')}`;
        left.appendChild(name);
        left.appendChild(meta);

        const badges = document.createElement('div');
        badges.className = 'zone-linked-badges';
        const dir = document.createElement('span');
        dir.className = `zone-badge ${idx % 2 ? 'zone-badge-exit' : 'zone-badge-enter'}`;
        dir.textContent = idx % 2 ? 'выезд' : 'въезд';
        const live = document.createElement('span');
        live.className = 'zone-badge';
        live.innerHTML = '<span class="zone-live-dot"></span>live';
        badges.appendChild(dir);
        badges.appendChild(live);

        row.appendChild(left);
        row.appendChild(badges);
        channelsList.appendChild(row);
      });
    }
  }

  const editBtn = document.getElementById('editZoneBtn');
  if (editBtn) editBtn.onclick = () => openZoneSettings(detail);
  const deleteBtn = document.getElementById('deleteZoneBtn');
  if (deleteBtn) deleteBtn.onclick = () => _confirmDeleteZone(detail.id);
}

function openZoneSettings(detail) {
  const nameEl = document.getElementById('zoneSettingName');
  const capEl = document.getElementById('zoneSettingCapacity');

  if (nameEl) nameEl.value = detail.name || '';
  if (capEl) capEl.value = detail.capacity ?? 0;
  openModal('editZoneModal');

  const saveBtn = document.getElementById('saveZoneBtn');
  if (saveBtn) saveBtn.onclick = () => _saveZone(detail.id);
}

async function _saveZone(zoneId) {
  const name = (document.getElementById('zoneSettingName')?.value || '').trim();
  const capacity = parseInt(document.getElementById('zoneSettingCapacity')?.value || '0', 10);
  if (!name) {
    showToast('Введите название зоны', 'error');
    return;
  }
  try {
    await updateZone(zoneId, { name, capacity });
    closeModal('editZoneModal');
    showToast('Зона сохранена');
    await loadZones();
  } catch (_e) {
    showToast('Ошибка сохранения зоны', 'error');
  }
}

export function openCreateZoneModal() {
  const nameEl = document.getElementById('newZoneName');
  const capEl = document.getElementById('newZoneCapacity');
  if (nameEl) nameEl.value = '';
  if (capEl) capEl.value = '0';
  openModal('createZoneModal');
  setTimeout(() => {
    if (nameEl) nameEl.focus();
  }, 50);
}

export async function doCreateZone() {
  const name = (document.getElementById('newZoneName')?.value || '').trim();
  const capacity = parseInt(document.getElementById('newZoneCapacity')?.value || '0', 10);
  if (!name) {
    document.getElementById('newZoneName')?.focus();
    return;
  }
  try {
    const created = await createZone({ name, capacity });
    closeModal('createZoneModal');
    _selectedZoneId = created.id;
    await loadZones();
  } catch (_e) {
    showToast('Ошибка создания зоны', 'error');
  }
}

async function _confirmDeleteZone(zoneId) {
  let detail;
  try {
    detail = await getZone(zoneId);
  } catch (_e) {
    showToast('Не удалось проверить зону', 'error');
    return;
  }

  const infoEl = document.getElementById('deleteZoneInfo');
  if (infoEl) {
    if (detail.channels && detail.channels.length) {
      const names = detail.channels.map((ch) => _esc(ch.name)).join(', ');
      infoEl.innerHTML = `<b>${_esc(detail.name)}</b><br>Привязанные каналы будут отвязаны: ${names}`;
    } else {
      infoEl.innerHTML = `<b>${_esc(detail.name)}</b>`;
    }
  }

  const confirmBtn = document.getElementById('deleteZoneConfirm');
  if (confirmBtn) confirmBtn.onclick = () => _doDeleteZone(zoneId);
  openModal('deleteZoneModal');
}

async function _doDeleteZone(zoneId) {
  try {
    await deleteZone(zoneId);
    closeModal('deleteZoneModal');
    if (_selectedZoneId === zoneId) _selectedZoneId = null;
    await loadZones();
    showToast('Зона удалена');
  } catch (_e) {
    showToast('Ошибка удаления зоны', 'error');
  }
}

export function initZonesTab() {
  const createBtn = document.getElementById('createZoneBtn');
  if (createBtn) createBtn.onclick = openCreateZoneModal;

  const modalClose = document.getElementById('createZoneModalClose');
  if (modalClose) modalClose.onclick = () => closeModal('createZoneModal');
  const modalCancel = document.getElementById('createZoneCancel');
  if (modalCancel) modalCancel.onclick = () => closeModal('createZoneModal');
  const modalConfirm = document.getElementById('createZoneConfirm');
  if (modalConfirm) modalConfirm.onclick = doCreateZone;
  const createZoneModal = document.getElementById('createZoneModal');
  if (createZoneModal) {
    createZoneModal.onclick = (e) => {
      if (e.target.id === 'createZoneModal') closeModal('createZoneModal');
    };
  }

  const editModalClose = document.getElementById('editZoneModalClose');
  if (editModalClose) editModalClose.onclick = () => closeModal('editZoneModal');
  const editCancel = document.getElementById('editZoneCancel');
  if (editCancel) editCancel.onclick = () => closeModal('editZoneModal');
  const editModal = document.getElementById('editZoneModal');
  if (editModal) {
    editModal.onclick = (e) => {
      if (e.target.id === 'editZoneModal') closeModal('editZoneModal');
    };
  }

  const deleteCancel = document.getElementById('deleteZoneCancel');
  if (deleteCancel) deleteCancel.onclick = () => closeModal('deleteZoneModal');
  const deleteZoneModal = document.getElementById('deleteZoneModal');
  if (deleteZoneModal) {
    deleteZoneModal.onclick = (e) => {
      if (e.target.id === 'deleteZoneModal') closeModal('deleteZoneModal');
    };
  }
}

function _setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function _zoneType(capacity) {
  return Number(capacity) > 0 ? 'Стоянка' : 'Контроль';
}

function _percent(occupied, capacity) {
  if (!capacity || capacity <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((occupied / capacity) * 100)));
}

function _loadClass(occupied, capacity) {
  const percent = _percent(occupied, capacity);
  if (percent >= 95) return 'danger';
  if (percent >= 80) return 'warn';
  return '';
}

function _esc(str) {
  return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
