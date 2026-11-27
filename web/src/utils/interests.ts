// Helpers for the interests survey. Pure functions so they can be unit tested.
import { CATEGORIES } from "./eventMedia.ts";
import { eventSource } from "./eventFilters.ts";

/** How many associations a user can follow (the preferences Lambda keeps 20). */
export const MAX_FOLLOWED = 10;

/**
 * Saved interests (lowercase values) as category labels to preselect.
 * Values that are not categories come from the old music survey
 * ("jazz", "pop"...), so they preselect Music.
 */
export function savedInterests(saved: unknown): string[] {
  if (!Array.isArray(saved)) return [];
  const labels = new Set<string>();
  for (const value of saved) {
    if (typeof value !== "string" || !value.trim()) continue;
    const match = CATEGORIES.find((c) => c.toLowerCase() === value.trim().toLowerCase());
    labels.add(match ?? "Music");
  }
  return CATEGORIES.filter((c) => labels.has(c));
}

/** Associations that publish events on FRONT ROW, sorted, without duplicates. */
export function associationOptions(events: readonly unknown[]): string[] {
  const names = new Map<string, string>();
  for (const event of events) {
    if (!event || typeof event !== "object") continue;
    const record = event as { artist?: unknown; source?: string };
    if (eventSource(record) !== "frontrow" || typeof record.artist !== "string") continue;
    const name = record.artist.trim().replace(/\s+/g, " ");
    if (name && !names.has(name.toLowerCase())) names.set(name.toLowerCase(), name);
  }
  return [...names.values()].sort((a, b) => a.localeCompare(b, "es", { sensitivity: "base" }));
}

/** Followed associations: picked chips first, then typed names, no duplicates. */
export function followedList(picked: readonly string[], typed: string): string[] {
  const out = new Map<string, string>();
  for (const name of [...picked, ...typed.split(",")]) {
    const clean = name.trim().replace(/\s+/g, " ");
    if (clean && !out.has(clean.toLowerCase())) out.set(clean.toLowerCase(), clean);
  }
  return [...out.values()].slice(0, MAX_FOLLOWED);
}
