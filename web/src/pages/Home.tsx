
import { useEffect, useState } from "react";
import EventCard, { type Event } from "../components/EventCard";
import { getEvents } from "../services/api";
import { upcomingEvents } from "../utils/events";

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
    id,
    name: record.name,

    artist:
      typeof record.artist === "string"
        ? record.artist
        : record.name,

    city:
      typeof record.city === "string"
        ? record.city
        : "Unknown city",

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
  };
}

type HomeProps = {
  onBuy?: (event: Event) => void;
};

export default function Home({ onBuy }: HomeProps) {
  const [events, setEvents] = useState<Event[]>(
    demoMode ? sampleEvents : []
  );

  const [search, setSearch] = useState("");
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

  // Search events by name, artist, city, genre or venue.
  const filteredEvents = upcomingEvents(events).filter((event) =>
    [
      event.name,
      event.artist,
      event.city,
      event.genre ?? "",
      event.venue ?? "",
    ]
      .join(" ")
      .toLowerCase()
      .includes(search.trim().toLowerCase())
  );

  return (
    <main className="container">
      <header className="site-header">
        <h1>Ticketing</h1>
        <nav>Discover events</nav>
      </header>

      <section className="hero">
        <h2>Find your next live experience.</h2>

        <p>
          Discover concerts and events across Spain.
        </p>

        <input
          type="search"
          placeholder="Search by artist, city or genre..."
          aria-label="Search events"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </section>

      <section>
        <h2>Upcoming Events</h2>

        {demoMode && (
          <p>Demo mode — displaying sample events.</p>
        )}

        {loading && (
          <p role="status">Loading events...</p>
        )}

        {error && (
          <p role="alert">
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
              <p>No matching events found.</p>
            )}
          </>
        )}
      </section>
    </main>
  );
}
