import assert from "node:assert/strict";
import test from "node:test";
import { MAX_FOLLOWED, associationOptions, followedList, savedInterests } from "../src/utils/interests.ts";

test("saved interests preselect categories; old music genres preselect Music", () => {
  assert.deepEqual(savedInterests(["finance", "food"]), ["Finance", "Food"]);
  assert.deepEqual(savedInterests(["jazz", "pop", "music"]), ["Music"]);
  assert.deepEqual(savedInterests(["networking", "rock"]), ["Networking", "Music"]);
  assert.deepEqual(savedInterests(undefined), []);
  assert.deepEqual(savedInterests([" ", 3]), []);
});

test("association options come only from Front Row events, without duplicates", () => {
  const events = [
    { artist: "ESADE Finance Club" },
    { artist: "esade finance club ", source: "internal" },
    { artist: "ESADE Tech Club" },
    { artist: "Palau de la Música", source: "barcelona_open_data" },
    { artist: "Old import", source: "ticketmaster" },
    { name: "no association" },
    null,
  ];
  assert.deepEqual(associationOptions(events), ["ESADE Finance Club", "ESADE Tech Club"]);
});

test("followed list merges chips and typed names, without duplicates, up to the limit", () => {
  assert.deepEqual(followedList(["ESADE Finance Club"], " esade finance club, ESADE Tech Club ,,"),
    ["ESADE Finance Club", "ESADE Tech Club"]);
  const many = Array.from({ length: 15 }, (_, i) => `Club ${i}`);
  assert.equal(followedList(many, "").length, MAX_FOLLOWED);
});
