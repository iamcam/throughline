# Frontend — React + Vite

> Moved from ARCHITECTURE.md §3.13. Referenced from ARCHITECTURE.md — see that doc for the high-level component map.

**Tech stack (as built, Phase 8):**
- React 19 + TypeScript, Vite 8, Tailwind v4 via `@tailwindcss/vite` plugin
- shadcn/ui (Radix style, custom mist theme), remixicon + lucide-react icon libraries
- TanStack Query v5 for server state, React Router v7 for routing
- axios for HTTP, Yarn as package manager
- `react-markdown` for LLM response rendering in chat
- `react-resizable-panels` via shadcn `Resizable` for split-panel chat layout
- Path alias: `@/*` → `src/*` in both tsconfig and vite config

**TanStack Query defaults (`main.tsx`):**

```typescript
new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        const status = getResponseStatus(error)
        if (status !== undefined && status >= 400 && status < 500) return false
        return failureCount < 3
      },
    },
  },
})
```

`retry` skips 4xx responses: a `404`/`409` is the server answering deliberately, and retrying it only repeats the answer (and, before this, multiplied the `409`s from READY-gated routes). Network errors and 5xx still retry up to 3 times.

`staleTime: 30_000` is global — any `useQuery` without its own `staleTime` override is considered fresh for 30 seconds after a successful fetch, even across component remounts. This matters when debugging "data isn't updating" symptoms: a remounted query that doesn't refetch is not necessarily a missing-invalidation bug — check whether the 30-second window is simply still open before assuming the cache key is wrong. Explicit `invalidateQueries()` calls bypass `staleTime` entirely and force a refetch regardless of this window; `useChatSession`'s `staleTime: Infinity` (below) is a per-hook override of this default, set for a different reason (session-orphaning prevention, not general staleness tolerance).

**Feed/episode cache invalidation pattern (`lib/queryInvalidation.ts`):**

Feed-level mutations (refresh, delete) affect data cached under multiple, separate query keys — `['feeds']` (list), `['feed', feedId]` (detail), and `['episodes', feedId]` (episode list for that feed). A mutation invalidating only the query key for the page it's triggered from leaves the others stale; this happened independently in four places before being consolidated. Two shared helpers encode the relationship once:

```typescript
invalidateFeedAndEpisodes(queryClient, feedId)       // feed refresh — all three keys still valid, just stale
invalidateAfterFeedDelete(queryClient, feedId)       // feed delete — detail/episode keys removed via removeQueries(); list key invalidated
invalidateEpisode(queryClient, episodeId, feedId)    // any single-episode mutation (reingest, reset) — invalidates ['episode', episodeId] and ['episodes', feedId]; does not touch feed-level keys
invalidateQueue(queryClient)                         // ['queue'] — after anything that starts, ends, or resets work
invalidateAfterPipelineChange(queryClient, episodeId, feedId, newStatus?)  // ingest/reingest/reset — patches status on success, drops speakers/previews/transcript, invalidates episode + queue
invalidateAfterBulkReset(queryClient)                // reset all errors — prefix-invalidates ['episode'], ['episodes'], ['queue']
```

Any new mutation that changes feed or episode data should use these helpers rather than inlining `invalidateQueries()` calls — the rule is about the data relationship, not about which page or component triggers the change. The `invalidateEpisode` helper was introduced in Phase 11 after the same missing-key bug (status not updating cross-page mid-ingestion) was found independently across four mutations.

**App shell layout:**
- `Layout.tsx` uses `h-screen flex flex-col` — nav takes natural height, `<main>` is `flex-1 overflow-auto p-6`
- Pages using resizable panels (`EpisodesPage`, `EpisodeDetailPage`) get `h-full` from the flex shell and manage their own scroll/padding
- `ChatPage` is lazy-loaded via `React.lazy()` + `Suspense` to keep initial bundle under Vite's 500kb warning threshold

**Chat contexts — three entry points:**

