// src/api/client.ts
import axios from "axios";

const api = axios.create({
  baseURL: `${import.meta.env.VITE_API_URL ?? ""}/api/v1`,
  headers: { "Content-Type": "application/json" },
});

// -- Types ---------------------------------------------------------------------

export interface Feed {
  id: string;
  rss_url: string;
  title: string | null;
  description: string | null;
  image_url: string | null;
  episode_count: number;
  latest_episode_published_at: string | null;
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
  pipeline_error: string | null;
  ingestion_job_id: string | null;
}

export interface TranscriptSegment {
  id: string;
  speaker_id: string;
  display_name: string | null;
  text: string;
  start_ms: number;
  end_ms: number;
  sequence_order: number;
}

export interface Transcript {
  episode_id: string;
  segments: TranscriptSegment[];
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

export interface ChatStreamHandlers {
  onToken: (delta: string) => void;
  onDone: (citations: CitationResult[], sessionId: string) => void;
  onError: (detail: string, errorType: string) => void;
}


// -- Feeds ---------------------------------------------------------------------

export const addFeed = (rss_url: string) =>
  api.post<Feed>("/feeds", { rss_url }).then((r) => r.data);

export const listFeeds = () => api.get<Feed[]>("/feeds", { params: { sort: "latest_episode" } }).then((r) => r.data);

export const getFeed = (feedId: string) =>
  api.get<Feed>(`/feeds/${feedId}`).then((r) => r.data);

export const deleteFeed = (feedId: string) => api.delete(`/feeds/${feedId}`);

export const refreshFeed = (feedId: string) =>
  api.post<Episode[]>(`/feeds/${feedId}/refresh`).then((r) => r.data);

// -- Episodes ------------------------------------------------------------------

export const listEpisodes = (feedId: string) =>
  api.get<Episode[]>(`/feeds/${feedId}/episodes`).then((r) => r.data);

export const getEpisode = (episodeId: string) =>
  api.get<Episode>(`/episodes/${episodeId}`).then((r) => r.data);

export const ingestEpisode = (episodeId: string) =>
  api
    .post(`/episodes/${episodeId}/ingest`, { })
    .then((r) => r.data);

export const reingestEpisode = (episodeId: string) =>
  api
    .post(`/episodes/${episodeId}/reingest`, { })
    .then((r) => r.data);


// -- Transcript ----------------------------------------------------------------

export const getTranscript = (episodeId: string) =>
  api.get<Transcript>(`/episodes/${episodeId}/transcript`).then((r) => r.data);

export const deleteEpisodeTranscript = (episodeId: string) =>
  api.delete(`/episodes/${episodeId}/transcript`);

// -- Speakers ------------------------------------------------------------------

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

// -- Chat ----------------------------------------------------------------------

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

export async function streamChatMessage(
  sessionId: string,
  message: string,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const baseURL = import.meta.env.VITE_API_URL ?? "";
  const response = await fetch(
    `${baseURL}/api/v1/chat/${sessionId}/message/stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      signal,
    }
  );

  if (!response.ok) {
    throw new Error(`Stream request failed: ${response.status}`);
  }

  for await (const { event, data } of parseSSEStream(response)) {
    if (event === "token") {
      handlers.onToken((JSON.parse(data) as { delta: string }).delta);
    } else if (event === "done") {
      const parsed = JSON.parse(data) as {
        citations: CitationResult[];
        session_id: string;
      };
      handlers.onDone(parsed.citations, parsed.session_id);
    } else if (event === "error") {
      const parsed = JSON.parse(data) as { detail: string; error_type: string };
      handlers.onError(parsed.detail, parsed.error_type);
    }
    // 'status' events intentionally produce no callback
  }
}


// -- Error helpers -------------------------------------------------------------

export function isError404(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    (error as { response?: { status?: number } }).response?.status === 404
  )
}

// -- Additions ------------------------------------------------------------------

// Generic: turns a fetch Response's streaming body into SSE (event, data) pairs.
// Knows nothing about chat -- reusable for any future POST-based SSE endpoint.
async function* parseSSEStream(response: Response): AsyncGenerator<{ event: string; data: string }> {
  if (!response.body) {
    throw new Error('Response has no body to stream')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventType: string | null = null
  let dataLines: string[] = []

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const lines = buffer.split('\n')
    buffer = lines.pop() ?? '' // last (possibly incomplete) line stays buffered

    for (const rawLine of lines) {
      const line = rawLine.replace(/\r$/, '')
      if (line.startsWith('event:')) {
        eventType = line.slice('event:'.length).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice('data:'.length).trim())
      } else if (line === '') {
        if (eventType !== null) {
          yield { event: eventType, data: dataLines.join('\n') }
        }
        eventType = null
        dataLines = []
      }
    }
  }
}

// -----------------------------------------

export default api;