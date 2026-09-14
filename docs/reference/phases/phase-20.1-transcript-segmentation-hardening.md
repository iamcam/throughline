# Phase 20.1 — Transcript Segmentation Hardening

> Moved from this bugfix chat. Status: ✅ Complete. Git tag: `v1.7.4`.
> Unplanned follow-up to Phase 20 (OpenAI Model Compatibility).

**Bug:** `openai.BadRequestError: Invalid 'input[9]': maximum input length is 8192 tokens` during ingestion embedding (`embed_texts(segment_texts)` in `pipeline.py`), on an episode transcribed with `faster_whisper` on the server (the same episode transcribed cleanly locally with `mlx_whisper`).

**Root cause:** confirmed via an OTEL trace — Whisper occasionally drops sentence-ending punctuation entirely across a long run of speech, a known upstream Whisper issue. The transcript segmenter in `src/transcription/local.py` only cut segments on terminal punctuation (`.`/`?`/`!`/`...`/`。`), so an unpunctuated run accumulated into one unbounded segment that later exceeded the embedding API's 8192-token limit.

### Tasks

#### 20.1.1 Three-tier segmentation, punctuation-first
New pure function `_build_segments_from_words(words, min_segment_words, max_segment_tokens, pause_threshold_s, tokenizer)` in `src/transcription/local.py`, extracted so it's directly testable without crossing the `ProcessPoolExecutor` boundary:
1. Cut on terminal punctuation, once at least `min_segment_words` have accumulated — unchanged from prior behavior.
2. If a run of words with no punctuation crosses `max_segment_tokens`, search backward (only past `min_segment_words`) for a word-timestamp gap greater than `pause_threshold_s`, and cut there instead — a rescue mechanism, not a routine cut, so normal speaking pauses inside a properly-punctuated sentence are never mistaken for segment boundaries.
3. If no such pause exists, hard-cut at the token boundary and log a warning. This tier is the actual fix for the crash, and only ever engages once both punctuation and pause-based cuts have failed.

#### 20.1.2 Settings-driven, not hardcoded
`src/config.py` gained `transcription_min_segment_words`, `transcription_max_segment_tokens`, `transcription_pause_threshold_s` (plus `embedding_max_input_tokens`, used by the diagnostic check below). `LocalTranscriptionService.__init__` takes all three as required constructor arguments — no defaults — so every call site must wire them explicitly from `Settings` rather than risk a silently different value at some future call site. `build_transcription_service()` in `pipeline_runner.py` is the only production call site.

#### 20.1.3 Backend-consistent word normalization
`faster_whisper`'s word-timestamp output carries a leading space baked into each word (`" Hello"`); `mlx_whisper`'s does not. `_transcribe_sync`'s `faster_whisper` branch now strips each word (`word.word.strip()`) at construction, matching the `mlx_whisper` branch, so `_build_segments_from_words` can assume clean words regardless of backend. Before this fix, unstripped words could double-space when joined and slightly inflate token counts.

#### 20.1.4 Diagnostic logging, not truncation
A defensive size check was added in `pipeline.py`, immediately before `embed_texts()`, logging any oversized segment (episode id, index, token count, word count, timestamps, text preview) using the already-injected `services.chunker.count_tokens()` and `services.embedder.max_input_tokens`. This reads off `PipelineServices` deliberately, rather than importing `tiktoken`/`Settings` directly, to keep `pipeline.py` — a plain orchestration function — decoupled from the running process's configuration.

#### 20.1.5 Rejected: embedding-layer mean-pooling defense
A second defensive layer was designed — `Embedder._split_for_embedding`/`_embed_batch`, splitting an oversized chunk into pieces and mean-pooling their embeddings — but rejected once the transcription-level fix was in place. Mean-pooling approximates content rather than fixing the actual defect, and the root cause is now handled at its source. `Embedder.max_input_tokens` and `Embedder._tokenizer` remain on the class (matching `Chunker`'s existing dependency-injection pattern) but are otherwise unused beyond the 20.1.4 diagnostic check.

### Test coverage
`tests/unit/test_local_transcription_segmentation.py` (new) — 10 tests against `_build_segments_from_words` directly: normal punctuation-based flush; short-sentence accumulation below `min_segment_words`; pause-rescue cut; hard-cut fallback with no pause available (with a warning-log assertion); a pause occurring before `min_segment_words` (correctly ignored); no words dropped or duplicated across arbitrary cuts; empty input; sequence-order assignment; the exact `pause_threshold_s` boundary (strict `>`, not `>=`); and two chained rescue-cuts within the same run.

`tests/integration/test_ingestion_pipeline.py`'s `test_local_transcription_satisfies_protocol()` updated to pass the three new required constructor args.

### Phase 20.1 Done When
- The originally-offending episode (server, `faster_whisper`) re-ingests without the `BadRequestError`
- `mlx_whisper` (local) and `faster_whisper` (server) both produce segments that respect `max_segment_tokens`
- All new and existing unit/integration tests green
- Git tag: `v1.7.4`
