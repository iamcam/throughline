# tests/unit/test_chunker.py

import math
import uuid
import pytest
from src.ingestion.chunker import Chunker, TopicSegment
from src.transcription.base import TranscriptSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_segment(
    text: str,
    start_ms: int,
    end_ms: int,
    speaker_id: str = "UNKNOWN",
    sequence_order: int = 0
) -> TranscriptSegment:
    return TranscriptSegment(
        speaker_id=speaker_id,
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
        sequence_order=sequence_order
    )


def word_tokenizer(text: str) -> int:
    """Fast stand-in for tiktoken. Counts whitespace-delimited words."""
    return len(text.split())


def make_chunker(
    chunk_size: int = 50,
    overlap: int = 5,
    threshold: float = 0.75,
    min_tokens: int = 20
) -> Chunker:
    return Chunker(
        chunk_size_tokens=chunk_size,
        chunk_overlap_tokens=overlap,
        min_tokens=min_tokens,
        topic_similarity_threshold=threshold,
        tokenizer=word_tokenizer,
    )


def unit_vector(index: int, size: int = 8) -> list[float]:
    """
    Returns a unit vector with 1.0 at `index` and 0.0 elsewhere.
    Cosine similarity between two different unit vectors = 0.0 (dissimilar).
    Cosine similarity between two identical unit vectors = 1.0 (identical).
    """
    v = [0.0] * size
    v[index] = 1.0
    return v


EPISODE_ID = uuid.uuid4()

# ---------------------------------------------------------------------------
# Short segment merging (speaker-aware)
# ---------------------------------------------------------------------------

def make_topic_segment(
    text: str,
    start_ms: int,
    end_ms: int,
    speaker_id: str = "SPEAKER_00",
) -> TopicSegment:
    return TopicSegment(
        speaker_id=speaker_id,
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
    )


def test_short_segment_merges_into_same_speaker_predecessor():
    long_text = " ".join(f"word{i}" for i in range(25))
    segments = [
        make_topic_segment(long_text, 0, 5000, speaker_id="SPEAKER_00"),
        make_topic_segment("yes", 5000, 6000, speaker_id="SPEAKER_00"),
    ]
    chunker = make_chunker(min_tokens=20)
    merged = chunker._merge_short_segments(segments)
    assert len(merged) == 1
    assert "yes" in merged[0].text
    assert merged[0].end_ms == 6000


def test_short_segment_not_merged_across_speaker_change():
    """The core regression test for the 2.9 bug: a short segment from a
    different speaker must never get folded into its neighbor's chunk."""
    long_text = " ".join(f"word{i}" for i in range(25))
    segments = [
        make_topic_segment(long_text, 0, 5000, speaker_id="SPEAKER_00"),
        make_topic_segment("yes", 5000, 6000, speaker_id="SPEAKER_01"),
    ]
    chunker = make_chunker(min_tokens=20)
    merged = chunker._merge_short_segments(segments)
    assert len(merged) == 2
    assert "yes" not in merged[0].text
    assert merged[1].speaker_id == "SPEAKER_01"
    assert merged[1].text == "yes"


def test_short_segment_between_different_speakers_stays_standalone():
    long_a = " ".join(f"a{i}" for i in range(25))
    long_c = " ".join(f"c{i}" for i in range(25))
    segments = [
        make_topic_segment(long_a, 0, 5000, speaker_id="SPEAKER_00"),
        make_topic_segment("yes", 5000, 6000, speaker_id="SPEAKER_01"),
        make_topic_segment(long_c, 6000, 11000, speaker_id="SPEAKER_02"),
    ]
    chunker = make_chunker(min_tokens=20)
    merged = chunker._merge_short_segments(segments)
    assert len(merged) == 3
    assert merged[1].speaker_id == "SPEAKER_01"
    assert merged[1].text == "yes"


def test_consecutive_short_same_speaker_segments_chain_merge():
    """Same-speaker short segments should still chain-merge across
    multiple filler turns in a row, not just a single one."""
    long_text = " ".join(f"word{i}" for i in range(25))
    segments = [
        make_topic_segment(long_text, 0, 5000, speaker_id="SPEAKER_00"),
        make_topic_segment("yes", 5000, 6000, speaker_id="SPEAKER_00"),
        make_topic_segment("okay", 6000, 6500, speaker_id="SPEAKER_00"),
    ]
    chunker = make_chunker(min_tokens=20)
    merged = chunker._merge_short_segments(segments)
    assert len(merged) == 1
    assert "yes" in merged[0].text
    assert "okay" in merged[0].text
    assert merged[0].end_ms == 6500


