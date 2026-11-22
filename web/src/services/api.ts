
import { fetchAuthSession } from "aws-amplify/auth";
import { isMissingOrder, readApiResponse } from "./http";

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

  return readApiResponse(response);
}

// EVENTS

export async function getEvents(): Promise<unknown[]> {
  const data = await apiRequest("/events");

  if (!Array.isArray(data)) {
    throw new Error("Invalid events API response");
  }

  return data;
}

export type CreateEventInput = {
  name: string;
  artist?: string;
  city: string;
  venue?: string;
  date: string;
  genre?: string;
  price: number;
  capacity: number;
};

export async function createEvent(
  eventData: CreateEventInput
): Promise<{ eventId: string }> {
  const result = await apiRequest(
    "/events",
    {
      method: "POST",
      body: JSON.stringify(eventData),
    },
    true
  );

  if (
    !result ||
    typeof result !== "object" ||
    !("eventId" in result) ||
    typeof result.eventId !== "string"
  ) {
    throw new Error("Invalid event creation response");
  }

  return { eventId: result.eventId };
}

// RECOMMENDATIONS

export function getRecommendations() {
  return apiRequest("/recommendations", {}, true);
}

// USER PREFERENCES

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

// PURCHASES

export function createPurchase(
  eventId: string,
  quantity: number,
  idempotencyKey: string
) {
  return apiRequest(
    "/purchases",
    {
      method: "POST",
      body: JSON.stringify({
        eventId,
        quantity,
        idempotencyKey,
      }),
    },
    true
  );
}

// ORDER STATUS AND QR TICKETS

export type Order = {
  orderId: string;
  eventId?: string;
  seatId?: string;
  orderStatus?: string;
  ticketStatus?: string;
  paymentStatus?: string;
  emailStatus?: string;
  qrPayload?: string;
  qrUrl?: string;
  issuedAt?: number;
  failureStage?: string;
  schemaVersion?: number;
  quantity?: number;
  unitPrice?: number;
  totalPrice?: number;
  tickets?: Ticket[];
};

export type Ticket = {
  ticketId: string;
  qrPayload: string;
  qrUrl?: string;
  issuedAt?: number;
  ticketNumber?: number;
};

export type Inventory = {
  eventId: string;
  capacity: number;
  available: number;
  sold: number;
  reserved: number;
  inventoryVersion: number;
  maxPurchaseQuantity: number;
  price: number;
};

export async function getInventory(eventId: string): Promise<Inventory> {
  const result = await apiRequest(`/events/${encodeURIComponent(eventId)}/inventory`) as Inventory;
  if (result.eventId !== eventId || result.inventoryVersion !== 2 || !Number.isSafeInteger(result.available) || result.available < 0) {
    throw new Error("Inventory is not available yet");
  }
  return result;
}

// Retrieve the authenticated user's order.
//
// Only the order Lambda's explicit missing-order response is retryable.
// API Gateway's missing-route 404 must remain an actionable read error.
//
// Purchase.tsx polls this endpoint until the order is
// CONFIRMED, FAILED, REJECTED or REVIEW_REQUIRED.

export async function getOrder(
  orderId: string
): Promise<Order | null> {
  try {
    const data = await apiRequest(
      `/orders/${encodeURIComponent(orderId)}`,
      {},
      true
    );

    if (!data || typeof data !== "object" || !("orderId" in data) || data.orderId !== orderId) {
      throw new Error("Invalid order response");
    }

    return data as Order;
  } catch (err) {
    if (isMissingOrder(err)) {
      return null;
    }

    throw err;
  }
}
