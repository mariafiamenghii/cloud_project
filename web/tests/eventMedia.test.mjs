import assert from "node:assert/strict";
import test from "node:test";
import { CATEGORIES, categoryLabel, categoryTone, imageError, mediaFields, formatEventPrice } from "../src/utils/eventMedia.ts";

test("every category has a placeholder colour; old or missing values keep the dark one", () => {
  for (const c of CATEGORIES) assert.notEqual(categoryTone(c.toLowerCase()), "none", c);
  assert.equal(categoryTone(" Social Impact "), "impact");
  assert.equal(categoryTone("jazz"), "none");
  assert.equal(categoryTone(undefined), "none");
});

test("category labels show the display name; old values and missing ones still display", () => {
  assert.equal(categoryLabel("finance"), "Finance");
  assert.equal(categoryLabel(" Networking "), "Networking");
  assert.equal(categoryLabel("jazz"), "jazz");
  assert.equal(categoryLabel(""), "Event");
  assert.equal(categoryLabel(undefined), "Event");
});

test("shared categories cover ESADE association topics and city culture", () => {
  for (const c of ["Consulting", "Finance", "Luxury", "Networking", "Food", "Music", "Theatre", "Art", "Talks", "Family"]) {
    assert.ok(CATEGORIES.includes(c), c);
  }
  for (const old of ["Pop", "Rock", "Reggaeton", "Catalan"]) assert.ok(!CATEGORIES.includes(old), old);
});
test("categories become unique, single-word lowercase stored values", () => {
  const stored = CATEGORIES.map(c => c.toLowerCase());
  assert.equal(new Set(stored).size, CATEGORIES.length);
  for (const value of stored) assert.match(value, /^[a-z]+( [a-z]+)*$/);
});
test("image type and size validation", () => {
  for (const type of ["image/jpeg", "image/png", "image/webp"]) assert.equal(imageError({type, size: 1024}), "");
  assert.match(imageError({type: "image/svg+xml", size: 100}), /JPEG/);
  assert.match(imageError({type: "image/png", size: 5242881}), /5 MB/);
});
test("media normalization propagates images, credits and currency safely", () => {
  assert.deepEqual(mediaFields({imageUrl: "https://image.example/a", imageAttribution: "Credit", currency: "USD"}),
    {imageUrl: "https://image.example/a", imageAttribution: "Credit", currency: "USD"});
  assert.equal(mediaFields({imageUrl: "javascript:alert(1)"}).imageUrl, undefined);
});
test("official currencies are formatted; missing external prices use provider copy", () => {
  assert.equal(formatEventPrice(25, "EUR", true), "From €25.00");
  assert.ok(!formatEventPrice(25, "USD", true).includes("€"));
  assert.equal(formatEventPrice(undefined, undefined, true), "See price on Ticketmaster");
  assert.equal(formatEventPrice(25, undefined, true), "See price on Ticketmaster");
  assert.equal(formatEventPrice(25, undefined, false), "From €25.00");
  assert.equal(formatEventPrice(0, "EUR", true), "Free");
  assert.equal(formatEventPrice(0, undefined, true, "the official site"), "See price on the official site");
});
