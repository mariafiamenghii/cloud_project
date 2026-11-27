import assert from "node:assert/strict";
import test from "node:test";
import {
  ESADE_ASSOCIATIONS, MAX_FOLLOWED, associationOptions, followedList, savedInterests, surveyAssociations,
} from "../src/utils/interests.ts";

test("saved interests preselect categories; old music genres preselect Music", () => {
  assert.deepEqual(savedInterests(["finance", "food"]), ["Finance", "Food"]);
  assert.deepEqual(savedInterests(["jazz", "pop", "music"]), ["Music"]);
  assert.deepEqual(savedInterests(["networking", "rock"]), ["Networking", "Music"]);
  assert.deepEqual(savedInterests(["social impact", "career development"]), ["Social Impact", "Career Development"]);
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

test("survey always offers the ESADE associations first, then other publishers once", () => {
  const options = surveyAssociations(["esade sports", "Tech Club"]);
  assert.deepEqual(options.slice(0, ESADE_ASSOCIATIONS.length), ESADE_ASSOCIATIONS);
  assert.deepEqual(options.slice(ESADE_ASSOCIATIONS.length), ["Tech Club"]);
  assert.deepEqual(surveyAssociations([]), ESADE_ASSOCIATIONS);
  assert.equal(MAX_FOLLOWED, 5);
});

test("followed list merges chips and typed names, without duplicates, up to the limit", () => {
  assert.deepEqual(followedList(["ESADE Finance Club"], " esade finance club, ESADE Tech Club ,,"),
    ["ESADE Finance Club", "ESADE Tech Club"]);
  const many = Array.from({ length: 15 }, (_, i) => `Club ${i}`);
  assert.equal(followedList(many, "").length, MAX_FOLLOWED);
});
