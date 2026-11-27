// Dates without a time describe the whole event day in Spain.
const eventDay = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Madrid",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

export function upcomingEvents<T extends { date: string }>(
  events: readonly T[],
  now = new Date()
): T[] {
  const today = eventDay.format(now);
  return events
    .filter(({ date }) => {
      const timestamp = Date.parse(date);
      if (!Number.isFinite(timestamp)) return false;
      return /^\d{4}-\d{2}-\d{2}$/.test(date)
        ? date >= today
        : timestamp >= now.getTime();
    })
    .sort((a, b) => Date.parse(a.date) - Date.parse(b.date));
}
