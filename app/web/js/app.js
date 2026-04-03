// Application entry point — initialization, DOM bindings, timers
import { eventSource, debugLogSource, overlayRefreshTimer, eventFeedRenderFrame, eventFeedRenderScheduled, setEventFeedRenderScheduled, setEventFeedRenderFrame } from './state.js';
import { api, getToken, setToken, getCurrentUser, showLoginOverlay } from './api.js';
import { switchTab, switchSettings, updateTopbarTitle, updateTopbarDateTime, applyTheme, val, setVal, openModal, closeModal, applySidebarLocked, initSidebarHover, loadBarColor, applyTabVisibility } from './ui.js';
import { refreshChannels, renderVideoGrid, scheduleVideoGridLayout, setupVideoGridLayoutGuards, setupVisionCanvas, setupPlateSizeInputListeners, switchChannelSettingsTab, syncChannelConfigVisibility, syncControllerConfigVisibility, fillChannelFilter, syncOverlayPolling, refreshOverlayStates, hotkeyMap, hotkeyFromEvent, isEditingTarget, triggerHotkey, updateRelayTimerState, updateChannelControllerBindingState, updateCustomListsVisibility, selectedChannelId, refreshPreviewSnapshot, defaultROIPointsForCanvas, drawPreview, renderROIPointsList, roiPoints, resetPlateSizeBoxes, resetROIPoints, saveChannel, createChannel, _doCreateChannel, deleteChannel, _doDeleteChannel, defaultPlateSizeOverlay, updateChannelLastPlate } from './channels.js';
import { renderEventFeed, scheduleEventFeedRender, setupEventFeedLayoutGuards, hydrateChannelLastPlates, loadEventFeedHistory, closeEventModal, pushEvent } from './events.js';
import { loadJournal, initJournalScroll } from './journal.js';
import { loadLists, loadEntries, refreshPlateLookup, exportCurrentListCSV, importCurrentListCSV, getEditingEntryId, setEditingEntryId, getDeletingEntryId, setDeletingEntryId } from './lists.js';
import { loadGlobalSettings, saveGeneral } from './settings.js';
import { loadControllers, createController, _doCreateController, deleteController, _doDeleteController, saveController, testController } from './controllers.js';
import { applyDebugPanelVisibility, loadDebugLogHistory, setupDebugLogStream, setupStream } from './debug.js';
import { initHelpSystem } from './help.js';
import { initBackupBindings } from './backup.js';
import { state, setCurrentUser } from './state.js';

// --- System monitoring ---
async function refreshSystemResources() {
  if (document.hidden) return;
  try {
    const resources = await (await fetch(api("/api/system/resources"), { headers: (() => { const h = { "Content-Type": "application/json" }; const t = getToken(); if (t) h["Authorization"] = `Bearer ${t}`; return h; })() })).json();
    const cpu = Math.round(Number(resources.cpu_percent) || 0);
    const ram = Math.round(Number(resources.ram_percent) || 0);
    const cpuStat = document.getElementById("cpuStat");
    const ramStat = document.getElementById("ramStat");
    const cpuBar = document.getElementById("cpuBar");
    const ramBar = document.getElementById("ramBar");
    if (cpuStat) cpuStat.textContent = `${cpu}%`;
    if (ramStat) ramStat.textContent = `${ram}%`;
    if (cpuBar) { cpuBar.style.width = `${cpu}%`; cpuBar.style.background = loadBarColor(cpu); }
    if (ramBar) { ramBar.style.width = `${ram}%`; ramBar.style.background = loadBarColor(ram); }
  } catch (_e) {}
}

async function checkServerHealth() {
  if (document.hidden) return;
  const dot = document.getElementById("serverDot");
  if (!dot) return;
  try {
    const t = getToken();
    const headers = t ? { "Authorization": `Bearer ${t}` } : {};
    const r = await fetch(api("/api/health"), { method: "GET", headers, signal: AbortSignal.timeout(4000) });
    dot.className = r.ok ? "server-dot live" : "server-dot off";
  } catch (_e) { dot.className = "server-dot off"; }
}

// --- Tab navigation bindings ---
document.querySelectorAll(".ttab").forEach((el) => (el.onclick = () => {
  switchTab(el.dataset.tab);
  if (el.dataset.tab === "obs") { scheduleVideoGridLayout(); renderEventFeed(true); }
}));
document.querySelectorAll(".snav-item").forEach((el) => (el.onclick = () => switchSettings(el.dataset.sp)));
document.querySelectorAll(".ch-tab").forEach((el) => (el.onclick = () => switchChannelSettingsTab(el.dataset.chTab)));
document.getElementById("gridSelect").onchange = () => scheduleVideoGridLayout(true);

