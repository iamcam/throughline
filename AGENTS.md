# AGENTS.md

Podcast Knowledge Engine (public name: **Throughline**) — a local-first RAG application that ingests podcast feeds, transcribes and diarizes episodes, and exposes a conversational interface for querying podcast content. Python/FastAPI backend, React/Vite frontend, PostgreSQL + pgvector, OpenTelemetry + Phoenix observability.

## Read first, every session

- `docs/ARCHITECTURE.md` — system design, component responsibilities, config reference, API reference, project structure, testing strategy, upgrade path
- `docs/IMPLEMENTATION_PLAN.md` — guiding principles, phase history at a glance, current status, agent-collaboration guidance

Both are intentionally lean. Neither requires the material below to be loaded up front — pull it in only when a task actually touches that area.

## Reference material — read on demand

`docs/reference/architecture/` — full component-level code and design notes that `ARCHITECTURE.md` §3 only summarizes. One file per subsystem:
- `protocols.md` — every Protocol definition (`LLMClient`, `EmbeddingClient`, `TranscriptionService`, `DiarizationService`, `IngestionQueue`, `VectorStore`, `SessionStore`)
- `ingestion-pipeline.md` — pipeline orchestration, queue/worker execution model, transcription, diarization + alignment
- `speaker-identity.md` — speaker inference, the speaker identity/state model
- `query-engine.md` — SSE status streaming, query engine internals, tool definitions
- `data-layer.md` — full Postgres/pgvector schema
- `observability.md` — OTel setup, span reference table
- `frontend.md` — React component inventory, layout patterns, hook details

Open the one file relevant to what you're building — not all seven.

`docs/reference/phases/` — full build history for every completed phase (0 through 15, plus the unplanned 10.1), one file per phase (`phase-NN-slug.md`). `IMPLEMENTATION_PLAN.md`'s Phase Overview table links to each. Open a phase file when you need the reasoning behind a past decision or tech debt noted at the time — not to plan new work.

## Also in `docs/` — read when relevant, not every session

- `FUTURE_SCOPE.md` — backlog and roadmap, organized by tier (high value → research/experimental). Check here before starting undirected work; "What to Build Next" at the bottom has a recommended order. Items marked "Shipped in Phase N" point to that phase's file in `docs/reference/phases/` rather than repeating the implementation detail.
- `OPERATIONS.md` — local dev setup, Docker Compose (the canonical copy — `ARCHITECTURE.md` §7 only summarizes and points here), demo hosting, auth, backups, monitoring

## Working process

- Vertical slices over horizontal layers — get one thing working end-to-end before generalizing
- Test as you go; don't skip a phase's test targets
- No premature abstraction — build the concrete thing, extract the interface once there are two implementations
- Never more than one phase "in flight" at a time
- Key design constraints (speaker_id vs. display_name, DB as source of truth for pipeline status, ProcessPoolExecutor for CPU/GPU-bound work, dependency injection via `dependencies.py`) are listed in `IMPLEMENTATION_PLAN.md`'s "Before You Start" — read them before touching ingestion or query code

## Keeping the docs from re-bloating

This structure only stays useful if new work follows the same split. When starting a new phase, add its task breakdown directly into `IMPLEMENTATION_PLAN.md` (like the archived phases originally had) rather than into `docs/reference/` — it belongs in the reference archive only once it's done. When a phase completes:

1. Write `docs/reference/phases/phase-NN-slug.md` covering what was built, decisions made, known issues/tech debt, and done-when criteria.
2. Trim `IMPLEMENTATION_PLAN.md` back to that phase's one-line row in the Phase Overview table, linking to the new file.
3. Update `IMPLEMENTATION_PLAN.md`'s "Current Status" section.
4. Update `ARCHITECTURE.md` (and the relevant `docs/reference/architecture/*.md` file) if the phase changed system design, config, or the API surface.
5. Update `FUTURE_SCOPE.md` if the phase shipped something tracked there — mark it shipped with a pointer to the new phase file, don't duplicate implementation detail into both places.

If a `docs/reference/architecture/*.md` file or `docs/reference/phases/*.md` file ever grows large enough to become its own burden, split it further rather than letting it regrow into what `ARCHITECTURE.md`/`IMPLEMENTATION_PLAN.md` used to be.