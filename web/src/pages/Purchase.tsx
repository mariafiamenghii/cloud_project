import { useEffect, useRef, useState } from "react";
import type { Event } from "../components/EventCard";
import { createPurchase, getOrder, getInventory, type Inventory, type Order } from "../services/api";
import { ApiError } from "../services/http";
import { issuedTickets, validTicketQuantity } from "../utils/tickets";
import TicketList from "../components/TicketList";

type Props = {
  event: Event;
  onBack: () => void;
};

const demoMode = import.meta.env.VITE_DEMO_MODE === "true";

// After SQS accepts a purchase, poll the order until the workflow settles.
// Display the QR ticket on the site because lab SES delivery is disabled.
const POLL_INTERVAL_MS = 2000;
const POLL_ATTEMPTS = 20;
const CONFIRMED = "CONFIRMED";
const FAILED_STATES = ["FAILED", "REJECTED", "REVIEW_REQUIRED"];

export default function Purchase({ event, onBack }: Props) {
  const [quantityText, setQuantityText] = useState("1");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [orderId, setOrderId] = useState("");
  const [order, setOrder] = useState<Order | null>(null);
  const [polling, setPolling] = useState(false);
  const [pollError, setPollError] = useState("");
  const [pollRun, setPollRun] = useState(0);
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [inventoryError, setInventoryError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const purchaseKey = useRef(crypto.randomUUID());

  const capacity = inventory?.capacity ?? event.capacity ?? 0;
  const quantity = Number(quantityText);
  const limit = Math.min(20, inventory?.maxPurchaseQuantity ?? 20, capacity,
    submitted ? capacity : inventory?.available ?? (demoMode ? capacity : 0));
  const validQuantity = validTicketQuantity(quantityText, limit);
  const unitPrice = inventory?.price ?? event.price;
  const tickets = order ? issuedTickets(order) : [];

  useEffect(() => {
    if (demoMode || orderId) return;
    let cancelled = false;
    async function refreshInventory() {
      try {
        const latest = await getInventory(event.id);
        if (!cancelled) { setInventory(latest); setInventoryError(""); }
      } catch (err) {
        if (!cancelled) setInventoryError(err instanceof Error ? err.message : "Unable to check availability");
      }
    }
    void refreshInventory();
    const timer = window.setInterval(() => void refreshInventory(), 10000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [event.id, orderId]);

  const confirmed = order?.orderStatus === CONFIRMED;
  const failed = order ? FAILED_STATES.includes(order.orderStatus ?? "") : false;
  const settled = confirmed || failed;

  function changeQuantity(value: string) {
    setQuantityText(value);
    setSubmitted(false);
    setError("");
    setOrder(null);
    setOrderId("");
    setPolling(false);
    setPollError("");
    purchaseKey.current = crypto.randomUUID();
  }

  useEffect(() => {
    if (!orderId || demoMode || settled) return;

    let attempts = 0;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      attempts += 1;
      try {
        const latest = await getOrder(orderId);
        if (cancelled) return;
        setPollError("");
        if (latest) {
          setOrder(latest);
          if (
            latest.orderStatus === CONFIRMED ||
            FAILED_STATES.includes(latest.orderStatus ?? "")
          ) {
            setPolling(false);
            return;
          }
        }
      } catch (err) {
        if (cancelled) return;
        setPollError(err instanceof Error ? err.message : "Unable to read order status.");
        if (err instanceof ApiError && [400, 401, 403, 404].includes(err.status)) {
          setPolling(false);
          return;
        }
      }

      if (cancelled) return;
      if (attempts >= POLL_ATTEMPTS) {
        setPolling(false);
        return;
      }
      timer = window.setTimeout(() => void tick(), POLL_INTERVAL_MS);
    };

    timer = window.setTimeout(() => void tick(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [orderId, settled, pollRun]);

  async function handlePurchase() {
    if (!validQuantity || loading || orderId) return;
    setLoading(true);
    setError("");

    try {
      if (demoMode) {
        const issuedAt = Math.floor(Date.now() / 1000);
        const demoOrderId = `demo-${purchaseKey.current}`;
        const demoTickets = Array.from({ length: quantity }, (_, index) => {
          const ticketId = `${demoOrderId}-${index + 1}`;
          return { ticketId, qrPayload: `DEMO|${ticketId}|${event.id}|${issuedAt}` };
        });
        setOrderId(demoOrderId);
        setOrder({ orderId: demoOrderId, eventId: event.id, quantity, schemaVersion: 2,
          orderStatus: CONFIRMED, ticketStatus: "issued", paymentStatus: "paid",
          emailStatus: "not_sent", tickets: demoTickets, unitPrice, totalPrice: (unitPrice ?? 0) * quantity });
        return;
      }

      setSubmitted(true);
      const response = await createPurchase(event.id, quantity, purchaseKey.current);
      if (
        !response ||
        typeof response !== "object" ||
        !("orderId" in response) ||
        typeof response.orderId !== "string" ||
        !("status" in response) ||
        response.status !== "accepted"
      ) {
        throw new Error("Unexpected purchase response");
      }

      // Set polling state in the event handler, not synchronously in an effect.
      setPolling(true);
      setOrderId(response.orderId);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to submit purchase. Try again with the same request."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="purchase-container">
      <button type="button" className="purchase-back" onClick={onBack}>
        Back to events
      </button>
      <h1>Complete your booking</h1>
      <div className="purchase-card">
        <h2>{event.name}</h2>
        <p>{event.artist}</p>
        <p>{event.city} · {event.date}</p>
        {event.venue && <p>Venue: {event.venue}</p>}
        {event.description && <p>{event.description}</p>}
        <div className="purchase-divider" />

        {!orderId && (
          <>
            <h3>Select number of tickets</h3>
            <p>Total capacity: {capacity} tickets</p>
            <p>{inventory ? `${inventory.available} tickets remaining` : demoMode ? `${capacity} tickets available (demo)` : "Checking availability…"}</p>
            {inventoryError && <p role="alert">{inventoryError}</p>}
            <label htmlFor="ticket-quantity">Ticket quantity</label>
            <input
              id="ticket-quantity"
              type="number"
              min="1"
              max={limit}
              step="1"
              value={quantityText}
              disabled={loading}
              onChange={(e) => changeQuantity(e.target.value)}
            />
            {!validQuantity && (
              <p role="alert">{limit === 0 ? "No tickets available for purchase right now." : `Enter a whole number between 1 and ${limit}.`}</p>
            )}
            <div className="purchase-summary">
              <h3>Order summary</h3>
              <p>Event: {event.name}</p>
              <p>Organised by: {event.artist}</p>
              <p>Ticket quantity: {quantityText}</p>
              <p>Price per ticket: {unitPrice !== undefined ? `€${unitPrice.toFixed(2)}` : "Not specified"}</p>
              <p>Total price: {unitPrice !== undefined && Number.isSafeInteger(quantity) && quantity > 0 ? `€${(unitPrice * quantity).toFixed(2)}` : "—"}</p>
            </div>
            <button
              type="button"
              className="purchase-confirm"
              disabled={!validQuantity || loading}
              onClick={() => void handlePurchase()}
            >
              {loading ? "Submitting request..." : "Confirm purchase"}
            </button>
            <p className="purchase-note">Payment is simulated for this MVP: no card is charged.</p>
          </>
        )}

        {error && (
          <div className="purchase-error" role="alert">
            <p>{error}</p>
            <p>If the request may have been received, retry without changing the ticket quantity.</p>
          </div>
        )}

        {orderId && !settled && (
          <div className="purchase-processing" role="status">
            <h3>Processing your purchase…</h3>
            <p>Reserving tickets, taking payment and issuing your QR codes.</p>
            <p>Order reference:</p>
            <code>{orderId}</code>
            {!polling && (
              <>
                <p role="alert">
                  {pollError ? `Unable to check your order: ${pollError}. ` : "This is taking longer than expected. "}
                  Keep your order reference. The purchase outcome is not yet confirmed.
                </p>
                <button type="button" className="purchase-back" onClick={() => {
                  setPollError("");
                  setPolling(true);
                  setPollRun((run) => run + 1);
                }}>Check order status again</button>
              </>
            )}
          </div>
        )}

        {confirmed && order && (
          <div className="purchase-success" role="status">
            <h3>Ticket confirmed 🎟️</h3>
            <p>
              Email delivery is disabled in this environment
              {order.emailStatus === "not_sent" ? " (not sent)" : ""}, so here is your ticket:
            </p>
            <TicketList tickets={tickets} />
            {tickets.length === 0 && <p role="alert">Your ticket records could not be loaded. Keep your order reference and contact support.</p>}
            <div className="ticket-details">
              <p>Event: {event.name}</p>
              <p>Ticket quantity: {order.quantity ?? 1}</p>
              {order.totalPrice !== undefined && <p>Total price: €{order.totalPrice.toFixed(2)}</p>}
              <p>Order reference:</p>
              <code>{order.orderId}</code>

            </div>
          </div>
        )}

        {failed && order && (
          <div className="purchase-error" role="alert">
            <h3>Purchase not completed</h3>
            <p>
              {order.orderStatus === "REJECTED"
                ? "There were not enough tickets available to complete this purchase."
                : order.orderStatus === "REVIEW_REQUIRED"
                  ? "Your payment went through but the ticket needs review. Keep your order reference."
                  : "The purchase could not be completed. Please try again."}
            </p>
            <p>Order reference:</p>
            <code>{order.orderId}</code>
            <button type="button" className="purchase-back" onClick={onBack}>
              Back to events
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
