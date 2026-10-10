// src/components/QueueActivity.tsx
import { QueueRow } from "@/components/QueueRow";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useQueueActive, useQueueWidget } from "@/hooks/useQueue";
import { useQueueClearedAt } from "@/hooks/useQueueClearedAt";
import { QUEUE_SECTIONS } from "@/lib/queue";
import { LucideArrowUpRightFromSquare, LucideCheckCheck, LucideCircle, LucideCircleFadingArrowUp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "./ui/button";
import { ScrollArea } from "./ui/scroll-area";

export function QueueActivity() {
  const { data: active = false } = useQueueActive();
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} modal={true} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="icon" aria-label={active ? "Queue: work in progress" : "Queue"}>

          {active ? <LucideCircleFadingArrowUp className="rotate-180" /> : <LucideCircle  />}

        </Button>
      </PopoverTrigger>
      <PopoverContent className="overflow-clip p-0 m-0 mr-16 max-h-[75dvh]">
        <ScrollArea className="overflow-y-auto scrollbar-thin dark:scrollbar-track-card  dark:scrollbar-thumb-card-foreground">
          <QueueWidgetPanel onNavigate={() => setOpen(false)} />
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}

function QueueWidgetPanel({ onNavigate }: { onNavigate: () => void }) {
  const { clearedAt, clear } = useQueueClearedAt();
  const { data, isLoading, isError } = useQueueWidget(clearedAt);

  if (isLoading) return <p>Loading…</p>;
  if (isError || !data) return <p>Failed to load queue.</p>;

  const { groups, latestResultAt } = data;
  const isEmpty = QUEUE_SECTIONS.every(({ key }) => groups[key].total === 0);

  return (
    <div
      className="bg-card"
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("a")) onNavigate();
      }}
    >
      <header className="px-4 flex flex-row justify-between items-center-safe border-b mb-4">
        <span className="">
          <span className="mr-1">Queue</span>
          <Link to="/queue" className="text-foreground hover:text-hover transition-colors">
            <LucideArrowUpRightFromSquare className="inline" size={14} />
          </Link>
        </span>

        <Button
          size="lg"
          variant="ghost"
          title="Mark all complete as read"
          onClick={() => latestResultAt !== null && clear(latestResultAt)}
          disabled={latestResultAt === null}
        >
          <LucideCheckCheck />
        </Button>
      </header>

      {isEmpty ? (
        <p className="p-4">Nothing in the hopper...</p>
      ) : (
        QUEUE_SECTIONS.map(({ key, title }) => {
          const group = groups[key];
          if (group.total === 0) return null;
          const more = group.total - group.items.length;
          return (
            <section className={"px-4 "} key={key}>
              <h3 className="border-b font-mono">
                {title} ({group.total})
              </h3>
              <ul className={(key === "finished" ? "text-muted-foreground " : "")} >
                {group.items.map((item) => (
                  <QueueRow key={item.id} item={item} compact />
                ))}
              </ul>
              {more > 0 && <Link to="/queue" className="hover:text-hover transition-colors">{more} more…</Link>}
            </section>
          );
        })
      )}

      <footer className="p-4 border-t">

      </footer>
    </div>
  );
}