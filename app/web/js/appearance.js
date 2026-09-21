// Browser wiring for appearance-core.js — the single owner of theme and style.
// ui.js only applies values to the DOM; nothing else may write a look to
// localStorage or decide which one wins.
import { createAppearance } from './appearance-core.js';
import { api } from './api.js';
import { applyStyle, applyTheme, showToast } from './ui.js';
import { loadPreferences, savePreferences } from './preferences.js';

// localStorage may be blocked or throw (private window, policy): the core wraps
// every call, this adapter only makes the property lookups themselves safe.
const storage = {
  get length() { try { return localStorage.length; } catch (_e) { return 0; } },
  key: (i) => { try { return localStorage.key(i); } catch (_e) { return null; } },
  getItem: (k) => localStorage.getItem(k),
  setItem: (k, v) => localStorage.setItem(k, v),
  removeItem: (k) => localStorage.removeItem(k),
};

export const appearance = createAppearance({
  storage,
  fetchPreferences: loadPreferences,
  patchPreferences: savePreferences,
  apply: ({ theme, style }) => { applyStyle(style); applyTheme(theme); },
  notify: (message) => showToast(message, 4000),
});
