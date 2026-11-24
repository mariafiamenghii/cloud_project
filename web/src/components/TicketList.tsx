import { QRCodeSVG } from "qrcode.react";
import type { Ticket } from "../services/api";

function IssuedTicket({ ticket, index, count }: { ticket: Ticket; index: number; count: number }) {
  return (
    <section className="ticket-details ticket-stub" aria-label={`Ticket ${index + 1} of ${count}`}>
      <h4>Ticket {index + 1} of {count}</h4>
      <QRCodeSVG className="ticket-qr" value={ticket.qrPayload} size={200} bgColor="#ffffff" fgColor="#000000" marginSize={4}
        title={`QR code for ticket ${index + 1} of ${count}`} />
      <p>Ticket ID:</p><code>{ticket.ticketId}</code>
      <p>Ticket code:</p><code>{ticket.qrPayload}</code>
    </section>
  );
}

export default function TicketList({ tickets }: { tickets: Ticket[] }) {
  return <>{tickets.map((ticket, index) => <IssuedTicket key={ticket.ticketId} ticket={ticket} index={index} count={tickets.length} />)}</>;
}
