// src/components/QueueRow.tsx
import { getFeedArtworkUrl, type QueueEpisodeItem } from "@/api/client";
import { ElapsedTime } from "@/components/ElapsedTime";
import { Button } from "@/components/ui/button";
import CoverArt from "@/components/ui/CoverArt";
import { ResetEpisodeButton } from "@/components/ui/ResetEpisodeButton";
import {
  queueActionErrorMessage,
  useEpisodeActions
} from "@/hooks/useQueueActions";
import { formatDuration, formatRelativeDate } from "@/lib/date";
import { ACTIVE_STATUSES, formatPipelineStatus, resetActionLabel } from "@/lib/episode";
import { LucideCheckCircle2, LucideSpeech, LucideTriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";

interface QueueRowProps {
  item: QueueEpisodeItem;
  compact?: boolean; // widget: title + status only
}

export function QueueRow({ item, compact = false }: QueueRowProps) {
  const isError = item.pipeline_status === "ERROR";
  const isActive = ACTIVE_STATUSES.includes(item.pipeline_status);

  const { retryMutation, resetMutation } = useEpisodeActions({
    episodeId: item.id,
    feedId: item.feed.id,
  });
  const error = retryMutation.error ?? resetMutation.error;

  return (
    <li className="flex flex-row gap-4 py-4 border-b last:border-b-0">
      <CoverArt
        src={item.image_url}
        className={(compact ? " max-w-10 h-10" : " max-w-16 h-16") + " w-full shadow-md aspect-square rounded"}
        proxySrc={getFeedArtworkUrl(item.feed.id)}
        alt={"CoverArt:" + item.title}
        />

      <div>
        <h3 className={(compact ? "" : " text-lg ") + " font-bold"}>
          <Link to={`/episodes/${item.id}`} className="hover:text-hover transition-colors">
            {item.title ?? "Untitled episode"}</Link>
        </h3>

        <p className={(compact ? "text-sm" : "text-md ") + " italic font-mono "}>
          <Link to={`/feeds/${item.feed.id}/episodes`} className="hover:text-hover transition-colors">{item.feed.title}</Link>
        </p>

        <div className={(compact ? "text-xs" : "text-xs") + " flex flex-row items-center gap-4 mt-2"}>
          <div className="">
            <LucideSpeech className="inline mr-2" size={18} />
            {formatDuration(item.duration_seconds)}
          </div>

          {!compact && (
          <div className="">
            <div className="flex flex-row items-center gap-6">

              {(!item.possibly_stuck && ACTIVE_STATUSES.includes(item.pipeline_status) && (
                    <div className={(compact ? "text-xs" : "text-xs") + " ml-2"}>
                  <ElapsedTime since={item.pipeline_status === 'QUEUED' ? item.queued_at : item.status_changed_at} className="block" />
                      <div className={" "}>{(formatPipelineStatus(item.pipeline_status))}</div>
                        </div>
              ))}

              {(!isError && item.possibly_stuck) && (
              <div className="flex flex-row items-center gap-2">
                <div title="Taking longer than expected...">
                  <LucideTriangleAlert size={18} className="inline" />
                </div>
                      <div className={(compact ? "text-xs" : "text-xs") + +" ml-2 items-start"}>
                  <ElapsedTime since={item.pipeline_status === 'QUEUED' ? item.queued_at : item.status_changed_at} className="block" />
                    <div className={(compact ? "text-xs" : "text-sm") + " text-xs "}>{formatPipelineStatus(item.pipeline_status)}</div>
                </div>
              </div>
              )}

            </div>

          {error && <p className="text-destructive text-xs">{queueActionErrorMessage(error)}</p>}

        </div>
        )}
          {compact && item.possibly_stuck && (
            <span title="Taking longer than expected...">
              <LucideTriangleAlert size={18} />
            </span>
          )}
          {(item.pipeline_status === "READY" && item.status_changed_at && (
            <div><LucideCheckCircle2 size={16} className="inline" /> {formatRelativeDate(item.status_changed_at)}</div>
          ))}
        </div>
        {
          !compact && (isError || isActive) && (
            <RowActions item={item} showRetry={isError} resetLabel={resetActionLabel(item.pipeline_status)} className="mt-2 shrink" />
          )
        }




      </div>
    </li>
  );
}

// Split out so the mutation hooks only mount on rows that have actions,
// and each row tracks its own pending/error state.
function RowActions({
  item,
  showRetry,
  resetLabel,
  className
}: {
    item: QueueEpisodeItem;
    showRetry: boolean;
    resetLabel: string
    className?: string | undefined;
}) {
  const { retryMutation, resetMutation } = useEpisodeActions({
    episodeId: item.id,
    feedId: item.feed.id,
  });
  const busy = retryMutation.isPending || resetMutation.isPending;

  return (
    <div className={className}>
    <div className="flex flex-row items-center gap-4 flex-wrap">
      {showRetry && (
        <Button size="xs" onClick={() => retryMutation.mutate()} disabled={busy}>
          Retry
        </Button>
      )}
      <ResetEpisodeButton episodeId={item.id} title={item.title} feedId={item.feed.id} disabled={busy} status={item.pipeline_status}  resetLabel={resetLabel} />
    </div>

    </div>
  );
}

