// Theme/style resolution (roadmap 7.2, 7.3, model 4.3) with every side effect faked.
import test from "node:test";
import assert from "node:assert/strict";

import { CODE_DEFAULTS, INSTANCE_KEY, USER_PREFIX, createAppearance } from "../../app/web/js/appearance-core.js";

class MemoryStorage {
  constructor() { this.map = new Map(); }
  get length() { return this.map.size; }
  key(i) { return [...this.map.keys()][i] ?? null; }
  getItem(k) { return this.map.has(k) ? this.map.get(k) : null; }
  setItem(k, v) { this.map.set(k, String(v)); }
  removeItem(k) { this.map.delete(k); }
  keys() { return [...this.map.keys()]; }
}

class BrokenStorage {
  get length() { throw new Error("blocked"); }
  key() { throw new Error("blocked"); }
  getItem() { throw new Error("blocked"); }
  setItem() { throw new Error("blocked"); }
  removeItem() { throw new Error("blocked"); }
}

// A tiny fake of the server: instance defaults + per-user personal values.
function makeServer({ instance = { theme: "light", style: "graphite-minimal" }, users = {} } = {}) {
  const server = { instance, users, fail: false, gate: null };
  server.resolvedFor = (id) => {
    const own = users[id] || {};
    const entry = (key) => ({ value: own[key] ?? server.instance[key], source: own[key] ? "user" : "instance" });
    return { preferences: { theme: entry("theme"), style: entry("style") } };
  };
  server.deps = (getId) => ({
    fetchPublic: async () => {
      if (server.fail) throw new Error("down");
      return { default_theme: server.instance.theme, default_style: server.instance.style };
    },
    fetchPreferences: async () => {
      if (server.fail) throw new Error("down");
      return server.resolvedFor(getId());
    },
    patchPreferences: async (patch) => {
      if (server.gate) await server.gate;
      if (server.fail) throw new Error("down");
      users[getId()] = { ...(users[getId()] || {}), ...patch };
      return server.resolvedFor(getId());
    },
  });
  return server;
}

function makeApp({ storage = new MemoryStorage(), server = makeServer() } = {}) {
  const userId = { current: null };
  const applied = [];
  const notes = [];
  const app = createAppearance({
    storage,
    ...server.deps(() => userId.current),
    apply: (look) => applied.push(look),
    notify: (message) => notes.push(message),
  });
  return { app, storage, server, applied, notes, userId };
}

test("first start without any cache: code defaults (graphite-minimal, light)", () => {
  const { app, applied } = makeApp();
  app.boot(null);
  assert.deepEqual(applied.at(-1), { theme: "light", style: "graphite-minimal" });
  assert.deepEqual(CODE_DEFAULTS, { theme: "light", style: "graphite-minimal" });
});

test("login screen: the cached instance default is applied synchronously, then confirmed by the public endpoint", async () => {
  const storage = new MemoryStorage();
  storage.setItem(INSTANCE_KEY, JSON.stringify({ theme: "dark", style: "aurora" }));
  const { app, applied } = makeApp({ storage, server: makeServer({ instance: { theme: "dark", style: "aurora" } }) });
  app.boot(null);
  assert.deepEqual(applied.at(-1), { theme: "dark", style: "aurora" }); // before any network
  await app.refreshInstance();
  assert.deepEqual(applied.at(-1), { theme: "dark", style: "aurora" });
});

test("a server answer overwrites the instance cache (server wins over the cache)", async () => {
  const storage = new MemoryStorage();
  storage.setItem(INSTANCE_KEY, JSON.stringify({ theme: "dark", style: "aurora" }));
  const { app, applied } = makeApp({ storage });
  app.boot(null);
  await app.refreshInstance();
  assert.deepEqual(applied.at(-1), { theme: "light", style: "graphite-minimal" });
  assert.deepEqual(JSON.parse(storage.getItem(INSTANCE_KEY)), { theme: "light", style: "graphite-minimal" });
});

test("signing in gives the user's own look and caches it under their id", async () => {
  const server = makeServer({ users: { 7: { theme: "dark", style: "aurora" } } });
  const { app, applied, storage, userId } = makeApp({ server });
  app.boot(null);
  userId.current = 7;
  await app.signIn(7);
  assert.deepEqual(applied.at(-1), { theme: "dark", style: "aurora" });
  assert.deepEqual(JSON.parse(storage.getItem(USER_PREFIX + "7")), { theme: "dark", style: "aurora" });
});

test("no personal preference: the instance default; an admin change reaches the user's look", async () => {
  const server = makeServer({ instance: { theme: "dark", style: "graphite-minimal" } });
  const { app, applied, userId } = makeApp({ server });
  app.boot(null);
  userId.current = 3;
  await app.signIn(3);
  assert.equal(applied.at(-1).theme, "dark");
  server.instance.theme = "light"; // the administrator changes the instance default
  await app.refreshUser();
  assert.equal(applied.at(-1).theme, "light");
});

