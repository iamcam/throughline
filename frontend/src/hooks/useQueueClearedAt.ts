// src/hooks/useQueueClearedAt.ts
import { useCallback, useState } from "react";

const COOKIE_NAME = "queue_cleared_at";
const MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30 days

function readClearedAt(): number | null {
  const entry = document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${COOKIE_NAME}=`));
  if (!entry) return null;
  const value = Number(entry.slice(COOKIE_NAME.length + 1));
  return Number.isFinite(value) ? value : null;
}

export function useQueueClearedAt() {
  // Lazy initializer: the cookie is read once on mount, not every render.
  const [clearedAt, setClearedAt] = useState<number | null>(readClearedAt);

  const clear = useCallback((upTo: number) => {
    document.cookie = `${COOKIE_NAME}=${upTo}; path=/; max-age=${MAX_AGE_SECONDS}; SameSite=Lax`;
    setClearedAt(upTo);
  }, []);

  return { clearedAt, clear };
}
