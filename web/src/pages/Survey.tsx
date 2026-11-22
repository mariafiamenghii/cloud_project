
import { useState, type FormEvent } from "react";
import { savePreferences } from "../services/api";
import { GENRES as genres } from "../utils/eventMedia";


const demoMode = import.meta.env.VITE_DEMO_MODE === "true";

export default function Survey() {
  const [selectedGenres, setSelectedGenres] = useState<string[]>([]);
  const [artists, setArtists] = useState("");
  const [city, setCity] = useState("Barcelona");
  const [maxPrice, setMaxPrice] = useState(80);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  function toggleGenre(genre: string) {
    setSelectedGenres((current) =>
      current.includes(genre)
        ? current.filter((g) => g !== genre)
        : [...current, genre]
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setError("");
    setMessage("");

    const preferences = {
      genres: selectedGenres.map((genre) => genre.toLowerCase()),
      favoriteArtists: artists
        .split(",")
        .map((artist) => artist.trim())
        .filter(Boolean)
        .slice(0, 5),
      city: city.trim(),
      maxPrice,
    };

    if (demoMode) {
      console.log("Demo preferences:", preferences);

      setMessage(
        "Demo complete! Your preferences were not saved to AWS."
      );
      return;
    }

    setLoading(true);

    try {
      await savePreferences(preferences);

      setMessage(
        "Your music preferences have been saved successfully!"
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to save preferences. Please try again."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="survey-container">
      <h1>Discover music you'll love</h1>

      <p>
        Tell us what you like so we can recommend
        the best concerts and events for you.
      </p>

      <form onSubmit={handleSubmit}>
        {/* MUSIC GENRES */}
        <section className="survey-section">
          <h2>1. What music genres do you enjoy?</h2>
          <p>Select as many as you like.</p>

          <div className="genre-grid">
            {genres.map((genre) => {
              const selected = selectedGenres.includes(genre);

              return (
                <button
                  key={genre}
                  type="button"
                  className={
                    selected
                      ? "genre-button selected"
                      : "genre-button"
                  }
                  aria-pressed={selected}
                  onClick={() => toggleGenre(genre)}
                >
                  {selected && <span aria-hidden="true">✓ </span>}
                  {genre}
                </button>
              );
            })}
          </div>
        </section>

        {/* FAVORITE ARTISTS */}
        <section className="survey-section">
          <h2>2. Who are your favorite artists?</h2>

          <p>
            Enter up to five artists, separated by commas.
          </p>

          <input
            type="text"
            value={artists}
            onChange={(event) => setArtists(event.target.value)}
            placeholder="Coldplay, Rosalía, Bad Bunny..."
          />
        </section>

        {/* HOME CITY */}
        <section className="survey-section">
          <h2>3. Where do you live?</h2>

          <p>
            We'll prioritize concerts happening near your city.
          </p>

          <input
            type="text"
            value={city}
            onChange={(event) => setCity(event.target.value)}
            placeholder="Your city"
            maxLength={60}
          />
        </section>

        {/* TICKET BUDGET */}
        <section className="survey-section">
          <h2>4. What's your maximum ticket budget?</h2>

          <label htmlFor="max-price">
            Maximum price: €{maxPrice}
          </label>

          <input
            id="max-price"
            type="range"
            min="0"
            max="300"
            step="10"
            value={maxPrice}
            onChange={(event) =>
              setMaxPrice(Number(event.target.value))
            }
          />
        </section>

        {/* SUBMIT */}
        <button
          type="submit"
          className="survey-submit"
          disabled={loading}
        >
          {loading ? "Saving..." : "Save my preferences"}
        </button>

        {message && (
          <p role="status">{message}</p>
        )}

        {error && (
          <p role="alert">{error}</p>
        )}
      </form>
    </main>
  );
}
