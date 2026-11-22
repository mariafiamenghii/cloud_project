import { useState } from "react";
import type { Ticket } from "../services/api";

function IssuedTicket({ ticket, index, count }: { ticket: Ticket; index: number; count: number }) {
  const [imageFailed, setImageFailed] = useState(false);
  return (
    <section className="ticket-details" aria-label={`Ticket ${index + 1} of ${count}`}>
      <h4>Ticket {index + 1} of {count}</h4>
      {!imageFailed && <img className="ticket-qr" width={200} height={200}
        src={ticket.qrUrl || `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(ticket.qrPayload)}`}
        alt={`QR code for ticket ${index + 1} of ${count}`} onError={() => setImageFailed(true)} />}
      {imageFailed && <p role="alert">The QR image could not load. Keep the ticket code below.</p>}
      <p>Ticket ID:</p><code>{ticket.ticketId}</code>
      <p>Ticket code:</p><code>{ticket.qrPayload}</code>
    </section>
  );
}

export default function TicketList({ tickets }: { tickets: Ticket[] }) {
  return <>{tickets.map((ticket, index) => <IssuedTicket key={ticket.ticketId} ticket={ticket} index={index} count={tickets.length} />)}</>;
}
