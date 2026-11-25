"""Unit tests for the two rerankers, promoted from their module self-tests.

The research modules self-test under `python -m ...`, which is a good habit and invisible to CI.
These are the same assertions as pytest cases, plus the properties that matter once the rerankers
run on live traffic rather than a benchmark.
"""

from __future__ import annotations

import pytest

from src.services.search.diversity import SceneCapReranker
from src.services.search.filters import (
    MetadataFilterReranker,
    metadata_constraint,
    satisfied_conditions,
    satisfies,
)

META_FRONT_LEFT = {
    "objects": {"car": 2, "pedestrian": 1},
    "relations": {"car": ["front", "front_left"], "pedestrian": ["front"]},
    "scene": {"time": "night"},
}
META_FRONT_RIGHT = {"objects": {"car": 1}, "relations": {"car": ["front_right"]}, "scene": {"time": "day"}}
CAR_FRONT_LEFT = {"objects": ["car"], "relations": {"car": ["front_left"]}, "scene": {}}
AT_NIGHT = {"objects": [], "relations": {}, "scene": {"time": "night"}}


class TestMetadataFilter:
    def test_matches_object_and_relation(self):
        assert satisfies(META_FRONT_LEFT, CAR_FRONT_LEFT) is True
        assert satisfies(META_FRONT_RIGHT, CAR_FRONT_LEFT) is False
        assert satisfies({"objects": {}, "relations": {}}, CAR_FRONT_LEFT) is False

    def test_relation_must_be_on_the_right_category(self):
        """A pedestrian at front-left is not a car at front-left, however tempting the counts are."""
        assert satisfies(META_FRONT_LEFT, {"objects": [], "relations": {"pedestrian": ["front_left"]}}) is False

    def test_unconstrained_queries_produce_no_constraint(self):
        """This is why single- and multi-tier results were bit-identical in 026ab3a6."""
        assert metadata_constraint(None) is None
        assert metadata_constraint({"objects": ["car"]}) is None
        assert metadata_constraint({"objects": ["car"], "relations": {"car": ["front_left"]}}) == CAR_FRONT_LEFT


class TestSceneTags:
    """M2_DESIGN §11.2 — `time` is a tagged field, so scene conditions now reach the filter."""

    def test_a_scene_condition_alone_is_enough_to_build_a_constraint(self):
        """`driving at night` carries no object and no relation, and must still filter."""
        assert metadata_constraint({"scene": {"time": "night"}}) == AT_NIGHT

    def test_untagged_axes_are_dropped_from_the_constraint(self):
        """`weather` measured 76.3%, so it is not written — and a constraint on it matches nothing.

        Passing it through would make `count_satisfying` read 0 and the graph relax a query the
        embedding could have answered perfectly well on its own.
        """
        assert metadata_constraint({"scene": {"weather": "rain"}}) is None
        assert (
            metadata_constraint(
                {"relations": {"car": ["front_left"]}, "objects": ["car"], "scene": {"weather": "rain"}}
            )
            == CAR_FRONT_LEFT
        )

    def test_time_is_matched_exactly(self):
        assert satisfies(META_FRONT_LEFT, AT_NIGHT) is True
        assert satisfies(META_FRONT_RIGHT, AT_NIGHT) is False

    def test_an_untagged_frame_is_unknown_not_non_matching(self):
        """A corpus promoted before tagging existed must degrade to the old behaviour, not to zero."""
        assert satisfies({"objects": {"car": 1}, "relations": {}}, AT_NIGHT) is True

    def test_scene_conditions_are_conjoined_with_object_ones(self):
        both = {"objects": ["car"], "relations": {"car": ["front_left"]}, "scene": {"time": "night"}}
        assert satisfies(META_FRONT_LEFT, both) is True
        assert satisfies({**META_FRONT_LEFT, "scene": {"time": "day"}}, both) is False

    def test_evidence_labels_name_the_scene_condition(self):
        assert satisfied_conditions(META_FRONT_LEFT, AT_NIGHT) == ["scene:time=night"]
        assert satisfied_conditions(META_FRONT_RIGHT, AT_NIGHT) == []

    def test_promotes_matches_preserving_relevance_order(self):
        meta = {"a": META_FRONT_LEFT, "b": META_FRONT_RIGHT, "c": META_FRONT_LEFT}
        assert MetadataFilterReranker(meta, CAR_FRONT_LEFT).rank(["b", "a", "c"], {}) == ["a", "c", "b"]

    def test_is_a_noop_without_a_constraint(self):
        assert MetadataFilterReranker({}, None).rank(["b", "a"], {}) == ["b", "a"]

    def test_unknown_frame_is_non_matching_not_an_error(self):
        """Detector recall is imperfect, so a frame with no metadata must rank low, not crash."""
        meta = {"a": META_FRONT_LEFT}
        assert MetadataFilterReranker(meta, CAR_FRONT_LEFT).rank(["zz", "a"], {}) == ["a", "zz"]

    def test_satisfied_conditions_reports_evidence(self):
        assert satisfied_conditions(META_FRONT_LEFT, CAR_FRONT_LEFT) == ["object:car", "rel:car:front_left"]
        assert satisfied_conditions(META_FRONT_RIGHT, CAR_FRONT_LEFT) == ["object:car"]
        assert satisfied_conditions(None, CAR_FRONT_LEFT) == []


class TestSceneDiversity:
    GROUPS = {**{f"a{i}": "sceneA" for i in range(6)}, "b1": "sceneB", "c1": "sceneC"}
    RANKED = ["a0", "a1", "a2", "a3", "a4", "a5", "b1", "c1"]

    def test_breaks_up_a_single_scene_run(self):
        """The near-duplicate collapse this exists to fix: six frames of one clip at the top."""
        out = SceneCapReranker(self.GROUPS, max_per_group=2, window=99).rank(self.RANKED, {})
        assert out[:4] == ["a0", "a1", "b1", "c1"]
        assert len({self.GROUPS[i] for i in out[:4]}) == 3

    def test_is_always_a_permutation(self):
        out = SceneCapReranker(self.GROUPS, 2, 99).rank(self.RANKED, {})
        assert sorted(out) == sorted(self.RANKED)

    def test_window_bounds_the_damage(self):
        """Past the window, relevance order is returned untouched — the §7 finding, as a test."""
        out = SceneCapReranker(self.GROUPS, max_per_group=2, window=3).rank(self.RANKED, {})
        assert out[:3] == ["a0", "a1", "b1"]
        assert out[3:] == ["a2", "a3", "a4", "a5", "c1"]

    def test_cap_at_or_above_worst_group_is_a_noop(self):
        assert SceneCapReranker(self.GROUPS, 6, 99).rank(self.RANKED, {}) == self.RANKED

    def test_ungrouped_items_are_their_own_group(self):
        assert SceneCapReranker({}, 1, 99).rank(self.RANKED, {}) == self.RANKED

    def test_relevance_order_preserved_within_a_group(self):
        out = SceneCapReranker(self.GROUPS, 2, 99).rank(self.RANKED, {})
        assert [i for i in out if self.GROUPS[i] == "sceneA"] == ["a0", "a1", "a2", "a3", "a4", "a5"]

    @pytest.mark.parametrize("cap,window", [(0, 10), (10, 0)])
    def test_rejects_degenerate_configuration(self, cap, window):
        with pytest.raises(ValueError):
            SceneCapReranker(self.GROUPS, max_per_group=cap, window=window)
