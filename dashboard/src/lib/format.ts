// Formatting + local-date helpers. The browser runs on the same machine as the
// collector, so browser-local time == configured timezone for the MVP.

export function fmtHM(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

export function fmtHMS(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
    : `${m}:${String(sec).padStart(2, "0")}`;
}

export function fmtHours(seconds: number, digits = 1): string {
  return (seconds / 3600).toFixed(digits);
}

export function fmtClock(ts: number): string {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function addDays(date: string, n: number): string {
  const d = new Date(`${date}T12:00:00`); // noon: DST-safe day arithmetic
  d.setDate(d.getDate() + n);
  return toISODate(d);
}

export function toISODate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function fmtDateLong(date: string): string {
  return new Date(`${date}T12:00:00`).toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function fmtDateShort(date: string): string {
  return new Date(`${date}T12:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
  });
}

/** Monday (ISO) of the week containing `date` — mirrors reporting.week_start_of. */
export function weekStartOf(date: string): string {
  const d = new Date(`${date}T12:00:00`);
  const dow = (d.getDay() + 6) % 7; // Mon=0
  d.setDate(d.getDate() - dow);
  return toISODate(d);
}

/** UTC epoch seconds where a local calendar day starts (day_start_hour offset). */
export function dayStartTs(date: string, dayStartHour: number): number {
  return Math.floor(new Date(`${date}T00:00:00`).getTime() / 1000) + dayStartHour * 3600;
}

/** Wall-clock "HH:MM" on a logical day → epoch seconds. Hours before
 * day_start_hour belong to the NEXT calendar date (§13.8): a 01:30 entry on the
 * "July 10" day is the small hours of July 11. Returns null on bad input. */
export function wallToTs(date: string, hhmm: string, dayStartHour: number): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm.trim());
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h > 23 || min > 59) return null;
  const midnight = Math.floor(new Date(`${date}T00:00:00`).getTime() / 1000);
  return midnight + h * 3600 + min * 60 + (h < dayStartHour ? 86400 : 0);
}

export function monthOf(date: string): string {
  return date.slice(0, 7); // YYYY-MM
}

export function addMonths(month: string, n: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + n, 15);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(y, m - 1, 15).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

/** All dates of a month as YYYY-MM-DD. */
export function monthDates(month: string): string[] {
  const [y, m] = month.split("-").map(Number);
  const days = new Date(y, m, 0).getDate();
  return Array.from({ length: days }, (_, i) => `${month}-${String(i + 1).padStart(2, "0")}`);
}
