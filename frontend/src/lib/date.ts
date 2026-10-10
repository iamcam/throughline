// src/lib/date.ts

// ~~~~~~ Units (in seconds) ~~~~~~

const SECOND = 1;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
const MONTH = 30 * DAY; // approximate -- relative display only
const YEAR = 365 * DAY; // approximate -- relative display only

const pad2 = (n: number) => String(n).padStart(2, "0");

// ~~~~~~ Durations ~~~~~~

const DURATION_UNITS = [
  { label: "d", size: DAY },
  { label: "h", size: HOUR },
  { label: "m", size: MINUTE },
  { label: "s", size: SECOND },
] as const;

// The `maxUnits` largest non-zero units: "42s", "3m 07s", "1h 04m", "1d 02h".
// Truncates, never rounds up.
function formatSeconds(totalSeconds: number, maxUnits = 2): string {
  let remaining = Math.max(0, Math.floor(totalSeconds));
  const parts: string[] = [];

  for (const { label, size } of DURATION_UNITS) {
    const value = Math.floor(remaining / size);
    remaining %= size;

    // Skip leading zero units ("0d 0h 3m" -> "3m"), but always emit seconds
    // so a zero duration still renders as "0s".
    if (parts.length === 0 && value === 0 && size > SECOND) continue;

    parts.push(
      parts.length === 0 ? `${value}${label}` : `${pad2(value)}${label}`
    );
    if (parts.length === maxUnits) break;
  }

  return parts.join(" ");
}

// Episode length, e.g. "1h 04m".
export function formatDuration(seconds: number | null): string {
  if (!seconds) return "";
  return formatSeconds(seconds);
}

// Time since `fromIso`, e.g. "3m 07s". Clamped: a browser clock slightly
// behind the server's gives "0s", not a negative duration.
export function formatElapsed(
  fromIso: string,
  now: number = Date.now(),
  maxUnits = 2
): string {
  return formatSeconds((now - Date.parse(fromIso)) / 1000, maxUnits);
}

// Clock-style position in audio, e.g. "1:04:12" or "4:12".
export function formatTimestamp(seconds: number | null): string {
  if (seconds == null) return "";
  const h = Math.floor(seconds / HOUR);
  const m = Math.floor((seconds % HOUR) / MINUTE);
  const s = Math.floor(seconds % MINUTE);
  return h > 0 ? `${h}:${pad2(m)}:${pad2(s)}` : `${m}:${pad2(s)}`;
}

// ~~~~~~ Dates ~~~~~~

export function formatDate(dateStr: string | null): string {
  if (!dateStr) return "";
  return new Date(dateStr).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const rtf = new Intl.RelativeTimeFormat(undefined, {
  numeric: "auto",
  style: "narrow",
});

// Below this, show "now" -- also absorbs small client/server clock skew.
const NOW_THRESHOLD = 10 * SECOND;

export function formatRelativeDate(
  isoDate: string,
  now: number = Date.now()
): string {
  const diff = Math.trunc((Date.parse(isoDate) - now) / 1000);
  const abs = Math.abs(diff);

  if (abs < NOW_THRESHOLD) return rtf.format(0, "second");
  if (abs < MINUTE) return rtf.format(diff, "second");
  if (abs < HOUR) return rtf.format(Math.trunc(diff / MINUTE), "minute");
  if (abs < DAY) return rtf.format(Math.trunc(diff / HOUR), "hour");
  if (abs < WEEK) return rtf.format(Math.round(diff / DAY), "day");
  if (abs < MONTH) return rtf.format(Math.round(diff / WEEK), "week");
  if (abs < YEAR) return rtf.format(Math.round(diff / MONTH), "month");
  return rtf.format(Math.round(diff / YEAR), "year");
}
