# src/ingestion/chunker.py

from __future__ import annotations
import math
import uuid
from dataclasses import dataclass
from typing import Callable
import tiktoken
from src.transcription.base import TranscriptSegment


# ~~~~~~ Tokenizer ~~~~~~


# load once rather than ever time tokenizer is used
_encoder = tiktoken.get_encoding("cl100k_base")

def _default_tokenizer(text: str) -> int:
    return len(_encoder.encode(text))


# ~~~~~~ Internal intermediate types ~~~~~~


@dataclass
class SpeakerBlock:
    """Contiguous run of segments from the same speaker."""
    speaker_id: str
    text: str
    start_ms: int
    end_ms: int


@dataclass
class TopicSegment:
    """One or more speaker blocks sharing a topic."""
    speaker_id: str
    text: str
    start_ms: int
    end_ms: int


# ~~~~~~ Output ~~~~~~


@dataclass
class ChunkData:
    """
    Plain dataclass output from the chunker.
    The pipeline converts this to the Chunk SQLAlchemy model before DB writes.
    embedding is None until the Embedder runs.
    """
    id: uuid.UUID
    episode_id: uuid.UUID
    parent_id: uuid.UUID | None
    chunk_level: str
    speaker_id: str
    text: str
    start_ms: int
    end_ms: int
    token_count: int
    embedding: list[float] | None = None


# ~~~~~~ Chunker ~~~~~~


