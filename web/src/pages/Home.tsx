
import { useEffect, useMemo, useState } from "react";
import EventCard, { type Event } from "../components/EventCard";
import { getEvents } from "../services/api";
import { upcomingEvents } from "../utils/events";
import { mediaFields } from "../utils/eventMedia";
import {
  DEFAULT_FILTERS, UNKNOWN_CITY, applyFilters, cityOptions, hasActiveFilters,
  hiddenUnpricedCount, priceCeiling, type EventFilters, type SourceFilter,
} from "../utils/eventFilters";

// Use sample events locally until AWS is connected.
const demoMode = import.meta.env.VITE_DEMO_MODE === "true";

// Demo events for testing the purchase interface.
const sampleEvents: Event[] = [
  {
    id: "1",
    name: "Indie Night Barcelona",
    artist: "Various Artists",
    city: "Barcelona",
    date: "2026-12-12",
    price: 25,
    genre: "Indie",
    source: "internal",
    capacity: 50,
  },
  {
    id: "2",
    name: "Electronic Music Festival",
    artist: "Various DJs",
    city: "Madrid",
    date: "2026-12-19",
    price: 45,
    genre: "Electronic",
    source: "internal",
    capacity: 50,
  },
  {
    id: "3",
    name: "Live Jazz Sessions",
    artist: "Jazz Collective",
    city: "Valencia",
    date: "2027-01-16",
    price: 20,
    genre: "Jazz",
    source: "internal",
    capacity: 50,
  },
];

// Convert DynamoDB event records to the React Event format.
function normalizeEvent(value: unknown): Event {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid event record");
  }

  const record = value as Record<string, unknown>;
  const id = record.eventId ?? record.id;

  if (
    typeof id !== "string" ||
    typeof record.name !== "string" ||
    typeof record.date !== "string"
  ) {
    throw new Error("Event is missing required fields");
  }

  const numericPrice =
    record.price === undefined || record.price === null
      ? undefined
      : Number(record.price);

  const numericCapacity =
    record.capacity === undefined || record.capacity === null
      ? undefined
      : Number(record.capacity);

  return {
    ...mediaFields(record),
    id,
    name: record.name,

    artist:
      typeof record.artist === "string"
        ? record.artist
        : record.name,

    city:
      typeof record.city === "string"
        ? record.city
        : UNKNOWN_CITY,

    date: record.date,

    venue:
      typeof record.venue === "string"
        ? record.venue
        : undefined,

    genre:
      typeof record.genre === "string"
        ? record.genre
        : undefined,

    price:
      numericPrice !== undefined &&
      Number.isFinite(numericPrice)
        ? numericPrice
        : undefined,

    source:
      typeof record.source === "string"
        ? record.source
        : undefined,

    externalUrl:
      typeof record.externalUrl === "string" &&
      /^https?:\/\//i.test(record.externalUrl)
        ? record.externalUrl
        : undefined,

    capacity:
      numericCapacity !== undefined &&
      Number.isSafeInteger(numericCapacity) &&
      numericCapacity >= 0
        ? numericCapacity
        : undefined,
    available: typeof record.available === "number" && Number.isSafeInteger(record.available) && record.available >= 0 ? record.available : undefined,
  };
}


type HomeProps = {
  onBuy?: (event: Event) => void;
};

const SOURCE_OPTIONS: { value: SourceFilter; label: string }[] = [
  { value: "all", label: "All Events" },
  { value: "frontrow", label: "Front Row Events" },
  { value: "ticketmaster", label: "Ticketmaster Events" },
];

const euro = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

