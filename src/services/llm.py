"""LLM factory and the two LLM calls the product makes.

One node calls a model, and it makes two requests concurrently: the query parse, and a separate
one-field check for a modifier the vocabulary cannot express. Retrieval, filtering, diversity and
rejection are all deterministic arithmetic over precomputed artifacts, so a search still costs two
short completions, not a conversation.

**They are two calls because folding them into one was measured to break the parser.** `v1.6` put
the modifier rules into `_SYSTEM`, which grew it to 10,428 characters, and `gpt-4o-mini` began
repeating categories — `objects: ['pedestrian', 'pedestrian']` — until it ran past `max_tokens` and
the structured output never closed. "a pedestrian on the right" then answered "Search is temporarily
unavailable" on every attempt against the deployed key. Raising `max_tokens` to 2000 did not help,
because the model was looping rather than running slightly over. `_SYSTEM` is therefore back at the
text `v1.5` shipped, which `scripts/measure/measure_parser_stability.py` scores 6/6 on that query;
`eval/results/parser_prompt_stability.json` has the full comparison.
"""

from __future__ import annotations

import asyncio
import logging

from langchain_openai import ChatOpenAI
from openai import LengthFinishReasonError, OpenAIError
from pydantic import BaseModel, Field, ValidationError

from src.config import get_settings
from src.models.schemas import Attribute, Category, QueryConstraint, Relation

logger = logging.getLogger(__name__)


class _CategoryCondition(BaseModel):
    """Everything the query says about one category of object."""

    category: Category
    positions: list[Relation] = Field(default_factory=list)
    attributes: list[Attribute] = Field(default_factory=list)


class _ParsedQuery(BaseModel):
    """The parser's own output shape, which is deliberately *not* `QueryConstraint`.

    `QueryConstraint` keys its relations and attributes by category — the right shape for the filter
    and for the API, since it is exactly what `metadata/filter.py:satisfies` consumes. But a Pydantic
    dict with a constrained key type emits `propertyNames` in its JSON schema, and OpenAI's
    structured-output validator rejects that outright:

        Invalid schema for response_format 'QueryConstraint':
        In context=('properties','relations'), 'propertyNames' is not permitted.

    A list of per-category conditions carries the same information in a shape the API accepts, and
    is a more natural thing to ask a model for than two parallel dicts that have to agree on their
    keys. `to_constraint` does the transposition, so the strictness stays on the API model where it
    protects the filter.
    """

    conditions: list[_CategoryCondition] = Field(default_factory=list)
    weather: str | None = Field(default=None, description="rain or clear, if the query says")
    time_of_day: str | None = Field(
        default=None, description="day or night — whether the query says it is light or dark out"
    )
    out_of_scope: str | None = None
    query_en: str = Field(default="", description="The query in English, verbatim if already English")
    unsupported_relation: str | None = Field(
        default=None, description="The object-relative phrase dropped, e.g. 'to the right of a bus'"
    )

    def to_constraint(self) -> QueryConstraint:
        """Transpose to the category-keyed shape the filter and the API use."""
        scene = {}
        if self.weather in ("rain", "clear"):
            scene["weather"] = self.weather
        if self.time_of_day in ("day", "night"):
            scene["time"] = self.time_of_day
        return QueryConstraint(
            objects=[c.category for c in self.conditions],
            relations={c.category: c.positions for c in self.conditions if c.positions},
            attributes={c.category: c.attributes for c in self.conditions if c.attributes},
            scene=scene,
            out_of_scope=self.out_of_scope,
            # Truncated rather than rejected: this only feeds the caption gate, and a long
            # translation is still a better verification text than a Vietnamese one. Empty stays
            # empty so `verify_node` falls back to the raw query.
            query_en=(self.query_en or "").strip()[:500] or None,
            # Same treatment as `out_of_scope`: bounded free text, empty normalised to None so the
            # responder's "did we ignore anything" test is a single truthiness check.
            unsupported_relation=(self.unsupported_relation or "").strip()[:200] or None,
        )


