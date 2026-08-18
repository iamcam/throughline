# Phase 7 — Frontend: Ingestion Flow

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v0.1.7-frontend-ingestion`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see ARCHITECTURE.md for current system design and `docs/reference/architecture/frontend.md` for current frontend detail.

**Goal:** Full ingestion flow in browser. SSE progress. Speaker confirmation UI.

### As Built

**Stack decisions:**
- Yarn (not npm), Vite 8, React 19, TypeScript, Tailwind v4 via `@tailwindcss/vite` plugin (no postcss.config.js needed)
- shadcn/ui with Radix style, custom mist theme, lucide-react icons
- TanStack Query v5, React Router v7, axios
- Path alias `@/*` → `src/*` in both tsconfig (`baseUrl` + `paths`) and vite config (`resolve.alias`). `components.json` uses explicit `src/` paths — shadcn CLI does not resolve `@/` aliases and will create a literal `@/` directory if aliases are used there.

**Deviations from plan:**
- `SpeakerNamingPage` is a stub — speaker naming built into `EpisodeDetailPage` instead (better UX, popover edit pattern)
- Scaffold uses `yarn create vite` not `npm create vite`; Tailwind v4 setup differs from v3 (no `tailwind.config.js`, single `@import "tailwindcss"` in CSS)
- `EpisodeDetailPage` added at `/episodes/:episodeId` — not in original plan but needed for episode detail + speaker editing
- `EpisodeResponse` backend schema updated to include `description: str | None`

**Critical implementation detail — SSE + TanStack cache sync:**

The `useEpisodeStatus` hook must invalidate the TanStack cache on terminal status. Without this, `episode.pipeline_status` stays stale after ingestion and the SSE hook cannot reopen on reingest. See ARCHITECTURE.md section 3.9 for the pattern.

**Known tech debt from this phase:**
- Episode delete not implemented — needs frontend + backend work (shipped in Phase 11)
- Audio clip playback for speaker verification not implemented — uses `#t=` fragment approach proven in Phase 8 citations; see Future Scope 1.10 (shipped in Phase 13)
- `SpeakerNamingPage` is a stub at `/episodes/:episodeId/speakers` — may be removed or repurposed
- Frontend Docker build not validated against Tailwind v4 Vite plugin — verify before demo deployment
- No error boundaries — API failures surface as silent empty states in most cases

### Phase 7 Done When ✅
- Add feed → trigger ingestion → watch SSE progress to READY — all in browser
- Speaker name (if inferred) visible with confidence badge; editable post-ingestion via popover
- Reingest works correctly — SSE hook reopens after cache invalidation
- Git tag: `v0.1.7-frontend-ingestion`
