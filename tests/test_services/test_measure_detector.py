"""Scoring logic for the §9.3 detector harness.

The harness itself needs the devkit, CUDA and a 6,858-frame corpus, so CI can never run it. The
arithmetic that turns two records into precision and recall needs none of those, and it is the part
that would be wrong silently — a swapped tp/fp still prints a plausible table.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from measure.measure_detector import facts_of, score_facts  # noqa: E402

CATEGORIES = ("bicycle", "bus", "car", "motorcycle", "pedestrian", "truck")


def test_facts_of_reads_presence_and_relations():
    record = {"objects": {"car": 3, "pedestrian": 1}, "relations": {"car": ["front", "front_left"]}}
    assert facts_of(record, CATEGORIES) == {
        "car present",
        "pedestrian present",
        "car front",
        "car front_left",
    }


def test_facts_of_drops_categories_the_detector_cannot_express():
    """Gold carries nine categories, `COCO_TO_VOCAB` maps six.

    Scoring `barrier` would report a recall of 0 that says nothing about the detector — the
    vocabulary simply has no way to predict it. See the module docstring in measure_detector.
    """
    record = {"objects": {"barrier": 2, "car": 1}, "relations": {"barrier": ["front"]}}
    assert facts_of(record, CATEGORIES) == {"car present"}


def test_facts_of_ignores_a_relation_outside_the_three_bands():
    record = {"objects": {"car": 1}, "relations": {"car": ["front", "behind"]}}
    assert facts_of(record, CATEGORIES) == {"car present", "car front"}


def test_score_counts_hits_misses_and_false_alarms_over_frames():
    gold = {
        "f1": {"objects": {"car": 1}, "relations": {}},
        "f2": {"objects": {"car": 1}, "relations": {}},
        "f3": {"objects": {}, "relations": {}},
    }
    predicted = {
        "f1": {"objects": {"car": 1}, "relations": {}},  # hit
        "f2": {"objects": {}, "relations": {}},  # miss
        "f3": {"objects": {"car": 1}, "relations": {}},  # false alarm
    }
    row = score_facts(gold, predicted, CATEGORIES)["car present"]
    assert (row["tp"], row["fn"], row["fp"]) == (1, 1, 1)
    assert row["support"] == 2
    assert row["precision"] == 0.5
    assert row["recall"] == 0.5


def test_a_frame_missing_from_the_predictions_counts_as_a_miss():
    """A detector that never ran on a frame must not quietly shrink the denominator."""
    gold = {"f1": {"objects": {"bus": 1}, "relations": {}}}
    row = score_facts(gold, {}, CATEGORIES)["bus present"]
    assert (row["tp"], row["fn"], row["recall"]) == (0, 1, 0.0)


def test_never_predicted_and_always_wrong_are_not_the_same_number():
    """Precision is None with no predictions, not 0.0.

    Reporting 0.0 would put "the detector never claimed this" and "it claimed it and was wrong every
    time" in the same cell, and those call for opposite responses.
    """
    gold = {"f1": {"objects": {"car": 1}, "relations": {}}}
    predicted = {"f1": {"objects": {}, "relations": {}}}
    row = score_facts(gold, predicted, CATEGORIES)["car present"]
    assert row["precision"] is None
    assert row["recall"] == 0.0