class _UnsupportedModifier(BaseModel):
    """The modifier check's whole output: one phrase, or nothing.

    Deliberately a single optional string and not a list. The `v1.6` failure was list-shaped — the
    model repeated entries into `conditions` until it exhausted `max_tokens` — and a schema with
    nowhere to put a list cannot fail that way. Keep it scalar.
    """

    phrase: str | None = Field(
        default=None,
        description="The state, colour, condition or accessory the filters cannot express, verbatim",
    )


# Everything the parser is allowed to emit. Inlined into the prompt because the model picks better
# from an explicit list than from a description, and anything outside it produces a constraint the
# metadata filter can never satisfy — a silent empty search rather than a visible error.
_SYSTEM = """You convert a driving-footage search query into a structured constraint.

Return one entry in `conditions` per object category the query mentions, with any positions and
attributes that belong to THAT category.

Categories: pedestrian, car, truck, bus, bicycle, motorcycle
Positions (relative to the ego vehicle, front camera only): front, front_left, front_right
Attributes: moving, stopped, parked, standing, with_rider, without_rider
weather: rain or clear.  time_of_day: day or night.

Rules:
- Extract only what the query actually says. **Never emit a category the query does not name** —
  not one the scene implies, and not one carried over from an example below.
- **positions MUST be empty unless the query names a direction.** Only these words justify one:
  "in front", "ahead", "front-left", "front-right", "to the left/right", "on the left/right", or an
  equivalent. A query that merely implies something is visible — "a car on a beach", "people in the
  street", "crossing" — gets NO position. Inventing one is worse than omitting it: it silently
  narrows the search.
- **A position is where something sits in the FRAME, never where it sits relative to another
  object.** "to the left" and "to the right" on their own are about the frame and take `front_left`
  and `front_right` — **the two sides are treated identically**, and a bare side word is never a
  reason to drop the position. Followed by "of <something>" it is about two objects, which this
  vocabulary cannot express — so emit each named category with **no position on any of them**. Same
  for "behind <something>", "next to <something>", "between <things>". `front_right` means "in the
  right third of the image", a different question from "to the right of that vehicle": most frames
  satisfying one do not satisfy the other, so answering the first when the second was asked is
  answering confidently and wrongly.
  **Whenever you drop a position for this reason, set `unsupported_relation` to the exact phrase you
  dropped** — "to the right of a bus", "behind the truck" — so the answer can admit what it ignored
  instead of quietly answering a narrower question. Leave it null in every other case, including
  when the query simply names no position.
- **"on the left"/"on the right" name a side of the frame; "on <a place>" names a location.** They
  share a word and nothing else: "a car on the left" takes `front_left`, while "a car on a beach"
  takes no position at all. Decide on what follows "on" — a side word, or a place — never on the
  preposition, and never on which object was named.
- Map synonyms onto the vocabulary: "person"/"someone walking" -> pedestrian; "cyclist" -> bicycle;
  "van"/"lorry" -> truck. Use nothing outside the lists above.
- Attach each position to the right category: "a pedestrian to the front-left" puts front_left on
  pedestrian, not on car.
- Set weather ONLY if the query mentions rain, wet roads, or explicitly clear weather. Otherwise
  leave it null — do not guess.
- **`time_of_day` is whether the query says it is LIGHT or DARK out — not whether it uses the words
  "day" and "night".** Set `day` for daylight: "daytime", "in the morning", "in the afternoon", "at
  midday"/"at noon", "sunny", "in bright sunshine", "in the hot sun", "ban ngày", "buổi sáng",
  "buổi chiều", "trời nắng". Set `night` for darkness: "at night", "night-time", "after dark", "in
  the dark", "at midnight", "late at night", "ban đêm", "buổi tối", "đêm khuya". Matching only the
  two literal words leaves a query that plainly states the time unfiltered, which in a night-heavy
  archive means most of it comes back regardless of what was asked.
- **Dusk, dawn, twilight, sunrise and sunset are NEITHER — leave time_of_day null**, and the same
  for "hoàng hôn" and "bình minh". This is the `rain` rule again: the vocabulary has two values and
  these fall between them, so picking the nearer one answers confidently and wrongly. Sunlight is a
  statement about *light*, so "in the hot sun" sets time_of_day day; it says nothing about the sky,
  so weather stays null unless the query separately mentions rain or clear conditions.
- **`rain` means rain. Snow, fog, haze, mist, hail, sleet, storms and dust are NOT rain** — the
  vocabulary has no value for them, so leave weather null rather than choosing the nearest word.
  Calling snow `rain` makes the search return real rainy footage and report it confidently, which
  is a worse answer than admitting the archive has nothing. Time of day is unaffected: "heavy snow
  at night" still sets time_of_day night, and leaves weather null.

- **`query_en` is the query in English, and it is NOT a rewrite.** If the query is already in
  English, return it back EXACTLY as given — same words, same order, same punctuation. Do not
  rephrase it, expand it, correct its spelling or make it more descriptive. If it is in another
  language, translate it plainly and literally into English, adding nothing the query does not say
  and dropping nothing it does. This text is compared against image descriptions, so invented detail
  becomes a false match and omitted detail becomes a false refusal.

- out_of_scope is ONLY for motion across time: cutting in, braking, overtaking, turning,
  accelerating, following, swerving. A single frame cannot show these, so no search can answer them.

- **Do NOT set out_of_scope because the footage might not exist.** "a snow-covered road", "an
  ambulance", "a desert road" are perfectly well-formed single-frame queries. Parse them normally
  and leave out_of_scope null; whether the archive actually contains them is decided later, by a
  separate check, which gives the user a far more useful answer than "out of scope" would.

Examples (the bare-side pairs below are deliberately given for BOTH sides — matching one side only
is how a parser learns to treat "left" and "right" differently, which is always a bug):
  "a pedestrian to the front-left" -> conditions: [{category: pedestrian, positions: [front_left]}]
  "a motorbike to the right" -> conditions: [{category: motorcycle, positions: [front_right]}]
  "a truck to the left" -> conditions: [{category: truck, positions: [front_left]}]
  "a bus on the right" -> conditions: [{category: bus, positions: [front_right]}]
  "a car on the left" -> conditions: [{category: car, positions: [front_left]}]
  "a motorbike to the right of a bus" -> conditions: [{category: motorcycle}, {category: bus}],
                                         unsupported_relation: "to the right of a bus"
  "a truck to the left of a car" -> conditions: [{category: truck}, {category: car}],
                                    unsupported_relation: "to the left of a car"
  "a truck on a wet road at night" -> conditions: [{category: truck}], weather: rain, time_of_day: night
  "a parked car to the front-right" -> conditions: [{category: car, positions: [front_right],
                                                    attributes: [parked]}]
  "a snow-covered road" -> conditions: [], weather: null, out_of_scope: null
  "a cyclist in dense fog" -> conditions: [{category: bicycle}], weather: null
  "a truck in the hot sun" -> conditions: [{category: truck}], time_of_day: day, weather: null
  "a bus in the morning" -> conditions: [{category: bus}], time_of_day: day
  "a pedestrian after dark" -> conditions: [{category: pedestrian}], time_of_day: night
  "a car at dusk" -> conditions: [{category: car}], time_of_day: null
  "a truck parked outside a shop" -> conditions: [{category: truck, attributes: [parked]}]
  "the ego vehicle braking hard" -> out_of_scope: "braking is motion over time, not one frame"

query_en examples (note the English ones are returned unchanged, not improved):
  "a bus on the street"    -> query_en: "a bus on the street"
  "car frontleft"          -> query_en: "car frontleft"
  "người đi bộ bên trái"   -> conditions: [{category: pedestrian, positions: [front_left]}],
                              query_en: "a pedestrian on the left"
  "xe máy vào ban đêm"     -> conditions: [{category: motorcycle}], time_of_day: night,
                              query_en: "a motorbike at night"
  "xe tải lúc trời nắng"   -> conditions: [{category: truck}], time_of_day: day,
                              query_en: "a truck in sunny weather"
  "ô tô đỗ trên phố lúc trời mưa" -> conditions: [{category: car, attributes: [parked]}],
                              weather: rain, query_en: "cars parked on a rainy street"
"""