// --- Journal bindings ---
document.getElementById("btnFind").onclick = loadJournal;
document.getElementById("btnReset").onclick = () => {
  document.getElementById("fltPlate").value = "";
  document.getElementById("fltChannel").value = "";
  document.getElementById("fltDateFrom").value = "";
  document.getElementById("fltDateTo").value = "";
  loadJournal();
};
document.getElementById("btnExport").onclick = () => {
  const params = new URLSearchParams();
  const plate = (document.getElementById("fltPlate").value || "").trim();
  const channelId = document.getElementById("fltChannel").value;
  const dateFrom = document.getElementById("fltDateFrom").value;
  const dateTo = document.getElementById("fltDateTo").value;
  if (plate) params.set("plate", plate);
  if (channelId) params.set("channel_id", channelId);
  if (dateFrom) params.set("start", new Date(dateFrom).toISOString());
  if (dateTo) params.set("end", new Date(dateTo).toISOString());
  const qs = params.toString();
  window.open(api(`/api/data/export/events.csv${qs ? "?" + qs : ""}`), "_blank");
};

// --- List modals ---
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
  const { jfetch } = await import('./api.js');
  await jfetch(api("/api/lists"), "POST", { name, type: "white" });
  closeModal("createListModal");
  await loadLists();
};
document.getElementById("createListModal").onclick = (e) => { if (e.target.id === "createListModal") closeModal("createListModal"); };
document.getElementById("newListName").onkeydown = (e) => { if (e.key === "Enter") document.getElementById("createListConfirm").click(); };

// --- Entry modals ---
document.getElementById("addEntryBtn").onclick = () => {
  if (!state.selectedListId) return;
  setEditingEntryId(null);
  document.getElementById("addEntryModalTitle").textContent = "Добавить запись";
  ["entryLastName","entryFirstName","entryMiddleName","entryPhone","entryCar","entryPlate","entryComment"].forEach(id => document.getElementById(id).value = "");
  document.getElementById("addEntryError").textContent = "";
  openModal("addEntryModal");
  setTimeout(() => document.getElementById("entryLastName").focus(), 50);
};
document.getElementById("addEntryModalClose").onclick = () => closeModal("addEntryModal");
document.getElementById("addEntryCancel").onclick = () => closeModal("addEntryModal");
document.getElementById("addEntryConfirm").onclick = async () => {
  const firstName = document.getElementById("entryFirstName").value.trim();
  const plate = document.getElementById("entryPlate").value.trim();
  const errEl = document.getElementById("addEntryError");
  if (!firstName || !plate) { errEl.textContent = "Поля «Имя» и «Гос. номер автомобиля» обязательны."; return; }
  errEl.textContent = "";
  const payload = {
    plate,
    last_name: document.getElementById("entryLastName").value.trim(),
    first_name: firstName,
    middle_name: document.getElementById("entryMiddleName").value.trim(),
    phone: document.getElementById("entryPhone").value.trim(),
    car: document.getElementById("entryCar").value.trim(),
    comment: document.getElementById("entryComment").value.trim(),
  };
  const { jfetch } = await import('./api.js');
  const editingEntryId = getEditingEntryId();
  try {
    if (editingEntryId !== null) await jfetch(api(`/api/lists/${state.selectedListId}/entries/${editingEntryId}`), "PUT", payload);
    else await jfetch(api(`/api/lists/${state.selectedListId}/entries`), "POST", payload);
  } catch (_e) {
    errEl.textContent = editingEntryId !== null ? "Не удалось обновить: возможно, номер уже существует." : "Не удалось сохранить: возможно, номер уже существует.";
    return;
  }
  setEditingEntryId(null);
  closeModal("addEntryModal");
  await loadEntries(state.selectedListId);
  await refreshPlateLookup();
  renderEventFeed(true);
};
document.getElementById("addEntryModal").onclick = (e) => { if (e.target.id === "addEntryModal") { setEditingEntryId(null); closeModal("addEntryModal"); } };

// --- Delete entry ---
document.getElementById("deleteEntryCancel").onclick = () => { setDeletingEntryId(null); closeModal("deleteEntryModal"); };
document.getElementById("deleteEntryConfirm").onclick = async () => {
  const entryId = getDeletingEntryId();
  if (!entryId || !state.selectedListId) return;
  const { jfetch } = await import('./api.js');
  await jfetch(api(`/api/lists/${state.selectedListId}/entries/${entryId}`), "DELETE");
  setDeletingEntryId(null);
  closeModal("deleteEntryModal");
  await loadLists();
};
document.getElementById("deleteEntryModal").onclick = (e) => { if (e.target.id === "deleteEntryModal") { setDeletingEntryId(null); closeModal("deleteEntryModal"); } };