def test_leading_short_segment_merges_forward_same_speaker():
    long_text = " ".join(f"word{i}" for i in range(25))
    segments = [
        make_topic_segment("yes", 0, 1000, speaker_id="SPEAKER_00"),
        make_topic_segment(long_text, 1000, 6000, speaker_id="SPEAKER_00"),
    ]
    chunker = make_chunker(min_tokens=20)
    merged = chunker._merge_short_segments(segments)
    assert len(merged) == 1
    assert "yes" in merged[0].text
    assert merged[0].start_ms == 0
    assert merged[0].end_ms == 6000


def test_leading_short_segment_not_merged_forward_different_speaker():
    long_text = " ".join(f"word{i}" for i in range(25))
    segments = [
        make_topic_segment("yes", 0, 1000, speaker_id="SPEAKER_00"),
        make_topic_segment(long_text, 1000, 6000, speaker_id="SPEAKER_01"),
    ]
    chunker = make_chunker(min_tokens=20)
    merged = chunker._merge_short_segments(segments)
    assert len(merged) == 2
    assert merged[0].text == "yes"
    assert merged[1].speaker_id == "SPEAKER_01"


def test_single_short_segment_returns_standalone():
    segments = [make_topic_segment("yes", 0, 1000, speaker_id="SPEAKER_00")]
    chunker = make_chunker(min_tokens=20)
    merged = chunker._merge_short_segments(segments)
    assert len(merged) == 1
    assert merged[0].text == "yes"


def test_merge_short_segments_empty_input_returns_empty():
    chunker = make_chunker(min_tokens=20)
    assert chunker._merge_short_segments([]) == []


def test_cross_speaker_skip_is_logged(caplog):
    long_text = " ".join(f"word{i}" for i in range(25))
    segments = [
        make_topic_segment(long_text, 0, 5000, speaker_id="SPEAKER_00"),
        make_topic_segment("yes", 5000, 6000, speaker_id="SPEAKER_01"),
    ]
    chunker = make_chunker(min_tokens=20)
    with caplog.at_level("INFO"):
        chunker._merge_short_segments(segments)
    assert "standalone" in caplog.text


# ---------------------------------------------------------------------------
# Topic segmentation
# ---------------------------------------------------------------------------

def test_identical_embeddings_produce_one_segment():
    """No topic shift — all content stays in one segment."""
    segments = [make_segment(f"sentence {i}", i * 1000, (i + 1) * 1000) for i in range(4)]
    embeddings = [unit_vector(0)] * 4   # all identical → similarity 1.0 everywhere
    chunker = make_chunker(threshold=0.75)
    topic_segments = chunker._segment_by_topic(embeddings, segments)
    assert len(topic_segments) == 1


def test_dissimilar_embeddings_produce_multiple_segments():
    """Each segment has a completely different embedding → cuts everywhere."""
    segments = [make_segment(f"sentence {i}", i * 1000, (i + 1) * 1000) for i in range(4)]
    embeddings = [unit_vector(i) for i in range(4)]  # all orthogonal → similarity 0.0
    chunker = make_chunker(threshold=0.75)
    topic_segments = chunker._segment_by_topic(embeddings, segments)
    assert len(topic_segments) > 1


def test_similarity_at_threshold_does_not_cut():
    """Boundary is exclusive — equal to threshold means no cut."""
    segments = [make_segment(f"sentence {i}", i * 1000, (i + 1) * 1000) for i in range(2)]
    # Craft two vectors with cosine similarity exactly at threshold
    threshold = 0.75
    v1 = [1.0, 0.0]
    angle = math.acos(threshold)
    v2 = [math.cos(angle), math.sin(angle)]
    embeddings = [v1, v2]
    chunker = make_chunker(threshold=threshold)
    topic_segments = chunker._segment_by_topic(embeddings, segments)
    assert len(topic_segments) == 1


def test_single_segment_produces_one_topic_segment():
    segments = [make_segment("Only one", 0, 1000)]
    embeddings = [unit_vector(0)]
    chunker = make_chunker()
    topic_segments = chunker._segment_by_topic(embeddings, segments)
    assert len(topic_segments) == 1


def test_topic_segments_preserve_timestamps():
    segments = [
        make_segment("Topic A start", 0, 1000),
        make_segment("Topic A end", 1000, 2000),
        make_segment("Topic B start", 2000, 3000),
    ]
    embeddings = [unit_vector(0), unit_vector(0), unit_vector(1)]  # cut before index 2
    chunker = make_chunker(threshold=0.75)
    topic_segments = chunker._segment_by_topic(embeddings, segments)
    assert topic_segments[0].start_ms == 0
    assert topic_segments[0].end_ms == 2000
    assert topic_segments[1].start_ms == 2000
    assert topic_segments[1].end_ms == 3000


# ---------------------------------------------------------------------------
# Chunk hierarchy
# ---------------------------------------------------------------------------

