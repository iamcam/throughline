# Phase 3 — Speaker Inference

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v0.1.3-speakers`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see ARCHITECTURE.md for current system design.
> Note: this phase's single-speaker-only design was later superseded by Phase 13 (per-diarized-speaker inference) — see that phase's file for what actually shipped.

**Goal:** LLM infers host name from intro text with a confidence score. Result pre-populates `episode_speakers`. Pipeline runs straight to chunking — no pause for user input. Speaker names can be updated anytime via API.

**Context:** Diarization is deferred (Future Scope 1.5). All transcript segments arrive from Phase 2 with `speaker_id = 'UNKNOWN'`. This phase attempts to identify a single host name from the intro window. Multi-speaker episodes remain `UNKNOWN` until diarization is available — this is expected and correct, not an error state.

### Tasks

#### 3.1 `InferredSpeaker` dataclass (`src/ingestion/speaker_resolver.py`)

Before writing `SpeakerResolver`, define what it returns:

```python
@dataclass
class InferredSpeaker:
    name: str
    confidence: str   # "high" | "medium" | "low"
```

This is the return type of `SpeakerResolver.infer()`. Returning a typed dataclass (rather than a raw dict) makes the downstream logic in `SpeakerStore` explicit and testable.

#### 3.2 `SpeakerResolver` (`src/ingestion/speaker_resolver.py`) 🤖

`SpeakerResolver` takes a `LLMClient` — not `AsyncOpenAI` directly.

```python
class SpeakerResolver:
    def __init__(self, llm_client: LLMClient, window_ms: int = 900_000):
        self._llm = llm_client
        self._window_ms = window_ms

    async def infer(
        self,
        segments: list[TranscriptSegment],
    ) -> InferredSpeaker | None:
        intro = [s for s in segments if s.start_ms < self._window_ms]
        if not intro:
            return None

        formatted = "\n".join(f'"{s.text}"' for s in intro)
        prompt = f"""Who is the speaker in this podcast transcript and what is your confidence on this answer from low, medium, or high? Use the structured format: {{"name": "[person name]", "confidence": "[low|medium|high]"}}

Transcript:
{formatted}"""

        response = await self._llm.complete(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        try:
            data = json.loads(response.content)
            if data.get("name") and data.get("confidence") in ("low", "medium", "high"):
                return InferredSpeaker(name=data["name"], confidence=data["confidence"])
        except (json.JSONDecodeError, KeyError):
            pass
        return None
```

A few design points worth understanding:

- `temperature=0.0` — this is a factual lookup, not creative generation. We want the most deterministic output the model can give.
- `response_format={"type": "json_object"}` — forces structured output on models that support it (OpenAI, most local models). Avoids the model wrapping the JSON in prose.
- Returning `None` on parse failure rather than raising — the pipeline treats `None` as "couldn't determine, skip" and continues. A bad LLM response shouldn't abort ingestion.
- No diarization means there is only ever one "speaker" to infer. The prompt reflects this — we're asking "who is the speaker" not "who are the speakers".

#### 3.3 Update `SpeakerStore.save_inferred()` (`src/ingestion/speaker_store.py`)

The existing `save_inferred()` was written expecting a `dict[str, str | None]` (one entry per diarized speaker). Update it to accept `InferredSpeaker | None`:

```python
async def save_inferred(
    self,
    episode_id: UUID,
    result: InferredSpeaker | None,
    db: AsyncSession,
) -> None:
    if result is None:
        # Nothing to do — UNKNOWN row already exists from initialize_from_transcript
        return

    # Promote UNKNOWN → SPEAKER_00, set display_name and confidence
    await db.execute(
        update(EpisodeSpeaker)
        .where(
            EpisodeSpeaker.episode_id == episode_id,
            EpisodeSpeaker.speaker_id == "UNKNOWN",
        )
        .values(
            speaker_id="SPEAKER_00",
            display_name=result.name,
            name_inferred=True,
            confidence=result.confidence,
        )
    )
    # Also update transcript_segments and chunks to SPEAKER_00
    await db.execute(
        update(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode_id)
        .values(speaker_id="SPEAKER_00")
    )
    await db.commit()
```

Why update `transcript_segments` too: the `speaker_id` in segments should match `episode_speakers` so joins work correctly. Since there's only one speaker in v1, this is a bulk update of the entire episode.

Note: chunks don't exist yet at this point in the pipeline — they're created in the next step. The chunker will read the updated `speaker_id` from segments.

#### 3.4 Update `episode_speakers` schema

Add `confidence` column to the Alembic migration:

```python
# New column in EpisodeSpeaker model (src/models/db.py)
confidence: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Generate migration:
```bash
uv run alembic revision --autogenerate -m "add confidence to episode_speakers"
uv run alembic upgrade head
```

#### 3.5 Speaker endpoints (`src/api/routers/speakers.py`)

```
GET  /api/v1/episodes/{episode_id}/speakers
→ [{
    speaker_id: "SPEAKER_00",
    display_name: "Marcus Webb",
    name_inferred: true,
    name_confirmed: false,
    confidence: "high"
  }]

GET  /api/v1/episodes/{episode_id}/speakers/preview
→ [{
    speaker_id: "SPEAKER_00",
    sample_quote: "Welcome to the show...",
    sample_timestamp_ms: 0
  }]
# Returns first segment > 20 words for the speaker

PUT  /api/v1/episodes/{episode_id}/speakers
Body: [{ "speaker_id": "SPEAKER_00", "display_name": "Marcus Webb" }]
→ 200 OK
```

`PUT /speakers` logic:
- If `display_name` matches the current `display_name` (user confirmed without editing): set `name_confirmed=true`, leave `name_inferred` unchanged
- If `display_name` differs: set `name_confirmed=true`, `name_inferred=false`
- No pipeline trigger needed — chunking is no longer gated on speaker confirmation

Remove the `AUTO_CHUNK_AFTER_NAMING` config and the `queue.enqueue()` call that was in the original Phase 3.3. The pipeline now runs straight through.

#### 3.6 Update pipeline orchestrator (`src/ingestion/pipeline.py`)

Merge the two-function design (`ingest_episode` + `chunk_episode`) into one continuous function. See the updated pseudocode in ARCHITECTURE.md section 3.4. Key change: no `PENDING_NAMES` status, no pause, no second enqueue.

#### 3.7 Tests

```python
# tests/unit/test_speaker_resolver.py
async def test_infers_name_and_confidence_from_intro()
async def test_returns_none_when_no_name_found()
async def test_returns_none_on_malformed_json()
async def test_filters_to_intro_window_only()
async def test_temperature_zero_used()
async def test_empty_segments_returns_none()

# tests/integration/test_speakers.py
async def test_save_inferred_promotes_unknown_to_speaker_00()
async def test_save_inferred_updates_transcript_segments()
async def test_save_inferred_none_leaves_unknown_intact()
async def test_confirmed_name_sets_name_confirmed_true()
async def test_edited_name_sets_name_inferred_false()
async def test_speaker_lookup_joins_correctly()
async def test_confidence_stored_on_episode_speakers()
```

### Phase 3 Done When
- `SpeakerResolver.infer()` returns `InferredSpeaker | None`
- `SpeakerStore.save_inferred()` promotes `UNKNOWN` → `SPEAKER_00` when name found
- `GET /speakers` returns inferred name with confidence level
- `PUT /speakers` confirms or corrects names; `name_inferred` flag updated correctly
- Pipeline runs straight to chunking — no `PENDING_NAMES` pause
- All tests pass using `MockLLMClient` — no real LLM required
- Git tag: `v0.1.3-speakers`
