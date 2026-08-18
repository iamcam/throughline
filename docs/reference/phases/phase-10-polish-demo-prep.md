# Phase 10 — Polish and Demo Prep

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v1.0.0`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary.
> Followed immediately by an unplanned Phase 10.1 — see `phase-10.1-feed-sort-cache-fixes.md`.

### Tasks

#### 10.1 README.md
- 2-sentence description
- Architecture diagram reference
- 5-command quick start
- Config reference
- Screenshot or demo GIF
- Backend README updated in Phase 9. Frontend README still needed.

#### 10.2 Whisper config rename
Rename `WHISPER_MODEL_SIZE` → `WHISPER_MODEL` in `local.py` constructor,
`_transcribe_sync` signature, and `dependencies.py` call site.
`config.py` already updated in Phase 9.

#### 10.3 Error handling audit
- All pipeline errors stored and surfaced via status endpoint and SSE
- Frontend shows meaningful error states
- Chat 404 on missing session handled gracefully

#### 10.4 Remove superseded endpoint
Remove `POST /api/v1/query/simple` — superseded by chat endpoints in Phase 6.

#### 10.5 Demo seed script
```bash
uv run python scripts/seed_demo.py --feed-url https://... --episodes 5
```
Pre-ingest demo episodes. Commit this so anyone can reproduce your demo.

#### 10.6 Final test pass
```bash
uv run pytest --cov=src --cov-report=term-missing
```
Target: >70% coverage. Ensure contract tests cover all Protocols:
- `OpenAICompatibleLLMClient` satisfies `LLMClient`
- `OpenAICompatibleEmbeddingClient` satisfies `EmbeddingClient`
- `LocalTranscriptionService` + `RemoteTranscriptionService` satisfy `TranscriptionService`
- `BackgroundTaskQueue` satisfies `IngestionQueue`
- `PgvectorStore` satisfies `VectorStore`
- `InMemorySessionStore` satisfies `SessionStore`

### Phase 10 Done When
- README gives a stranger enough to run it
- Seed script produces a good demo state
- Auth in place (`DEMO_AUTH_ENABLED=true`) for hosted version
- Git tag: `v1.0.0`
