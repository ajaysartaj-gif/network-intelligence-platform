"""Tests for core/troubleshooting/hypotheses.py's near-duplicate detection."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.troubleshooting.hypotheses import _similar, content_tokens


def test_distinct_timer_mismatches_are_not_merged_as_similar():
    """Regression: "OSPF hello timer mismatch between neighbors" vs "OSPF
    dead timer mismatch between neighbors" measured at Jaccard ~0.71 (above
    the 0.6 threshold) because domain-boilerplate words (ospf, mismatch,
    between, neighbors) dominated the token overlap, silently merging two
    genuinely DIFFERENT root causes into one and discarding the second
    entirely. Expanding the stop-word list to exclude these connector/
    protocol-name tokens fixes this without weakening real duplicate
    detection (two literal restatements of the SAME cause still merge)."""
    a = "OSPF hello timer mismatch between neighbors"
    b = "OSPF dead timer mismatch between neighbors"
    assert not _similar(a, b), (content_tokens(a), content_tokens(b))


def test_genuine_restatement_still_merges():
    a = "MTU mismatch between OSPF neighbors prevents DBD packet exchange"
    b = "MTU mismatch between OSPF neighbors blocks DBD packet exchange"
    assert _similar(a, b)


def test_exact_duplicate_merges():
    a = "OSPF authentication mismatch between neighbors"
    assert _similar(a, a)