// --- Export/Import ---
document.getElementById("exportListBtn").onclick = exportCurrentListCSV;
document.getElementById("importListBtn").onclick = () => { if (!state.selectedListId) return; const input = document.getElementById("importListFileInput"); input.value = ""; input.click(); };
document.getElementById("importListFileInput").onchange = (e) => { const file = e.target.files[0]; if (file) importCurrentListCSV(file); };

// --- List settings modal ---
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
  const { jfetch } = await import('./api.js');
  await jfetch(api(`/api/lists/${state.selectedListId}`), "PUT", { name, type });
  closeModal("listSettingsModal");
  await loadLists();
};
document.getElementById("listSettingsModal").onclick = (e) => { if (e.target.id === "listSettingsModal") closeModal("listSettingsModal"); };

// --- Delete list ---
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
  const { jfetch } = await import('./api.js');
  await jfetch(api(`/api/lists/${state.selectedListId}`), "DELETE");
  closeModal("deleteListModal");
  state.selectedListId = null; state.currentEntries = [];
  document.getElementById("listTitle").textContent = "—";
  document.getElementById("entriesBody").innerHTML = "";
  await loadLists();
};
document.getElementById("deleteListModal").onclick = (e) => { if (e.target.id === "deleteListModal") closeModal("deleteListModal"); };

// --- Event modal ---
document.getElementById("eventModalClose").onclick = closeEventModal;
document.getElementById("eventModal").onclick = (e) => { if (e.target.id === "eventModal") closeEventModal(); };

// --- Settings buttons ---
document.getElementById("saveGeneralBtn").onclick = saveGeneral;
document.getElementById("saveChannelBtn").onclick = saveChannel;
document.getElementById("deleteChannelBtn").onclick = deleteChannel;
document.getElementById("createChannelBtn").onclick = createChannel;
document.getElementById("createControllerBtn").onclick = createController;
document.getElementById("saveControllerBtn").onclick = saveController;
document.getElementById("deleteControllerBtn").onclick = deleteController;

// --- Create/Delete Channel modals ---
document.getElementById("createChannelModalClose").onclick = () => closeModal("createChannelModal");
document.getElementById("createChannelCancel").onclick = () => closeModal("createChannelModal");
document.getElementById("createChannelModal").onclick = (e) => { if (e.target.id === "createChannelModal") closeModal("createChannelModal"); };
document.getElementById("newChannelName").onkeydown = (e) => { if (e.key === "Enter") document.getElementById("createChannelConfirm").click(); };
document.getElementById("createChannelConfirm").onclick = async () => { const name = document.getElementById("newChannelName").value.trim() || "Канал"; closeModal("createChannelModal"); await _doCreateChannel(name); };
document.getElementById("deleteChannelCancel").onclick = () => closeModal("deleteChannelModal");
document.getElementById("deleteChannelModal").onclick = (e) => { if (e.target.id === "deleteChannelModal") closeModal("deleteChannelModal"); };
document.getElementById("deleteChannelConfirm").onclick = async () => { closeModal("deleteChannelModal"); await _doDeleteChannel(); };

// --- Create/Delete Controller modals ---
document.getElementById("createControllerModalClose").onclick = () => closeModal("createControllerModal");
document.getElementById("createControllerCancel").onclick = () => closeModal("createControllerModal");
document.getElementById("createControllerModal").onclick = (e) => { if (e.target.id === "createControllerModal") closeModal("createControllerModal"); };
document.getElementById("newControllerName").onkeydown = (e) => { if (e.key === "Enter") document.getElementById("createControllerConfirm").click(); };
document.getElementById("createControllerConfirm").onclick = async () => { const name = document.getElementById("newControllerName").value.trim() || "Контроллер"; closeModal("createControllerModal"); await _doCreateController(name); };
document.getElementById("deleteControllerCancel").onclick = () => closeModal("deleteControllerModal");
document.getElementById("deleteControllerModal").onclick = (e) => { if (e.target.id === "deleteControllerModal") closeModal("deleteControllerModal"); };
document.getElementById("deleteControllerConfirm").onclick = async () => { closeModal("deleteControllerModal"); await _doDeleteController(); };

// --- Controller relay/theme/misc bindings ---
document.getElementById("testRelay0Btn").onclick = () => testController(0);
document.getElementById("testRelay1Btn").onclick = () => testController(1);
document.getElementById("ctrlR0Mode").onchange = () => updateRelayTimerState(0);
document.getElementById("ctrlR1Mode").onchange = () => updateRelayTimerState(1);
document.getElementById("c_controller_id").onchange = updateChannelControllerBindingState;
document.getElementById("c_list_filter_mode").onchange = updateCustomListsVisibility;
document.getElementById("saveDebugBtn").onclick = saveGeneral;
document.getElementById("g_theme").onchange = () => applyTheme(val("g_theme"));
document.getElementById("g_sidebar_locked").onchange = () => applySidebarLocked(document.getElementById("g_sidebar_locked").checked);
document.getElementById("themeToggleBtn").onclick = () => { const nextTheme = val("g_theme") === "light" ? "dark" : "light"; setVal("g_theme", nextTheme); applyTheme(nextTheme); };
document.getElementById("plateSizeResetBtn").onclick = resetPlateSizeBoxes;
document.getElementById("roiRefreshBtn").onclick = refreshPreviewSnapshot;
document.getElementById("roiClearBtn").onclick = resetROIPoints;

