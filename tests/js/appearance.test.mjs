// Theme/style resolution — device-local only (class L), with every side
// effect faked. No server, no per-user identity: see appearance-core.js.
import test from "node:test";
import assert from "node:assert/strict";

import { CODE_DEFAULTS, createAppearance } from "../../app/web/js/appearance-core.js";

class MemoryStorage {
  constructor() { this.map = new Map(); }
  getItem(k) { return this.map.has(k) ? this.map.get(k) : null; }
  setItem(k, v) { this.map.set(k, String(v)); }
}

class BrokenStorage {
  getItem() { throw new Error("blocked"); }
  setItem() { throw new Error("blocked"); }
}

function makeApp({ storage = new MemoryStorage() } = {}) {
  const applied = [];
  const app = createAppearance({ storage, apply: (look) => applied.push(look) });
  return { app, applied, storage };
}

test("boot with nothing stored shows the code defaults", () => {
  const { app, applied } = makeApp();
  app.boot();
  assert.deepEqual(applied.at(-1), CODE_DEFAULTS);
  assert.deepEqual(app.current(), CODE_DEFAULTS);
});

test("boot applies whatever this browser already has stored", () => {
  const storage = new MemoryStorage();
  storage.setItem("anpr_theme", "dark");
  storage.setItem("anpr_style", "aurora");
  const { app, applied } = makeApp({ storage });
  app.boot();
  assert.deepEqual(applied.at(-1), { theme: "dark", style: "aurora" });
});

test("set() applies immediately and persists to localStorage", () => {
  const { app, applied, storage } = makeApp();
  app.boot();
  app.set({ theme: "dark" });
  assert.equal(applied.at(-1).theme, "dark");
  assert.equal(storage.getItem("anpr_theme"), "dark");
  // The other key is untouched by a partial patch.
  assert.equal(app.current().style, CODE_DEFAULTS.style);
});

test("a later boot() picks up what set() persisted — same browser, e.g. after a reload", () => {
  const storage = new MemoryStorage();
  const first = makeApp({ storage });
  first.app.boot();
  first.app.set({ theme: "dark", style: "aurora" });

  const second = makeApp({ storage });
  second.app.boot();
  assert.deepEqual(second.app.current(), { theme: "dark", style: "aurora" });
});

test("a blocked/throwing storage still boots to the code defaults and set() still applies on screen", () => {
  const { app, applied } = makeApp({ storage: new BrokenStorage() });
  app.boot();
  assert.deepEqual(applied.at(-1), CODE_DEFAULTS);
  app.set({ theme: "dark" });
  assert.equal(applied.at(-1).theme, "dark"); // shown even though persisting it failed
});

test("an empty/garbage patch changes nothing", () => {
  const { app, applied } = makeApp();
  app.boot();
  const before = app.current();
  app.set({});
  assert.deepEqual(app.current(), before);
  assert.deepEqual(applied.at(-1), before);
});
