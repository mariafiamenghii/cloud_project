import { useEffect, useState } from "react";

import TicketList from "../components/TicketList";
import { getMyOrders } from "../services/api";
import type { Order } from "../services/api";
import { issuedTickets } from "../utils/tickets";

function statusText(order: Order): string {
  switch (order.orderStatus) {
    case "CONFIRMED":
      return "Confirmed";
    case "REJECTED":
      return "Not available: the tickets were sold out";
    case "FAILED":
      return "The purchase could not be completed";
    case "REVIEW_REQUIRED":
      return "Under review by the organisers";
    default:
      return "Being processed";
  }
}

function OrderCard({ order }: { order: Order }) {
  const tickets = issuedTickets(order);
  const event = order.event;
  const details = [event?.artist, event?.venue, event?.city, event?.date]
    .filter(Boolean)
    .join(" · ");

  return (
    <section className="ticket-details">
      <h3>{event?.name || "Event"}</h3>
      {details && <p>{details}</p>}
      <p>
        {statusText(order)}
        {order.schemaVersion !== 2 && order.seatId
          ? ` · Seat ${order.seatId}`
          : ""}
        {order.issuedAt
          ? ` · ${new Date(order.issuedAt * 1000).toLocaleString()}`
          : ""}
      </p>
      {tickets.length > 0 && <TicketList tickets={tickets} />}
    </section>
  );
}

export default function MyTickets() {
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    getMyOrders()
      .then((result) => {
        if (active) setOrders(result);
      })
      .catch((err: unknown) => {
        if (active) {
          setError(
            err instanceof Error ? err.message : "Could not load your tickets."
          );
        }
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="container">
      <h2>My Tickets</h2>

      {error && <p role="alert">{error}</p>}
      {!error && orders === null && <p>Loading your tickets...</p>}
      {orders !== null && orders.length === 0 && (
        <p>You have not bought any tickets yet.</p>
      )}
      {orders?.map((order) => (
        <OrderCard key={order.orderId} order={order} />
      ))}
    </main>
  );
}