// --- Debug panel toggle ---
const toggleDebugPanelBtn = document.getElementById("toggleDebugPanelBtn");
if (toggleDebugPanelBtn) {
  toggleDebugPanelBtn.onclick = () => {
    const panel = document.getElementById("obsDebugPanel");
    if (!panel) return;
    const collapsed = panel.dataset.collapsed === "1";
    panel.dataset.collapsed = collapsed ? "0" : "1";
    toggleDebugPanelBtn.textContent = collapsed ? "Свернуть" : "Развернуть";
    scheduleVideoGridLayout(true);
  };
}

// --- Global hotkey handler ---
document.addEventListener("keydown", (event) => {
  if (event.repeat || isEditingTarget(event.target)) return;
  const hotkey = hotkeyFromEvent(event);
  if (!hotkey || !hotkeyMap.has(hotkey)) return;
  event.preventDefault();
  triggerHotkey(hotkey);
});

// --- Timers ---
updateTopbarDateTime();
setInterval(updateTopbarDateTime, 1000);
refreshSystemResources();
setInterval(refreshSystemResources, 10000);
checkServerHealth();
setInterval(checkServerHealth, 10000);

// --- Cleanup ---
function cleanupStreamsAndTimers() {
  if (eventSource) { try { eventSource.close(); } catch (_e) {} }
  if (debugLogSource) { try { debugLogSource.close(); } catch (_e) {} }
  if (overlayRefreshTimer) clearInterval(overlayRefreshTimer);
  if (eventFeedRenderFrame !== null) { cancelAnimationFrame(eventFeedRenderFrame); setEventFeedRenderFrame(null); setEventFeedRenderScheduled(false); }
}
window.addEventListener("beforeunload", cleanupStreamsAndTimers);
window.addEventListener("pagehide", cleanupStreamsAndTimers);
window.addEventListener("resize", () => scheduleEventFeedRender(true));

// --- Sidebar ---
initSidebarHover();

// --- Help & Backup ---
initHelpSystem();
initBackupBindings();

// --- Main init ---
(async function init() {
  const apiBaseEl = document.getElementById("apiBase");
  if (apiBaseEl) apiBaseEl.value = window.location.origin;
  try { applyTheme(localStorage.getItem("anpr_theme") || "dark"); }
  catch (_e) { applyTheme("dark"); }

  // --- Auth check ---
  const token = getToken();
  if (!token) {
    showLoginOverlay((user) => { setCurrentUser(user); _applyUserUI(user); location.reload(); });
    return;
  }
  let currentUser;
  try {
    currentUser = await getCurrentUser();
    setCurrentUser(currentUser);
  } catch (_e) {
    // Token expired or invalid — clear it and re-authenticate
    setToken(null);
    showLoginOverlay((user) => { setCurrentUser(user); _applyUserUI(user); location.reload(); });
    return;
  }
  _applyUserUI(currentUser);
  applyTabVisibility(currentUser.permissions || [], currentUser.role === "admin");

  // --- Logout button ---
  const logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) logoutBtn.onclick = () => { setToken(null); location.reload(); };

  syncChannelConfigVisibility();
  syncControllerConfigVisibility();
  setupVideoGridLayoutGuards(() => {
    refreshChannels();
    refreshSystemResources();
    checkServerHealth();
  });
  setupEventFeedLayoutGuards();
  setupVisionCanvas();
  setupPlateSizeInputListeners();
  switchChannelSettingsTab("channel");
  updateTopbarTitle();
  await refreshChannels();
  await hydrateChannelLastPlates();
  initJournalScroll();
  await loadEventFeedHistory();
  await loadLists();
  await loadJournal();
  await loadGlobalSettings();
  await refreshOverlayStates();
  await loadDebugLogHistory();
  setupDebugLogStream();
  await loadControllers();
  setupStream();
  setInterval(refreshChannels, 8000);
  syncOverlayPolling();
})();

function _applyUserUI(user) {
  if (!user) return;
  const pill = document.getElementById("topbarUserPill");
  const loginEl = document.getElementById("topbarUserLogin");
  if (loginEl) loginEl.textContent = user.login || "";
  if (pill) pill.style.display = "inline-flex";
}
