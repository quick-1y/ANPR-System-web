// Global application state — shared across all modules
export const state = {
  channels: [],
  lists: [],
  selectedListId: null,
  allEvents: [],
  lastPlatesByChannelId: {},
  plateLookup: {},
  currentEntries: [],
  currentUser: null,  // { id, login, role, permissions: [...] }
};

// Mutable singletons shared across modules
export let eventSource = null;
export let streamReconnectTimer = null;
export let debugLogSource = null;
export let debugLogReconnectTimer = null;
export let lastDebugLogId = 0;
export let debugSettingsCache = null;
export let overlayRefreshTimer = null;
export let eventFeedResizeObserver = null;
export let eventFeedRenderScheduled = false;
export let eventFeedRenderFrame = null;

// Setter helpers for mutable lets (ES modules export live bindings but
// only the declaring module can assign to them)
export function setEventSource(v) { eventSource = v; }
export function setStreamReconnectTimer(v) { streamReconnectTimer = v; }
export function setDebugLogSource(v) { debugLogSource = v; }
export function setDebugLogReconnectTimer(v) { debugLogReconnectTimer = v; }
export function setLastDebugLogId(v) { lastDebugLogId = v; }
export function setDebugSettingsCache(v) { debugSettingsCache = v; }
export function setOverlayRefreshTimer(v) { overlayRefreshTimer = v; }
export function setEventFeedResizeObserver(v) { eventFeedResizeObserver = v; }
export function setEventFeedRenderScheduled(v) { eventFeedRenderScheduled = v; }
export function setEventFeedRenderFrame(v) { eventFeedRenderFrame = v; }

// Current user helpers
export function setCurrentUser(user) { state.currentUser = user; }
export function isAdmin() { return state.currentUser?.role === "admin"; }
export function hasPermission(key) {
  if (!state.currentUser) return false;
  if (isAdmin()) return true;
  return Array.isArray(state.currentUser.permissions) && state.currentUser.permissions.includes(key);
}
