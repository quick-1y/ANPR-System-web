let api = null;
let jfetch = null;
let val = null;
let setVal = null;
let showToast = null;
let openModal = null;
let closeModal = null;
let syncControllerConfigVisibility = null;

let controllersCache = [];
let selectedControllerId = null;
const hotkeyMap = new Map();

export function initControllersModule(deps) {
  api = deps.api;
  jfetch = deps.jfetch;
  val = deps.val;
  setVal = deps.setVal;
  showToast = deps.showToast;
  openModal = deps.openModal;
  closeModal = deps.closeModal;
  syncControllerConfigVisibility = deps.syncControllerConfigVisibility;
}

export function hasSelectedController() {
  return Boolean(selectedControllerId);
}

export function hasHotkeyBinding(hotkey) {
  return hotkeyMap.has(hotkey);
}

export function updateChannelControllerBindingState() {
  const hasController = Boolean(val("c_controller_id"));
  const relayEl = document.getElementById("c_controller_relay");
  relayEl.disabled = !hasController;
  if (!hasController) {
    setVal("c_controller_relay", 0);
  }
}

export function renderChannelControllerOptions(selectedId = "") {
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

function rebuildHotkeyMap() {
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
  duplicates.forEach((_hotkey) => {
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
  } catch (_err) {
  }
}

function setControllerFormDisabled(disabled) {
  [
    "ctrlName",
    "ctrlType",
    "ctrlAddress",
    "ctrlPassword",
    "ctrlR0Mode",
    "ctrlR0Timer",
    "ctrlR0Hotkey",
    "ctrlR1Mode",
    "ctrlR1Timer",
    "ctrlR1Hotkey",
    "testRelay0Btn",
    "testRelay1Btn",
    "saveControllerBtn",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = !!disabled;
  });
}

function updateRelayTimerState(relayIndex) {
  const modeEl = document.getElementById(`ctrlR${relayIndex}Mode`);
  const timerEl = document.getElementById(`ctrlR${relayIndex}Timer`);
  if (!modeEl || !timerEl) return;
  const isPulseTimer = modeEl.value === "pulse_timer";
  timerEl.disabled = !isPulseTimer;
  if (!isPulseTimer) {
    timerEl.value = "1";
  }
}

function fillControllerForm(c) {
  if (!c) {
    setVal("ctrlName", "");
    setVal("ctrlType", "DTWONDER2CH");
    setVal("ctrlAddress", "");
    setVal("ctrlPassword", "0");
    setVal("ctrlR0Mode", "pulse");
    setVal("ctrlR0Timer", 1);
    setVal("ctrlR0Hotkey", "");
    setVal("ctrlR1Mode", "pulse");
    setVal("ctrlR1Timer", 1);
    setVal("ctrlR1Hotkey", "");
    setControllerFormDisabled(true);
    return;
  }
  setVal("ctrlName", c.name);
  setVal("ctrlType", c.type);
  setVal("ctrlAddress", c.address);
  setVal("ctrlPassword", c.password);
  setVal("ctrlR0Mode", c.relays?.[0]?.mode || "pulse");
  setVal("ctrlR0Timer", c.relays?.[0]?.timer_seconds || 1);
  setVal("ctrlR0Hotkey", c.relays?.[0]?.hotkey || "");
  setVal("ctrlR1Mode", c.relays?.[1]?.mode || "pulse");
  setVal("ctrlR1Timer", c.relays?.[1]?.timer_seconds || 1);
  setVal("ctrlR1Hotkey", c.relays?.[1]?.hotkey || "");
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
    row.textContent = c.name;
    row.onclick = () => selectController(c.id);
    box.appendChild(row);
  });
}

function selectController(id) {
  selectedControllerId = id;
  syncControllerConfigVisibility();
  const item = controllersCache.find((c) => c.id === id);
  fillControllerForm(item || null);
  renderControllerItems();
}

