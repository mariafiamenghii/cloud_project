
import { useEffect, useState, type FormEvent } from "react";
import { getEvents, getPreferences, savePreferences } from "../services/api";
import { CATEGORIES as categories } from "../utils/eventMedia";
import {
  ESADE_ASSOCIATIONS, MAX_FOLLOWED, associationOptions, followedList, savedInterests, surveyAssociations,
} from "../utils/interests";


const demoMode = import.meta.env.VITE_DEMO_MODE === "true";

export default function Survey() {
  const [interests, setInterests] = useState<string[]>([]);
  const [associations, setAssociations] = useState<string[]>(ESADE_ASSOCIATIONS);
  const [followed, setFollowed] = useState<string[]>([]);
  const [otherFollowed, setOtherFollowed] = useState("");
  const [city, setCity] = useState("Barcelona");
  const [maxPrice, setMaxPrice] = useState(80);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // Load the associations that publish events and the user's saved answers,
  // so the survey can be edited later. Failures keep the ESADE list and an empty form.
  useEffect(() => {
    if (demoMode) return;
    let active = true;

    getEvents()
      .then((events) => { if (active) setAssociations(surveyAssociations(associationOptions(events))); })
      .catch(() => undefined);

    getPreferences()
      .then((saved) => {
        if (!active || !saved || typeof saved !== "object") return;
        const prefs = saved as Record<string, unknown>;
        setInterests(savedInterests(prefs.genres));
        if (Array.isArray(prefs.favoriteArtists)) {
          setFollowed(prefs.favoriteArtists.filter((name): name is string => typeof name === "string"));
        }
        if (typeof prefs.city === "string" && prefs.city.trim()) setCity(prefs.city);
        if (typeof prefs.maxPrice === "number") setMaxPrice(prefs.maxPrice);
      })
      .catch(() => undefined);

    return () => { active = false; };
  }, []);

  function toggle(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  // Followed names that are not in the published list (typed before, or saved).
  const extraFollowed = followed.filter(
    (name) => !associations.some((a) => a.toLowerCase() === name.toLowerCase())
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setError("");
    setMessage("");

    const preferences = {
      // Field names are kept for compatibility with the preferences API:
      // "genres" = interests (category values), "favoriteArtists" = associations.
      genres: interests.map((category) => category.toLowerCase()),
      favoriteArtists: followedList(followed, otherFollowed),
      city: city.trim(),
      maxPrice,
    };

    if (demoMode) {
      console.log("Demo preferences:", preferences);

      setMessage(
        "Demo complete! Your interests were not saved to AWS."
      );
      return;
    }

    setLoading(true);

    try {
      await savePreferences(preferences);

      setFollowed(preferences.favoriteArtists);
      setOtherFollowed("");
      setMessage(
        "Your interests have been saved. Check “Recommended for You”."
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to save your interests. Please try again."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="survey-container">
      <h1>Find events you'll love</h1>

      <p>
        Tell us what you're into and which associations you follow,
        and we'll recommend ESADE and Barcelona events for you.
        You can change your answers at any time.
      </p>

      <form onSubmit={handleSubmit}>
        {/* INTERESTS (event categories) */}
        <section className="survey-section">
          <h2>1. Which topics interest you?</h2>
          <p>Select as many as you like.</p>

          <div className="genre-grid">
            {categories.map((category) => {
              const selected = interests.includes(category);

              return (
                <button
                  key={category}
                  type="button"
                  className={
                    selected
                      ? "genre-button selected"
                      : "genre-button"
                  }
                  aria-pressed={selected}
                  onClick={() => setInterests((current) => toggle(current, category))}
                >
                  {selected && <span aria-hidden="true">✓ </span>}
                  {category}
                </button>
              );
            })}
          </div>
        </section>

        {/* FOLLOWED ASSOCIATIONS */}
        <section className="survey-section">
          <h2>2. Which associations do you follow?</h2>

          <p>
            Events from associations you follow get a higher score.
            Choose up to {MAX_FOLLOWED}.
          </p>

          {(associations.length > 0 || extraFollowed.length > 0) && (
            <div className="genre-grid">
              {[...associations, ...extraFollowed].map((name) => {
                const selected = followed.some((f) => f.toLowerCase() === name.toLowerCase());

                return (
                  <button
                    key={name}
                    type="button"
                    className={selected ? "genre-button selected" : "genre-button"}
                    aria-pressed={selected}
                    disabled={!selected && followed.length >= MAX_FOLLOWED}
                    onClick={() => setFollowed((current) =>
                      selected
                        ? current.filter((f) => f.toLowerCase() !== name.toLowerCase())
                        : [...current, name])}
                  >
                    {selected && <span aria-hidden="true">✓ </span>}
                    {name}
                  </button>
                );
              })}
            </div>
          )}

          <label htmlFor="other-associations">
            Other associations or clubs (separated by commas)
          </label>
          <input
            id="other-associations"
            type="text"
            value={otherFollowed}
            onChange={(event) => setOtherFollowed(event.target.value)}
            placeholder="180 Degrees Consulting, Esade Sports..."
          />
        </section>

        {/* HOME CITY */}
        <section className="survey-section">
          <h2>3. Where do you live?</h2>

          <p>
            We'll prioritize events happening in your city.
          </p>

          <input
            type="text"
            value={city}
            onChange={(event) => setCity(event.target.value)}
            aria-label="Your city"
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
          {loading ? "Saving..." : "Save my interests"}
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
