// src/lib/date.ts
export function formatDuration(seconds: number | null): string {
  if (!seconds) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`;
}

export function formatDate(dateStr: string | null): string {
  if (!dateStr) return "";
  return new Date(dateStr).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto", style:"narrow" });

export function formatRelativeDate(isoDate: string): string {
  const diffMs = new Date(isoDate).getTime() - Date.now();
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));

  if (Math.abs(diffDays) < 1) return rtf.format(0, "day");
  if (Math.abs(diffDays) < 7) return rtf.format(diffDays, "day");
  if (Math.abs(diffDays) < 30)
    return rtf.format(Math.round(diffDays / 7), "week");
  if (Math.abs(diffDays) < 365)
    return rtf.format(Math.round(diffDays / 30), "month");
  return rtf.format(Math.round(diffDays / 365), "year");
}