test("login screen to app: no theme change when the user has no personal preference", async () => {
  const server = makeServer({ instance: { theme: "dark", style: "aurora" } });
  const { app, applied, userId } = makeApp({ server });
  app.boot(null);
  await app.refreshInstance(); // the login screen now shows the instance look
  const onLoginScreen = applied.length;
  userId.current = 4;
  await app.signIn(4);
  assert.deepEqual(applied.slice(onLoginScreen).filter((look) => look.theme !== "dark" || look.style !== "aurora"), [],
    "the look changed between the login screen and the app");
});

test("the choice survives a reload: the cache paints it before the network answers", async () => {
  const storage = new MemoryStorage();
  const server = makeServer();
  const first = makeApp({ storage, server });
  first.userId.current = 9;
  first.app.boot(null);
  await first.app.signIn(9);
  assert.equal(await first.app.setPersonal({ theme: "dark" }), true);
  // "reload": a brand-new appearance over the same storage; the token names the user
  const second = makeApp({ storage, server });
  second.userId.current = 9;
  second.app.boot("9");
  assert.equal(second.applied.at(-1).theme, "dark");
  assert.equal(second.applied.length, 1, "painted once, synchronously");
});

test("the cache changes only after the server confirmed the change", async () => {
  const server = makeServer();
  const { app, storage, userId } = makeApp({ server });
  userId.current = 5;
  app.boot(null);
  await app.signIn(5);
  const before = storage.getItem(USER_PREFIX + "5");
  let release;
  server.gate = new Promise((resolve) => { release = resolve; });
  const pending = app.setPersonal({ theme: "dark" });
  assert.equal(storage.getItem(USER_PREFIX + "5"), before, "cache untouched while the request is in flight");
  release();
  await pending;
  assert.equal(JSON.parse(storage.getItem(USER_PREFIX + "5")).theme, "dark");
});

test("network error on save: the screen reverts, the cache is unchanged, the user is told", async () => {
  const server = makeServer({ users: { 2: { theme: "light" } } });
  const { app, applied, storage, notes, userId } = makeApp({ server });
  userId.current = 2;
  app.boot(null);
  await app.signIn(2);
  const cached = storage.getItem(USER_PREFIX + "2");
  server.fail = true;
  assert.equal(await app.setPersonal({ theme: "dark" }), false);
  assert.equal(applied.at(-1).theme, "light"); // reverted
  assert.equal(storage.getItem(USER_PREFIX + "2"), cached);
  assert.equal(notes.length, 1);
});

test("user A logs out, user B logs in: B never sees A's look on any frame", async () => {
  const storage = new MemoryStorage();
  const server = makeServer({ users: { 1: { theme: "dark", style: "aurora" } } });

  const a = makeApp({ storage, server });
  a.userId.current = 1;
  a.app.boot("1");
  await a.app.signIn(1);
  assert.equal(a.applied.at(-1).theme, "dark");
  a.app.signOut(); // logout
  assert.deepEqual(storage.keys().filter((k) => k.startsWith(USER_PREFIX)), [], "A's keys removed");

  // the page reloads without a token: the login screen shows the instance look
  const login = makeApp({ storage, server });
  login.app.boot(null);
  assert.equal(login.applied.at(-1).theme, "light");

  const b = makeApp({ storage, server });
  b.userId.current = 2;
  b.app.boot("2");
  await b.app.signIn(2);
  assert.equal(b.applied.filter((l) => l.theme === "dark" || l.style === "aurora").length, 0,
    "A's look appeared for B");
});

test("token expired without an explicit logout: A's stale cache is never applied to B and is dropped at B's sign-in", async () => {
  const storage = new MemoryStorage();
  storage.setItem(USER_PREFIX + "1", JSON.stringify({ theme: "dark", style: "aurora" }));
  const b = makeApp({ storage });
  b.userId.current = 2;
  b.app.boot("2");
  assert.equal(b.applied.at(-1).theme, "light");
  await b.app.signIn(2);
  assert.equal(storage.getItem(USER_PREFIX + "1"), null);
});

test("localStorage disabled or throwing everywhere: nothing breaks", async () => {
  const server = makeServer({ users: { 8: { theme: "dark" } } });
  const applied = [];
  const app = createAppearance({
    storage: new BrokenStorage(),
    ...server.deps(() => 8),
    apply: (look) => applied.push(look),
  });
  app.boot("8");
  await app.refreshInstance();
  await app.signIn(8);
  assert.equal(await app.setPersonal({ theme: "light" }), true);
  app.signOut();
  assert.ok(applied.length >= 4);
  assert.equal(applied.at(-1).theme, "light");
});

test("server unreachable at start: the cached look stays and nothing throws", async () => {
  const storage = new MemoryStorage();
  storage.setItem(USER_PREFIX + "6", JSON.stringify({ theme: "dark", style: "aurora" }));
  const server = makeServer();
  server.fail = true;
  const { app, applied } = makeApp({ storage, server });
  app.boot("6");
  await app.refreshInstance();
  await app.signIn(6);
  assert.deepEqual(applied.at(-1), { theme: "dark", style: "aurora" });
});
