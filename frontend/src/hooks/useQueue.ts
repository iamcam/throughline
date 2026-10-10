// src/hooks/useQueue.ts
import {
  getQueue,
  type QueueEpisodeItem,
  type QueueGroup,
  type QueueResponse,
} from "@/api/client";
import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";

export const QUEUE_QUERY_KEY = ["queue"] as const;

const ACTIVE_POLL_MS = 5_000;
const IDLE_POLL_MS = 30_000;
const WIDGET_ITEMS_PER_GROUP = 3;

export function hasActiveWork(data: QueueResponse | undefined): boolean {
  return data !== undefined && data.queued.total + data.in_progress.total > 0;
}

function useQueueQuery<T>(select: (data: QueueResponse) => T, poll: boolean) {
  return useQuery({
    queryKey: QUEUE_QUERY_KEY,
    queryFn: getQueue,
    select,
    staleTime: ACTIVE_POLL_MS,
    refetchInterval: poll
      ? (query) =>
          hasActiveWork(query.state.data) ? ACTIVE_POLL_MS : IDLE_POLL_MS
      : false,
  });
}

const selectIsActive = (data: QueueResponse) => hasActiveWork(data);

/**
 * Mount exactly once (in Layout). Owns the app-wide polling timer and
 * returns whether anything is queued or running — the header icon's
 * animation flag.
 */
export function useQueuePoller() {
  return useQueueQuery(selectIsActive, true);
}

/** Non-polling read of the active flag (eg header icon). */
export function useQueueActive() {
  return useQueueQuery(selectIsActive, false);
}

const selectAll = (data: QueueResponse) => data;

export function useQueue() {
  return useQueueQuery(selectAll, false);
}

function changedAfter(iso: string | null, clearedAt: number): boolean {
  return iso !== null && Date.parse(iso) > clearedAt;
}

function latestTimestamp(items: QueueEpisodeItem[]): number | null {
  let latest: number | null = null;
  for (const item of items) {
    if (item.status_changed_at === null) continue;
    const t = Date.parse(item.status_changed_at);
    if (latest === null || t > latest) latest = t;
  }
  return latest;
}

// total is the visible count, not the server's — valid because getQueue()
// sends no limit, so items already holds every row in each group.
function trimGroup(items: QueueEpisodeItem[], perGroup: number): QueueGroup {
  return { total: items.length, items: items.slice(0, perGroup) };
}

export interface QueueWidgetView {
  groups: QueueResponse;
  // Newest visible Finished/Error timestamp — what Clear hides up to.
  latestResultAt: number | null;
}

export function useQueueWidget(
  clearedAt: number | null,
  perGroup = WIDGET_ITEMS_PER_GROUP
) {
  const select = useCallback(
    (data: QueueResponse): QueueWidgetView => {
      const visible = (group: QueueGroup) =>
        clearedAt === null
          ? group.items
          : group.items.filter((item) =>
              changedAfter(item.status_changed_at, clearedAt)
            );
      const finished = visible(data.finished);
      const errored = visible(data.error);
      return {
        groups: {
          queued: trimGroup(data.queued.items, perGroup),
          in_progress: trimGroup(data.in_progress.items, perGroup),
          finished: trimGroup(finished, perGroup),
          error: trimGroup(errored, perGroup),
        },
        latestResultAt: latestTimestamp([...finished, ...errored]),
      };
    },
    [clearedAt, perGroup]
  );
  return useQueueQuery(select, false);
}