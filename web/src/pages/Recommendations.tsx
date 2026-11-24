
import { useEffect, useState } from "react";
import EventCard, { type Event } from "../components/EventCard";
import { getRecommendations } from "../services/api";
import { upcomingEvents } from "../utils/events";
import { mediaFields } from "../utils/eventMedia";

type RecommendedEvent = Event & {
  score: number;
  reasons: string[];
};

const demoMode = import.meta.env.VITE_DEMO_MODE === "true";

// Sample recommendations for local development only.
const demoRecommendations: RecommendedEvent[] = [
  {
    id: "demo-1",
    name: "Indie Night Barcelona",
    artist: "Various Artists",
    city: "Barcelona",
    date: "2026-12-12",
    price: 25,
    genre: "Indie",
    source: "sample",
    score: 6,
    reasons: ["you like indie", "in Barcelona", "fits your budget"],
  },
  {
    id: "demo-2",
    name: "Electronic Music Festival",
    artist: "Various DJs",
    city: "Madrid",
    date: "2026-12-19",
    price: 45,
    genre: "Electronic",
    source: "sample",
    score: 4,
    reasons: ["you like electronic", "fits your budget"],
  },
];

function normalizeRecommendation(value: unknown): RecommendedEvent {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid recommendation");
  }

  const record = value as Record<string, unknown>;
  const id = record.eventId ?? record.id;

  if (
    typeof id !== "string" ||
    typeof record.name !== "string" ||
    typeof record.date !== "string"
  ) {
    throw new Error("Missing required event information");
  }

  const price =
    record.price === undefined || record.price === null
      ? undefined
      : Number(record.price);

  return {
    ...mediaFields(record),
    id,
    name: record.name,
    artist: typeof record.artist === "string"
      ? record.artist
      : record.name,
    city: typeof record.city === "string"
      ? record.city
      : "Unknown city",
    date: record.date,
    venue: typeof record.venue === "string"
      ? record.venue
      : undefined,
    genre: typeof record.genre === "string"
      ? record.genre
      : undefined,
    price: price !== undefined && Number.isFinite(price)
      ? price
      : undefined,
    source: typeof record.source === "string"
      ? record.source
      : undefined,
    externalUrl: typeof record.externalUrl === "string" &&
      /^https?:\/\//i.test(record.externalUrl)
      ? record.externalUrl
      : undefined,
    capacity: record.capacity !== undefined && record.capacity !== null &&
      Number.isSafeInteger(Number(record.capacity)) && Number(record.capacity) >= 0
      ? Number(record.capacity)
      : undefined,
    score: typeof record.score === "number"
      ? record.score
      : 0,
    reasons: Array.isArray(record.reasons)
      ? record.reasons.filter(
          (reason): reason is string => typeof reason === "string"
        )
      : [],
  };
}

export default function Recommendations({ onBuy }: { onBuy?: (event: Event) => void }) {
  const [events, setEvents] = useState<RecommendedEvent[]>(
    demoMode ? demoRecommendations : []
  );
  const [loading, setLoading] = useState(!demoMode);
  const [error, setError] = useState("");

  useEffect(() => {
    if (demoMode) return;

    let active = true;

    async function loadRecommendations() {
      try {
        const response = await getRecommendations();

        if (!Array.isArray(response)) {
          throw new Error("Invalid recommendations response");
        }

        const normalized = response.map(normalizeRecommendation);

        if (active) setEvents(normalized);
      } catch (err) {
        if (active) {
          setError(
            err instanceof Error
              ? err.message
              : "Unable to load recommendations"
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadRecommendations();

    return () => {
      active = false;
    };
  }, []);

  const upcoming = upcomingEvents(events);

  return (
    <main className="container">
      <section className="hero">
        <p className="hero-kicker">Picked for your taste</p>
        <h1>Recommended for You</h1>
        <p>
          Discover concerts that match your music taste.
        </p>
      </section>

      {demoMode && (
        <p>Demo mode — showing example recommendations.</p>
      )}

      {loading && <p>Finding your concerts...</p>}

      {error && <p role="alert">{error}</p>}

      {!loading && !error && (
        <>
          <div className="event-grid">
            {upcoming.map((event) => (
              <div key={event.id}>
                <EventCard event={event} onBuy={onBuy} />

                <div className="recommendation-reasons">
                  <strong>Why we recommend this:</strong>
                  <p>
                    {event.reasons.join(" · ") || "Upcoming event"}
                  </p>
                  <small>Match score: {event.score}</small>
                </div>
              </div>
            ))}
          </div>

          {upcoming.length === 0 && (
            <p>No recommendations available yet.</p>
          )}
        </>
      )}
    </main>
  );
}
