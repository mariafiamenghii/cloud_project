export const GENRES = ["Pop", "Rock", "Indie", "Electronic", "Hip-Hop", "Reggaeton", "Jazz", "Classical", "R&B", "Latin", "Catalan"];
export const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
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

export function formatEventPrice(price: number | undefined, currency: string | undefined, external: boolean): string {
  if (price !== undefined && Number.isFinite(price) && price >= 0 && (!external || currency)) {
    try { return `From ${new Intl.NumberFormat("en-IE", { style: "currency", currency: currency || "EUR" }).format(price)}`; }
    catch { /* Invalid currency falls back to the provider link. */ }
  }
  return external ? "See price on Ticketmaster" : "Price unavailable";
}
