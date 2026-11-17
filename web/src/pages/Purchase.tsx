
import { useRef, useState } from "react";
import type { Event } from "../components/EventCard";
import { createPurchase } from "../services/api";

type Props = {
  event: Event;
  onBack: () => void;
};

type PurchaseResponse = {
  orderId: string;
  status: string;
};

const demoMode = import.meta.env.VITE_DEMO_MODE === "true";

export default function Purchase({ event, onBack }: Props) {
  const [seatId, setSeatId] = useState("1");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PurchaseResponse | null>(null);

  // Keep the same key when retrying the same purchase.
  const purchaseKey = useRef(crypto.randomUUID());

  const capacity = event.capacity ?? 0;
  const seatNumber = Number(seatId);

  const validSeat =
    Number.isSafeInteger(seatNumber) &&
    seatNumber >= 1 &&
    seatNumber <= capacity &&
    String(seatNumber) === seatId;

  function changeSeat(value: string) {
    setSeatId(value);
    setError("");
    setResult(null);

    // Selecting a different seat is a new purchase attempt.
    purchaseKey.current = crypto.randomUUID();
  }

  async function handlePurchase() {
    if (!validSeat || loading || result) return;

    setLoading(true);
    setError("");

    try {
      if (demoMode) {
        // Local demonstration: no AWS request is sent.
        const demoResponse: PurchaseResponse = {
          orderId: `demo-${purchaseKey.current}`,
          status: "simulated",
        };

        setResult(demoResponse);
        return;
      }

      const response = await createPurchase(
        event.id,
        seatId,
        purchaseKey.current
      );

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

      setResult({
        orderId: response.orderId,
        status: response.status,
      });
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
      <button
        type="button"
        className="purchase-back"
        onClick={onBack}
      >
        Back to events
      </button>

      <h1>Complete your booking</h1>

      <div className="purchase-card">
        <h2>{event.name}</h2>
        <p>{event.artist}</p>
        <p>{event.city} · {event.date}</p>

        {event.venue && <p>Venue: {event.venue}</p>}

        <div className="purchase-divider" />

        <h3>Select your seat</h3>

        <p>
          Available seat numbers: 1 to {capacity}
        </p>

        <label htmlFor="seat-id">Seat number</label>

        <input
          id="seat-id"
          type="number"
          min="1"
          max={capacity}
          step="1"
          value={seatId}
          disabled={loading || Boolean(result)}
          onChange={(e) => changeSeat(e.target.value)}
        />

        {!validSeat && (
          <p role="alert">
            Enter a valid seat number between 1 and {capacity}.
          </p>
        )}

        <div className="purchase-summary">
          <h3>Order summary</h3>
          <p>Event: {event.name}</p>
          <p>Seat: {seatId}</p>
          <p>
            Price: {event.price !== undefined
              ? `€${event.price}`
              : "Not specified"}
          </p>
        </div>

        {!result && (
          <button
            type="button"
            className="purchase-confirm"
            disabled={!validSeat || loading}
            onClick={() => void handlePurchase()}
          >
            {loading
              ? "Submitting request..."
              : "Confirm purchase request"}
          </button>
        )}

        {error && (
          <div className="purchase-error" role="alert">
            <p>{error}</p>
            <p>
              If the request may have been received,
              retry without changing the seat.
            </p>
          </div>
        )}

        {result && (
          <div className="purchase-success" role="status">
            <h3>
              {demoMode
                ? "Demo purchase completed"
                : "Purchase request accepted"}
            </h3>

            <p>Order reference:</p>
            <code>{result.orderId}</code>

            <p>
              {demoMode
                ? "This is a simulation. No ticket was purchased or reserved."
                : "Your request was accepted for processing. Payment and ticket issuance are not yet confirmed."}
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
