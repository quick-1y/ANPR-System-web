// Controller CRUD
import { api, jfetch } from './api.js';
import { val, setVal, showToast, openModal, closeModal } from './ui.js';
import { controllersCache, setControllersCache, selectedControllerId, setSelectedControllerId, syncControllerConfigVisibility, updateRelayTimerState, rebuildHotkeyMap } from './channels.js';

function renderChannelControllerOptions(selectedId = "") {
  const select = document.getElementById("c_controller_id");
  if (!select) return;
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
  if (select.value !== current) select.value = "";
}

function setControllerFormDisabled(disabled) {
  ["ctrlName","ctrlType","ctrlAddress","ctrlPassword","ctrlR0Mode","ctrlR0Timer","ctrlR0Hotkey","ctrlR1Mode","ctrlR1Timer","ctrlR1Hotkey","testRelay0Btn","testRelay1Btn","saveControllerBtn"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = !!disabled;
  });
}

function fillControllerForm(c) {
  if (!c) {
    setVal("ctrlName", ""); setVal("ctrlType", "DTWONDER2CH"); setVal("ctrlAddress", ""); setVal("ctrlPassword", "0");
    setVal("ctrlR0Mode", "pulse"); setVal("ctrlR0Timer", 1); setVal("ctrlR0Hotkey", "");
    setVal("ctrlR1Mode", "pulse"); setVal("ctrlR1Timer", 1); setVal("ctrlR1Hotkey", "");
    setControllerFormDisabled(true);
    return;
  }
  setVal("ctrlName", c.name); setVal("ctrlType", c.type); setVal("ctrlAddress", c.address); setVal("ctrlPassword", c.password);
  setVal("ctrlR0Mode", c.relays?.[0]?.mode || "pulse"); setVal("ctrlR0Timer", c.relays?.[0]?.timer_seconds || 1); setVal("ctrlR0Hotkey", c.relays?.[0]?.hotkey || "");
  setVal("ctrlR1Mode", c.relays?.[1]?.mode || "pulse"); setVal("ctrlR1Timer", c.relays?.[1]?.timer_seconds || 1); setVal("ctrlR1Hotkey", c.relays?.[1]?.hotkey || "");
  setControllerFormDisabled(false);
  updateRelayTimerState(0);
  updateRelayTimerState(1);
}

function renderControllerItems() {
  const box = document.getElementById("controllerItems");
  box.innerHTML = "";
  if (!controllersCache.length) {
    box.innerHTML = '<div class="ch-item">Нет контроллеров</div>';
    setControllerFormDisabled(true);
    syncControllerConfigVisibility();
    return;
  }
  controllersCache.forEach((c) => {
    const row = document.createElement("div");
    row.className = `ch-item ${c.id === selectedControllerId ? "active" : ""}`;
    row.innerHTML = `
      <div class="ch-item-main">
        <div class="ch-item-name">${c.name}</div>
        <div class="ch-item-sub">${c.type || "—"} · ${c.address || "—"}</div>
      </div>
      <span class="ch-item-status">2CH</span>
    `;
    row.onclick = () => selectController(c.id);
    box.appendChild(row);
  });
}

export function selectController(id) {
  setSelectedControllerId(id);
  syncControllerConfigVisibility();
  const item = controllersCache.find((c) => c.id === id);
  const title = document.getElementById("controllerConfigTitle");
  if (title) title.textContent = item?.name || `Контроллер ${id}`;
  fillControllerForm(item || null);
  renderControllerItems();
}

export async function loadControllers() {
  setControllersCache(await jfetch(api("/api/controllers")));
  const title = document.getElementById("controllerConfigTitle");
  if (controllersCache.length) {
    if (!selectedControllerId || !controllersCache.some((c) => c.id === selectedControllerId)) {
      setSelectedControllerId(controllersCache[0].id);
    }
    selectController(selectedControllerId);
  } else {
    setSelectedControllerId(null);
    if (title) title.textContent = "—";
    fillControllerForm(null);
    renderControllerItems();
  }
  syncControllerConfigVisibility();
  rebuildHotkeyMap();
  renderChannelControllerOptions(val("c_controller_id"));
  renderControllerItems();
}

function controllerPayload() {
  return {
    name: val("ctrlName"), type: val("ctrlType") || "DTWONDER2CH", address: val("ctrlAddress"), password: val("ctrlPassword") || "0",
    relays: [
      { mode: val("ctrlR0Mode") || "pulse", timer_seconds: val("ctrlR0Mode") === "pulse_timer" ? Math.max(1, Number(val("ctrlR0Timer") || 1)) : 1, hotkey: (val("ctrlR0Hotkey") || "").trim().toUpperCase() },
      { mode: val("ctrlR1Mode") || "pulse", timer_seconds: val("ctrlR1Mode") === "pulse_timer" ? Math.max(1, Number(val("ctrlR1Timer") || 1)) : 1, hotkey: (val("ctrlR1Hotkey") || "").trim().toUpperCase() },
    ],
  };
}

export async function createController() {
  document.getElementById("newControllerName").value = "";
  document.getElementById("newControllerName").placeholder = "Введите название";
  openModal("createControllerModal");
  setTimeout(() => document.getElementById("newControllerName").focus(), 50);
}

export async function _doCreateController(name) {
  const body = controllerPayload();
  body.name = name || "Контроллер";
  try {
    await jfetch(api("/api/controllers"), "POST", body);
    await loadControllers();
    if (controllersCache.length) {
      setSelectedControllerId(controllersCache[controllersCache.length - 1].id);
      selectController(selectedControllerId);
    }
  } catch (err) { alert(`Не удалось создать контроллер: ${err.message}`); }
}

export async function deleteController() {
  if (!selectedControllerId) return;
  const ctrl = controllersCache.find((c) => c.id === selectedControllerId);
  document.getElementById("deleteControllerNameLabel").textContent = ctrl ? ctrl.name : `#${selectedControllerId}`;
  openModal("deleteControllerModal");
}

export async function _doDeleteController() {
  try { await jfetch(api(`/api/controllers/${selectedControllerId}`), "DELETE"); await loadControllers(); }
  catch (err) { alert(err.message); }
}

export async function saveController() {
  if (!selectedControllerId) return;
  try {
    await jfetch(api(`/api/controllers/${selectedControllerId}`), "PUT", controllerPayload());
    await loadControllers();
    showToast("Настройки сохранены");
  } catch (err) { alert(`Не удалось сохранить контроллер: ${err.message}`); }
}

export async function testController(relay) {
  if (!selectedControllerId) return;
  await jfetch(api(`/api/controllers/${selectedControllerId}/test`), "POST", { relay_index: relay, is_on: true });
}
