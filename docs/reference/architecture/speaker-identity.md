# Speaker Inference and Identity Model

> Moved from ARCHITECTURE.md §3.7–§3.8. Referenced from ARCHITECTURE.md — see that doc for the high-level component map. `LLMClient` Protocol referenced below lives in `docs/reference/architecture/protocols.md`; diarization/alignment context lives in `docs/reference/architecture/ingestion-pipeline.md`.

## Speaker Inference

LLM-assisted name detection runs automatically after diarization + alignment. Uses `LLMClient` Protocol — not the OpenAI SDK directly. One inference call happens per diarized speaker, not once per episode.

**When it runs:** Immediately after diarization/alignment, as part of the single continuous pipeline job. No pipeline pause, regardless of how many speakers are found.

**Per-speaker context window:** for each diarized speaker, the window spans from `padding_ms` before that speaker's first utterance through `window_ms` after it — long enough to catch an introduction spoken by someone else immediately preceding their first line ("my guest today is Marcus..."), not just their own words. All speakers' segments inside that window are included in the prompt, rendered as a labeled script:

SPEAKER_00: "Welcome to the show. My guest today is Marcus Webb."
SPEAKER_01: "Thanks for having me."


**Prompt** (per target speaker):

Below is a transcript excerpt from a podcast, labeled by speaker.
Who is {speaker_id} (what is their name) and what is your confidence on this answer
from low, medium, or high? Use the structured format:

`{"name": "[person name]", "confidence": "[low|medium|high]"}`


**Return type:**

```python
@dataclass
class InferredSpeaker:
    name: str
    confidence: str   # "high" | "medium" | "low"

# src/ingestion/speaker_resolver.py
class SpeakerResolver:
    def __init__(self, llm_client: LLMClient, window_ms: int, padding_ms: int): ...

    async def infer(
        self,
        segments: list[TranscriptSegment],
    ) -> dict[str, InferredSpeaker | None]:
        # One entry per distinct non-UNKNOWN speaker_id present in segments
        # Never guess — a speaker maps to None rather than a low-quality result
```

**Post-inference logic in `SpeakerStore.save_inferred()`:**

| Inference result (per speaker) | Action                                                                                                                                       |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Name found (any confidence)    | Update that speaker's row: `display_name=name`, `name_inferred=true`, `confidence=level`, `name_confirmed=false`                             |
| None found                     | Leave that speaker's row unchanged — `display_name=NULL`. Other speakers on the same episode are unaffected. Pipeline continues to chunking. |

**User confirmation via `PUT /speakers`:**
- If user saves without editing the name: `name_confirmed=true`, `name_inferred` unchanged
- If user edits the name: `name_confirmed=true`, `name_inferred=false`
- Speaker display name can be updated at any time — it is pure metadata, no re-chunking required

**Configuration:**

```
SPEAKER_INFERENCE_WINDOW_MS=900000
SPEAKER_INFERENCE_PADDING_MS=60000
```

**Known limit:** the context window is time-bounded, not length-bounded. A chaotic multi-speaker episode (panel discussion, several speakers all talking within the same window) could produce a very long prompt with no current truncation strategy — not yet hit in practice, tracked in Future Scope if it becomes a problem.

---

## Speaker Identity Model

**Core principle:** `speaker_id` is a stable identifier linking segments and chunks to speaker metadata in `episode_speakers`. Display names are mutable metadata — a name change is a single row update with no effect on chunks or embeddings.

**Diarization-assigned identity:** Segments are written `UNKNOWN` by transcription, then relabeled to real `SPEAKER_00`, `SPEAKER_01`, ... by the diarization + alignment stage (see `docs/reference/architecture/ingestion-pipeline.md`) before `SpeakerResolver` ever runs. A segment with no overlapping diarization turn stays `UNKNOWN` — alignment does not guess.

**Why `UNKNOWN` not a guess:** `UNKNOWN` signals that speaker identity genuinely could not be determined for that segment — either diarization found no overlapping turn (alignment), or `SpeakerResolver` found no confident name for a real diarized speaker. It is never used as a stand-in for "diarization hasn't run" anymore — diarization always runs.

**`SPEAKER_00` is episode-scoped, not global:** The same `SPEAKER_00` identifier in two different episodes refers to two different people. Speaker name resolution in `ToolDispatcher` is scoped to the session's feed IDs to prevent cross-feed collisions. Chunks ingested before multi-feed support was introduced may have ambiguous `speaker_id` values — re-ingestion resolves this.

**Speaker states** (per speaker_id row in `episode_speakers`):

| name_inferred | name_confirmed | confidence            | Meaning                                  |
| --------------- | ----------------- | ------------------------ | ------------------------------------------- |
| false         | false          | NULL                  | Diarized, but inference found no name    |
| true          | false          | "high"/"medium"/"low" | LLM inferred a name, unconfirmed         |
| true          | true           | "high"/"medium"/"low" | Inferred, user confirmed without editing |
| false         | true           | NULL                  | User entered or edited the name manually |

A segment that never got a real diarized label at all (`speaker_id = 'UNKNOWN'`) has no corresponding `episode_speakers` row to look up — `ResultHydrator` falls back to a display placeholder for those, same as before.

**Resolution at read time:** All reads join `episode_speakers` on `speaker_id`. `VectorStore.search()` returns `RawChunkResult` with `speaker_id`. `ResultHydrator` resolves to `display_name` (or `NULL` / "Unknown Speaker" fallback) before returning to callers. Speaker filter queries against `UNKNOWN` speaker_id return no results — expected behavior until diarization runs.
