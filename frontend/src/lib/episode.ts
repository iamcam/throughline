// src/lib/episode.ts

export const ACTIVE_STATUSES = [
  "QUEUED",
  "DOWNLOADING",
  "TRANSCRIBING",
  "DIARIZING",
  "INFERRING_SPEAKERS",
  "CHUNKING",
  "EMBEDDING",
];
// Mirror the backend: reingest from READY/ERROR; reset from READY/ERROR/QUEUED.
// (The backend also allows resetting an active stage once possibly_stuck —
// that case is handled from the queue page, which knows the stuck flag.)
export const REINGESTABLE_STATUSES = ['READY', 'ERROR']

export const canReset = (status: string) => status !== "PENDING";

export const resetActionLabel = (status: string) =>
  ACTIVE_STATUSES.includes(status) ? "Cancel" : "Reset";

// "INFERRING_SPEAKERS" → "Inferring speakers"
export const formatPipelineStatus = (status: string) =>
  status.charAt(0) + status.slice(1).toLowerCase().replaceAll("_", " ");