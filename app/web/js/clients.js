// Client management — all-clients view, client card, list attachment
import { state } from './state.js';
import { api, jfetch } from './api.js';
import { openModal, closeModal, showToast, esc } from './ui.js';

// ── Private state ──────────────────────────────────────────────
let _editingClientId = null;
let _searchDebounceTimer = null;

// ── Data loading ───────────────────────────────────────────────

export async function loadAllClients() {
  state.allClients = await jfetch(api('/api/clients'));
  renderClientsTable();
}

export function renderClientsTable() {
  const body = document.getElementById('clientsBody');
  if (!body) return;
  body.innerHTML = '';
  (state.allClients || []).forEach((c) => {
    const listName = c.list_id
      ? (state.lists.find((l) => l.id === c.list_id)?.name ?? `#${c.list_id}`)
      : '—';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="plate-cell">${esc(c.plate)}</td>
      <td>${esc(c.last_name)}</td>
      <td>${esc(c.first_name)}</td>
      <td>${esc(c.phone)}</td>
      <td>${esc(c.car)}</td>
      <td>${esc(listName)}</td>`;
    tr.onclick = () => openClientCard(c.id);
    body.appendChild(tr);
  });
}

// ── Client card (create / edit) ────────────────────────────────

export async function openClientCard(clientId) {
  state.selectedClientId = clientId;
  _editingClientId = clientId;
  let client;
  try {
    client = await jfetch(api(`/api/clients/${clientId}`));
  } catch (_e) {
    showToast('Не удалось загрузить данные клиента', 3000);
    return;
  }
  _populateClientCard(client);
  openModal('clientCardModal');
  setTimeout(() => document.getElementById('clientCardLastName').focus(), 50);
}

export function openAddClientModal() {
  _editingClientId = null;
  state.selectedClientId = null;
  _populateClientCard(null);
  openModal('clientCardModal');
  setTimeout(() => document.getElementById('clientCardLastName').focus(), 50);
}

function _populateClientCard(client) {
  const isNew = client === null;
  document.getElementById('clientCardTitle').textContent = isNew ? 'Добавить клиента' : (client.plate || 'Клиент');
  document.getElementById('clientCardLastName').value   = client?.last_name   || '';
  document.getElementById('clientCardFirstName').value  = client?.first_name  || '';
  document.getElementById('clientCardMiddleName').value = client?.middle_name || '';
  document.getElementById('clientCardPhone').value      = client?.phone       || '';
  document.getElementById('clientCardCar').value        = client?.car         || '';
  document.getElementById('clientCardPlate').value      = client?.plate       || '';
  document.getElementById('clientCardComment').value    = client?.comment     || '';
  document.getElementById('clientCardError').textContent = '';

  const listName = client?.list_id
    ? (state.lists.find((l) => l.id === client.list_id)?.name ?? `#${client.list_id}`)
    : '—';
  document.getElementById('clientCardListName').textContent = listName;
  const listBtn = document.getElementById('clientCardListBtn');
  if (isNew) {
    listBtn.style.display = 'none';
  } else {
    listBtn.style.display = '';
    listBtn.textContent = client.list_id ? 'Открепить от списка' : 'Прикрепить к списку';
  }
  document.getElementById('clientCardDeleteBtn').style.display = isNew ? 'none' : '';
}

// ── Save (create or update) ────────────────────────────────────

export async function saveClientChanges() {
  const plate  = document.getElementById('clientCardPlate').value.trim();
  const errEl  = document.getElementById('clientCardError');
  if (!plate) { errEl.textContent = 'Гос. номер обязателен.'; return; }
  errEl.textContent = '';

  const payload = {
    plate,
    last_name:   document.getElementById('clientCardLastName').value.trim(),
    first_name:  document.getElementById('clientCardFirstName').value.trim(),
    middle_name: document.getElementById('clientCardMiddleName').value.trim(),
    phone:       document.getElementById('clientCardPhone').value.trim(),
    car:         document.getElementById('clientCardCar').value.trim(),
    comment:     document.getElementById('clientCardComment').value.trim(),
  };

  try {
    if (_editingClientId !== null) {
      await jfetch(api(`/api/clients/${_editingClientId}`), 'PUT', payload);
    } else {
      await jfetch(api('/api/clients'), 'POST', payload);
    }
  } catch (_e) {
    errEl.textContent = _editingClientId !== null
      ? 'Не удалось обновить: возможно, номер уже существует.'
      : 'Не удалось создать клиента.';
    return;
  }

  closeModal('clientCardModal');
  await _refreshAll();
}

// ── Delete ─────────────────────────────────────────────────────

export function openDeleteClientConfirm() {
  if (_editingClientId === null) return;
  const plate = document.getElementById('clientCardPlate').value.trim() || '?';
  document.getElementById('deleteClientPlateLabel').textContent = plate;
  openModal('deleteClientModal');
}

export async function confirmDeleteClient() {
  if (_editingClientId === null) return;
  try {
    await jfetch(api(`/api/clients/${_editingClientId}`), 'DELETE');
  } catch (_e) {
    showToast('Не удалось удалить клиента', 3000);
    return;
  }
  closeModal('deleteClientModal');
  closeModal('clientCardModal');
  _editingClientId = null;
  state.selectedClientId = null;
  await _refreshAll();
}

// ── List attachment ────────────────────────────────────────────

export function openListPickerModal() {
  if (_editingClientId === null) return;
  const clientId = _editingClientId;
  const items = document.getElementById('listPickerItems');
  items.innerHTML = '';

  if (!state.lists?.length) {
    items.innerHTML = '<p style="padding:8px;color:var(--text3);font-size:var(--font-sm);">Нет доступных списков</p>';
  } else {
    state.lists.forEach((l) => {
      const row = document.createElement('div');
      row.className = 'picker-item';
      row.innerHTML = `
        <div class="picker-item-label">${esc(l.name)}</div>
        <span class="picker-item-sub">${esc(l.type)}</span>
        <button class="btn btn-primary btn-sm">Прикрепить</button>`;
      row.querySelector('button').onclick = () => _attachAndRefresh(clientId, l.id);
      items.appendChild(row);
    });
  }

  openModal('listPickerModal');
}

async function _attachAndRefresh(clientId, listId) {
  try {
    await jfetch(api(`/api/clients/${clientId}/attach`), 'POST', { list_id: listId });
  } catch (_e) {
    showToast('Не удалось прикрепить клиента', 3000);
    return;
  }
  closeModal('listPickerModal');
  showToast('Клиент прикреплён к списку');
  await _refreshAll();
  // Re-open the card with updated attachment info
  if (_editingClientId === clientId) await openClientCard(clientId);
}

export function detachClientFromList() {
  if (_editingClientId === null) return;
  const plate = document.getElementById('clientCardPlate').value.trim() || '?';
  document.getElementById('detachClientPlateLabel').textContent = plate;
  openModal('detachClientModal');
}

export async function confirmDetachClient() {
  if (_editingClientId === null) return;
  const clientId = _editingClientId;
  try {
    await jfetch(api(`/api/clients/${clientId}/attach`), 'DELETE');
  } catch (_e) {
    showToast('Не удалось открепить клиента', 3000);
    return;
  }
  closeModal('detachClientModal');
  showToast('Клиент откреплён от списка');
  await _refreshAll();
  await openClientCard(clientId);
}

// ── Search ─────────────────────────────────────────────────────

export function searchClients(query) {
  clearTimeout(_searchDebounceTimer);
  if (!query.trim()) {
    loadAllClients();
    return;
  }
  _searchDebounceTimer = setTimeout(async () => {
    try {
      state.allClients = await jfetch(api(`/api/clients/search?q=${encodeURIComponent(query.trim())}`));
      renderClientsTable();
    } catch (_e) { /* keep current render on error */ }
  }, 300);
}

// ── Internal helpers ───────────────────────────────────────────

async function _refreshAll() {
  await loadAllClients();
  // Dynamic import breaks the potential circular dep with lists.js
  const { loadLists } = await import('./lists.js');
  await loadLists();
}
