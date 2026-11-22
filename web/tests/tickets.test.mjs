import assert from "node:assert/strict";
import test from "node:test";
import { issuedTickets, validTicketQuantity } from "../src/utils/tickets.ts";

test("quantity is a canonical integer within remaining inventory", () => {
  for (const value of ["0", "-1", "1.5", "4.0", "04", "", "1e1", "21"]) assert.equal(validTicketQuantity(value, 20), false);
  assert.equal(validTicketQuantity("4", 5), true);
  assert.equal(validTicketQuantity("4", 3), false);
});

test("one and four distinct confirmed tickets display; incomplete or duplicate sets do not", () => {
  for (const count of [1, 4]) {
    const order = { orderId: "o", schemaVersion: 2, quantity: count, orderStatus: "CONFIRMED",
      tickets: Array.from({ length: count }, (_, i) => ({ ticketId: `ticket-${i}`, qrPayload: `qr-${i}` })) };
    assert.equal(issuedTickets(order).length, count);
    assert.deepEqual(issuedTickets({ ...order, orderStatus: "PAID" }), []);
    assert.deepEqual(issuedTickets({ ...order, quantity: count + 1 }), []);
    if (count > 1) assert.deepEqual(issuedTickets({ ...order, tickets: order.tickets.map(() => order.tickets[0]) }), []);
  }
});

test("historical single-ticket QR codes stay intact", () => {
  assert.deepEqual(issuedTickets({ orderId: "legacy", orderStatus: "CONFIRMED", seatId: "4", qrPayload: "old-qr", qrUrl: "old-url" }),
    [{ ticketId: "legacy", qrPayload: "old-qr", qrUrl: "old-url" }]);
});
