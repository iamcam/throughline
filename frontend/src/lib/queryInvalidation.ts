// src/lib/queryInvalidation.ts
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
