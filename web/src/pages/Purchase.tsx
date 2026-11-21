import { useEffect, useRef, useState } from "react";
import type { Event } from "../components/EventCard";
import { createPurchase, getOrder, type Order } from "../services/api";

type Props = {
  event: Event;
  onBack: () => void;
};

const demoMode = import.meta.env.VITE_DEMO_MODE === "";

// After SQS accepts a purchase, poll the order until the workflow settles.
// Display the QR ticket on the site because lab SES delivery is disabled.
const POLL_INTERVAL_MS = 2000;
const POLL_ATTEMPTS = 20;
const CONFIRMED = "CONFIRMED";
const FAILED_STATES = ["FAILED", "REJECTED", "REVIEW_REQUIRED"];

export default function Purchase({ event, onBack }: Props) {
  const [seatId, setSeatId] = useState("1");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [orderId, setOrderId] = useState("");
  const [order, setOrder] = useState<Order | null>(null);
  const [polling, setPolling] = useState(false);
  const purchaseKey = useRef(crypto.randomUUID());

  const capacity = event.capacity ?? 0;
  const seatNumber = Number(seatId);
  const validSeat =
    Number.isSafeInteger(seatNumber) &&
    seatNumber >= 1 &&
    seatNumber <= capacity &&
    String(seatNumber) === seatId;

  const confirmed = order?.orderStatus === CONFIRMED;
  const failed = order ? FAILED_STATES.includes(order.orderStatus ?? "") : false;
  const settled = confirmed || failed;

  function changeSeat(value: string) {
    setSeatId(value);
    setError("");
    setOrder(null);
    setOrderId("");
    setPolling(false);
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
      } catch {
        // A transient read failure must not be treated as a failed purchase.
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
  }, [orderId, settled]);

  async function handlePurchase() {
    if (!validSeat || loading || orderId) return;
    setLoading(true);
    setError("");

    try {
      if (demoMode) {
        const issuedAt = Math.floor(Date.now() / 1000);
        const demoOrderId = `demo-${purchaseKey.current}`;
        const payload = `TICKET|${demoOrderId}|${event.id}|${seatId}|${issuedAt}`;
        setOrderId(demoOrderId);
        setOrder({
          orderId: demoOrderId,
          eventId: event.id,
          seatId,
          orderStatus: CONFIRMED,
          ticketStatus: "issued",
          paymentStatus: "paid",
          emailStatus: "not_sent",
          qrPayload: payload,
          qrUrl:
            "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=" +
            encodeURIComponent(payload),
          issuedAt,
        });
        return;
      }

      const response = await createPurchase(event.id, seatId, purchaseKey.current);
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
        <div className="purchase-divider" />

        {!orderId && (
          <>
            <h3>Select your seat</h3>
            <p>Available seat numbers: 1 to {capacity}</p>
            <label htmlFor="seat-id">Seat number</label>
            <input
              id="seat-id"
              type="number"
              min="1"
              max={capacity}
              step="1"
              value={seatId}
              disabled={loading}
              onChange={(e) => changeSeat(e.target.value)}
            />
            {!validSeat && (
              <p role="alert">Enter a valid seat number between 1 and {capacity}.</p>
            )}
            <div className="purchase-summary">
              <h3>Order summary</h3>
              <p>Event: {event.name}</p>
              <p>Seat: {seatId}</p>
              <p>Price: {event.price !== undefined ? `€${event.price}` : "Not specified"}</p>
            </div>
            <button
              type="button"
              className="purchase-confirm"
              disabled={!validSeat || loading}
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
            <p>If the request may have been received, retry without changing the seat.</p>
          </div>
        )}

        {orderId && !settled && (
          <div className="purchase-processing" role="status">
            <h3>Processing your purchase…</h3>
            <p>Reserving the seat, taking payment and issuing your ticket.</p>
            <p>Order reference:</p>
            <code>{orderId}</code>
            {!polling && (
              <p role="alert">
                This is taking longer than expected. Keep your order reference and check
                My Tickets later. The purchase outcome is not yet confirmed.
              </p>
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
            {order.qrUrl && (
              <img
                className="ticket-qr"
                src={order.qrUrl}
                alt="Your ticket QR code"
                width={200}
                height={200}
              />
            )}
            <div className="ticket-details">
              <p>Event: {event.name}</p>
              <p>Seat: {order.seatId}</p>
              <p>Order reference:</p>
              <code>{order.orderId}</code>
              {order.qrPayload && (
                <>
                  <p>Ticket code:</p>
                  <code>{order.qrPayload}</code>
                </>
              )}
            </div>
          </div>
        )}

        {failed && order && (
          <div className="purchase-error" role="alert">
            <h3>Purchase not completed</h3>
            <p>
              {order.orderStatus === "REJECTED"
                ? "That seat was not available. Please pick another seat."
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