| Context | Route | Scope |
| ------- | ----- | ----- |
| All feeds | `/chat` | No scope — all ingested episodes |
| Single feed | `/feeds/:feedId/episodes` | `scopeFeedIds={[feedId]}` |
| Single episode | `/episodes/:episodeId` | `scopeEpisodeIds={[episodeId]}` |

**Key components:**

- `ChatInterface` — reusable chat UI; accepts optional `scopeFeedIds` and `scopeEpisodeIds` props; owns session via `useChatSession`; `flex flex-col h-full` layout; toolbar shown only when no scope set; `SearchFilterList` sheet rendered only when no scope set
- `CitationList` — collapsible citation block per assistant message; top 7 by similarity score; audio playback via `#t=` URI fragment (Media Fragments spec — browser seeks natively, no JS event listener needed); chunk ID copy button; similarity score badge
- `SearchFilterList` — Sheet-based knowledge base browser (`side="left"`); self-contained, fetches its own feeds data; accordion per feed (`type="multiple"`); lazy episode fetch per feed from TanStack cache; read-only in V1; navigate buttons close sheet and route to feeds/episodes pages
- `EpisodeRow` — episode card; owns its own SSE connection via `useEpisodeStatus`; derives `isActive` from live status not cached status
- `SpeakerRow` — speaker display with confidence badge; popover edit with cancel/save
- `Layout` — nav shell with `NavLink`
- `EpisodeKebab` — Re-transcribe/Reset menu; calls `useEpisodeActions` itself (no mutation props); Re-transcribe per `REINGESTABLE_STATUSES`, Reset per `canReset` (anything but `PENDING`), labelled "Cancel" via `resetActionLabel` for active statuses
- `QueueRow` — one queue item; `compact` for the widget; `RowActions` sub-component mounts `useEpisodeActions` only on rows with actions (errored: Retry + Reset; queued/in progress: Cancel)
- `ElapsedTime` + `useNow` — live durations. `useNow` is one module-level 1s interval shared through `useSyncExternalStore` (created on first subscriber, cleared on last), so every row ticks in step; `ElapsedTime` is a leaf component so only its `<time>` re-renders each second. Formatting lives in `lib/date.ts` (`formatElapsed`: the two largest non-zero units; one set of second-based unit constants shared with `formatDuration`, `formatTimestamp`, `formatRelativeDate`). Queue rows time from `queued_at` while `QUEUED` and from `started_at` once running (v1.9.1)
- `QueueActivity` — header icon + popover; reads the active flag via `useQueueActive` (no polling of its own); the popover panel (`useQueueWidget`, cleared-at cookie) mounts only while open

**Resizable panel pattern (`EpisodesPage`, `EpisodeDetailPage`):**

```tsx
<ResizablePanelGroup orientation="horizontal" className="h-full">
  <ResizablePanel defaultSize="100%" minSize="50%">
    {/* page content — overflow-y-auto h-full p-6 on inner div */}
  </ResizablePanel>
  <ResizableHandle withHandle />
  <ResizablePanel
    panelRef={chatPanelRef}   // usePanelRef() from react-resizable-panels
    defaultSize={0}
    minSize={320}             // pixels, not percentage — prevents overflow at narrow widths
    maxSize="50%"
    collapsible
    onResize={(size) => setChatOpen(size.asPercentage > 0)}
    className="flex flex-col h-full"
  >
    <div className="shrink-0 flex items-center p-2 border-b">
      {/* panel header with close button */}
    </div>
    <div className="flex-1 min-h-0 overflow-hidden">
      <ChatInterface scopeFeedIds/scopeEpisodeIds />
    </div>
  </ResizablePanel>
</ResizablePanelGroup>
```

**Critical layout notes:**
- `min-h-0` on the `ChatInterface` wrapper div is required — without it a flex child won't shrink below its content size and internal scroll breaks
- `overflow-hidden` on the same wrapper clips content during collapse animation, preventing horizontal scrollbar at zero panel width
- `onCollapse`/`onExpand` callbacks were removed in current `react-resizable-panels`; use `onResize={(size) => setChatOpen(size.asPercentage > 0)}` instead
- `panelRef` prop + `usePanelRef()` hook are the current imperative API; `ref` prop and `ImperativePanel` type are no longer exported

