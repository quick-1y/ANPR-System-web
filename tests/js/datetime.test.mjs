// Display-time behaviour (roadmap 7.5). Run under several process time zones by
// tests/test_frontend_js.py: nothing here may depend on the machine's zone.
import test from "node:test";
import assert from "node:assert/strict";

import {
  configureZone, formatDate, formatDateTime, formatTime, getZoneInfo, onZoneChange,
  serverNow, setServerTime, syncServerTime, utcToWallTime, wallTimeToUtcIso,
} from "../../app/web/js/datetime.js";

const UTC_NOON = "2026-09-21T12:00:00Z";

test("changing the zone changes the rendering at once, without a reload", () => {
  configureZone({ zone: "UTC", configured: true });
  assert.equal(formatDateTime(UTC_NOON), "21.09.2026, 12:00:00");
  const seen = [];
  const off = onZoneChange((info) => seen.push(info.zone));
  configureZone({ zone: "Europe/Minsk", configured: true });
  assert.equal(formatDateTime(UTC_NOON), "21.09.2026, 15:00:00");
  configureZone({ zone: "Europe/Minsk", configured: true }); // unchanged -> silent
  off();
  assert.deepEqual(seen, ["Europe/Minsk"]);
});

test("one locale for every view: ru-RU layout regardless of the browser locale", () => {
  configureZone({ zone: "UTC", configured: true });
  assert.equal(formatDate(UTC_NOON), "21.09.2026");
  assert.equal(formatTime(UTC_NOON), "12:00:00");
  assert.equal(formatTime("2026-09-21T00:00:00Z"), "00:00:00"); // never "24:00:00"
  assert.equal(formatDateTime(null), "—");
  assert.equal(formatDateTime("not a date"), "—");
});

test("a journal filter 'from 08:00' is the same UTC instant whatever the browser zone", () => {
  configureZone({ zone: "Europe/Minsk", configured: true });
  assert.equal(wallTimeToUtcIso("2026-09-21T08:00"), "2026-09-21T05:00:00.000Z");
  assert.equal(wallTimeToUtcIso("2026-09-21T18:00"), "2026-09-21T15:00:00.000Z");
  configureZone({ zone: "Asia/Almaty", configured: true });
  assert.equal(wallTimeToUtcIso("2026-09-21T08:00"), "2026-09-21T03:00:00.000Z");
  assert.equal(wallTimeToUtcIso("bad"), null);
});

test("wall time and UTC round-trip in the display zone", () => {
  configureZone({ zone: "Europe/Kyiv", configured: true });
  const iso = wallTimeToUtcIso("2026-07-01T09:30");
  assert.equal(utcToWallTime(iso), "2026-07-01T09:30");
});

test("daylight saving: the same zone is +02:00 in winter and +03:00 in summer", () => {
  configureZone({ zone: "Europe/Kyiv", configured: true });
  assert.equal(formatTime("2026-03-28T12:00:00Z"), "14:00:00");
  assert.equal(formatTime("2026-03-30T12:00:00Z"), "15:00:00");
  // the exact switch: 03:00 EET jumps to 04:00 EEST at 01:00 UTC
  assert.equal(formatTime("2026-03-29T00:59:59Z"), "02:59:59");
  assert.equal(formatTime("2026-03-29T01:00:00Z"), "04:00:00");
  // a filter typed in summer time converts with the summer offset
  assert.equal(wallTimeToUtcIso("2026-03-30T15:00"), "2026-03-30T12:00:00.000Z");
  assert.equal(wallTimeToUtcIso("2026-03-28T14:00"), "2026-03-28T12:00:00.000Z");
});

test("the topbar shows server time even when the workstation clock is wrong", () => {
  const realNow = Date.now;
  const workstation = Date.UTC(2020, 0, 1, 0, 0, 0); // clock set to 2020
  try {
    Date.now = () => workstation;
    setServerTime({ serverUtc: "2026-09-21T10:00:00Z", sentAt: workstation, receivedAt: workstation });
    assert.equal(serverNow().toISOString(), "2026-09-21T10:00:00.000Z");
    Date.now = () => workstation + 5000; // five local seconds later
    assert.equal(serverNow().toISOString(), "2026-09-21T10:00:05.000Z");
  } finally {
    Date.now = realNow;
  }
});

test("network latency is split: the server stamped its answer mid-request", () => {
  const realNow = Date.now;
  try {
    // request sent at local 1000, answered at local 1200 (200 ms round trip);
    // the server says it is 5000 ms, which it was at local 1100.
    Date.now = () => 1200;
    setServerTime({ serverUtc: new Date(5000).toISOString(), sentAt: 1000, receivedAt: 1200 });
    assert.equal(serverNow().getTime(), 5100); // 100 ms have passed since that moment
  } finally {
    Date.now = realNow;
  }
});

test("server zone and the 'not configured' flag show up in the label", async () => {
  await syncServerTime(async () => ({ server_utc: UTC_NOON, display_timezone: "UTC", timezone_configured: false }));
  let info = getZoneInfo();
  assert.equal(info.source, "server");
  assert.match(info.label, /UTC \(по умолчанию\)/);
  await syncServerTime(async () => ({ server_utc: UTC_NOON, display_timezone: "Europe/Minsk", timezone_configured: true }));
  info = getZoneInfo();
  assert.equal(info.label, "Europe/Minsk");
});

test("unavailable server: the browser zone is used and explicitly marked", async () => {
  await syncServerTime(async () => { throw new Error("down"); });
  const info = getZoneInfo();
  assert.equal(info.source, "browser");
  assert.match(info.label, /\(зона браузера\)$/);
});

test("an invalid zone from the server falls back to the browser zone", () => {
  configureZone({ zone: "Mars/Olympus", configured: true });
  assert.equal(getZoneInfo().source, "browser");
});
