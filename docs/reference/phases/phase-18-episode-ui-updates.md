# Phase 18 — Episode UI Updates

Small, unrelated-in-substance UI improvements to the episode views, bundled as one phase since they landed together.

**Episode artwork:** per-episode artwork (`<itunes:image>` at the RSS item level), extending the existing feed-level artwork pattern. `episodes.image_url` column (migration `739a4ca980cb`); item-level parsing in `rss_parser.py` mirrors the existing feed-level `hasattr` pattern; `EpisodeResponse.image_url` and `client.ts` `Episode.image_url` carry it to the frontend; `EpisodeRow` and `EpisodeDetailPage` display it, falling back to the feed's artwork when an episode has none.

**Transcript view:** consecutive segments from the same speaker are now concatenated into a single block instead of rendering one block per segment, so speaker labels and formatting read consistently line to line and speaker to speaker. Each speaker block now shows a start timestamp.

**Tests:** `sample_feed.xml` fixture updated (one item with `<itunes:image>`, two without); `test_rss_parser.py` covers both the present and absent cases. No new tests for the transcript-grouping change or for frontend display — no frontend test infrastructure exists yet in this project.