export default function Home({ onBuy }: HomeProps) {
  const [events, setEvents] = useState<Event[]>(
    demoMode ? sampleEvents : []
  );

  const [filters, setFilters] = useState<EventFilters>(DEFAULT_FILTERS);
  const [loading, setLoading] = useState(!demoMode);
  const [error, setError] = useState<string | null>(null);

  // Load actual events from API Gateway when demo mode is disabled.
  useEffect(() => {
    if (demoMode) return;

    let active = true;

    async function loadEvents() {
      try {
        const data = await getEvents();
        const normalized = data.map(normalizeEvent);

        if (active) {
          setEvents(normalized);
          setError(null);
        }
      } catch (err) {
        if (active) {
          setError(
            err instanceof Error
              ? err.message
              : "Unable to load events"
          );
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadEvents();

    return () => {
      active = false;
    };
  }, []);

  // Past events are excluded and the rest sorted by date before any filter runs.
  const upcoming = useMemo(() => upcomingEvents(events), [events]);
  const cities = useMemo(() => cityOptions(upcoming), [upcoming]);
  const ceiling = useMemo(() => priceCeiling(upcoming), [upcoming]);

  // A maximum above the current ceiling means "any price".
  const effective: EventFilters =
    filters.maxPrice !== null && (ceiling === null || filters.maxPrice >= ceiling)
      ? { ...filters, maxPrice: null }
      : filters;

  const filteredEvents = applyFilters(upcoming, effective);
  const hiddenUnpriced = hiddenUnpricedCount(upcoming, effective);
  const filtersActive = hasActiveFilters(effective);
  const cityLabel = cities.find((city) => city.value === effective.city)?.label;

  function update(changes: Partial<EventFilters>) {
    setFilters((current) => ({ ...current, ...changes }));
  }

  const chips: { label: string; clear: () => void }[] = [];
  if (effective.search.trim()) chips.push({ label: `“${effective.search.trim()}”`, clear: () => update({ search: "" }) });
  if (cityLabel) chips.push({ label: cityLabel, clear: () => update({ city: "" }) });
  if (effective.maxPrice !== null) chips.push({ label: `Up to ${euro.format(effective.maxPrice)}`, clear: () => update({ maxPrice: null }) });
  if (effective.source !== "all") {
    const label = SOURCE_OPTIONS.find((option) => option.value === effective.source)?.label ?? "";
    chips.push({ label, clear: () => update({ source: "all" }) });
  }

  return (
    <main className="container">
      <section className="hero">
        <p className="hero-kicker">Live music across Spain</p>
        <h1>Find your next live experience.</h1>
        <p>Concerts from FRONT ROW artists and Ticketmaster, all in one place.</p>
      </section>

      <section className="filters" aria-labelledby="filters-title">
        <h2 id="filters-title" className="visually-hidden">Filter events</h2>

        <div className="filter-search">
          <label htmlFor="event-search">Search</label>
          <input
            id="event-search"
            type="search"
            placeholder="Artist, event, city, genre or venue…"
            value={filters.search}
            onChange={(event) => update({ search: event.target.value })}
          />
        </div>

        <div className="filter-row">
          <div className="filter-field">
            <label htmlFor="event-location">Location</label>
            <select
              id="event-location"
              value={effective.city}
              onChange={(event) => update({ city: event.target.value })}
            >
              <option value="">All locations</option>
              {cities.map((city) => (
                <option key={city.value} value={city.value}>{city.label}</option>
              ))}
            </select>
          </div>

          <div className="filter-field filter-price">
            <div className="filter-price-head">
              <label htmlFor="event-price">
                Maximum price: <strong>{effective.maxPrice === null ? "Any" : euro.format(effective.maxPrice)}</strong>
              </label>
              <button
                type="button"
                className="link-button"
                disabled={effective.maxPrice === null}
                onClick={() => update({ maxPrice: null })}
              >
                Any price
              </button>
            </div>
            {ceiling === null ? (
              <p className="filter-hint">No event prices available to filter.</p>
            ) : (
              <>
                <input
                  id="event-price"
                  type="range"
                  min={0}
                  max={ceiling}
                  step={1}
                  value={effective.maxPrice ?? ceiling}
                  aria-valuetext={effective.maxPrice === null ? "Any price" : `Up to ${euro.format(effective.maxPrice)}`}
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    update({ maxPrice: value >= ceiling ? null : value });
                  }}
                />
                <div className="range-scale" aria-hidden="true">
                  <span>{euro.format(0)}</span>
                  <span>{euro.format(ceiling)}+</span>
                </div>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={filters.includeUnpriced}
                    disabled={effective.maxPrice === null}
                    onChange={(event) => update({ includeUnpriced: event.target.checked })}
                  />
                  Include events without a listed price
                </label>
              </>
            )}
          </div>

          <fieldset className="filter-field segmented">
            <legend>Source</legend>
            <div className="segmented-options">
              {SOURCE_OPTIONS.map((option) => (
                <label key={option.value} className={effective.source === option.value ? "is-selected" : undefined}>
                  <input
                    type="radio"
                    name="event-source"
                    value={option.value}
                    checked={effective.source === option.value}
                    onChange={() => update({ source: option.value })}
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </fieldset>
        </div>

        <div className="filter-status">
          <p role="status" aria-live="polite" className="result-count">
            {loading
              ? "Loading events…"
              : `${filteredEvents.length} ${filteredEvents.length === 1 ? "event" : "events"}`}
            {hiddenUnpriced > 0 && !loading && (
              <span className="filter-hint">
                {" "}· {hiddenUnpriced} without a listed price hidden by the price filter
              </span>
            )}
          </p>

          {chips.length > 0 && (
            <ul className="chips" aria-label="Active filters">
              {chips.map((chip) => (
                <li key={chip.label}>
                  <button type="button" className="chip" onClick={chip.clear}>
                    {chip.label}
                    <span aria-hidden="true"> ×</span>
                    <span className="visually-hidden"> (remove filter)</span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          <button
            type="button"
            className="btn btn-ghost btn-small"
            disabled={!filtersActive && !filters.includeUnpriced}
            onClick={() => setFilters(DEFAULT_FILTERS)}
          >
            Clear all filters
          </button>
        </div>
      </section>

      <section aria-labelledby="events-title">
        <h2 id="events-title" className="section-title">Upcoming events</h2>

        {demoMode && (
          <p className="notice">Demo mode — displaying sample events.</p>
        )}

        {error && (
          <p className="notice notice-error" role="alert">
            Unable to load events: {error}
          </p>
        )}

        {!loading && !error && (
          <>
            <div className="event-grid">
              {filteredEvents.map((event) => (
                <EventCard
                  key={event.id}
                  event={event}
                  onBuy={onBuy}
                />
              ))}
            </div>

            {filteredEvents.length === 0 && (
              <div className="empty-state">
                {upcoming.length === 0 ? (
                  <>
                    <h3>No upcoming events yet</h3>
                    <p>New concerts are added regularly. Check back soon.</p>
                  </>
                ) : (
                  <>
                    <h3>No events match your filters</h3>
                    <p>Try another location, a higher maximum price or a different search.</p>
                    <button type="button" className="btn btn-primary" onClick={() => setFilters(DEFAULT_FILTERS)}>
                      Clear all filters
                    </button>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </section>
    </main>
  );
}