# Scoped narrowly on purpose. It reports *modifiers* only — never a missing object category. The
# archive holds plenty the filter vocabulary cannot name, and reporting "we cannot check for traffic
# cones" as though it meant "we have none" is exactly the defect issue #112 recorded: 241 of 6,858
# captions name cones, and the product was telling users the archive certainly lacked them.
_MODIFIER_SYSTEM = """A driving-footage archive can filter on: six object categories (pedestrian,
car, truck, bus, bicycle, motorcycle), which third of the frame something appears in, whether it is
moving, stopped, parked, standing, or carrying a rider, rain or clear weather, and day or night.

Return the phrase in the query naming a state, colour, condition or accessory that none of those can
express. Copy it exactly as the query writes it, in the query's own language. Return null when there
is none.

Three things are not your job and return null on their own:
- a position — "on the right", "to the right of a bus". Another step already handles those.
- anything the list above already covers — "parked", "at night", "in the rain".
- an object the archive may simply contain — "traffic cones", "a fire hydrant". A missing filter is
  not missing footage, and reporting it as a caveat tells the user something untrue.

  "a bus on fire"                   -> "on fire"
  "a motorcyclist without a helmet" -> "without a helmet"
  "a red car at night"              -> "red"
  "a pedestrian on the right"       -> null
  "a parked truck in the rain"      -> null
  "traffic cones on the road"       -> null
  "xe máy không đội mũ bảo hiểm"    -> "không đội mũ bảo hiểm"
"""


