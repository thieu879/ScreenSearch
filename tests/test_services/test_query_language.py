"""Issue #70: the caption gate must be scored in English, whatever language was typed.

Two failure modes are pinned here, and they fail in opposite directions.

The first is the bug itself: `all-MiniLM-L6-v2` is English-only and the Florence-2 captions are
English, so a Vietnamese query scored 0.057-0.123 where its English twin scored 0.145-0.707. Every
Vietnamese query fell under `tau_reject` and was refused — and the Vietnamese scores did not merely
sit lower, they carried no relevance signal at all, so no threshold could have separated them.

The second is what a careless fix would break. `tau_reject`/`tau_confident` were fitted to MiniLM's
score distribution over English query text. If the canonicalisation rephrased English queries on the
way through, every English score would shift off the distribution the band was measured on — a
regression that no existing test would notice, because the pipeline would still return results.

Retrieval is deliberately not covered here: it is not affected. Measured over 8 en/vn pairs, top-10
object precision was 0.750 English against 0.787 Vietnamese — SigLIP2's text tower reads Vietnamese
directly, so `retrieve_node` keeps the raw query.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.agents.nodes.search_nodes import verify_node
from src.services.llm import _CategoryCondition, _ParsedQuery

VN = "người đi bộ bên trái"
EN = "a pedestrian on the left"


class TestVerifyScoresEnglish:
    @pytest.mark.asyncio
    async def test_a_vietnamese_query_is_verified_against_its_english_translation(self):
        """The whole bug: without this the caption score is 0.123 and the archive is refused."""
        with patch("src.agents.nodes.search_nodes.service.verify", return_value=("high", 0.6, 0.5)) as verify:
            out = await verify_node(
                {"query": VN, "constraint": {"objects": ["pedestrian"], "query_en": EN}, "ranked": ["f0"]}
            )
        assert verify.call_args.args[0] == EN
        assert out["matched"] is True

    @pytest.mark.asyncio
    async def test_an_english_query_is_scored_verbatim(self):
        """The band was calibrated on English query text; a rephrase would move the scores under it."""
        with patch("src.agents.nodes.search_nodes.service.verify", return_value=("high", 0.6, 0.5)) as verify:
            await verify_node(
                {"query": EN, "constraint": {"objects": ["pedestrian"], "query_en": EN}, "ranked": ["f0"]}
            )
        assert verify.call_args.args[0] == EN

    @pytest.mark.asyncio
    async def test_the_constraint_still_reaches_verify_unchanged(self):
        """`query_en` rides in the constraint dict but must not disturb what verify does with it —
        `contradicts_corpus` reads `scene` off this same object."""
        constraint = {"objects": ["motorcycle"], "scene": {"time": "night"}, "query_en": "a motorbike at night"}
        with patch("src.agents.nodes.search_nodes.service.verify", return_value=("high", 0.6, 0.5)) as verify:
            await verify_node({"query": "xe máy vào ban đêm", "constraint": constraint, "ranked": ["f0"]})
        assert verify.call_args.args[2] is constraint

    @pytest.mark.parametrize("constraint", [None, {}, {"query_en": None}, {"query_en": ""}])
    @pytest.mark.asyncio
    async def test_falls_back_to_the_raw_query_when_there_is_no_translation(self, constraint):
        """A parse failure must degrade to the old behaviour, never to verifying an empty string —
        that scores near zero against every caption and would refuse the entire archive."""
        with patch("src.agents.nodes.search_nodes.service.verify", return_value=("high", 0.6, 0.5)) as verify:
            await verify_node({"query": EN, "constraint": constraint, "ranked": ["f0"]})
        assert verify.call_args.args[0] == EN


class TestParsedQueryCanonicalisation:
    def test_the_translation_is_carried_onto_the_constraint(self):
        parsed = _ParsedQuery(conditions=[_CategoryCondition(category="pedestrian")], query_en=EN)
        assert parsed.to_constraint().query_en == EN

    @pytest.mark.parametrize("raw", ["", "   ", "\n"])
    def test_an_absent_translation_becomes_none_not_an_empty_string(self, raw):
        """None is what `verify_node` falls back on. An empty string is falsy too, but storing it
        would put a field in the API response that says the query was canonicalised to nothing."""
        assert _ParsedQuery(query_en=raw).to_constraint().query_en is None

    def test_surrounding_whitespace_is_stripped(self):
        assert _ParsedQuery(query_en=f"  {EN}\n").to_constraint().query_en == EN

    def test_an_overlong_translation_is_truncated_rather_than_rejected(self):
        """`QueryConstraint.query_en` caps at 500. A model that runs on must not raise a
        ValidationError and turn a working search into a 500 — the text only feeds the caption gate,
        where a truncated English sentence still beats an untranslated one."""
        constraint = _ParsedQuery(query_en="a pedestrian " * 100).to_constraint()
        assert len(constraint.query_en) == 500
