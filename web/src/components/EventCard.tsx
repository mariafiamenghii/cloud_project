
import { useState } from "react";
import { categoryLabel, categoryTone, formatEventPrice } from "../utils/eventMedia";
import { EXTERNAL_SOURCES, eventSource, formatEventDate } from "../utils/eventFilters";

export type Event = {
  id: string;
  name: string;
  artist: string;
  city: string;
  date: string;
  venue?: string;
  description?: string;
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
        : <span className={`event-image-fallback tone-${categoryTone(event.genre)}`} role="img"
            aria-label={`${categoryLabel(event.genre)} event, no image`}>
            <span aria-hidden="true">★</span>
            {event.genre && <span className="event-image-fallback-label" aria-hidden="true">{categoryLabel(event.genre)}</span>}
          </span>}
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
  const source = eventSource(event);
  // External events (Barcelona agenda, legacy Ticketmaster) are only shown with a link.
  const isExternal = EXTERNAL_SOURCES.includes(event.source ?? "");
  const providerName = source === "barcelona" ? "the official site" : "Ticketmaster";
  const soldOut = !isExternal && event.available === 0;

  // Only internal events with positive capacity can be purchased.
  const canPurchase =
    !isExternal &&
    (event.capacity ?? 0) > 0 && event.available !== 0;

  return (
    <article className={`event-card${isExternal ? " is-external" : ""}`}>
      <div className="event-media">
        <EventImage key={event.imageUrl || "fallback"} event={event} />
        {source !== "other" && (
          <span className={`source-badge source-${source}`}>
            {source === "ticketmaster" ? "Ticketmaster" : source === "barcelona" ? "Barcelona" : "Front Row"}
          </span>
        )}
      </div>

      <div className="event-info">
        <span className="event-genre">
          {categoryLabel(event.genre)}
        </span>

        <h3>{event.name}</h3>
        <p className="event-artist">{event.artist}</p>
        {event.description && <p className="event-description">{event.description}</p>}

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
              {formatEventPrice(event.price, event.currency, isExternal, providerName)}
            </strong>
            {!isExternal && event.available !== undefined && (
              <span className={`stock${soldOut ? " is-sold-out" : event.available <= 10 ? " is-low" : ""}`}>
                {soldOut ? "Sold out" : `${event.available} tickets remaining`}
              </span>
            )}
          </div>

          {isExternal ? (
            event.externalUrl ? (
              <a
                className="btn btn-outline"
                href={event.externalUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                {source === "barcelona" ? "More info" : "View on Ticketmaster"}
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
