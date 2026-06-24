// src/hooks/useEpisodeStatus.ts
import type { PipelineStatusUpdate } from "@/api/client";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";


const TERMINAL_STATUSES = ["READY", "ERROR"];

export function useEpisodeStatus(episodeId: string | null) {
  const [status, setStatus] = useState<PipelineStatusUpdate | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!episodeId) return;

    const source = new EventSource(
      `/api/v1/episodes/${episodeId}/status/stream`
    );

    source.onmessage = (e) => {
      const update: PipelineStatusUpdate = JSON.parse(e.data);
      setStatus(update);
      if (TERMINAL_STATUSES.includes(update.status)) {
        source.close();
        queryClient.invalidateQueries({ queryKey: ["episodes"] });
        queryClient.invalidateQueries({ queryKey: ["episode", episodeId] });
        setStatus(null)
      }
    };

    source.onerror = () => source.close();

    return () => source.close();
  }, [episodeId, queryClient]);

  return status;
}
