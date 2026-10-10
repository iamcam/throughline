// src/hooks/useQueueActions.ts
import {
  getResponseStatus,
  reingestEpisode,
  resetEpisode,
  resetErroredEpisodes,
} from "@/api/client";
import {
  invalidateAfterBulkReset,
  invalidateAfterPipelineChange,
} from "@/lib/queryInvalidation";
import { useMutation, useQueryClient } from "@tanstack/react-query";

export interface EpisodeRef {
  episodeId: string;
  feedId: string;
}

// One instance per row/component — each gets its own pending/error state.
// Callbacks live in the hook options so they still run if the row unmounts
// (e.g. a reset episode leaves the queue).
export function useEpisodeActions({ episodeId, feedId }: EpisodeRef) {
  const queryClient = useQueryClient();

  const refresh = (newStatus?: string) =>
    invalidateAfterPipelineChange(queryClient, episodeId, feedId, newStatus);

  const retryMutation = useMutation({
    mutationFn: () => reingestEpisode(episodeId),
    onSettled: (_data, error) => refresh(error ? undefined : "QUEUED"),
  });

  const resetMutation = useMutation({
    mutationFn: () => resetEpisode(episodeId),
    onSettled: (_data, error) => refresh(error ? undefined : "PENDING"),
  });

  return { retryMutation, resetMutation };
}

export function useResetAllErrors() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: resetErroredEpisodes,
    onSettled: () => invalidateAfterBulkReset(queryClient),
  });
}

export function queueActionErrorMessage(error: unknown): string {
  switch (getResponseStatus(error)) {
    // case 409:
    //   return "This episode changed state before the action landed — the list has been refreshed.";
    case 503:
      return "The job queue is unavailable. The episode is marked as errored; try again shortly.";
    default:
      return "Something went wrong. Please try again.";
  }
}