export async function loadControllers() {
  controllersCache = await jfetch(api("/api/controllers"));
  if (controllersCache.length) {
    if (
      !selectedControllerId ||
      !controllersCache.some((c) => c.id === selectedControllerId)
    ) {
      selectedControllerId = controllersCache[0].id;
    }
    selectController(selectedControllerId);
  } else {
    selectedControllerId = null;
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
    name: val("ctrlName"),
    type: val("ctrlType") || "DTWONDER2CH",
    address: val("ctrlAddress"),
    password: val("ctrlPassword") || "0",
    relays: [
      {
        mode: val("ctrlR0Mode") || "pulse",
        timer_seconds: val("ctrlR0Mode") === "pulse_timer" ? Math.max(1, Number(val("ctrlR0Timer") || 1)) : 1,
        hotkey: (val("ctrlR0Hotkey") || "").trim().toUpperCase(),
      },
      {
        mode: val("ctrlR1Mode") || "pulse",
        timer_seconds: val("ctrlR1Mode") === "pulse_timer" ? Math.max(1, Number(val("ctrlR1Timer") || 1)) : 1,
        hotkey: (val("ctrlR1Hotkey") || "").trim().toUpperCase(),
      },
    ],
  };
}

async function createController() {
  document.getElementById("newControllerName").value = "";
  document.getElementById("newControllerName").placeholder = "Введите название";
  openModal("createControllerModal");
  setTimeout(() => document.getElementById("newControllerName").focus(), 50);
}

async function _doCreateController(name) {
  const body = controllerPayload();
  body.name = name || "Контроллер";
  try {
    await jfetch(api("/api/controllers"), "POST", body);
    await loadControllers();
    if (controllersCache.length) {
      selectedControllerId = controllersCache[controllersCache.length - 1].id;
      selectController(selectedControllerId);
    }
  } catch (err) {
    alert(`Не удалось создать контроллер: ${err.message}`);
  }
}

async function deleteController() {
  if (!selectedControllerId) return;
  const ctrl = controllersCache.find((c) => c.id === selectedControllerId);
  const label = ctrl ? ctrl.name : `#${selectedControllerId}`;
  document.getElementById("deleteControllerNameLabel").textContent = label;
  openModal("deleteControllerModal");
}

async function _doDeleteController() {
  try {
    await jfetch(api(`/api/controllers/${selectedControllerId}`), "DELETE");
    await loadControllers();
  } catch (err) {
    alert(err.message);
  }
}

async function saveController() {
  if (!selectedControllerId) return;
  try {
    await jfetch(
      api(`/api/controllers/${selectedControllerId}`),
      "PUT",
      controllerPayload(),
    );
    await loadControllers();
    showToast("Настройки сохранены");
  } catch (err) {
    alert(`Не удалось сохранить контроллер: ${err.message}`);
  }
}

async function testController(relay) {
  if (!selectedControllerId) return;
  await jfetch(api(`/api/controllers/${selectedControllerId}/test`), "POST", {
    relay_index: relay,
    is_on: true,
  });
}

export function initControllersBindings() {
  document.getElementById("createControllerBtn").onclick = createController;
  document.getElementById("saveControllerBtn").onclick = saveController;
  document.getElementById("deleteControllerBtn").onclick = deleteController;

  document.getElementById("createControllerModalClose").onclick = () => closeModal("createControllerModal");
  document.getElementById("createControllerCancel").onclick = () => closeModal("createControllerModal");
  document.getElementById("createControllerModal").onclick = (e) => {
    if (e.target.id === "createControllerModal") closeModal("createControllerModal");
  };
  document.getElementById("newControllerName").onkeydown = (e) => {
    if (e.key === "Enter") document.getElementById("createControllerConfirm").click();
  };
  document.getElementById("createControllerConfirm").onclick = async () => {
    const name = document.getElementById("newControllerName").value.trim() || "Контроллер";
    closeModal("createControllerModal");
    await _doCreateController(name);
  };

  document.getElementById("deleteControllerCancel").onclick = () => closeModal("deleteControllerModal");
  document.getElementById("deleteControllerModal").onclick = (e) => {
    if (e.target.id === "deleteControllerModal") closeModal("deleteControllerModal");
  };
  document.getElementById("deleteControllerConfirm").onclick = async () => {
    closeModal("deleteControllerModal");
    await _doDeleteController();
  };
  document.getElementById("testRelay0Btn").onclick = () => testController(0);
  document.getElementById("testRelay1Btn").onclick = () => testController(1);
  document.getElementById("ctrlR0Mode").onchange = () => updateRelayTimerState(0);
  document.getElementById("ctrlR1Mode").onchange = () => updateRelayTimerState(1);
  document.getElementById("c_controller_id").onchange = updateChannelControllerBindingState;
}
