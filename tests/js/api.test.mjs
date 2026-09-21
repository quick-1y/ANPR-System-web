// The user id is taken from the JWT only to choose the appearance cache key.
import test from "node:test";
import assert from "node:assert/strict";

import { getTokenUserId } from "../../app/web/js/api.js";

function withToken(token, fn) {
  const store = new Map(token === undefined ? [] : [["anpr_token", token]]);
  globalThis.localStorage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k) };
  try { return fn(); } finally { delete globalThis.localStorage; }
}

const jwt = (payload) => `h.${Buffer.from(JSON.stringify(payload)).toString("base64")}.s`;

test("the subject of the token is the user id, as a string", () => {
  assert.equal(withToken(jwt({ sub: 12 }), getTokenUserId), "12");
  assert.equal(withToken(jwt({ sub: "7" }), getTokenUserId), "7");
});

test("no token, garbage or a token without a subject give null and never throw", () => {
  assert.equal(withToken(undefined, getTokenUserId), null);
  assert.equal(withToken("garbage", getTokenUserId), null);
  assert.equal(withToken(jwt({ role: "x" }), getTokenUserId), null);
});
