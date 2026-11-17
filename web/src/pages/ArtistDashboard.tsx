
import { useState, type FormEvent } from "react";
import {
  createEvent,
  type CreateEventInput,
} from "../services/api";

const demoMode = import.meta.env.VITE_DEMO_MODE === "true";

const genres = [
  "Pop",
  "Rock",
  "Indie",
  "Electronic",
  "Hip-Hop",
  "Reggaeton",
  "Jazz",
  "Classical",
  "R&B",
  "Latin",
];

export default function ArtistDashboard() {
  const [name, setName] = useState("");
  const [artist, setArtist] = useState("");
  const [city, setCity] = useState("Barcelona");
  const [venue, setVenue] = useState("");
  const [date, setDate] = useState("");
  const [genre, setGenre] = useState("");
  const [price, setPrice] = useState("");
  const [capacity, setCapacity] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [createdEventId, setCreatedEventId] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setError("");
    setSuccessMessage("");
    setCreatedEventId("");

    const numericPrice = Number(price);
    const numericCapacity = Number(capacity);

    if (
      !name.trim() ||
      !city.trim() ||
      !date ||
      price.trim() === "" ||
      capacity.trim() === ""
    ) {
      setError("Please complete all required fields.");
      return;
    }

    if (!Number.isFinite(numericPrice) || numericPrice < 0) {
      setError("Please enter a valid ticket price.");
      return;
    }

    if (
      !Number.isSafeInteger(numericCapacity) ||
      numericCapacity < 1
    ) {
      setError("Capacity must be a positive whole number.");
      return;
    }

    const eventData: CreateEventInput = {
      name: name.trim(),
      city: city.trim(),
      date,
      price: numericPrice,
      capacity: numericCapacity,
      ...(artist.trim() && { artist: artist.trim() }),
      ...(venue.trim() && { venue: venue.trim() }),
      ...(genre && { genre: genre.toLowerCase() }),
    };

    setLoading(true);

    try {
      if (demoMode) {
        const demoId = `demo-event-${crypto.randomUUID()}`;

        console.log("Demo event:", eventData);

        setCreatedEventId(demoId);
        setSuccessMessage(
          "Demo event created! This event was not saved to AWS."
        );
      } else {
        const result = await createEvent(eventData);

        setCreatedEventId(result.eventId);
        setSuccessMessage(
          "Your event was successfully published."
        );
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to create event. Please try again."
      );
    } finally {
      setLoading(false);
    }
  }

  function resetForm() {
    setName("");
    setArtist("");
    setCity("Barcelona");
    setVenue("");
    setDate("");
    setGenre("");
    setPrice("");
    setCapacity("");
    setError("");
    setSuccessMessage("");
    setCreatedEventId("");
  }

  return (
    <main className="artist-container">
      <section className="artist-header">
        <h1>Artist Dashboard</h1>
        <p>
          Create and publish your events on our ticketing platform.
        </p>
      </section>

      {demoMode && (
        <p className="artist-demo-notice">
          Demo mode — events will not be saved to AWS.
        </p>
      )}

      <form className="artist-form" onSubmit={handleSubmit}>
        <h2>Create a New Event</h2>

        <div className="artist-field">
          <label htmlFor="event-name">Event Name *</label>
          <input
            id="event-name"
            type="text"
            required
            maxLength={120}
            placeholder="Indie Night Barcelona"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div className="artist-field">
          <label htmlFor="artist-name">Artist Name</label>
          <input
            id="artist-name"
            type="text"
            maxLength={80}
            placeholder="Your artist or band name"
            value={artist}
            onChange={(e) => setArtist(e.target.value)}
          />
        </div>

        <div className="artist-form-grid">
          <div className="artist-field">
            <label htmlFor="event-city">City *</label>
            <input
              id="event-city"
              type="text"
              required
              maxLength={60}
              value={city}
              onChange={(e) => setCity(e.target.value)}
            />
          </div>

          <div className="artist-field">
            <label htmlFor="event-venue">Venue</label>
            <input
              id="event-venue"
              type="text"
              maxLength={80}
              placeholder="Sala Apolo"
              value={venue}
              onChange={(e) => setVenue(e.target.value)}
            />
          </div>
        </div>

        <div className="artist-form-grid">
          <div className="artist-field">
            <label htmlFor="event-date">Event Date *</label>
            <input
              id="event-date"
              type="date"
              required
              min={new Date().toLocaleDateString("en-CA")}
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>

          <div className="artist-field">
            <label htmlFor="event-genre">Music Genre</label>
            <select
              id="event-genre"
              value={genre}
              onChange={(e) => setGenre(e.target.value)}
            >
              <option value="">Select a genre</option>
              {genres.map((g) => (
                <option key={g} value={g.toLowerCase()}>
                  {g}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="artist-form-grid">
          <div className="artist-field">
            <label htmlFor="ticket-price">Ticket Price (€) *</label>
            <input
              id="ticket-price"
              type="number"
              min="0"
              step="0.01"
              required
              placeholder="25.00"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
            />
          </div>

          <div className="artist-field">
            <label htmlFor="event-capacity">
              Number of Seats *
            </label>
            <input
              id="event-capacity"
              type="number"
              min="1"
              step="1"
              required
              placeholder="100"
              value={capacity}
              onChange={(e) => setCapacity(e.target.value)}
            />
          </div>
        </div>

        <button
          className="artist-submit"
          type="submit"
          disabled={loading}
        >
          {loading ? "Publishing event..." : "Publish Event"}
        </button>

        {error && (
          <p className="artist-error" role="alert">
            {error}
          </p>
        )}

        {successMessage && (
          <div className="artist-success" role="status">
            <h3>{successMessage}</h3>
            <p>Event ID: {createdEventId}</p>

            <button
              type="button"
              onClick={resetForm}
            >
              Create Another Event
            </button>
          </div>
        )}
      </form>
    </main>
  );
}
