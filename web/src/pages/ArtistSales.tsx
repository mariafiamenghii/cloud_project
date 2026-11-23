import { useEffect, useState } from "react";

import { deleteEvent, getMyEvents } from "../services/api";
import type { EventSales } from "../services/api";

const REFRESH_MS = 15000;

function euros(value: number): string {
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "EUR",
  }).format(value);
}

export default function ArtistSales() {
  const [events, setEvents] = useState<EventSales[] | null>(null);
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState("");
  const [confirmId, setConfirmId] = useState("");
  const [deletingId, setDeletingId] = useState("");
  const [deleteError, setDeleteError] = useState("");

  async function handleDelete(eventId: string) {
    setDeleteError("");
    setDeletingId(eventId);
    try {
      await deleteEvent(eventId);
      setEvents((current) =>
        current ? current.filter((e) => e.eventId !== eventId) : current
      );
    } catch (err) {
      setDeleteError(
        err instanceof Error ? err.message : "Could not delete the event."
      );
    } finally {
      setDeletingId("");
      setConfirmId("");
    }
  }

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const result = await getMyEvents();
        if (!active) return;
        setEvents(result);
        setError("");
        setUpdatedAt(new Date().toLocaleTimeString());
      } catch (err) {
        if (active) {
          setError(
            err instanceof Error ? err.message : "Could not load your sales."
          );
        }
      }
    }

    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const totalSold = events?.reduce((sum, e) => sum + e.sold, 0) ?? 0;
  const totalRevenue = events?.reduce((sum, e) => sum + e.revenue, 0) ?? 0;

  return (
    <main className="container">
      <h2>Ticket Sales</h2>

      {error && <p role="alert">{error}</p>}
      {deleteError && <p role="alert">{deleteError}</p>}
      {!error && events === null && <p>Loading your sales...</p>}
      {events !== null && events.length === 0 && (
        <p>You have not created any events yet.</p>
      )}

      {events !== null && events.length > 0 && (
        <>
          <p>
            <strong>{totalSold}</strong> tickets sold ·{" "}
            <strong>{euros(totalRevenue)}</strong> revenue
          </p>

          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th align="left">Event</th>
                <th align="left">Date</th>
                <th align="left">Sold</th>
                <th align="left">Left</th>
                <th align="left">Revenue</th>
                <th align="left">Status</th>
                <th align="left"></th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.eventId}>
                  <td>
                    {e.name || "Event"}
                    {e.city ? ` · ${e.city}` : ""}
                  </td>
                  <td>{e.date || ""}</td>
                  <td>
                    <progress
                      value={e.sold}
                      max={e.capacity || 1}
                      aria-label={`${e.sold} of ${e.capacity} tickets sold`}
                    />{" "}
                    {e.sold} / {e.capacity}
                  </td>
                  <td>{e.available}</td>
                  <td>{euros(e.revenue)}</td>
                  <td>{e.soldOut ? "Sold out" : "On sale"}</td>
                  <td>
                    {confirmId === e.eventId ? (
                      <>
                        <button
                          type="button"
                          disabled={deletingId === e.eventId}
                          onClick={() => void handleDelete(e.eventId)}
                        >
                          {deletingId === e.eventId ? "Deleting..." : "Confirm?"}
                        </button>{" "}
                        <button
                          type="button"
                          disabled={deletingId === e.eventId}
                          onClick={() => setConfirmId("")}
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        disabled={e.sold > 0 || e.reserved > 0}
                        title={
                          e.sold > 0 || e.reserved > 0
                            ? "Events with sales cannot be deleted"
                            : "Delete this event"
                        }
                        onClick={() => {
                          setDeleteError("");
                          setConfirmId(e.eventId);
                        }}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <p>
            <small>Updates every 15 seconds. Last update: {updatedAt}</small>
          </p>
        </>
      )}
    </main>
  );
}
