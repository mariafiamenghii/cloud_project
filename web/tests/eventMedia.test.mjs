import assert from "node:assert/strict";
import test from "node:test";
import { GENRES, imageError, mediaFields, formatEventPrice } from "../src/utils/eventMedia.ts";

test("shared genre options preserve all existing genres and include Catalan", () => {
  assert.equal(GENRES.length, 11);
  assert.ok(GENRES.includes("Catalan"));
  assert.equal(GENRES.find(g => g === "Catalan").toLowerCase(), "catalan");
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
});
