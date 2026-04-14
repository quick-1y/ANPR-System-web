// Plate lists management, list members view, CSV import/export
import { state } from './state.js';
import { api, jfetch } from './api.js';
import { showToast, openModal, closeModal, esc } from './ui.js';
import { renderCustomListOptions } from './channels.js';
import { renderEventFeed } from './events.js';

let currentChannelCustomListIds_ref = [];

export function setCurrentChannelCustomListIds(v) { currentChannelCustomListIds_ref = v; }

// ── Plate lookup (used by channel automation UI) ───────────────

export async function refreshPlateLookup() {
  try {
    const plates = await jfetch(api('/api/lists/plates'));
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

// ── Lists ──────────────────────────────────────────────────────

export async function loadLists() {
  state.lists = await jfetch(api('/api/lists'));
  renderLists();
  renderCustomListOptions(currentChannelCustomListIds_ref);
  await refreshPlateLookup();
  renderEventFeed(true);
}

function syncListMainVisibility() {
  const hasSelection = !!state.selectedListId && state.lists.length > 0;
  const header = document.getElementById('listsMainHeader');
  const dataWrap = document.getElementById('listsDataWrap');
  const emptyState = document.getElementById('listsEmptyState');
  if (header) header.style.display = hasSelection ? '' : 'none';
  if (dataWrap) dataWrap.style.display = hasSelection ? '' : 'none';
  if (emptyState) emptyState.style.display = hasSelection ? 'none' : '';
}

function listTypeDot(type) {
  if (type === 'black') return 'dot-black';
  if (type === 'info') return 'dot-info';
  return 'dot-white';
}

export function renderLists() {
  const items = document.getElementById('listItems');
  if (!items) return;
  items.innerHTML = '';
  state.lists.forEach((l, idx) => {
    const isActive = l.id === state.selectedListId || (!state.selectedListId && idx === 0);
    if (!state.selectedListId && idx === 0) state.selectedListId = l.id;
    const div = document.createElement('div');
    div.className = `list-item type-${l.type}${isActive ? ' active' : ''}`;
    div.innerHTML = `<div class='list-item-dot ${listTypeDot(l.type)}'></div><div class='list-item-name'>${esc(l.name)}</div><div class='list-item-count'>${esc(String(l.clients_count ?? '…'))}</div>`;
    div.onclick = () => {
      state.selectedListId = l.id;
      renderLists();
      loadListClients(l.id);
    };
    items.appendChild(div);
  });
  syncListMainVisibility();
  if (state.selectedListId) loadListClients(state.selectedListId);
}

// ── List members ───────────────────────────────────────────────

export async function loadListClients(listId) {
  const rows = await jfetch(api(`/api/lists/${listId}/clients`));
  state.listMembers = rows;
  const list = state.lists.find((x) => x.id === listId);
  const titleEl = document.getElementById('listTitle');
  if (titleEl) titleEl.textContent = list ? list.name : '—';
  renderListClientsTable(rows);
}

export function renderListClientsTable(clients) {
  const body = document.getElementById('listMembersBody');
  if (!body) return;
  body.innerHTML = '';
  (clients || []).forEach((c) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="plate-cell">${esc(c.plate)}</td>
      <td>${esc(c.first_name)}</td>
      <td>${esc(c.last_name)}</td>
      <td>${esc(c.phone)}</td>
      <td>${esc(c.car)}</td>
      <td>${esc(c.comment)}</td>`;
    const openCard = async () => {
      const { openClientCard } = await import('./clients.js');
      openClientCard(c.id);
    };
    tr.onclick = openCard;
    body.appendChild(tr);
  });
}

// ── Client picker (attach an existing client to the current list) ──

export async function openClientPickerModal(listId) {
  const items = document.getElementById('clientPickerItems');
  const searchInput = document.getElementById('clientPickerSearch');
  if (!items || !searchInput) return;

  searchInput.value = '';

  const renderPickerItems = (clients) => {
    items.innerHTML = '';
    if (!clients.length) {
      items.innerHTML = '<p style="padding:8px;color:var(--text3);font-size:12px;">Клиенты не найдены</p>';
      return;
    }
    clients.forEach((c) => {
      const label = [c.last_name, c.first_name, c.middle_name].filter(Boolean).join(' ') || '—';
      const row = document.createElement('div');
      row.className = 'picker-item';
      row.innerHTML = `
        <div class="picker-item-label">${esc(label)}</div>
        <span class="picker-item-sub">${esc(c.plate)}</span>
        <button class="btn btn-primary btn-sm">Прикрепить</button>`;
      row.querySelector('button').onclick = async () => {
        try {
          await jfetch(api(`/api/clients/${c.id}/attach`), 'POST', { list_id: listId });
        } catch (_e) {
          showToast('Не удалось прикрепить клиента', 3000);
          return;
        }
        closeModal('clientPickerModal');
        showToast('Клиент прикреплён к списку');
        await loadListClients(listId);
        const { loadAllClients } = await import('./clients.js');
        await loadAllClients();
        await loadLists();
      };
      items.appendChild(row);
    });
  };

  renderPickerItems(state.allClients || []);

  let searchTimer = null;
  searchInput.oninput = () => {
    clearTimeout(searchTimer);
    const q = searchInput.value.trim();
    if (!q) { renderPickerItems(state.allClients || []); return; }
    searchTimer = setTimeout(async () => {
      try {
        const results = await jfetch(api(`/api/clients/search?q=${encodeURIComponent(q)}`));
        renderPickerItems(results);
      } catch (_e) { /* keep current */ }
    }, 300);
  };

  openModal('clientPickerModal');
  setTimeout(() => searchInput.focus(), 50);
}

// ── CSV export ─────────────────────────────────────────────────

export function exportCurrentListCSV() {
  if (!state.selectedListId) return;
  const list = state.lists.find((l) => l.id === state.selectedListId);
  const headers = ['Гос. номер', 'Имя', 'Фамилия', 'Отчество', 'Телефон', 'Марка авто', 'Комментарий'];
  const lines = [headers.join(',')];
  (state.listMembers || []).forEach((r) => {
    const cells = [r.plate, r.first_name || '', r.last_name || '', r.middle_name || '', r.phone || '', r.car || '', r.comment || '']
      .map((v) => `"${String(v).replace(/"/g, '""')}"`);
    lines.push(cells.join(','));
  });
  const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${list ? list.name : 'list'}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function parseCSVLine(line) {
  const cells = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"' && line[i + 1] === '"') { current += '"'; i++; }
      else if (ch === '"') { inQuotes = false; }
      else { current += ch; }
    } else {
      if (ch === '"') { inQuotes = true; }
      else if (ch === ',') { cells.push(current); current = ''; }
      else { current += ch; }
    }
  }
  cells.push(current);
  return cells.map((c) => c.trim());
}

