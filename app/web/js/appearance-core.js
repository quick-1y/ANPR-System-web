// Appearance resolution (roadmap 7.2/7.3, model 4.3) — the logic, with every
// side effect injected so it can be tested without a browser.
//
// Order:  personal preference -> instance default -> code default.
// The server is the source of truth. localStorage is only a fast-load cache:
//   * anpr_appearance_instance        — anonymous instance default (login screen)
//   * anpr_appearance_user:<user id>  — that user's resolved look
// Every server answer overwrites the cache; user keys are removed on logout and
// when another user signs in, so a look never leaks between people (P17).
// Storage that is missing or throws only costs the flash-suppression.

export const INSTANCE_KEY = "anpr_appearance_instance";
export const USER_PREFIX = "anpr_appearance_user:";
export const CODE_DEFAULTS = Object.freeze({ theme: "light", style: "graphite-minimal" });

function pick(source) {
  const out = {};
  if (source && typeof source.theme === "string" && source.theme) out.theme = source.theme;
  if (source && typeof source.style === "string" && source.style) out.style = source.style;
  return out;
}

export function createAppearance({ storage, fetchPublic, fetchPreferences, patchPreferences, apply, notify = () => {} }) {
  let userId = null;
  let instance = { ...CODE_DEFAULTS };
  let current = { ...CODE_DEFAULTS };

  const readJson = (key) => {
    try { const raw = storage.getItem(key); return raw ? JSON.parse(raw) : null; } catch (_e) { return null; }
  };
  const writeJson = (key, value) => { try { storage.setItem(key, JSON.stringify(value)); } catch (_e) { /* cache only */ } };
  const userKeys = () => {
    const keys = [];
    try {
      for (let i = 0; i < storage.length; i++) {
        const key = storage.key(i);
        if (key && key.startsWith(USER_PREFIX)) keys.push(key);
      }
    } catch (_e) { /* ignore */ }
    return keys;
  };
  const dropUserKeys = (except = null) => {
    for (const key of userKeys()) {
      if (key === except) continue;
      try { storage.removeItem(key); } catch (_e) { /* ignore */ }
    }
  };
  const show = (values) => {
    current = { ...current, ...pick(values) };
    apply({ ...current });
  };
  const fromPreferences = (body) => {
    const prefs = (body && body.preferences) || {};
    return pick({ theme: prefs.theme && prefs.theme.value, style: prefs.style && prefs.style.value });
  };

  return {
    // Synchronous, before any network: cached look of the token's user if there
    // is one, else the cached instance default, else the code defaults.
    boot(tokenUserId = null) {
      instance = { ...CODE_DEFAULTS, ...pick(readJson(INSTANCE_KEY)) };
      userId = tokenUserId === null || tokenUserId === undefined ? null : String(tokenUserId);
      const cachedUser = userId === null ? {} : pick(readJson(USER_PREFIX + userId));
      current = { ...CODE_DEFAULTS };
      show({ ...instance, ...cachedUser });
    },

    async refreshInstance() {
      try {
        const body = await fetchPublic();
        instance = { ...CODE_DEFAULTS, ...pick({ theme: body.default_theme, style: body.default_style }) };
        writeJson(INSTANCE_KEY, instance);
        if (userId === null) show(instance);
      } catch (_e) { /* keep what is shown */ }
    },

    async signIn(id) {
      userId = String(id);
      dropUserKeys(USER_PREFIX + userId);
      await this.refreshUser();
    },

    async refreshUser() {
      if (userId === null) return;
      try {
        const values = fromPreferences(await fetchPreferences());
        writeJson(USER_PREFIX + userId, values);
        show({ ...instance, ...values });
      } catch (_e) { /* offline: the cached look stays */ }
    },

    // Optimistic on screen, authoritative on the server. The cache changes only
    // after a successful answer; on failure the previous look returns.
    async setPersonal(patch) {
      if (userId === null) return false;
      const previous = { ...current };
      show(patch);
      try {
        const values = fromPreferences(await patchPreferences(pick(patch)));
        writeJson(USER_PREFIX + userId, values);
        show(values);
        return true;
      } catch (_e) {
        show(previous);
        notify("Не удалось сохранить оформление — сервер недоступен");
        return false;
      }
    },

    signOut() {
      dropUserKeys();
      userId = null;
      show(instance);
    },

    current: () => ({ ...current }),
    userId: () => userId,
  };
}
