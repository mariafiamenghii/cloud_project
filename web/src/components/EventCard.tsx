
export type Event = {
  id: string;
  name: string;
  artist: string;
  city: string;
  date: string;
  venue?: string;
  price?: number;
  genre?: string;
  source?: string;
  externalUrl?: string;
  capacity?: number;
  available?: number;
};

type Props = {
  event: Event;
  onBuy?: (event: Event) => void;
};

export default function EventCard({ event, onBuy }: Props) {
  const isTicketmaster = event.source === "ticketmaster";

  // Only internal events with positive capacity can be purchased.
  const canPurchase =
    !isTicketmaster &&
    (event.capacity ?? 0) > 0 && event.available !== 0;

  return (
    <article className="event-card">
      <div className="event-image">🎵</div>

      <div className="event-info">
        <span className="event-genre">
          {event.genre || "Live Music"}
        </span>

        <h3>{event.name}</h3>
        <p>{event.artist}</p>

        <p>
          {event.city}
          {event.venue ? ` · ${event.venue}` : ""}
        </p>

        <p>{event.date}</p>

        <strong>
          {event.price !== undefined
            ? `From €${event.price}`
            : "Price unavailable"}
        </strong>
        {!isTicketmaster && event.available !== undefined && (
          <p>{event.available === 0 ? "Sold out" : `${event.available} tickets remaining`}</p>
        )}

        {isTicketmaster ? (
          event.externalUrl ? (
            <a
              className="ticket-button"
              href={event.externalUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              View on Ticketmaster
            </a>
          ) : (
            <button type="button" disabled>
              External tickets unavailable
            </button>
          )
        ) : (
          <button
            type="button"
            disabled={!canPurchase || !onBuy}
            onClick={() => onBuy?.(event)}
          >
            {canPurchase
              ? "Buy Tickets"
              : event.available === 0 ? "Sold out" : "Tickets unavailable"}
          </button>
        )}
      </div>
    </article>
  );
}
