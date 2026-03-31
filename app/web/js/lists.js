let api = null;
let jfetch = null;
let state = null;
let openModal = null;
let closeModal = null;
let showToast = null;
let renderEventFeed = null;
let renderCustomListOptions = null;
let getCurrentChannelCustomListIds = null;

let editingEntryId = null;

export function initListsModule(deps) {
  api = deps.api;
  jfetch = deps.jfetch;
  state = deps.state;
  openModal = deps.openModal;
  closeModal = deps.closeModal;
  showToast = deps.showToast;
  renderEventFeed = deps.renderEventFeed;
  renderCustomListOptions = deps.renderCustomListOptions;
  getCurrentChannelCustomListIds = deps.getCurrentChannelCustomListIds;
}

async function refreshPlateLookup() {
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

function renderLists() {
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

export async function loadLists() {
  state.lists = await jfetch(api("/api/lists"));
  renderLists();
  renderCustomListOptions(getCurrentChannelCustomListIds());
  await refreshPlateLookup();
  renderEventFeed(true);
}

async function loadEntries(listId) {
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

function openEditEntryModal(entry) {
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

function exportCurrentListCSV() {
  if (!state.selectedListId) return;
  const list = state.lists.find((l) => l.id === state.selectedListId);
  const headers = ["Гос. номер", "Имя", "Фамилия", "Отчество", "Телефон", "Марка авто"];
  const lines = [headers.join(",")];
  (state.currentEntries || []).forEach((r) => {
    let info = {};
    try { info = JSON.parse(r.comment || "{}"); } catch (_e) {}
    const cells = [r.plate, info.first_name || "", info.last_name || "", info.patronymic || "", info.phone || "", info.car_make || ""]
      .map((v) => `\"${String(v).replace(/\"/g, '\"\"')}\"`);
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

async function importCurrentListCSV(file) {
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
  showToast(`Импортировано: ${imported}, пропущено: ${skipped}`);
}

export function initListsBindings() {
  document.getElementById("addListBtn").onclick = () => {
    document.getElementById("newListName").value = "";
    openModal("createListModal");
    setTimeout(() => document.getElementById("newListName").focus(), 50);
  };
  document.getElementById("createListModalClose").onclick = () => closeModal("createListModal");
  document.getElementById("createListCancel").onclick = () => closeModal("createListModal");
  document.getElementById("createListConfirm").onclick = async () => {
    const name = document.getElementById("newListName").value.trim();
    if (!name) { document.getElementById("newListName").focus(); return; }
    await jfetch(api("/api/lists"), "POST", { name, type: "white" });
    closeModal("createListModal");
    await loadLists();
  };
  document.getElementById("createListModal").onclick = (e) => {
    if (e.target.id === "createListModal") closeModal("createListModal");
  };
  document.getElementById("newListName").onkeydown = (e) => {
    if (e.key === "Enter") document.getElementById("createListConfirm").click();
  };

  document.getElementById("addEntryBtn").onclick = () => {
    if (!state.selectedListId) return;
    editingEntryId = null;
    document.getElementById("addEntryModalTitle").textContent = "Добавить запись";
    document.getElementById("entryLastName").value = "";
    document.getElementById("entryFirstName").value = "";
    document.getElementById("entryPatronymic").value = "";
    document.getElementById("entryPhone").value = "";
    document.getElementById("entryCarMake").value = "";
    document.getElementById("entryPlate").value = "";
    document.getElementById("addEntryError").textContent = "";
    openModal("addEntryModal");
    setTimeout(() => document.getElementById("entryLastName").focus(), 50);
  };
  document.getElementById("addEntryModalClose").onclick = () => closeModal("addEntryModal");
  document.getElementById("addEntryCancel").onclick = () => closeModal("addEntryModal");
  document.getElementById("addEntryConfirm").onclick = async () => {
    const firstName = document.getElementById("entryFirstName").value.trim();
    const lastName = document.getElementById("entryLastName").value.trim();
    const patronymic = document.getElementById("entryPatronymic").value.trim();
    const phone = document.getElementById("entryPhone").value.trim();
    const carMake = document.getElementById("entryCarMake").value.trim();
    const plate = document.getElementById("entryPlate").value.trim();
    const errEl = document.getElementById("addEntryError");
    if (!firstName || !plate) {
      errEl.textContent = "Поля «Имя» и «Гос. номер автомобиля» обязательны.";
      return;
    }
    errEl.textContent = "";
    const comment = JSON.stringify({
      last_name: lastName,
      first_name: firstName,
      patronymic: patronymic,
      phone: phone,
      car_make: carMake,
    });
    try {
      if (editingEntryId !== null) {
        await jfetch(api(`/api/lists/${state.selectedListId}/entries/${editingEntryId}`), "PUT", { plate, comment });
      } else {
        await jfetch(api(`/api/lists/${state.selectedListId}/entries`), "POST", { plate, comment });
      }
    } catch (_e) {
      errEl.textContent = editingEntryId !== null
        ? "Не удалось обновить: возможно, номер уже существует."
        : "Не удалось сохранить: возможно, номер уже существует.";
      return;
    }
    editingEntryId = null;
    closeModal("addEntryModal");
    await loadEntries(state.selectedListId);
    await refreshPlateLookup();
    renderEventFeed(true);
  };
  document.getElementById("addEntryModal").onclick = (e) => {
    if (e.target.id === "addEntryModal") { editingEntryId = null; closeModal("addEntryModal"); }
  };

  document.getElementById("exportListBtn").onclick = exportCurrentListCSV;

  document.getElementById("importListBtn").onclick = () => {
    if (!state.selectedListId) return;
    const input = document.getElementById("importListFileInput");
    input.value = "";
    input.click();
  };
  document.getElementById("importListFileInput").onchange = (e) => {
    const file = e.target.files[0];
    if (file) importCurrentListCSV(file);
  };

  document.getElementById("listSettingsBtn").onclick = () => {
    if (!state.selectedListId) return;
    const list = state.lists.find((l) => l.id === state.selectedListId);
    if (!list) return;
    document.getElementById("settingsListName").value = list.name;
    document.getElementById("settingsListType").value = list.type || "white";
    openModal("listSettingsModal");
    setTimeout(() => document.getElementById("settingsListName").focus(), 50);
  };
  document.getElementById("listSettingsModalClose").onclick = () => closeModal("listSettingsModal");
  document.getElementById("listSettingsCancel").onclick = () => closeModal("listSettingsModal");
  document.getElementById("listSettingsConfirm").onclick = async () => {
    const name = document.getElementById("settingsListName").value.trim();
    const type = document.getElementById("settingsListType").value;
    if (!name || !state.selectedListId) return;
    await jfetch(api(`/api/lists/${state.selectedListId}`), "PUT", { name, type });
    closeModal("listSettingsModal");
    await loadLists();
  };
  document.getElementById("listSettingsModal").onclick = (e) => {
    if (e.target.id === "listSettingsModal") closeModal("listSettingsModal");
  };

  document.getElementById("deleteListBtn").onclick = () => {
    if (!state.selectedListId) return;
    const list = state.lists.find((l) => l.id === state.selectedListId);
    if (!list) return;
    document.getElementById("deleteListNameLabel").textContent = list.name;
    openModal("deleteListModal");
  };
  document.getElementById("deleteListCancel").onclick = () => closeModal("deleteListModal");
  document.getElementById("deleteListConfirm").onclick = async () => {
    if (!state.selectedListId) return;
    await jfetch(api(`/api/lists/${state.selectedListId}`), "DELETE");
    closeModal("deleteListModal");
    state.selectedListId = null;
    state.currentEntries = [];
    document.getElementById("listTitle").textContent = "—";
    document.getElementById("entriesBody").innerHTML = "";
    await loadLists();
  };
  document.getElementById("deleteListModal").onclick = (e) => {
    if (e.target.id === "deleteListModal") closeModal("deleteListModal");
  };
}
