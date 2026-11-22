import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, isMissingOrder, readApiResponse } from "../src/services/http.ts";

test("only an explicit order-reader 404 is a missing order", async () => {
  for (const [status, body, missing] of [
    [404, { error: "Order not found" }, true],
    [404, { message: "Not Found" }, false],
    [401, { error: "Authentication required" }, false],
    [403, { message: "Forbidden" }, false],
    [503, { error: "Temporarily unavailable" }, false],
  ]) {
    await assert.rejects(readApiResponse(Response.json(body, { status })), (err) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.status, status);
      assert.equal(isMissingOrder(err), missing);
      return true;
    });
  }
});

test("HTTP errors with non-JSON bodies keep their status", async () => {
  await assert.rejects(readApiResponse(new Response("Bad gateway", { status: 502 })),
    (err) => err instanceof ApiError && err.status === 502 && !isMissingOrder(err));
});

test("confirmed ticket fields pass through and empty responses are handled", async () => {
  const order = { orderId: "purchase-123", orderStatus: "CONFIRMED", qrPayload: "TICKET|123" };
  assert.deepEqual(await readApiResponse(Response.json(order)), order);
  assert.equal(await readApiResponse(new Response(null, { status: 204 })), null);
  await assert.rejects(readApiResponse(new Response("invalid JSON")), /Invalid API response/);
});
