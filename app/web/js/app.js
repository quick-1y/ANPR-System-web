// Application entry point — initialization, DOM bindings, timers
import { eventSource, debugLogSource, overlayRefreshTimer, eventFeedRenderFrame, eventFeedRenderScheduled, setEventFeedRenderScheduled, setEventFeedRenderFrame } from './state.js';
import { api, getToken, setToken, isTokenExpired, getCurrentUser, showLoginOverlay, logoutRequest } from './api.js';
import { switchTab, switchSettings, updateTopbarTitle, updateTopbarDateTime, applyTheme, val, setVal, openModal, closeModal, applySidebarLocked, initSidebarHover, applyTabVisibility, showToast } from './ui.js';
import { refreshChannels, renderVideoGrid, scheduleVideoGridLayout, setupVideoGridLayoutGuards, setupVideoGridDragDrop, setupVisionCanvas, setupPlateSizeInputListeners, switchChannelSettingsTab, syncChannelConfigVisibility, syncControllerConfigVisibility, fillChannelFilter, syncOverlayPolling, refreshOverlayStates, hotkeyMap, hotkeyFromEvent, isEditingTarget, triggerHotkey, updateRelayTimerState, updateChannelControllerBindingState, updateCustomListsVisibility, selectedChannelId, refreshPreviewSnapshot, defaultROIPointsForCanvas, drawPreview, renderROIPointsList, roiPoints, resetPlateSizeBoxes, resetROIPoints, saveChannel, createChannel, _doCreateChannel, deleteChannel, _doDeleteChannel, defaultPlateSizeOverlay, updateChannelLastPlate, clearExpandMode, updateZoneChannelTypeState } from './channels.js';
import { renderEventFeed, scheduleEventFeedRender, setupEventFeedLayoutGuards, hydrateChannelLastPlates, loadEventFeedHistory, closeEventModal, pushEvent } from './events.js';
import { loadJournal, initJournalScroll, initJournalBindings } from './journal.js';
import { loadLists, refreshPlateLookup, exportCurrentListCSV, importCurrentListCSV, openClientPickerModal } from './lists.js';
import { loadAllClients, openAddClientModal, searchClients, saveClientChanges, openDeleteClientConfirm, confirmDeleteClient, openListPickerModal, detachClientFromList, confirmDetachClient } from './clients.js';
import { loadGlobalSettings, saveGeneral } from './settings.js';
import { loadControllers, createController, _doCreateController, deleteController, _doDeleteController, saveController, testController } from './controllers.js';
import { applyDebugPanelVisibility, loadDebugLogHistory, setupDebugLogStream, setupStream } from './debug.js';
import { initHelpSystem } from './help.js';
import { initBackupBindings } from './backup.js';
import { state, setCurrentUser } from './state.js';
import { initUsersPane } from './users.js';
import { loadZones, initZonesTab } from './zones.js';
import { initSystemPolling, refreshSystemResources, checkServerHealth } from './system.js';

// --- Tab navigation bindings ---
document.querySelectorAll(".ttab").forEach((el) => (el.onclick = () => {
  switchTab(el.dataset.tab);
  if (el.dataset.tab === "obs") { scheduleVideoGridLayout(); renderEventFeed(true); }
  if (el.dataset.tab === "zones") { loadZones(); }
}));
document.querySelectorAll(".snav-item").forEach((el) => (el.onclick = () => switchSettings(el.dataset.sp)));
document.querySelectorAll(".ch-tab").forEach((el) => (el.onclick = () => switchChannelSettingsTab(el.dataset.chTab)));
document.getElementById("gridSelect").onchange = () => { clearExpandMode(); scheduleVideoGridLayout(true); };

initJournalBindings();

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

// --- Clients sub-tab switching ---
document.querySelectorAll('.clients-subtab-btn').forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll('.clients-subtab-btn').forEach((b) => b.classList.remove('active'));
    document.querySelectorAll('.subtab-pane').forEach((p) => p.classList.remove('active'));
    btn.classList.add('active');
    const pane = document.getElementById(`subtab-${btn.dataset.subtab}`);
    if (pane) pane.classList.add('active');
  };
});

// --- All clients table ---
document.getElementById('addClientBtn').onclick = openAddClientModal;
document.getElementById('clientsSearchInput').oninput = (e) => searchClients(e.target.value);

// --- Client card modal ---
document.getElementById('clientCardClose').onclick = () => closeModal('clientCardModal');
document.getElementById('clientCardCancel').onclick = () => closeModal('clientCardModal');
document.getElementById('clientCardModal').onclick = (e) => { if (e.target.id === 'clientCardModal') closeModal('clientCardModal'); };
document.getElementById('clientCardSaveBtn').onclick = saveClientChanges;
document.getElementById('clientCardDeleteBtn').onclick = openDeleteClientConfirm;
document.getElementById('clientCardListBtn').onclick = () => {
  const btn = document.getElementById('clientCardListBtn');
  if (btn.textContent.trim() === 'Открепить от списка') {
    detachClientFromList();
  } else {
    openListPickerModal();
  }
};

