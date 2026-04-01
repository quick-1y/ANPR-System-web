// Plate lists management, CSV import/export
import { state } from './state.js';
import { api, jfetch } from './api.js';
import { showToast, normalizePlate, openModal } from './ui.js';
import { renderCustomListOptions } from './channels.js';
import { renderEventFeed } from './events.js';

let editingEntryId = null;
let currentChannelCustomListIds_ref = [];

export function setCurrentChannelCustomListIds(v) { currentChannelCustomListIds_ref = v; }

export async function refreshPlateLookup() {
  try {
    const plates = await jfetch(api("/api/lists/plates"));
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

export async function loadLists() {
  state.lists = await jfetch(api("/api/lists"));
  renderLists();
  renderCustomListOptions(currentChannelCustomListIds_ref);
  await refreshPlateLookup();
  renderEventFeed(true);
}

function syncListMainVisibility() {
  const hasSelection = !!state.selectedListId && state.lists.length > 0;
  const header = document.getElementById("listsMainHeader");
  const dataWrap = document.getElementById("listsDataWrap");
  const emptyState = document.getElementById("listsEmptyState");
  if (header) header.style.display = hasSelection ? "" : "none";
  if (dataWrap) dataWrap.style.display = hasSelection ? "" : "none";
  if (emptyState) emptyState.style.display = hasSelection ? "none" : "";
}

function listTypeDot(type) {
  if (type === "black") return "dot-black";
  if (type === "info") return "dot-info";
  return "dot-white";
}

export function renderLists() {
  const items = document.getElementById("listItems");
  items.innerHTML = "";
  state.lists.forEach((l, idx) => {
    const isActive = l.id === state.selectedListId || (!state.selectedListId && idx === 0);
    if (!state.selectedListId && idx === 0) state.selectedListId = l.id;
    const div = document.createElement("div");
    div.className = `list-item type-${l.type}${isActive ? " active" : ""}`;
    div.innerHTML = `<div class='list-item-dot ${listTypeDot(l.type)}'></div><div class='list-item-name'>${l.name}</div><div class='list-item-count'>${l.entries_count ?? "…"}</div>`;
    div.onclick = () => {
      state.selectedListId = l.id;
      renderLists();
      loadEntries(l.id);
    };
    items.appendChild(div);
  });
  syncListMainVisibility();
  if (state.selectedListId) loadEntries(state.selectedListId);
}

export async function loadEntries(listId) {
  const rows = await jfetch(api(`/api/lists/${listId}/entries`));
  state.currentEntries = rows;
  const list = state.lists.find((x) => x.id === listId);
  document.getElementById("listTitle").textContent = list ? list.name : "—";
  const body = document.getElementById("entriesBody");
  body.innerHTML = "";
  rows.forEach((r) => {
    let info = {};
    try { info = JSON.parse(r.comment || "{}"); } catch (_e) {}
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class='plate-cell'>${r.plate}</td><td>${info.first_name || ""}</td><td>${info.last_name || ""}</td><td>${info.patronymic || ""}</td><td>${info.phone || ""}</td><td>${info.car_make || ""}</td><td class="col-actions"><button class="entry-edit-btn">Изменить</button></td>`;
    tr.querySelector(".entry-edit-btn").onclick = () => openEditEntryModal(r);
    body.appendChild(tr);
  });
}

export function openEditEntryModal(entry) {
  editingEntryId = entry.id;
  let info = {};
  try { info = JSON.parse(entry.comment || "{}"); } catch (_e) {}
  document.getElementById("addEntryModalTitle").textContent = "Изменить запись";
  document.getElementById("entryLastName").value = info.last_name || "";
  document.getElementById("entryFirstName").value = info.first_name || "";
  document.getElementById("entryPatronymic").value = info.patronymic || "";
  document.getElementById("entryPhone").value = info.phone || "";
  document.getElementById("entryCarMake").value = info.car_make || "";
  document.getElementById("entryPlate").value = entry.plate || "";
  document.getElementById("addEntryError").textContent = "";
  openModal("addEntryModal");
  setTimeout(() => document.getElementById("entryLastName").focus(), 50);
}

export function exportCurrentListCSV() {
  if (!state.selectedListId) return;
  const list = state.lists.find((l) => l.id === state.selectedListId);
  const headers = ["Гос. номер", "Имя", "Фамилия", "Отчество", "Телефон", "Марка авто"];
  const lines = [headers.join(",")];
  (state.currentEntries || []).forEach((r) => {
    let info = {};
    try { info = JSON.parse(r.comment || "{}"); } catch (_e) {}
    const cells = [r.plate, info.first_name || "", info.last_name || "", info.patronymic || "", info.phone || "", info.car_make || ""]
      .map((v) => `"${String(v).replace(/"/g, '""')}"`);
    lines.push(cells.join(","));
  });
  const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${list ? list.name : "list"}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function parseCSVLine(line) {
  const cells = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"' && line[i + 1] === '"') { current += '"'; i++; }
      else if (ch === '"') { inQuotes = false; }
      else { current += ch; }
    } else {
      if (ch === '"') { inQuotes = true; }
      else if (ch === ',') { cells.push(current); current = ""; }
      else { current += ch; }
    }
  }
  cells.push(current);
  return cells.map((c) => c.trim());
}

export async function importCurrentListCSV(file) {
  if (!state.selectedListId || !file) return;
  const EXPECTED_HEADERS = ["Гос. номер", "Имя", "Фамилия", "Отчество", "Телефон", "Марка авто"];
  const text = await file.text();
  const rawLines = text.replace(/^\uFEFF/, "").split(/\r?\n/);
  const lines = rawLines.filter((l) => l.trim().length > 0);
  if (lines.length < 1) { showToast("Файл пуст", 3000); return; }

  const headerCells = parseCSVLine(lines[0]);
  const headersMatch = EXPECTED_HEADERS.every((h, i) => (headerCells[i] || "").trim() === h);
  if (!headersMatch) {
    showToast("Неверный формат списка", 3000);
    return;
  }

  const dataLines = lines.slice(1);
  if (dataLines.length === 0) { showToast("Нет записей для импорта", 3000); return; }

  let imported = 0;
  let skipped = 0;
  for (const line of dataLines) {
    const cells = parseCSVLine(line);
    const plate = (cells[0] || "").trim();
    if (!plate) { skipped++; continue; }
    const comment = JSON.stringify({
      first_name: (cells[1] || "").trim(),
      last_name: (cells[2] || "").trim(),
      patronymic: (cells[3] || "").trim(),
      phone: (cells[4] || "").trim(),
      car_make: (cells[5] || "").trim(),
    });
    try {
      await jfetch(api(`/api/lists/${state.selectedListId}/entries`), "POST", { plate, comment });
      imported++;
    } catch (_e) {
      skipped++;
    }
  }

  await loadEntries(state.selectedListId);
  await refreshPlateLookup();
  renderEventFeed(true);
  showToast(`Импортировано: ${imported}, про��ущено: ${skipped}`);
}

// Expose for DOM bindings
export function getEditingEntryId() { return editingEntryId; }
export function setEditingEntryId(v) { editingEntryId = v; }
