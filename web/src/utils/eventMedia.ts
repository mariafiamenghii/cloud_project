// Event categories: the survey, the event-creation form and the recommendations
// all use this list. Stored lowercase in the event's "genre" field. The backend
// copy is lambdas/create_event/categories.py (tests/test_categories.py checks
// that both lists stay identical).
export const CATEGORIES = [
  // ESADE student association topics
  "Consulting", "Finance", "Tech", "Entrepreneurship", "Marketing", "Luxury",
  "Sustainability", "Networking", "Sports", "Volunteering", "Social Impact",
  "Career Development", "Social Events",
  // City and culture
  "Food", "Music", "Festivals", "Workshops", "Theatre", "Art", "Talks", "Family",
  "Culture",
];
/**
 * Display name for a stored category ("finance" -> "Finance"). Events saved
 * before the categories existed may hold an old music genre ("jazz"); that
 * value is shown as it is. Events without a category show "Event".
 */
export function categoryLabel(value: string | undefined): string {
  const clean = (value ?? "").trim();
  if (!clean) return "Event";
  return CATEGORIES.find((c) => c.toLowerCase() === clean.toLowerCase()) ?? clean;
}

/** Colour group of the placeholder shown when an event has no image. */
export type CategoryTone = "career" | "innovation" | "impact" | "social" | "culture" | "none";

const TONES: Record<Exclude<CategoryTone, "none">, string[]> = {
  career: ["consulting", "finance", "marketing", "luxury", "networking", "career development"],
  innovation: ["tech", "entrepreneurship", "workshops", "talks"],
  impact: ["sustainability", "volunteering", "social impact"],
  social: ["sports", "social events", "festivals", "food", "family"],
  culture: ["music", "theatre", "art", "culture"],
};

export function categoryTone(value: string | undefined): CategoryTone {
  const clean = (value ?? "").trim().toLowerCase();
  const tone = (Object.keys(TONES) as (keyof typeof TONES)[]).find((t) => TONES[t].includes(clean));
  return tone ?? "none";
}

export const IMAGE_TYPES =["image/jpeg", "image/png", "image/webp"];
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

export function imageError(file: { type: string; size: number }): string {
  if (!IMAGE_TYPES.includes(file.type)) return "Choose a JPEG, PNG or WebP image.";
  if (file.size <= 0 || file.size > MAX_IMAGE_BYTES) return "Images must be between 1 byte and 5 MB.";
  return "";
}

export function mediaFields(record: Record<string, unknown>) {
  return {
    imageUrl: typeof record.imageUrl === "string" && /^https:\/\//i.test(record.imageUrl) ? record.imageUrl : undefined,
    imageAttribution: typeof record.imageAttribution === "string" ? record.imageAttribution : undefined,
    currency: typeof record.currency === "string" && /^[A-Z]{3}$/.test(record.currency) ? record.currency : undefined,
  };
}

export function formatEventPrice(price: number | undefined, currency: string | undefined, external: boolean, provider = "Ticketmaster"): string {
  if (price === 0 && (!external || currency)) return "Free";
  if (price !== undefined && Number.isFinite(price) && price >= 0 && (!external || currency)) {
    try { return `From ${new Intl.NumberFormat("en-IE", { style: "currency", currency: currency || "EUR" }).format(price)}`; }
    catch { /* Invalid currency falls back to the provider link. */ }
  }
  return external ? `See price on ${provider}` : "Price unavailable";
}
