# Phase 8 — Frontend: Chat Interface

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v0.1.8-frontend-chat`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see ARCHITECTURE.md for current system design and `docs/reference/architecture/frontend.md` for current frontend detail.

**Goal:** Freeform conversational query UI. Chat available in three contexts: all feeds, single feed, single episode.

### As Built

**New files:**
- `src/hooks/useChatSession.ts` — TanStack `useQuery`-based session hook; StrictMode-safe via query deduplication; `staleTime: Infinity` + focus/reconnect refetch disabled
- `src/components/ChatInterface.tsx` — reusable chat component; `scopeFeedIds?` and `scopeEpisodeIds?` props; `flex flex-col h-full` layout; toolbar + knowledge base sheet shown only when no scope set
- `src/components/CitationList.tsx` — collapsible citations; top 7 by similarity score; audio playback via `#t=` URI fragment
- `src/components/SearchFilterList.tsx` — Sheet knowledge base browser (`side="left"`); self-contained data fetch; read-only V1

**Modified files:**
- `src/pages/ChatPage.tsx` — thin wrapper around `<ChatInterface />`; lazy-loaded via `React.lazy()`
- `src/pages/EpisodesPage.tsx` — `ResizablePanelGroup` wrapping existing content + `<ChatInterface scopeFeedIds={[feedId]} />`; Ask AI button in feed header
- `src/pages/EpisodeDetailPage.tsx` — same resizable pattern; Ask AI disabled when `status !== 'READY'`; chat scoped to episode
- `src/components/Layout.tsx` — updated to `h-screen flex flex-col`; `<main>` is `flex-1 overflow-auto p-6`
- `backend/src/query/result_hydrator.py` — added `audio_url` to `ChunkResult`; episode query fetches title + audio_url in single batched dict
- `backend/src/api/routers/query.py` — added `audio_url` to `CitationResponse`

**Key decisions and gotchas:**

`useChatSession` uses `useQuery` not `useEffect`. React 19 StrictMode double-mounts components — raw `useEffect` triggered two `POST /chat/sessions` calls. TanStack Query's internal deduplication prevents duplicate requests. Confirmed: one network call on mount.

`react-resizable-panels` API as of current version:
- `orientation` not `direction` on `ResizablePanelGroup`
- `panelRef` prop + `usePanelRef()` hook (not `ref` + `ImperativePanel` type — no longer exported)
- `onCollapse`/`onExpand` removed; use `onResize={(size) => setChatOpen(size.asPercentage > 0)}`
- `minSize={320}` in pixels prevents overflow at narrow widths; percentage minSize is too small on mobile

Resizable chat panel layout — critical combination:
```tsx
<ResizablePanel className="flex flex-col h-full">
  <div className="shrink-0 ...">header</div>
  <div className="flex-1 min-h-0 overflow-hidden">
    <ChatInterface ... />
  </div>
</ResizablePanel>
```
`min-h-0` allows flex child to shrink below content size so internal scroll works. `overflow-hidden` clips during collapse animation preventing horizontal scrollbar at zero width. Without both, the chat panel breaks.

`audio_url` in `ResultHydrator` — fetch episode data as a plain dict per row, not as a stored Row object. SQLAlchemy Row objects are only valid during iteration:
```python
episode_data = {
    row.id: {"title": row.title, "audio_url": row.audio_url}
    for row in episode_rows
}
```

Audio playback uses `#t=` URI fragment (Media Fragments spec) — browser seeks natively without JS event listeners. Seek to `start_ms - 3000ms` for context. Confirmed working on major podcast CDNs.

**Known tech debt:**
- V2 scope filtering deferred — scope set once at session creation, no mid-conversation update. Backend needs `GET /chat/{session_id}` and `PATCH /chat/{session_id}`. See Future Scope 1.11.
- `SpeakerNamingPage` still a stub
- Frontend Docker build not validated against Tailwind v4
- No error boundaries

### Phase 8 Done When ✅
- Full product usable end-to-end in browser
- Chat works at `/chat` (all feeds), on EpisodesPage (feed scope), on EpisodeDetailPage (episode scope)
- Citations show resolved speaker names, timestamps, audio playback
- Resizable chat panel opens/closes correctly, preserves state while collapsed
- Git tag: `v0.1.8-frontend-chat`
