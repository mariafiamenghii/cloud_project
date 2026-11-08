
import { useState } from "react";
import EventCard, { type Event } from "../components/EventCard";

const sampleEvents: Event[] = [
  {
    id: "1",
    name: "Indie Night Barcelona",
    artist: "Various Artists",
    city: "Barcelona",
    date: "2026-12-12",
    price: 25,
    genre: "Indie",
  },
  {
    id: "2",
    name: "Electronic Music Festival",
    artist: "Various DJs",
    city: "Madrid",
    date: "2026-12-19",
    price: 45,
    genre: "Electronic",
  },
  {
    id: "3",
    name: "Live Jazz Sessions",
    artist: "Jazz Collective",
    city: "Valencia",
    date: "2027-01-16",
    price: 20,
    genre: "Jazz",
  },
];

export default function Home() {
  const [search, setSearch] = useState("");

  const filteredEvents = sampleEvents.filter((event) =>
    `${event.name} ${event.artist} ${event.city} ${event.genre}`
      .toLowerCase()
      .includes(search.toLowerCase())
  );

  return (
    <main className="container">
      <header className="site-header">
        <h1>Ticketing</h1>
        <nav>Discover events</nav>
      </header>

      <section className="hero">
        <h2>Find your next live experience.</h2>
        <p>Discover concerts and events across Spain.</p>

        <input
          type="search"
          placeholder="Search by artist, city or genre..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </section>

      <section>
        <h2>Upcoming Events</h2>

        <div className="event-grid">
          {filteredEvents.map((event) => (
            <EventCard key={event.id} event={event} />
          ))}
        </div>

        {filteredEvents.length === 0 && (
          <p>No matching events found.</p>
        )}
      </section>
    </main>
  );
}
