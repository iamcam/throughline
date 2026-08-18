# Phase 10.1 — Feed Sort, Cache Invalidation, Pagination Fixes

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v0.2.1-app-polish`.
> Unplanned follow-up to Phase 10, scoped from its deferred polish items.

**Goal:** Feed list sortable by latest episode; fixes a class of cache-invalidation bugs found during manual testing; pagination scroll fix.

### Tasks

#### 10.1.1 Feed sort by latest episode
`GET /api/v1/feeds?sort=created_at|latest_episode` — descending only. `list_feeds()` selects `MAX(Episode.published_at)` alongside the existing `COUNT(Episode.id)` in the same grouped query; `nulls_last()` on the `latest_episode` sort so feeds with zero episodes sort to the bottom, not the top — sort answers "what's recent," not "what's broken." `FeedResponse` gains `latest_episode_published_at: datetime | None`, populated by every route that returns a `FeedResponse` (new `get_feed_stats()` helper for the single-feed routes).

#### 10.1.2 FeedKebab component
Reusable refresh/delete menu (shadcn `DropdownMenu` + `AlertDialog` confirm step), replacing always-visible refresh/delete buttons on the feed card footer. Used on `FeedsPage` and `EpisodeDetailPage`. Narrow `MutationLike` prop type, not the full TanStack `UseMutationResult` generic — component only needs `.mutate()` and `.isPending`.

#### 10.1.3 Cache invalidation consolidation
Found and fixed the same bug independently in four places: a mutation invalidating only the TanStack query key for the page it was triggered from, not the related feed↔episode keys. Consolidated into `frontend/src/lib/queryInvalidation.ts` — `invalidateFeedAndEpisodes()` and `invalidateAfterFeedDelete()` (delete uses `removeQueries()`, not `invalidateQueries()`, since the data no longer exists).

#### 10.1.4 Pagination scroll fix
`EpisodesPage` pagination wasn't scrolling the list back to top on page change. Fixed with `useLayoutEffect` + a ref on the actual scrolling container (not `window`) — `useEffect` was visibly landing short when the new page's content height differed from the old page's.

### Phase 10.1 Done When
- `GET /feeds?sort=latest_episode` returns correctly sorted, fully-populated results
- Feed card shows episode count + relative latest-episode date
- Refresh/delete on either Feeds or EpisodeDetail correctly updates all affected views
- Pagination returns to top of list on page change
- Git tag: `v0.2.1-app-polish`
