
export type Event = {
  id: string;
  name: string;
  artist: string;
  city: string;
  date: string;
  price: number;
  genre: string;
};

type Props = {
  event: Event;
};

export default function EventCard({ event }: Props) {
  return (
    <article className="event-card">
      <div className="event-image">🎵</div>

      <div className="event-info">
        <span className="event-genre">{event.genre}</span>
        <h3>{event.name}</h3>
        <p>{event.artist}</p>
        <p>{event.city} · {event.date}</p>
        <strong>€{event.price}</strong>
        <button type="button" disabled>
          Tickets coming soon
        </button>
      </div>
    </article>
  );
}