export async function importCurrentListCSV(file) {
  if (!state.selectedListId || !file) return;
  const EXPECTED_HEADERS = ['Гос. номер', 'Имя', 'Фамилия', 'Отчество', 'Телефон', 'Марка авто', 'Комментарий'];
  const text = await file.text();
  const rawLines = text.replace(/^\uFEFF/, '').split(/\r?\n/);
  const lines = rawLines.filter((l) => l.trim().length > 0);
  if (lines.length < 1) { showToast('Файл пуст', 3000); return; }

  const headerCells = parseCSVLine(lines[0]);
  const headersMatch = EXPECTED_HEADERS.every((h, i) => (headerCells[i] || '').trim() === h);
  if (!headersMatch) { showToast('Неверный формат списка', 3000); return; }

  const dataLines = lines.slice(1);
  if (dataLines.length === 0) { showToast('Нет записей для импорта', 3000); return; }

  let imported = 0;
  let skipped = 0;
  for (const line of dataLines) {
    const cells = parseCSVLine(line);
    const plate = (cells[0] || '').trim();
    if (!plate) { skipped++; continue; }
    try {
      const result = await jfetch(api('/api/clients'), 'POST', {
        plate,
        first_name:  (cells[1] || '').trim(),
        last_name:   (cells[2] || '').trim(),
        middle_name: (cells[3] || '').trim(),
        phone:       (cells[4] || '').trim(),
        car:         (cells[5] || '').trim(),
        comment:     (cells[6] || '').trim(),
      });
      if (result?.id) {
        await jfetch(api(`/api/clients/${result.id}/attach`), 'POST', { list_id: state.selectedListId });
      }
      imported++;
    } catch (_e) {
      skipped++;
    }
  }

  await loadListClients(state.selectedListId);
  const { loadAllClients } = await import('./clients.js');
  await loadAllClients();
  await refreshPlateLookup();
  renderEventFeed(true);
  showToast(`Импортировано: ${imported}, пропущено: ${skipped}`);
}
