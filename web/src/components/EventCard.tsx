
import { useState } from "react";
import { formatEventPrice } from "../utils/eventMedia";
import { eventSource, formatEventDate } from "../utils/eventFilters";

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
  imageUrl?: string;
  imageAttribution?: string;
  currency?: string;
};

function EventImage({ event }: { event: Event }) {
  const [failed, setFailed] = useState(false);
  return <>
    <div className="event-image">
      {event.imageUrl && !failed
        ? <img src={event.imageUrl} alt={event.name} loading="lazy" decoding="async" onError={() => setFailed(true)} />
        : <span className="event-image-fallback" role="img" aria-label="Event image unavailable">♪</span>}
    </div>
    {event.imageUrl && !failed && (event.imageAttribution || event.source === "ticketmaster") &&
      <small className="event-image-credit">{event.imageAttribution || "Image supplied by Ticketmaster"}</small>}
  </>;
}

type Props = {
  event: Event;
  onBuy?: (event: Event) => void;
};

export default function EventCard({ event, onBuy }: Props) {
  const isTicketmaster = event.source === "ticketmaster";
  const source = eventSource(event);
  const soldOut = !isTicketmaster && event.available === 0;

  // Only internal events with positive capacity can be purchased.
  const canPurchase =
    !isTicketmaster &&
    (event.capacity ?? 0) > 0 && event.available !== 0;

  return (
    <article className={`event-card${isTicketmaster ? " is-external" : ""}`}>
      <div className="event-media">
        <EventImage key={event.imageUrl || "fallback"} event={event} />
        {source !== "other" && (
          <span className={`source-badge source-${source}`}>
            {source === "ticketmaster" ? "Ticketmaster" : "Front Row"}
          </span>
        )}
      </div>

      <div className="event-info">
        <span className="event-genre">
          {event.genre === "catalan" ? "Catalan" : event.genre || "Live Music"}
        </span>

        <h3>{event.name}</h3>
        <p className="event-artist">{event.artist}</p>

        <dl className="event-meta">
          <div>
            <dt>Date</dt>
            <dd><time dateTime={event.date}>{formatEventDate(event.date)}</time></dd>
          </div>
          <div>
            <dt>Where</dt>
            <dd>
              {event.city}
              {event.venue ? ` · ${event.venue}` : ""}
            </dd>
          </div>
        </dl>

        <div className="event-footer">
          <div className="event-price">
            <strong>
              {formatEventPrice(event.price, event.currency, isTicketmaster)}
            </strong>
            {!isTicketmaster && event.available !== undefined && (
              <span className={`stock${soldOut ? " is-sold-out" : event.available <= 10 ? " is-low" : ""}`}>
                {soldOut ? "Sold out" : `${event.available} tickets remaining`}
              </span>
            )}
          </div>

          {isTicketmaster ? (
            event.externalUrl ? (
              <a
                className="btn btn-outline"
                href={event.externalUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                View on Ticketmaster
                <span className="visually-hidden"> (opens in a new tab)</span>
                <span aria-hidden="true"> ↗</span>
              </a>
            ) : (
              <button type="button" className="btn btn-outline" disabled>
                External tickets unavailable
              </button>
            )
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              disabled={!canPurchase || !onBuy}
              onClick={() => onBuy?.(event)}
            >
              {canPurchase
                ? "Buy Tickets"
                : event.available === 0 ? "Sold out" : "Tickets unavailable"}
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