class Chunker:
    def __init__(
        self,
        chunk_size_tokens: int,
        chunk_overlap_tokens: int,
        min_tokens: int,
        topic_similarity_threshold: float,
        tokenizer: Callable[[str], int] | None = None,
    ):
        self._chunk_size = chunk_size_tokens
        self._overlap = chunk_overlap_tokens
        self._threshold = topic_similarity_threshold
        self._min_tokens = min_tokens
        self._tokenize = tokenizer or _default_tokenizer


    def chunk(
        self,
        episode_id: uuid.UUID,
        segments: list[TranscriptSegment],
        segment_embeddings: list[list[float]],
    ) -> list[ChunkData]:
        if not segments:
            return []
        return self._build_chunks(episode_id, segments, segment_embeddings)


    def _group_by_speaker(
        self,
        segments: list[TranscriptSegment],
    ) -> list[SpeakerBlock]:
        if not segments:
            return []

        blocks: list[SpeakerBlock] = []
        current_segments: list[TranscriptSegment] = [segments[0]]
        current_speaker = segments[0].speaker_id

        for segment in segments[1:]:
            if segment.speaker_id == current_speaker:
                current_segments.append(segment)
            else:
                blocks.append(SpeakerBlock(
                    speaker_id=current_speaker,
                    text=" ".join(s.text for s in current_segments),
                    start_ms=current_segments[0].start_ms,
                    end_ms=current_segments[-1].end_ms,
                ))
                current_segments = [segment]
                current_speaker = segment.speaker_id

        blocks.append(SpeakerBlock(
            speaker_id=current_speaker,
            text=" ".join(s.text for s in current_segments),
            start_ms=current_segments[0].start_ms,
            end_ms=current_segments[-1].end_ms,
        ))
        return blocks


    def _average_embeddings(embeddings: list[list[float]]) -> list[float]:
        if not embeddings:
            return []
        dim = len(embeddings[0])
        centroid = [0.0] * dim
        for emb in embeddings:
            for i, val in enumerate(emb):
                centroid[i] += val
        return [v / len(embeddings) for v in centroid]


    def _segment_by_topic(
        self,
        blocks: list[SpeakerBlock],
        segment_embeddings: list[list[float]],
        segments: list[TranscriptSegment],
    ) -> list[TopicSegment]:
        """
        Cuts on two conditions:
        1. Cosine similarity between adjacent segments drops below threshold
        2. Speaker changes (block boundary)
        Groups resulting runs into TopicSegments.
        """
        if not segments:
            return []

        # Build cut points — indices where a new topic segment starts
        cut_points: set[int] = {0}

        # Condition 1: similarity drops
        for i in range(1, len(segment_embeddings)):
            similarity = _cosine_similarity(segment_embeddings[i-1], segment_embeddings[i])
            if similarity < self._threshold:
                cut_points.add(i)

        # Condition 2: speaker changes
        for i in range(1, len(segments)):
            if segments[i].speaker_id != segments[i-1].speaker_id:
                cut_points.add(i)

        # Build TopicSegments from cut points
        sorted_cuts = sorted(cut_points)
        topic_segments: list[TopicSegment] = []

        for cut_idx, start in enumerate(sorted_cuts):
            end = sorted_cuts[cut_idx + 1] if cut_idx + 1 < len(sorted_cuts) else len(segments)
            seg_slice = segments[start:end]
            topic_segments.append(TopicSegment(
                speaker_id=seg_slice[0].speaker_id,
                text=" ".join(s.text for s in seg_slice),
                start_ms=seg_slice[0].start_ms,
                end_ms=seg_slice[-1].end_ms,
            ))

        return topic_segments


    def _block_embedding_indices(
        self,
        blocks: list[SpeakerBlock],
    ) -> list[int]:
        """
        For each block, return the index of its first segment
        in the flat segment list, for embedding lookup.
        """
        indices = []
        cursor = 0
        for block in blocks:
            # Each block was built from segments — we need to know
            # how many segments it consumed to advance the cursor.
            # Since SpeakerBlock no longer holds segments, we derive
            # the count from token approximation — but we've lost that info.
            # See note below.
            indices.append(cursor)
            cursor += 1  # placeholder — see note
        return indices


    # ~~~ Hierarchical chunk construction ~~~


    def _build_chunks(
        self,
        episode_id: uuid.UUID,
        segments: list[TranscriptSegment],
        segment_embeddings: list[list[float]],
    ) -> list[ChunkData]:
        blocks = self._group_by_speaker(segments)
        topic_segments = self._segment_by_topic(blocks, segment_embeddings, segments)

        chunks: list[ChunkData] = []

        # Help ensure the segments are sufficient length to be useful
        topic_segments = self._merge_short_segments(topic_segments)

        for topic in topic_segments:
            parent_id = uuid.uuid4()
            parent_text = topic.text
            parent_token_count = self._tokenize(parent_text)

            parent = ChunkData(
                id=parent_id,
                episode_id=episode_id,
                parent_id=None,
                chunk_level="parent",
                speaker_id=topic.speaker_id,
                text=parent_text,
                start_ms=topic.start_ms,
                end_ms=topic.end_ms,
                token_count=parent_token_count,
            )
            chunks.append(parent)

            leaves = self._make_leaf_chunks(
                episode_id=episode_id,
                parent_id=parent_id,
                text=parent_text,
                start_ms=topic.start_ms,
                end_ms=topic.end_ms,
                speaker_id=topic.speaker_id,
            )
            chunks.extend(leaves)

        return chunks

    def _make_leaf_chunks(
        self,
        episode_id: uuid.UUID,
        parent_id: uuid.UUID,
        text: str,
        start_ms: int,
        end_ms: int,
        speaker_id: str,
    ) -> list[ChunkData]:
        """
        Sliding window over parent text.
        Window size: chunk_size_tokens. Step: chunk_size - overlap.
        Timestamps on leaves are approximated linearly from the parent range.
        """
        words = text.split()
        total_words = len(words)
        step = max(1, self._chunk_size - self._overlap)
        duration_ms = end_ms - start_ms

        leaves: list[ChunkData] = []
        start = 0

        while start < total_words:
            end = min(start + self._chunk_size, total_words)
            window_text = " ".join(words[start:end])
            token_count = self._tokenize(window_text)

            # Linear interpolation for timestamps
            leaf_start_ms = start_ms + int((start / total_words) * duration_ms)
            leaf_end_ms = start_ms + int((end / total_words) * duration_ms)

            leaves.append(ChunkData(
                id=uuid.uuid4(),
                episode_id=episode_id,
                parent_id=parent_id,
                chunk_level="leaf",
                speaker_id=speaker_id,
                text=window_text,
                start_ms=leaf_start_ms,
                end_ms=leaf_end_ms,
                token_count=token_count,
            ))

            if end == total_words:
                break
            start += step

        return leaves


    def _merge_short_segments(
        self,
        segments: list[TopicSegment]
    ) -> list[TopicSegment]:
        """
        Merge any TopicSegment below min_tokens into its predecessor.
        The first segment is merged forward into the next if it's short
        and has no predecessor to absorb it.
        """
        if not segments:
            return []

        merged: list[TopicSegment] = []
        for segment in segments:
            if merged and self._tokenize(segment.text) < self._min_tokens:
                prev = merged[-1]
                merged[-1] = TopicSegment(
                    speaker_id=prev.speaker_id,
                    text=prev.text + " " + segment.text,
                    start_ms=prev.start_ms,
                    end_ms=segment.end_ms,
                )
            else:
                merged.append(segment)

        # If first segment is short and got no predecessor, merge and forward into the second if one exists
        if len(merged) >= 2 and self._tokenize(merged[0].text) < self._min_tokens:
            merged[1] = TopicSegment(
                speaker_id=merged[1].speaker_id,
                text=merged[0].text + " " + merged[1].text,
                start_ms=merged[0].start_ms,
                end_ms=merged[1].end_ms,
            )
            merged = merged[1:]

        return merged


# ~~~~~~ Helpers ~~~~~~

def _average_embeddings(embeddings: list[list[float]]) -> list[float]:
    """Component-wise average (centroid) of a list of embeddings."""
    if not embeddings:
        return []
    dim = len(embeddings[0])
    centroid = [0.0] * dim
    for emb in embeddings:
        for i, val in enumerate(emb):
            centroid[i] += val
    return [v / len(embeddings) for v in centroid]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _blocks_to_topic_segment(blocks: list[SpeakerBlock]) -> TopicSegment:
    """
    Combines a list of speaker blocks into one topic segment.
    Dominant speaker: whichever speaker_id appears most in the block list.
    In v1 this is always UNKNOWN — logic is correct for diarized future.
    """
    text = " ".join(b.text for b in blocks)
    start_ms = blocks[0].start_ms
    end_ms = blocks[-1].end_ms
    counts: dict[str, int] = {}
    for block in blocks:
        counts[block.speaker_id] = counts.get(block.speaker_id, 0) + 1
    dominant_speaker = max(counts, key=lambda k: counts[k])
    return TopicSegment(
        speaker_id=dominant_speaker,
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
    )
