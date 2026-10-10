// src/pages/QueuePage.tsx
import type { QueueGroup } from "@/api/client";
import { QueueRow } from "@/components/QueueRow";
import { Button } from "@/components/ui/button";
import { useQueue } from "@/hooks/useQueue";
import {
  queueActionErrorMessage,
  useResetAllErrors,
} from "@/hooks/useQueueActions";
import { QUEUE_SECTIONS } from "@/lib/queue";
import { LucideIterationCcw } from "lucide-react";
import type { ReactNode } from "react";



export default function QueuePage() {
  const { data, isLoading, isError } = useQueue();
  const resetAll = useResetAllErrors();

  if (isLoading) return <p>Loading queue…</p>;
  if (isError || !data) return <p>Failed to load queue.</p>;

  return (
    <div className="p-8">
      <h1 className="font-bold wrap-anywhere text-2xl">Episode Queue</h1>
      {/* subtitle: "Finished and errored episodes from the last 24 hours" */}
      <div className="text-sm text-muted-foreground mb-8">Recently ~ Last 24h</div>

      {QUEUE_SECTIONS.filter(({ key })=>data[key].items.length > 0).map(({ key, title }) => (
        <QueueSection
          sectionKey={key}
          key={key}
          title={title}
          group={data[key]}
          headerAction={
            key === "error" && data.error.total > 0 ? (
              <Button
                size="xs"
                variant="ghost"
                className="round-full"
                onClick={() => resetAll.mutate()}
                disabled={resetAll.isPending}
                title="Reset errored episodes"
              >
                <LucideIterationCcw /> Reset all
              </Button>
            ) : null
          }
        />

      ))}
      {resetAll.isError && <p>{queueActionErrorMessage(resetAll.error)}</p>}
    </div>
  );
}

function QueueSection({
  sectionKey,
  title,
  group,
  headerAction,
}: {
  sectionKey: string;
  title: string;
  group: QueueGroup;
  headerAction?: ReactNode;
}) {
  return (
    <div className="py-4">
      <header className="border-b-2 flex flex-row justify-between pb-0">
        <h2 className="font-mono">
          {title}  ({group.total})
        </h2>
        {headerAction}
      </header>
      {group.items.length === 0 ? (
        <p>None</p>
      ) : (
          <ul className={(sectionKey === "finished" ? "text-muted-foreground " : "")} >
            {group.items.map((item) => (
            <QueueRow key={item.id} item={item} />
          ))}
        </ul>
      )}
    </div>
  );
}