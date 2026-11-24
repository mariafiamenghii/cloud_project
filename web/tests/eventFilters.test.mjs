import assert from "node:assert/strict";
import test from "node:test";
import {
  DEFAULT_FILTERS, applyFilters, cityKey, cityOptions, comparablePrice, eventSource,
  formatEventDate, hasActiveFilters, hiddenUnpricedCount, priceCeiling,
} from "../src/utils/eventFilters.ts";

const ev = (overrides) => ({ name: "Show", artist: "Band", city: "Madrid", ...overrides });

const events = [
  ev({ name: "Rock Night", genre: "rock", city: "Barcelona", price: 30 }),
  ev({ name: "Big Rock", genre: "rock", city: "Barcelona", price: 67, source: "internal" }),
  ev({ name: "Rock Madrid", genre: "rock", city: "Madrid", price: 20 }),
  ev({ name: "Imported Rock", genre: "rock", city: "Barcelona", source: "ticketmaster" }),
  ev({ name: "Jazz", genre: "jazz", city: "barcelona ", price: 10 }),
  ev({ name: "Catalan Folk", genre: "catalan", city: "Girona", price: 0 }),
  ev({ name: "Partner", city: "Madrid", source: "partner", price: 5 }),
];

const names = (list) => list.map((e) => e.name);

test("sources follow the data model", () => {
  assert.equal(eventSource({}), "frontrow");
  assert.equal(eventSource({ source: "internal" }), "frontrow");
  assert.equal(eventSource({ source: "ticketmaster" }), "ticketmaster");
  assert.equal(eventSource({ source: "partner" }), "other");
  assert.deepEqual(names(applyFilters(events, { ...DEFAULT_FILTERS, source: "ticketmaster" })), ["Imported Rock"]);
  assert.ok(!names(applyFilters(events, { ...DEFAULT_FILTERS, source: "frontrow" })).includes("Partner"));
  assert.equal(applyFilters(events, DEFAULT_FILTERS).length, events.length);
});

test("search is case-insensitive across name, artist, city, genre and venue", () => {
  const list = [ev({ name: "A", venue: "Sala Apolo" }), ev({ name: "B", artist: "ROSALÍA" }), ev({ name: "C", genre: "Catalan" })];
  assert.deepEqual(names(applyFilters(list, { ...DEFAULT_FILTERS, search: "  apolo " })), ["A"]);
  assert.deepEqual(names(applyFilters(list, { ...DEFAULT_FILTERS, search: "rosalía" })), ["B"]);
  assert.deepEqual(names(applyFilters(list, { ...DEFAULT_FILTERS, search: "CATALAN" })), ["C"]);
});

test("cities are unique, case-insensitive, sorted and skip unknown values", () => {
  const list = [...events, ev({ city: "Unknown city" }), ev({ city: "  " }), ev({ city: "BARCELONA" })];
  assert.deepEqual(cityOptions(list), [
    { value: "barcelona", label: "Barcelona" },
    { value: "girona", label: "Girona" },
    { value: "madrid", label: "Madrid" },
  ]);
  assert.equal(cityKey("Unknown city"), null);
  assert.deepEqual(names(applyFilters(events, { ...DEFAULT_FILTERS, city: "barcelona" })),
    ["Rock Night", "Big Rock", "Imported Rock", "Jazz"]);
});

test("prices are only compared in EUR and missing prices are never €0", () => {
  assert.equal(comparablePrice(ev({ price: 25 })), 25);
  assert.equal(comparablePrice(ev({ price: 0 })), 0);
  assert.equal(comparablePrice(ev({ source: "ticketmaster", price: 25 })), null);
  assert.equal(comparablePrice(ev({ source: "ticketmaster", price: 25, currency: "EUR" })), 25);
  assert.equal(comparablePrice(ev({ price: 25, currency: "GBP" })), null);
  assert.equal(comparablePrice(ev({})), null);
  assert.equal(priceCeiling(events), 70);
  assert.equal(priceCeiling([ev({ price: 0 })]), 5);
  assert.equal(priceCeiling([ev({ source: "ticketmaster" })]), null);
});

test("a maximum price hides unknown prices unless they are included", () => {
  const filters = { ...DEFAULT_FILTERS, maxPrice: 20 };
  assert.deepEqual(names(applyFilters(events, filters)), ["Rock Madrid", "Jazz", "Catalan Folk"]);
  assert.equal(hiddenUnpricedCount(events, filters), 2);
  assert.deepEqual(names(applyFilters(events, { ...filters, includeUnpriced: true })),
    ["Rock Madrid", "Imported Rock", "Jazz", "Catalan Folk", "Partner"]);
  assert.equal(hiddenUnpricedCount(events, { ...filters, includeUnpriced: true }), 0);
});

test("all filters combine instead of overwriting each other", () => {
  const filters = { search: "Rock", city: "barcelona", maxPrice: 50, includeUnpriced: false, source: "frontrow" };
  assert.deepEqual(names(applyFilters(events, filters)), ["Rock Night"]);
  assert.ok(hasActiveFilters(filters));
  assert.ok(!hasActiveFilters(DEFAULT_FILTERS));
});

test("event dates are shown in Spanish time and invalid dates are kept", () => {
  assert.equal(formatEventDate("2026-12-12"), "Sat, 12 Dec 2026");
  assert.equal(formatEventDate("2026-12-12T20:30:00Z"), "Sat, 12 Dec 2026 · 21:30");
  assert.equal(formatEventDate("TBA"), "TBA");
});
