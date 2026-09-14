# tests/unit/test_local_transcription_segmentation.py
from src.transcription.local import _build_segments_from_words


def _word_tokenizer(text: str) -> int:
    """Stub tokenizer for these tests -- word count, not real BPE. Keeps
    token-count math in assertions simple and independent of tiktoken."""
    return len(text.split())


def test_punctuation_flushes_normal_sentence():
    words = [
        (0.0, 0.2, "Hello"), (0.2, 0.4, "there,"), (0.4, 0.6, "how"),
        (0.6, 0.8, "are"), (0.8, 1.0, "you?"),
    ]
    segments = _build_segments_from_words(
        words, min_segment_words=5, max_segment_tokens=200,
        pause_threshold_s=1.2, tokenizer=_word_tokenizer,
    )
    assert len(segments) == 1
    assert segments[0].text == "Hello there, how are you?"
    assert segments[0].start_ms == 0
    assert segments[0].end_ms == 1000


def test_short_sentence_below_min_words_does_not_flush_early():
    words = [
        (0.0, 0.2, "Yes."), (0.2, 0.4, "No."), (0.4, 0.6, "Maybe."),
        (0.6, 0.8, "I"), (0.8, 1.0, "think"), (1.0, 1.2, "so."),
    ]
    segments = _build_segments_from_words(
        words, min_segment_words=5, max_segment_tokens=200,
        pause_threshold_s=1.2, tokenizer=_word_tokenizer,
    )
    # None of the one-word "sentences" meet min_segment_words, so everything
    # accumulates into a single final segment.
    assert len(segments) == 1
    assert segments[0].text == "Yes. No. Maybe. I think so."


def test_rescue_cuts_at_pause_when_punctuation_missing():
    # No punctuation anywhere. A 1.5s gap appears after index 6 -- past
    # min_segment_words=3, and before max_segment_tokens=8 would force a
    # hard cut with no pause available.
    words = [
        (0.0, 0.2, "one"), (0.2, 0.4, "two"), (0.4, 0.6, "three"),
        (0.6, 0.8, "four"), (0.8, 1.0, "five"), (1.0, 1.2, "six"),
        (1.2, 1.4, "seven"),
        (2.9, 3.1, "eight"), (3.1, 3.3, "nine"), (3.3, 3.5, "ten"),
    ]
    segments = _build_segments_from_words(
        words, min_segment_words=3, max_segment_tokens=8,
        pause_threshold_s=1.2, tokenizer=_word_tokenizer,
    )
    assert len(segments) == 2
    assert segments[0].text == "one two three four five six seven"
    assert segments[1].text == "eight nine ten"
    assert segments[0].end_ms == 1400
    assert segments[1].start_ms == 2900


def test_rescue_hard_cuts_when_no_pause_available(caplog):
    # No punctuation, no pause anywhere -- true run-on case.
    words = [(i * 0.2, i * 0.2 + 0.2, f"word{i}") for i in range(12)]
    with caplog.at_level("WARNING"):
        segments = _build_segments_from_words(
            words, min_segment_words=3, max_segment_tokens=5,
            pause_threshold_s=1.2, tokenizer=_word_tokenizer,
        )
    assert [len(s.text.split()) for s in segments] == [5, 5, 2]
    assert "Forcing segment cut" in caplog.text


def test_pause_before_min_segment_words_is_ignored():
    # 1.8s gap after only 1 word -- min_segment_words=4 means the rescue
    # search only scans from index 4 onward, so this pause must be skipped.
    words = [
        (0.0, 0.2, "one"),
        (2.0, 2.2, "two"), (2.2, 2.4, "three"), (2.4, 2.6, "four"),
        (2.6, 2.8, "five"), (2.8, 3.0, "six"),
    ]
    segments = _build_segments_from_words(
        words, min_segment_words=4, max_segment_tokens=6,
        pause_threshold_s=1.2, tokenizer=_word_tokenizer,
    )
    # No qualifying pause found after index 4 either -> hard cut at 6 words
    assert len(segments[0].text.split()) == 6


def test_no_words_dropped_or_duplicated():
    words = [(i * 0.3, i * 0.3 + 0.3, f"w{i}") for i in range(37)]
    segments = _build_segments_from_words(
        words, min_segment_words=4, max_segment_tokens=7,
        pause_threshold_s=1.2, tokenizer=_word_tokenizer,
    )
    assert " ".join(s.text for s in segments).split() == [f"w{i}" for i in range(37)]


def test_empty_words_produces_no_segments():
    segments = _build_segments_from_words(
        [], min_segment_words=5, max_segment_tokens=200,
        pause_threshold_s=1.2, tokenizer=_word_tokenizer,
    )
    assert segments == []


def test_sequence_order_is_assigned_in_order():
    words = [
        (0.0, 0.2, "Hi."), (0.2, 0.4, "there"), (0.4, 0.6, "friend"),
        (0.6, 0.8, "how"), (0.8, 1.0, "goes?"),
        (1.0, 1.2, "Good,"), (1.2, 1.4, "thanks"), (1.4, 1.6, "for"),
        (1.6, 1.8, "asking"), (1.8, 2.0, "today."),
    ]
    segments = _build_segments_from_words(
        words, min_segment_words=5, max_segment_tokens=200,
        pause_threshold_s=1.2, tokenizer=_word_tokenizer,
    )
    assert [s.sequence_order for s in segments] == list(range(len(segments)))

def test_pause_exactly_at_threshold_does_not_trigger_rescue():
    words = [
        (0.0, 0.2, "one"), (0.2, 0.4, "two"), (0.4, 0.6, "three"),
        (0.6, 0.8, "four"), (0.8, 1.0, "five"), (1.0, 1.2, "six"),
        (2.4, 2.6, "seven"), (2.6, 2.8, "eight"), (2.8, 3.0, "nine"),
    ]
    segments = _build_segments_from_words(
        words, min_segment_words=3, max_segment_tokens=8,
        pause_threshold_s=1.2, tokenizer=_word_tokenizer,
    )
    assert len(segments) == 2
    assert len(segments[0].text.split()) == 8
    assert segments[1].text == "nine"


def test_multiple_rescue_cuts_in_sequence():
    """Two consecutive pause-rescue cuts back to back, confirming the loop
    resets 'current' cleanly and re-applies the same rescue logic to the
    next run rather than carrying stale state across cuts."""
    words = [
        (0.0, 0.2, "one"), (0.2, 0.4, "two"), (0.4, 0.6, "three"),
        (0.6, 0.8, "four"), (0.8, 1.0, "five"), (1.0, 1.2, "six"),
        (1.2, 1.4, "seven"),
        (2.9, 3.1, "eight"), (3.1, 3.3, "nine"), (3.3, 3.5, "ten"),
        (3.5, 3.7, "eleven"), (3.7, 3.9, "twelve"), (3.9, 4.1, "thirteen"),
        (4.1, 4.3, "fourteen"),
        (5.8, 6.0, "fifteen"),
    ]
    segments = _build_segments_from_words(
        words, min_segment_words=3, max_segment_tokens=8,
        pause_threshold_s=1.2, tokenizer=_word_tokenizer,
    )
    assert len(segments) == 3
    assert segments[0].text == "one two three four five six seven"
    assert segments[1].text == "eight nine ten eleven twelve thirteen fourteen"
    assert segments[2].text == "fifteen"
    assert segments[0].end_ms == 1400
    assert segments[1].start_ms == 2900
    assert segments[1].end_ms == 4300
    assert segments[2].start_ms == 5800