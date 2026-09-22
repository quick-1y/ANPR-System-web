// Browser wiring for appearance-core.js — the single owner of theme and
// style. Device-local only (class L): no server, no per-user identity. ui.js
// only applies values to the DOM; nothing else may write a look to
// localStorage or decide which one wins.
import { createAppearance } from './appearance-core.js';
import { applyStyle, applyTheme } from './ui.js';

// localStorage may be blocked or throw (private window, policy): the core
// wraps every call, this adapter only makes the property lookups themselves safe.
const storage = {
  getItem: (k) => { try { return localStorage.getItem(k); } catch (_e) { return null; } },
  setItem: (k, v) => { try { localStorage.setItem(k, v); } catch (_e) { /* device state only */ } },
};

export const appearance = createAppearance({
  storage,
  apply: ({ theme, style }) => {
    applyStyle(style);
    applyTheme(theme);
    // Keep the "Мои предпочтения" selects in sync with whatever just applied,
    // however it changed (boot, the topbar toggle, or the selects themselves).
    const themeEl = document.getElementById("p_theme");
    const styleEl = document.getElementById("p_style");
    if (themeEl) themeEl.value = theme;
    if (styleEl) styleEl.value = style;
  },
});
