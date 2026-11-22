import type { Order, Ticket } from "../services/api";

export function issuedTickets(order: Order): Ticket[] {
  if (order.orderStatus !== "CONFIRMED") return [];
  if (order.schemaVersion === 2) {
    const tickets = order.tickets;
    if (!Number.isSafeInteger(order.quantity) || !tickets || tickets.length !== order.quantity ||
        tickets.some((ticket) => !ticket.ticketId || !ticket.qrPayload) ||
        new Set(tickets.map((ticket) => ticket.ticketId)).size !== tickets.length ||
        new Set(tickets.map((ticket) => ticket.qrPayload)).size !== tickets.length) return [];
    return tickets;
  }
  return order.qrPayload ? [{ ticketId: order.orderId, qrPayload: order.qrPayload, qrUrl: order.qrUrl }] : [];
}

export function validTicketQuantity(value: string, maximum: number): boolean {
  const quantity = Number(value);
  return /^[1-9][0-9]*$/.test(value) && Number.isSafeInteger(quantity) && quantity <= maximum;
}
