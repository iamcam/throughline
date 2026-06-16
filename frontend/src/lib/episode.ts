// src/lib/episode.ts

export const ACTIVE_STATUSES = [
  "QUEUED",
  "DOWNLOADING",
  "TRANSCRIBING",
  "INFERRING_SPEAKERS",
  "CHUNKING",
  "EMBEDDING",
];

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
