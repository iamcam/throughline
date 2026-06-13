// src/hooks/useChatSession.ts
import { createChatSession } from "@/api/client";
import { useQuery, useQueryClient } from "@tanstack/react-query";

export function useChatSession(
  scopeFeedIds?: string[],
  scopeEpisodeIds?: string[]
) {
  const queryClient = useQueryClient();

  const queryKey = ["chat-session", scopeFeedIds ?? [], scopeEpisodeIds ?? []];

  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () => createChatSession(scopeFeedIds ?? [], scopeEpisodeIds ?? []),
    staleTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const resetSession = async () => {
    await queryClient.invalidateQueries({ queryKey });
  };

  return {
    sessionId: data?.session_id ?? null,
    isCreating: isLoading,
    error: error ? "Failed to start session. Is the backend running?" : null,
    resetSession,
  };
}