def get_llm(temperature: float | None = None) -> ChatOpenAI:
    """The shared chat model. `temperature=0` for anything structural — parsing is not creative."""
    settings = get_settings()
    google_key = settings.google_api_key.strip()
    openai_key = settings.openai_api_key.strip()

    use_gemini = bool(google_key) or openai_key.startswith("AIza") or settings.model_name.startswith("gemini")
    api_key = google_key or openai_key
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai/" if use_gemini else None
    model = settings.model_name
    if use_gemini and (not model or model.startswith("gpt-")):
        model = "gemini-3.5-flash-lite"

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=settings.llm_temperature if temperature is None else temperature,
        max_tokens=1000 if use_gemini else 300,
    )


# How many extra attempts a length-capped parse gets. Three attempts total.
#
# **This is a retry, not a fix, and the distinction is the point.** `_SYSTEM` is at its measured
# size limit and shrinking it does not work — every shorter variant that still reports modifiers was
# unstable on the canary, and the real repair was splitting the modifier check into its own call
# (`v1.6.1`). What remains is a residue: `gpt-4o-mini` occasionally degenerates, repeating entries
# until it exhausts `max_tokens`, so the structured output never closes and the search answers
# "Search is temporarily unavailable".
#
# Measured on the deployed key 2026-08-31, in-container because the box's key is not the developer's
# and the same prompt has scored 12/12 on one OpenAI project and 2/6 on another:
#
#   a pedestrian to the front-left   18/20 ok, 2/20 LengthFinishReasonError   (~10%)
#   six canary queries x 10 trials   60/60 parsed                             (0%)
#
# So it is one query *shape* rather than the parser at large.
#
# **The paragraph that stood here claimed the retry took ~10% to ~0.1%. It does not, and the
# arithmetic is the correction (2026-09-01).** Re-measured against the Live URL, `a pedestrian to
# the front-left` failed **12 of 23 calls (~52%)** with `production` unmoved since 2026-08-30 — so
# the model drifted, not us. The failures separate by latency: unrecovered calls took 8.8-11.4 s
# against 1.6-6.6 s for the rest, which is **all three attempts burning the cap inside one request**.
# Independence would have turned 10% into 0.1%; 52% is what correlated attempts look like, and every
# attempt sends an identical prompt at temperature 0, which is the least likely draw to diverge.
#
# The retry still earns its place — the 4.4-6.6 s successes are attempts 2 and 3 landing, so it is
# rescuing calls that would otherwise fail. It is just far weaker than advertised, and **the number
# to quote is the residue, not 0.1%**.
#
# **Two knobs were tried on 2026-09-01 and neither is shipped. Do not re-derive them:**
# - *Hotter retries.* Measured on a developer key over 30 parses per rung: temperature 0.8 invented
#   6 constraints and dropped 2 named categories (`a red car at night` gained `stopped`; `a motorbike
#   to the right of a bus` lost the bus), while `length` did not fall. Trading a visible outage for a
#   silently narrowed search is the wrong direction for this product.
# - *A bigger `max_tokens`.* Untestable where it was tried: the same key produced 0-3 length errors
#   per 30 parses at every cap, so there was nothing to move. `closed-work.md` rejected it in
#   2026-08-23 against the *v1.6* prompt, which is a different prompt from the one shipping.
#
# Both are open questions, not closed ones, and `scripts/measure_parse_degeneration.py` is the
# experiment — run it in a container against the box's key, because that is the only place the
# failure is common enough to measure.
_PARSE_RETRIES = 2


