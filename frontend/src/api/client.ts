// src/api/client.ts
import axios from "axios";

const api = axios.create({
  baseURL: `${import.meta.env.VITE_API_URL ?? ""}/api/v1`,
  headers: { "Content-Type": "application/json" },
});

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Feed {
  id: string;
  rss_url: string;
  title: string | null;
  description: string | null;
  image_url: string | null;
  episode_count: number;
  created_at: string;
}

export interface Episode {
  id: string;
  feed_id: string;
  title: string | null;
  description: string | null;
  published_at: string | null;
  duration_seconds: number | null;
  audio_url: string | null;
  pipeline_status: string;
  pipeline_stage: string | null;
  pipeline_progress: number | null;
  ingestion_job_id: string | null;
}

export interface PipelineStatusUpdate {
  status: string;
  stage: string | null;
  progress: number | null;
  position: number | null;
  error: string | null;
}

export interface Speaker {
  speaker_id: string;
  display_name: string | null;
  name_inferred: boolean;
  name_confirmed: boolean;
  confidence: string | null;
}

export interface SpeakerPreview {
  speaker_id: string;
  sample_quote: string;
  sample_timestamp_ms: number;
}

export interface CitationResult {
  chunk_id: string;
  text: string;
  parent_text: string | null;
  episode_id: string;
  episode_title: string | null;
  display_name: string | null;
  timestamp_display: string;
  start_ms: number;
  end_ms: number;
  similarity_score: number;
  audio_url: string | null;
}

export interface ChatSession {
  session_id: string;
  scope_feed_ids: string[];
  scope_episode_ids: string[];
}

export interface ChatMessageResponse {
  message: string;
  session_id: string;
  citations: CitationResult[];
}

// ── Feeds ─────────────────────────────────────────────────────────────────────

export const addFeed = (rss_url: string) =>
  api.post<Feed>("/feeds", { rss_url }).then((r) => r.data);

export const listFeeds = () => api.get<Feed[]>("/feeds").then((r) => r.data);

export const getFeed = (feedId: string) =>
  api.get<Feed>(`/feeds/${feedId}`).then((r) => r.data);

export const deleteFeed = (feedId: string) => api.delete(`/feeds/${feedId}`);

export const refreshFeed = (feedId: string) =>
  api.post<Episode[]>(`/feeds/${feedId}/refresh`).then((r) => r.data);

// ── Episodes ──────────────────────────────────────────────────────────────────

export const listEpisodes = (feedId: string) =>
  api.get<Episode[]>(`/feeds/${feedId}/episodes`).then((r) => r.data);

export const getEpisode = (episodeId: string) =>
  api.get<Episode>(`/episodes/${episodeId}`).then((r) => r.data);

export const ingestEpisode = (episodeId: string, speakerCountHint?: number) =>
  api
    .post(`/episodes/${episodeId}/ingest`, {
      speaker_count_hint: speakerCountHint,
    })
    .then((r) => r.data);

export const reingestEpisode = (episodeId: string, speakerCountHint?: number) =>
  api
    .post(`/episodes/${episodeId}/reingest`, {
      speaker_count_hint: speakerCountHint,
    })
    .then((r) => r.data);

// ── Speakers ──────────────────────────────────────────────────────────────────

export const listSpeakers = (episodeId: string) =>
  api.get<Speaker[]>(`/episodes/${episodeId}/speakers`).then((r) => r.data);

export const getSpeakerPreviews = (episodeId: string) =>
  api
    .get<SpeakerPreview[]>(`/episodes/${episodeId}/speakers/preview`)
    .then((r) => r.data);

export const updateSpeakers = (
  episodeId: string,
  speakers: Pick<Speaker, "speaker_id" | "display_name">[]
) => api.put(`/episodes/${episodeId}/speakers`, speakers).then((r) => r.data);

// ── Chat ──────────────────────────────────────────────────────────────────────

export const createChatSession = (
  scopeFeedIds: string[] = [],
  scopeEpisodeIds: string[] = []
) =>
  api
    .post<ChatSession>("/chat/sessions", {
      scope_feed_ids: scopeFeedIds,
      scope_episode_ids: scopeEpisodeIds,
    })
    .then((r) => r.data);

export const sendChatMessage = (sessionId: string, message: string) =>
  api
    .post<ChatMessageResponse>(`/chat/${sessionId}/message`, { message })
    .then((r) => r.data);

export const deleteChatSession = (sessionId: string) =>
  api.delete(`/chat/${sessionId}`);

export default api;


// ── Error helpers ─────────────────────────────────────────────────────────────

export function isError404(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    (error as { response?: { status?: number } }).response?.status === 404
  )
}