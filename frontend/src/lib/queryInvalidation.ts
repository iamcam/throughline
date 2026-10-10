// src/lib/queryInvalidation.ts
import type { Episode } from "@/api/client";
import type { QueryClient } from "@tanstack/react-query";

export function invalidateFeedAndEpisodes(
  queryClient: QueryClient,
  feedId: string
) {
  queryClient.invalidateQueries({ queryKey: ["feeds"] });
  queryClient.invalidateQueries({ queryKey: ["feed", feedId] });
  queryClient.invalidateQueries({ queryKey: ["episodes", feedId] });
}

export function invalidateAfterFeedDelete(
  queryClient: QueryClient,
  feedId: string
) {
  queryClient.invalidateQueries({ queryKey: ["feeds"] });
  queryClient.removeQueries({ queryKey: ["feed", feedId] });
  queryClient.removeQueries({ queryKey: ["episodes", feedId] });
}

export function invalidateEpisode(
  queryClient: QueryClient,
  episodeId: string,
  feedId: string
) {
  queryClient.invalidateQueries({ queryKey: ["episode", episodeId] });
  queryClient.invalidateQueries({ queryKey: ["episodes", feedId] });
}

export function invalidateSpeakersAndTranscript(
  queryClient: QueryClient,
  episodeId: string
) {
  queryClient.invalidateQueries({ queryKey: ["speakers", episodeId] });
  queryClient.invalidateQueries({ queryKey: ["transcript", episodeId] });
}

export function invalidateQueue(queryClient: QueryClient) {
  // Must match QUEUE_QUERY_KEY in hooks/useQueue.ts
  queryClient.invalidateQueries({ queryKey: ["queue"] });
}

// Ingest, Retry (reingest), and Reset wipe the episode's derived data and
// move it out of READY. On success, pass the status the server just
// committed: writing it into the cache first flips the READY-gated
// speakers/transcript queries to disabled *before* their data is removed,
// so nothing refetches into a 409. On error, the status is unknown — omit it.
export function invalidateAfterPipelineChange(
  queryClient: QueryClient,
  episodeId: string,
  feedId: string,
  newStatus?: string
) {
  if (newStatus) {
    queryClient.setQueryData<Episode>(["episode", episodeId], (episode) =>
      episode && {
        ...episode,
        pipeline_status: newStatus,
        pipeline_progress: null,
        pipeline_error: null,
      }
    );
  }
  queryClient.removeQueries({ queryKey: ["speakers", episodeId] });
  queryClient.removeQueries({ queryKey: ["speakerPreviews", episodeId] });
  queryClient.removeQueries({ queryKey: ["transcript", episodeId] });
  invalidateEpisode(queryClient, episodeId, feedId);
  invalidateQueue(queryClient);
}

// Reset all touches every ERROR episode across feeds, including ones
// outside the queue's 24h window — so invalidate by prefix rather than id.
export function invalidateAfterBulkReset(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: ["episode"] });
  queryClient.invalidateQueries({ queryKey: ["episodes"] });
  invalidateQueue(queryClient);
}