async def _parse(query: str) -> _ParsedQuery:
    """The structured parse, retried when the model runs past `max_tokens` without closing.

    Only `LengthFinishReasonError` is retried, and deliberately so. It is the one failure here known
    to be non-deterministic; an auth error, a rate limit or a schema violation would repeat
    identically and retrying them would turn one clear failure into three slow ones.
    """
    llm = get_llm(temperature=0).with_structured_output(_ParsedQuery)
    for attempt in range(_PARSE_RETRIES + 1):
        try:
            return await llm.ainvoke([("system", _SYSTEM), ("human", query)])
        except LengthFinishReasonError:
            if attempt == _PARSE_RETRIES:
                # Out of attempts: raise, so `search_nodes` still reports the honest "temporarily
                # unavailable" rather than a constraint nobody parsed.
                logger.warning("parse hit the token cap on all %d attempts", _PARSE_RETRIES + 1)
                raise
            logger.info("parse hit the token cap, retrying (attempt %d)", attempt + 1)
    raise AssertionError("unreachable: the loop either returns or raises")


async def detect_unsupported_modifier(query: str) -> str | None:
    """The phrase in `query` naming something the filters cannot express, or None.

    **Advisory, so it fails soft.** This produces a caveat shown beside results; it does not decide
    what is retrieved. A search that returns the right frames without the caveat is a far better
    outcome than no search at all, so any failure here is logged and swallowed. That is the second
    thing the split buys, after stability: in `v1.6` this job shared the parser's call, so it shared
    the parser's failure, and one unparseable modifier took the whole search down with it.
    """
    llm = get_llm(temperature=0).with_structured_output(_UnsupportedModifier)
    try:
        found = await llm.ainvoke([("system", _MODIFIER_SYSTEM), ("human", query)])
    except (OpenAIError, ValidationError) as exc:
        logger.warning("modifier check failed, answering without a caveat: %s", type(exc).__name__)
        return None
    return (found.phrase or "").strip()[:200] or None


async def parse_constraint(query: str) -> QueryConstraint:
    """Natural language → structured constraint.

    This closes the gap M2_DESIGN §9.4 named as the next one: the metadata filter's +0.129 → +0.323
    was measured with constraints *read from the query spec*, which is honest about the facts but is
    not a product. Here the constraint is parsed from the sentence the user actually typed.

    Structured output rather than JSON-in-a-string: the schema is enforced by the API, so an
    unparseable response fails here instead of producing a constraint that silently matches nothing.

    The two requests are issued **concurrently**, not in sequence. The modifier check does not gate
    retrieval and its result is only consulted at the end, so awaiting it in series would add its
    latency to every search for nothing. Cost is one extra completion against a ~600-character
    prompt — a few percent of the parser's, which is what kept this inside the budget in
    [`cost-discipline.md`](../../.claude/rules/cost-discipline.md).

    **Precedence matters and is not arbitrary.** The parser sets `unsupported_relation` itself for a
    dropped *object-relative* phrase ("to the right of a bus"), and that reading wins. It is the more
    specific finding — it names a position the search deliberately ignored — where the modifier check
    only reports a word the vocabulary lacks. Overwriting it would replace "we ignored where you said
    it was" with something vaguer.
    """
    parsed, modifier = await asyncio.gather(_parse(query), detect_unsupported_modifier(query))
    constraint = parsed.to_constraint()
    if modifier and not constraint.unsupported_relation:
        constraint.unsupported_relation = modifier
    return constraint
