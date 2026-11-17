
import { fetchAuthSession } from "aws-amplify/auth";

const API_URL = import.meta.env.VITE_API_URL;

export async function apiRequest(
  path: string,
  options: RequestInit = {},
  authenticated = false
): Promise<unknown> {
  if (!API_URL) {
    throw new Error("AWS API URL is not configured");
  }

  const headers = new Headers(options.headers);

  if (options.body) {
    headers.set("Content-Type", "application/json");
  }

  if (authenticated) {
    const session = await fetchAuthSession();
    const token = session.tokens?.accessToken?.toString();

    if (!token) {
      throw new Error("You must log in first");
    }

    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(
    `${API_URL.replace(/\/$/, "")}${path}`,
    { ...options, headers }
  );

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }

  if (response.status === 204) return null;

  return response.json();
}

export async function getEvents(): Promise<unknown[]> {
  const data = await apiRequest("/events");

  if (!Array.isArray(data)) {
    throw new Error("Invalid events API response");
  }

  return data;
}

export function getRecommendations() {
  return apiRequest("/recommendations", {}, true);
}

export function getPreferences() {
  return apiRequest("/preferences", {}, true);
}

export function savePreferences(
  preferences: Record<string, unknown>
) {
  return apiRequest(
    "/preferences",
    {
      method: "POST",
      body: JSON.stringify(preferences),
    },
    true
  );
}

export function createPurchase(
  eventId: string,
  seatId: string,
  idempotencyKey: string
) {
  return apiRequest(
    "/purchases",
    {
      method: "POST",
      body: JSON.stringify({
        eventId,
        seatId,
        idempotencyKey,
      }),
    },
    true
  );
}