def test_each_topic_segment_produces_one_parent():
    segments = [make_segment(" ".join(f"word{j}" for j in range(25)), i * 1000, (i + 1) * 1000) for i in range(4)]
    embeddings = [unit_vector(0), unit_vector(0), unit_vector(1), unit_vector(1)]
    chunker = make_chunker(threshold=0.75)
    chunks = chunker._build_chunks(EPISODE_ID, segments, embeddings)
    parents = [c for c in chunks if c.chunk_level == "parent"]
    assert len(parents) == 2


def test_leaf_chunks_reference_parent_id():
    segments = [make_segment(f"word {i}", i * 1000, (i + 1) * 1000) for i in range(3)]
    embeddings = [unit_vector(0)] * 3
    chunker = make_chunker(chunk_size=2, overlap=0)
    chunks = chunker._build_chunks(EPISODE_ID, segments, embeddings)
    leaves = [c for c in chunks if c.chunk_level == "leaf"]
    parents = [c for c in chunks if c.chunk_level == "parent"]
    assert len(parents) == 1
    assert all(leaf.parent_id == parents[0].id for leaf in leaves)


def test_chunks_carry_speaker_id_not_display_name():
    segments = [make_segment("Hello world", 0, 1000, speaker_id="SPEAKER_00")]
    embeddings = [unit_vector(0)]
    chunker = make_chunker()
    chunks = chunker._build_chunks(EPISODE_ID, segments, embeddings)
    for chunk in chunks:
        assert chunk.speaker_id == "SPEAKER_00"
        assert not hasattr(chunk, "display_name")


def test_unknown_speaker_id_passes_through():
    segments = [make_segment("Hello world", 0, 1000, speaker_id="UNKNOWN")]
    embeddings = [unit_vector(0)]
    chunker = make_chunker()
    chunks = chunker._build_chunks(EPISODE_ID, segments, embeddings)
    for chunk in chunks:
        assert chunk.speaker_id == "UNKNOWN"


def test_leaf_chunks_within_token_limit():
    long_text = " ".join([f"word{i}" for i in range(200)])
    segments = [make_segment(long_text, 0, 10000)]
    embeddings = [unit_vector(0)]
    chunker = make_chunker(chunk_size=20, overlap=2)
    chunks = chunker._build_chunks(EPISODE_ID, segments, embeddings)
    leaves = [c for c in chunks if c.chunk_level == "leaf"]
    for leaf in leaves:
        assert leaf.token_count <= 20


def test_short_segment_produces_exactly_one_leaf():
    """A segment short enough to fit in one leaf should not be split."""
    segments = [make_segment("short text here", 0, 1000)]
    embeddings = [unit_vector(0)]
    chunker = make_chunker(chunk_size=50, overlap=5)
    chunks = chunker._build_chunks(EPISODE_ID, segments, embeddings)
    leaves = [c for c in chunks if c.chunk_level == "leaf"]
    assert len(leaves) == 1


def test_parent_chunk_spans_full_segment_timestamps():
    segments = [
        make_segment("first", 0, 1000),
        make_segment("second", 1000, 2000),
        make_segment("third", 2000, 5000),
    ]
    embeddings = [unit_vector(0)] * 3
    chunker = make_chunker()
    chunks = chunker._build_chunks(EPISODE_ID, segments, embeddings)
    parent = next(c for c in chunks if c.chunk_level == "parent")
    assert parent.start_ms == 0
    assert parent.end_ms == 5000


def test_chunk_episode_id_set_correctly():
    segments = [make_segment("hello", 0, 1000)]
    embeddings = [unit_vector(0)]
    chunker = make_chunker()
    chunks = chunker._build_chunks(EPISODE_ID, segments, embeddings)
    for chunk in chunks:
        assert chunk.episode_id == EPISODE_ID

def test_short_segments_merged_into_predecessor():
    long_text = " ".join(f"word{i}" for i in range(25))
    short_text = "yes"
    segments = [
        make_segment(long_text, 0, 5000),
        make_segment(short_text, 5000, 6000),
    ]
    embeddings = [unit_vector(0), unit_vector(1)]
    chunker = make_chunker(threshold=0.75)
    chunks = chunker._build_chunks(EPISODE_ID, segments, embeddings)
    parents = [c for c in chunks if c.chunk_level == "parent"]
    assert len(parents) == 1
    assert "yes" in parents[0].text

# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_segments_returns_empty_chunks():
    chunker = make_chunker()
    chunks = chunker._build_chunks(EPISODE_ID, [], [])
    assert chunks == []


def test_token_count_populated_on_all_chunks():
    segments = [make_segment("hello world foo bar", 0, 1000)]
    embeddings = [unit_vector(0)]
    chunker = make_chunker()
    chunks = chunker._build_chunks(EPISODE_ID, segments, embeddings)
    for chunk in chunks:
        assert chunk.token_count is not None
        assert chunk.token_count > 0