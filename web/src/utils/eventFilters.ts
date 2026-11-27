// Discover Events filters. Pure functions so they can be unit tested with Node.
//
// Data model notes (checked against the events table):
// - source is "barcelona_open_data" for events imported from the Barcelona city
//   agenda, "ticketmaster" for the legacy import (being removed), and "internal"
//   or missing for events published on FRONT ROW by ESADE associations. External
//   events are only shown with a link; Front Row events are sold in the app. Any
//   other value is unknown and only appears under "All Events".
// - Front Row prices are stored without a currency and are sold in euros.
//   External prices only count when the record states its currency.
// - Prices are only compared in EUR. When a maximum price is set, events without a
//   known EUR price (no price, or another currency) are hidden unless the user ticks
//   "Include events without a listed price". They are never treated as €0.

export type SourceFilter = "all" | "frontrow" | "ticketmaster" | "barcelona";

/** Sources whose tickets are sold elsewhere (we only show them). */
export const EXTERNAL_SOURCES = ["ticketmaster", "barcelona_open_data"];

export type EventFilters = {
  search: string;
  city: string; // "" = all locations, otherwise a cityKey()
  maxPrice: number | null; // null = any price
  includeUnpriced: boolean;
  source: SourceFilter;
};

export type FilterableEvent = {
  name: string;
  artist: string;
  city: string;
  genre?: string;
  venue?: string;
  price?: number;
  currency?: string;
  source?: string;
};

export const DEFAULT_FILTERS: EventFilters = {
  search: "",
  city: "",
  maxPrice: null,
  includeUnpriced: false,
  source: "all",
};

export const UNKNOWN_CITY = "Unknown city";
export const PRICE_CURRENCY = "EUR";

export function eventSource(event: { source?: string }): "frontrow" | "ticketmaster" | "barcelona" | "other" {
  if (event.source === "ticketmaster") return "ticketmaster";
  if (event.source === "barcelona_open_data") return "barcelona";
  if (event.source === undefined || event.source === "internal") return "frontrow";
  return "other";
}

/** Normalised key for a city, or null when the city is missing or invalid. */
export function cityKey(city: string | undefined): string | null {
  if (typeof city !== "string") return null;
  const clean = city.trim().replace(/\s+/g, " ");
  if (!clean || clean.toLowerCase() === UNKNOWN_CITY.toLowerCase()) return null;
  return clean.toLocaleLowerCase("es");
}

/** Unique cities sorted alphabetically; the most common spelling is shown. */
export function cityOptions(events: readonly FilterableEvent[]): { value: string; label: string }[] {
  const spellings = new Map<string, Map<string, number>>();
  for (const event of events) {
    const key = cityKey(event.city);
    if (!key) continue;
    const label = event.city.trim().replace(/\s+/g, " ");
    const counts = spellings.get(key) ?? new Map<string, number>();
    counts.set(label, (counts.get(label) ?? 0) + 1);
    spellings.set(key, counts);
  }
  return [...spellings.entries()]
    .map(([value, counts]) => ({
      value,
      label: [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "es"))[0][0],
    }))
    .sort((a, b) => a.label.localeCompare(b.label, "es", { sensitivity: "base" }));
}

/** The event's price in EUR, or null when it is unknown or in another currency. */
export function comparablePrice(event: FilterableEvent): number | null {
  const { price } = event;
  if (typeof price !== "number" || !Number.isFinite(price) || price < 0) return null;
  const currency = event.currency ?? (eventSource(event) === "frontrow" ? PRICE_CURRENCY : undefined);
  return currency === PRICE_CURRENCY ? price : null;
}

/** Slider upper limit: the highest EUR price rounded up to the next €5, or null. */
export function priceCeiling(events: readonly FilterableEvent[]): number | null {
  const prices = events.map(comparablePrice).filter((price): price is number => price !== null);
  if (prices.length === 0) return null;
  return Math.max(5, Math.ceil(Math.max(...prices) / 5) * 5);
}

export function matchesSearch(event: FilterableEvent, search: string): boolean {
  const query = search.trim().toLocaleLowerCase("es");
  if (!query) return true;
  return [event.name, event.artist, event.city, event.genre ?? "", event.venue ?? ""]
    .join(" ")
    .toLocaleLowerCase("es")
    .includes(query);
}

export function matchesFilters(event: FilterableEvent, filters: EventFilters): boolean {
  if (!matchesSearch(event, filters.search)) return false;
  if (filters.city && cityKey(event.city) !== filters.city) return false;
  if (filters.source !== "all" && eventSource(event) !== filters.source) return false;
  if (filters.maxPrice !== null) {
    const price = comparablePrice(event);
    if (price === null) return filters.includeUnpriced;
    if (price > filters.maxPrice) return false;
  }
  return true;
}

/** Applies every filter together and keeps the input order. */
export function applyFilters<T extends FilterableEvent>(events: readonly T[], filters: EventFilters): T[] {
  return events.filter((event) => matchesFilters(event, filters));
}

/** Events that only the price filter hides because their EUR price is unknown. */
export function hiddenUnpricedCount(events: readonly FilterableEvent[], filters: EventFilters): number {
  if (filters.maxPrice === null || filters.includeUnpriced) return 0;
  const withoutPrice = { ...filters, maxPrice: null };
  return events.filter((event) => comparablePrice(event) === null && matchesFilters(event, withoutPrice)).length;
}

export function hasActiveFilters(filters: EventFilters): boolean {
  return Boolean(filters.search.trim()) || filters.city !== "" || filters.maxPrice !== null || filters.source !== "all";
}

const dayFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Madrid", weekday: "short", day: "numeric", month: "short", year: "numeric",
});
const timeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Madrid", hour: "2-digit", minute: "2-digit",
});

/** Readable event date in Spanish time, falling back to the stored value. */
export function formatEventDate(date: string): string {
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(date);
  const timestamp = Date.parse(dateOnly ? `${date}T12:00:00Z` : date);
  if (!Number.isFinite(timestamp)) return date;
  const day = dayFormat.format(timestamp);
  return dateOnly ? day : `${day} · ${timeFormat.format(timestamp)}`;
}