**`useChatSession` hook:**

Uses `useQuery` (not `useEffect`) for session creation. React 19 StrictMode double-mounts components in development — a raw `useEffect` triggered two `POST /chat/sessions` calls. TanStack Query's internal deduplication prevents duplicate in-flight requests for the same query key.

```typescript
useQuery({
  queryKey: ['chat-session', scopeFeedIds ?? [], scopeEpisodeIds ?? []],
  queryFn: () => createChatSession(scopeFeedIds ?? [], scopeEpisodeIds ?? []),
  staleTime: Infinity,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
})
```

`staleTime: Infinity` prevents refetch on window focus or reconnect from creating a new session and orphaning the conversation. `resetSession` invalidates the cache entry and refetches, used for 404 recovery.

**SSE / TanStack cache pattern:**

SSE delivers real-time pipeline updates; TanStack Query cache is what React renders from. `useEpisodeStatus(episodeId, cachedStatus)` bridges them. The **cached** status decides when to stream: the hook opens a stream only while the cache says the episode is active, so a mutation that patches the cache (ingest → `QUEUED`, reset/cancel → `PENDING`) opens or closes the stream in the same render. The hook returns a live value only if it came from the stream that is open right now — clearing state in an effect cleanup happens a render too late, so without that check a cancelled row would flash (or, before Phase 21, keep) its last stage. On `READY`, `ERROR`, or `PENDING` the stream ends, the hook returns `null`, and `['episodes']` / `['episode', episodeId]` are invalidated so the cache catches up. Callers render `liveStatus?.status ?? episode.pipeline_status`.

**Queue polling and actions (Phase 21):**

- **One poller.** Every `useQuery` observer with a `refetchInterval` runs its own timer, and requests only dedupe when in flight at the same moment — so the page and the widget polling independently would double the traffic. `useQueuePoller` (mounted once in `Layout`, which wraps every route) owns the interval; `useQueueActive` (header icon), `useQueue` (page), and `useQueueWidget` read the same `['queue']` entry with no interval. Keep the poller in the app shell, not in a visual component: it was first placed in `QueueActivity`, and any page that didn't render the widget stopped polling. The interval is a function of the raw response (`query.state.data`), so it drops to 5s as soon as any refetch shows active work.
- **Views via `select`.** The widget's cleared-at filter and per-group trim run in `select`, so the page and widget share one request. `select` functions are module-level or `useCallback`-wrapped so they don't re-run every render; a boolean `select` (the poller's active flag) only re-renders on change.
- **Mutation state lives where the mutation is triggered.** `useEpisodeActions` is called per row/kebab, so each episode has its own `isPending`/`error`. Callbacks go in the hook options, not `.mutate(vars, {...})` — the latter don't run if the component unmounts, and a reset row leaves the queue.
- **`onSettled` argument order.** `onSuccess(data, variables)` but `onSettled(data, error, variables)` — switching one for the other without adding `_error` silently passes the error (usually `null`) as the variables.
- **`removeQueries` with mounted observers.** Removing a query that a mounted, enabled component still uses just makes it refetch. After ingest/reingest/reset, the READY-gated speaker/transcript queries would refetch into `409`; `invalidateAfterPipelineChange` patches the episode's status in the cache first, so they disable before their data is removed.
- **Widget Clear uses server time.** The cookie stores the newest visible `status_changed_at`, not `Date.now()`, so the comparison never mixes clocks.

**Session state:**

Chat session state lives in `ChatInterface` component. `InMemorySessionStore` on the backend is ephemeral — sessions are lost on server restart. Frontend handles 404 on stale session: shows error message, calls `resetSession()` to create a fresh session automatically.

**Docker note:**

Frontend Docker build (`frontend/Dockerfile` and `frontend` service in `docker-compose.yml`) has not been validated against the Tailwind v4 Vite plugin build. Verify before demo deployment.
