// src/hooks/useEpisodeStatus.ts
import type { PipelineStatusUpdate } from "@/api/client";
import { ACTIVE_STATUSES } from "@/lib/episode";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

// Any of these ends a run: finished, failed, or reset/cancelled.
const STREAM_END_STATUSES = ["READY", "ERROR", "PENDING"];

interface LiveUpdate {
  episodeId: string;
  update: PipelineStatusUpdate;
}

/**
 * Streams live pipeline status while the *cached* status says the episode is
 * active. Returns null otherwise -- callers fall back to the cached status.
 */
export function useEpisodeStatus(
  episodeId: string | null,
  cachedStatus: string | undefined
) {
  const [live, setLive] = useState<LiveUpdate | null>(null);
  const queryClient = useQueryClient();

  const streamId =
    episodeId && cachedStatus && ACTIVE_STATUSES.includes(cachedStatus)
      ? episodeId
      : null;

  useEffect(() => {
    if (!streamId) return;

    const source = new EventSource(
      `/api/v1/episodes/${streamId}/status/stream`
    );

    source.onmessage = (e) => {
      const update: PipelineStatusUpdate = JSON.parse(e.data);
      if (STREAM_END_STATUSES.includes(update.status)) {
        source.close();
        setLive(null);
        queryClient.invalidateQueries({ queryKey: ["episodes"] });
        queryClient.invalidateQueries({ queryKey: ["episode", streamId] });
        return;
      }
      setLive({ episodeId: streamId, update });
    };

    source.onerror = () => source.close();

    return () => {
      source.close();
      setLive(null);
    };
  }, [streamId, queryClient]);

  // Only trust a live value from the stream that is open right now.
  return live && live.episodeId === streamId ? live.update : null;
}