// --- Delete client confirmation ---
document.getElementById('deleteClientCancel').onclick = () => closeModal('deleteClientModal');
document.getElementById('deleteClientConfirm').onclick = confirmDeleteClient;
document.getElementById('deleteClientModal').onclick = (e) => { if (e.target.id === 'deleteClientModal') closeModal('deleteClientModal'); };

// --- Detach client confirmation ---
document.getElementById('detachClientCancel').onclick = () => closeModal('detachClientModal');
document.getElementById('detachClientConfirm').onclick = confirmDetachClient;
document.getElementById('detachClientModal').onclick = (e) => { if (e.target.id === 'detachClientModal') closeModal('detachClientModal'); };

// --- List picker (attach client → list) ---
document.getElementById('listPickerClose').onclick = () => closeModal('listPickerModal');
document.getElementById('listPickerCancel').onclick = () => closeModal('listPickerModal');
document.getElementById('listPickerModal').onclick = (e) => { if (e.target.id === 'listPickerModal') closeModal('listPickerModal'); };

// --- Client picker (attach client to list from the Lists subtab) ---
document.getElementById('attachClientToListBtn').onclick = () => { if (!state.selectedListId) return; openClientPickerModal(state.selectedListId); };
document.getElementById('clientPickerClose').onclick = () => closeModal('clientPickerModal');
document.getElementById('clientPickerCancel').onclick = () => closeModal('clientPickerModal');
document.getElementById('clientPickerModal').onclick = (e) => { if (e.target.id === 'clientPickerModal') closeModal('clientPickerModal'); };

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
  state.selectedListId = null; state.listMembers = [];
  const listTitleEl = document.getElementById("listTitle");
  if (listTitleEl) listTitleEl.textContent = "—";
  const listMembersBodyEl = document.getElementById("listMembersBody");
  if (listMembersBodyEl) listMembersBodyEl.innerHTML = "";
  await loadLists();
  await loadAllClients();
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
initSystemPolling();

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
initZonesTab();
const _zoneBeforeEl = document.getElementById("c_zone_before_id");
const _zoneAfterEl = document.getElementById("c_zone_after_id");
if (_zoneBeforeEl) _zoneBeforeEl.onchange = updateZoneChannelTypeState;
if (_zoneAfterEl) _zoneAfterEl.onchange = updateZoneChannelTypeState;

// --- Main init ---
(async function init() {
  const apiBaseEl = document.getElementById("apiBase");
  if (apiBaseEl) apiBaseEl.value = window.location.origin;
  try { applyTheme(localStorage.getItem("anpr_theme") || "dark"); }
  catch (_e) { applyTheme("dark"); }

  const startLoginFlow = () => {
    showLoginOverlay((user) => {
      setCurrentUser(user);
      _applyUserUI(user);
      location.reload();
    });
  };

  // --- Auth check ---
  const token = getToken();
  if (!token || isTokenExpired()) {
    setToken(null);
    startLoginFlow();
    return;
  }
  let currentUser;
  try {
    currentUser = await getCurrentUser();
    setCurrentUser(currentUser);
  } catch (_e) {
    // Token expired or invalid — clear it and re-authenticate
    setToken(null);
    startLoginFlow();
    return;
  }
  _applyUserUI(currentUser);
  applyTabVisibility(currentUser.permissions || [], currentUser.role === "superadmin");
  applyDebugPanelVisibility();
  initUsersPane();

  // --- Superadmin-only: reveal "Разработка" section ---
  if (currentUser.role === "superadmin") {
    const devLabel = document.getElementById("snav-label-dev");
    const debugItem = document.getElementById("snav-debug");
    if (devLabel) devLabel.classList.remove("hidden");
    if (debugItem) debugItem.classList.remove("hidden");
  }

  // --- Logout button ---
  const logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) logoutBtn.onclick = async () => {
    await logoutRequest();
    setToken(null);
    location.reload();
  };

  syncChannelConfigVisibility();
  syncControllerConfigVisibility();
  setupVideoGridLayoutGuards(() => {
    refreshChannels();
    refreshSystemResources();
    checkServerHealth();
  });
  setupVideoGridDragDrop();
  setupEventFeedLayoutGuards();
  setupVisionCanvas();
  setupPlateSizeInputListeners();
  switchChannelSettingsTab("channel");
  updateTopbarTitle();
  await refreshChannels();
  loadZones();
  await hydrateChannelLastPlates();
  initJournalScroll();
  await loadEventFeedHistory();
  await loadLists();
  await loadAllClients();
  await loadJournal();
  if (currentUser.role === "superadmin") {
    await loadGlobalSettings();
    await refreshOverlayStates();
    await loadDebugLogHistory();
    setupDebugLogStream();
    await loadControllers();
  }
  setupStream();
  setInterval(refreshChannels, 8000);
  syncOverlayPolling();
})();

function _applyUserUI(user) {
  if (!user) return;
  const loginEl = document.getElementById("railUserLogin");
  if (loginEl) loginEl.textContent = user.login || "";
  const railBottom = document.getElementById("railBottom");
  if (railBottom) railBottom.classList.add("has-user");
}
