import assert from "node:assert/strict";
import test from "node:test";
import { upcomingEvents } from "../src/utils/events.ts";

test("hides past and invalid dates, sorts upcoming dates, and keeps today", () => {
  const events = [
    { date: "2027-01-01" },
    { date: "invalid" },
    { date: "2026-11-17" },
    { date: "2026-11-18" },
    { date: "2026-12-01" },
  ];
  const result = upcomingEvents(events, new Date("2026-11-18T15:00:00Z"));
  assert.deepEqual(result.map(({ date }) => date), [
    "2026-11-18", "2026-12-01", "2027-01-01",
  ]);
  assert.equal(events[0].date, "2027-01-01");
});

test("date-only concerts follow Madrid's calendar across midnight and summer time", () => {
  for (const now of ["2026-11-18T23:30:00Z", "2026-07-18T22:30:00Z"]) {
    const month = now.slice(5, 7);
    const result = upcomingEvents([
      { date: `2026-${month}-18` }, { date: `2026-${month}-19` },
    ], new Date(now));
    assert.deepEqual(result, [{ date: `2026-${month}-19` }]);
  }
});

test("timestamps use the actual instant, including timezone offsets", () => {
  const result = upcomingEvents([
    { date: "2026-11-18T17:30:00+02:00" },
    { date: "2026-11-18T14:59:00Z" },
    { date: "2026-11-18T15:00:00Z" },
  ], new Date("2026-11-18T15:00:00Z"));
  assert.deepEqual(result.map(({ date }) => date), [
    "2026-11-18T15:00:00Z", "2026-11-18T17:30:00+02:00",
  ]);
});
