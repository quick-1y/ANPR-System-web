// Theme and style resolution — the logic, with every side effect injected so
// it can be tested without a browser.
//
// Device-local only (class L): `anpr_theme` / `anpr_style` in localStorage,
// shared by whoever is using this browser — the same rule grid layout
// already follows in video-grid.js. There is no server, no per-user
// identity and no cross-workstation sync; a shared security-post PC shows
// one look to every operator, same as it already shows one grid layout.
// Storage that is missing or throws just means the code defaults apply.

export const CODE_DEFAULTS = Object.freeze({ theme: "light", style: "graphite-minimal" });
const KEYS = { theme: "anpr_theme", style: "anpr_style" };

function pick(source) {
  const out = {};
  if (source && typeof source.theme === "string" && source.theme) out.theme = source.theme;
  if (source && typeof source.style === "string" && source.style) out.style = source.style;
  return out;
}

export function createAppearance({ storage, apply }) {
  let current = { ...CODE_DEFAULTS };

  const readStored = () => {
    const out = {};
    try { const theme = storage.getItem(KEYS.theme); if (theme) out.theme = theme; } catch (_e) { /* device state only */ }
    try { const style = storage.getItem(KEYS.style); if (style) out.style = style; } catch (_e) { /* device state only */ }
    return pick(out);
  };
  const show = (values) => {
    current = { ...current, ...pick(values) };
    apply({ ...current });
  };

  return {
    // Synchronous, no network involved: whatever this browser has stored, or
    // the code defaults.
    boot() {
      current = { ...CODE_DEFAULTS };
      show(readStored());
    },

    // Applied immediately and persisted immediately — nothing can fail short
    // of a blocked/full localStorage, which just means the choice does not
    // survive a reload.
    set(patch) {
      const values = pick(patch);
      if (values.theme) { try { storage.setItem(KEYS.theme, values.theme); } catch (_e) { /* device state only */ } }
      if (values.style) { try { storage.setItem(KEYS.style, values.style); } catch (_e) { /* device state only */ } }
      show(values);
    },

    current: () => ({ ...current }),
  };
}
