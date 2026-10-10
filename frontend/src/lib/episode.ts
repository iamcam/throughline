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

// lib/episode.ts
const STATUS_LABELS: Record<string, string> = {
  PENDING: "New",
  QUEUED: "Waiting",
  DOWNLOADING: "Downloading",
  TRANSCRIBING: "Transcribing 1/2",
  DIARIZING: "Transcribing 1/2",
  INFERRING_SPEAKERS: "Processing 1/3",
  CHUNKING: "Processing 2/3",
  EMBEDDING: "Processing 3/3",
  READY: "Ready",
  ERROR: "Failed",
};

export const statusLabel = (status: string) =>
  STATUS_LABELS[status] ?? formatPipelineStatus(status);