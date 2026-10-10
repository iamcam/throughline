// src/lib/queue.ts
import type { QueueGroupKey } from "@/api/client";

export const QUEUE_SECTIONS: { key: QueueGroupKey; title: string }[] = [
  { key: "queued", title: "Queued" },
  { key: "in_progress", title: "In progress" },
  { key: "finished", title: "Finished" },
  { key: "error", title: "Error" },
];
