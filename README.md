---
title: SceneSearch
emoji: 🚗
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 8000
pinned: false
license: cc-by-nc-sa-4.0
---

<!-- The block above is Hugging Face Spaces configuration, not documentation. Spaces reads sdk and
     app_port from it to know this is a Docker Space serving on 8000; without it the Space routes to
     port 7860 and shows nothing. GitHub renders it as a small metadata table. Keeping one README
     rather than a Space-only copy means the Live URL shows the real project, and there is no second
     file to forget to update. -->

# SceneSearch

**Find driving footage by describing it — and be told honestly when it isn't there.**

An autonomous-driving team holds thousands of hours of unlabelled video. An engineer who needs "a
wet road at night with a pedestrian" for a simulation scenario currently has no way to find it
except scrubbing video or hoping someone tagged it.

The value is not that search beats SQL. It is that **nobody has to define the label taxonomy up
front**. A metadata database can only answer questions someone predicted when the schema was
written; the engineer above is asking for a combination no annotator was ever asked to tag.

That sets the acceptance bar: the system earns its place if an engineer finds usable frames for a
scenario that was never a label.

> **Live URL:** **<https://scenesearch.duckdns.org>** — live since 2026-08-09 on a Google Cloud VM,
> Caddy terminating TLS. `GET /health` answers `corpus_frames: 6858`.
> **Current release:** [`v1.6.1`](../../releases/tag/v1.6.1) · **Serving:** `v1.6.1` — see
> [Releases](#releases) · **Team:** _see [Team](#team)_

---

## What makes this different from "CLIP over some images"

Three things, each measured rather than assumed. The full evidence is in
[`experiments/m1/RESULTS.md`](experiments/m1/RESULTS.md) and
[`experiments/M2_DESIGN.md`](experiments/M2_DESIGN.md); the short version:

**1. It says "nothing matches", and that is a component, not a message.**
An engineer sourcing footage the archive does not contain must be told so. Ten confident wrong
frames cost more than an empty result, because they have to be watched to find out they are wrong.
Rejection works by captioning the top 5 results and checking the query against those descriptions —
which recovers **0.898** of a full caption index's 0.907 Neg-AUROC while captioning 5 frames per
query instead of all of them.

It ships as a **band, not a switch**: high confidence, low confidence (results shown *with* a
caveat), or no match. A single threshold hid about a quarter of legitimate searches, and a wrongly
hidden result is the one error a user cannot detect — they conclude the archive lacks footage it
holds and stop looking.

**2. Spatial queries use detected structure, not a bigger model.**
"A car to the front-left" fails for every image embedding tested, and not because the models cannot
see left from right: cars appear in **5,187 of the 6,858 frames** (76%), so the query carries almost
no object signal and collapses to pure position. A structured filter does not care how common the
object is. The lift was measured on the 404-frame mini corpus the choice was made on, where cars
appeared in 395 of 404: relational mAP-lift **+0.129 → +0.323**, and that query specifically from
*below chance* (−0.015) to +0.352.

The facts come from **pixels** — an object detector plus camera intrinsics — never from the dataset's
own annotations. Reusing those would have compared a fact with itself and scored beautifully while
proving nothing.

**3. It does not return ten frames of the same five seconds.**
Keyframes are sampled at 2 Hz, so consecutive frames are near-identical. Measured, the top 10
spanned only **2.75** distinct clips; a per-clip cap doubles that to **5.50**. The cap applies to the
displayed head only — applying it deeper costs two-thirds of the ranking quality and buys *no*
additional variety.

**4. It knows what it cannot hold, and says so as a fact rather than a score.**
A caption enumerates what is *there* and never states an absence, so caption similarity cannot detect
one: `a street at night` scored **0.559** on a corpus where every frame is tagged `day` — higher than
several genuine queries, and no threshold reaches it. So the refusal consults the archive's own
structured record instead: **scene tags no frame carries**. That gets a different message, one that
does not suggest a rephrase that cannot work.

**A second refusal was tried on object categories and removed on 2026-08-18** — the story is worth
more than the feature was. It refused any category the detector could not emit, on the reasoning that
an unemittable class means zero frames. It does not: it means *we cannot check*. All three categories
it fired on turned out to be plainly present — 241 of 6,858 captions name traffic cones, and the
thumbnails show cones, a row of barriers and a forklift — so the product was telling users the
archive certainly lacked footage it holds, while retrieval had the right frame at rank 1. The fix was
to stop the parser naming what the detector cannot see (issue #112), which makes the mistake
unreachable rather than merely unlikely; a test now pins the two vocabularies together.

**The surviving rule reads a census, not a capability**, and that distinction is the whole lesson: a
scene-tag census records what the corpus *contains*, while a detector vocabulary is a fact about the
*pipeline* — and only the first can carry a claim about the footage. A **count** cannot carry one
either, which is why neither rule was ever built on one: `bicycle` is 136 frames of 6,858 and detector
recall is 0.28–0.40 on the weak classes, so "zero frames found" is one unlucky ingest away from
telling a user, as a fact, that the archive holds no bicycles. The removed rule avoided that trap and
fell into the neighbouring one.

**5. Vietnamese queries work, and are not translated for retrieval.**
The caption encoder and the captions are both English-only, so a Vietnamese query scored 0.057–0.123
against captions its English twin scored 0.145–0.707 on — under `tau_reject` every time, which
refused every Vietnamese query regardless of what the archive held. It is now canonicalised to
English **for the rejection gate only**; retrieval keeps the original, because SigLIP2 reads
Vietnamese fine (0.787 against 0.750 for the English twin).

**6. Humans can grade the results, and the verdicts are the dataset.**
Each result takes a verdict, stored against a pseudonymous reviewer id. The export is what turns a
demo into labelled data — and is why it sits behind a login rather than being open.

## Architecture

Split by **when work happens**, not by what the code does — see
[`docs/architecture_diagram.md`](docs/architecture_diagram.md) for the full diagram and rationale.

```
INGEST  (offline, hours, restartable)      QUERY  (online, read-only)
  decode → keyframes → embed                 parse → retrieve → verify → rerank → respond
                    → detect objects                     ▲                  │
                    → caption                            └──── relax ◄──────┘
          │                                              (bounded, max 3)
          └──────────► artifacts ◄──────────────────────────────┘
```

The two halves never call each other; they share artifacts. The expensive models run **once,
offline** — captioning 4 s/frame and detection 3.95 s/frame on CPU (1.085 and 0.514 on a Quadro
P2000) — so a search is two text towers and one matmul.

**Stack:** FastAPI · LangGraph · SigLIP2 (`open_clip`) · Florence-2 + MiniLM · PyTorch (CPU) ·
pytest · Ruff · Docker · GitHub Actions. Python 3.11.

No vector database, deliberately: the corpus is 6,858 × 768 floats (21 MB) held in memory, and Chroma
would add a service and a second copy of the data to do the same arithmetic more slowly.
`M2_DESIGN.md` §5 is where that stops being true — at 7.2M frames, not here.

**The search path needs no SQL database either**, and did not have one until 2026-08-21. This line
read "no SQL database, deliberately" until 2026-08-25; the auth feature (`9615e17`, in `v1.6.1`) added
a **Postgres** users table and **Redis** for OTP codes, alongside the `sqlite` file that already held
the human review verdicts. All three sit outside a search request — a query is still two text towers
and one matmul. Auth is mounted and its JWT gating works on the deployed box, but the box carries no
auth secrets, so `login`/`register` return `500` there until its `.env` is provisioned; the search
product does not depend on any of it.

## Quick start

```bash
git clone <repo> && cd P-057
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements-dev.txt        # runtime + test tooling
# pip install -r requirements.txt          # runtime only — what the container installs

cp .env.example .env        # then add your OpenAI key
make run                    # http://localhost:8000 — interactive docs at /docs
```

`make run` and `make test` fetch the corpus assets first — the search index (**32 MB**) and the frame
thumbnails (**274 MB** as one tarball) live in a companion Hugging Face dataset rather than in git,
because `docs/guide/chapter-09.md` allows no committed file over 10 MB and `vectors.npy` alone is
21 MB. The fetch is pinned to a dataset revision, so an unchanged commit always builds the same
product. No account or token is needed; the dataset is public. `python scripts/fetch_assets.py` does
it explicitly if you would rather not go through make, and `--what index` skips the images.

**First start takes ~36 s, and the port is closed for all of it.** uvicorn runs the corpus load
before it binds the socket, so `curl localhost:8000/health` is refused rather than slow until the
load finishes — which reads like a dead server if you are not expecting it. Warming both text towers
is part of that time, so the first search is not the slow one.

> **Windows note.** If `pip install` fails with `[WinError 206] filename or extension is too long`,
> PyTorch's bundled licence tree has exceeded `MAX_PATH`. Create the virtualenv at a short path
> (`python -m venv C:/venvs/p57`) or enable long-path support. Nothing else needs to change.

```bash
curl localhost:8000/health
curl -X POST localhost:8000/api/v1/search \
     -H 'Content-Type: application/json' \
     -d '{"query": "a wet road at night", "top_k": 10}'
```

Four queries that each demonstrate a different behaviour:

| query | what it shows |
|---|---|
| `a wet road at night` | a confident match, spread across clips |
| `a pedestrian to the front-left` | the metadata filter, returned with a low-confidence caveat |
| `a bus on fire` | an honest refusal — buses are common here, fires are not |
| `a vehicle cutting into our lane` | out of scope: one frame cannot show motion over time |

### Docker

```bash
docker compose up --build       # same thing, on python:3.11-slim
```

Production deploy — **Google Cloud free trial**, with Caddy obtaining and renewing TLS:
**[`docs/deploy.md`](docs/deploy.md)**. That doc also covers Hugging Face Spaces and Oracle Cloud
Always Free, but the live box is Google Cloud and everything under `deploy/` runs on it unchanged.

A deployed box tracks the **`production`** branch, never `main`. Versions are tags with a GitHub
Release — see [Releases](#releases).

### Tests

```bash
make test                                     # 390 tests, no model download, prints coverage
pytest -m slow                                # adds the real encoder end-to-end
pytest --cov=src --cov-report=term-missing    # 88% on src/
```

The important one is `tests/test_services/test_fidelity.py`: it asserts the shipped query path still
reproduces experiment `40095e80` — the same top-1 scores *and* the same top-10 clip spread as the
measured research run. Without it, the production copy and the research copy would drift silently
and the service would keep answering, just not with the numbers anyone measured.

## Configuration

Names only — values live in `.env`, which is gitignored and must stay that way.

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | query parsing (gpt-4o-mini). The only paid call in the system |
| `MODEL_NAME` | defaults to `gpt-4o-mini` |
| `APP_ENV` | `development` \| `production` \| `test`. Production closes the operator endpoints — see below |
| `CORS_ORIGINS` | comma-separated. **The deployed frontend origin must be here or every browser request fails** |
| `ARTIFACTS_DIR` / `THUMBS_DIR` | where `promote_artifacts.py` wrote its output |
| `TAU_REJECT` / `TAU_CONFIDENT` | the rejection band, `0.30` / `0.50` |
| `DIVERSITY_CAP` | max frames per clip in the displayed head, default `2` |
| `VERIFY_TOP_K` | frames caption-checked for rejection, default `5`. Larger is *worse* — see below |
| `TRUST_PROXY_HEADERS` | believe `X-Forwarded-For`. True **only** behind a trusted proxy |
| `LLM_RATE_LIMIT_PER_MINUTE` / `LLM_DAILY_CAP` / `WRITE_RATE_LIMIT_PER_MINUTE` | abuse limits; the daily cap is what protects the bill |
| `REVIEW_DB` | path to the verdict database. The deployment overrides it onto a volume |
| `DATABASE_URL` | Postgres for the auth users table. Default is a localhost dev URL; **auth needs a real one in production or `login` 500s** |
| `REDIS_URL` | OTP-code store; falls back to in-memory if unreachable |
| `JWT_SECRET_KEY` / `JWT_ALGORITHM` / `JWT_ACCESS_EXPIRE_MINUTES` / `JWT_REFRESH_EXPIRE_DAYS` | token signing. **Must be overridden in production** — the default is a public placeholder |
| `COOKIE_SECURE` / `COOKIE_SAMESITE` | refresh-cookie flags; `Secure` requires HTTPS |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth 2.0 sign-in |
| `MAIL_HOST` / `MAIL_PORT` / `MAIL_USERNAME` / `MAIL_PASSWORD` | Gmail SMTP for OTP email |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | tracing, off by default |

**`.env.example` is the source of truth for values, and copying it is safe** — it was not always. It
shipped the retired `0.35 / 0.457` band until 2026-08-12, so anyone who copied it silently overrode
the fitted values and got `a pedestrian to the front-left` (0.330) refused outright. The two files
must stay equal to `src/config.py`'s defaults.

**The review export requires a signed-in user — any account, no role** (`src/api/security.py`). It
was gated on a shared `OPERATOR_TOKEN` until 2026-08-27, back when the service had no accounts; the
login replaced the reason for a shared secret. It is deliberately *not* `Admin`-gated: the dataset
is the engineer's own output. A public URL must not hand out the export, because `decision=all`
returns exactly the triples a mass delete needs.

`VERIFY_TOP_K=5` beats 10 and 20. The score is a max over k captions, so a larger k gives an *empty*
query more chances to hit one spuriously agreeable caption.

## API

Full contract, including the states the frontend must handle:
**[`docs/api-contract.md`](docs/api-contract.md)**

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness — cheap, no dependency on the corpus |
| `GET /api/v1/status` | readiness + which experiment the artifacts came from |
| `POST /api/v1/search` | the product |
| `GET /api/v1/frames/{id}/thumb` | 640 × 360 JPEG, path-traversal checked before touching disk |
| `POST /api/v1/chat` | prose alias, retained from the template contract |
| `POST /api/v1/reviews` | one human verdict on one (query, frame) pair |
| `GET /api/v1/reviews/summary?reviewer=…` | that reviewer's own verdicts — no token needed |
| `GET /api/v1/reviews/summary` *(no reviewer)* | the whole table — **signed in** |
| `GET /api/v1/reviews/export` | the labelled dataset — **signed in** (any role) |

**Accounts (added 2026-08-21, `v1.6.1`).** A JWT auth layer is mounted but **no product route above
requires it** — search, reviews and thumbnails stay open. It is not provisioned on the current
deploy (login/register `500` without a DB and secrets on the box), so treat it as codebase-present,
not a live feature.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/auth/register` · `/login` · `/refresh` · `/logout` | JWT auth, refresh token in an httpOnly cookie |
| `POST /api/v1/auth/send-otp` · `/forgot-password` · `/reset-password` | email OTP flow (Redis-backed, in-memory fallback) |
| `POST /api/v1/auth/google` | Google OAuth 2.0 sign-in |
| `GET /api/v1/auth/me` · `GET,PATCH /api/v1/users/me` · `PATCH /api/v1/users/me/password` | the signed-in user's own profile |
| `GET,POST,PATCH,DELETE /api/v1/admin/users…` · `GET /api/v1/admin/stats` | **`Admin` role only** (`require_role`) |

## Agent traces

Eight public LangSmith traces, one per query, each showing the full path: input → `parse` (the LLM
call) → `retrieve` → `verify` → `rerank` → `respond`.

They are chosen so that *together* they exercise every behaviour the system has — including the
three a live demo makes invisible, because nothing visibly happens: the confidence band, an honest
refusal, and a query the archive cannot settle from single frames.

Captured **2026-08-31** against **`v1.9`** over the merged **9,069-frame** corpus (6,858 nuScenes +
2,211 Hanoi, fingerprint `6279d28247bb`, encoder `openclip:ViT-B-16-SigLIP2:webli`) — the corpus the
Live URL serves, not a development set.

| # | Query | What the trace shows | Result | Trace |
|---|---|---|---|---|
| 1 | `a wet road at night` | high confidence — the ordinary path | 10 hits / 7 clips | [view](https://smith.langchain.com/public/91f98979-b75a-4131-b149-fbb027e40fc0/r) |
| 2 | `a pedestrian to the front-left` | low confidence — answered, but flagged | 10 hits / 6 clips | [view](https://smith.langchain.com/public/ae1aa3e2-939c-45f2-9a5c-581755889a2c/r) |
| 3 | `a car to the front-left` | the query no image embedding can answer — cars are in 7,619 of 9,069 frames (84%) | 10 hits / 8 clips | [view](https://smith.langchain.com/public/aafc3aa6-5493-4a4d-a7ad-5751acc7b0bf/r) |
| 4 | `a bus at night` | multi-condition: object + scene together | 10 hits / 7 clips | [view](https://smith.langchain.com/public/2935aac7-a07d-4f10-8a37-762983134f34/r) |
| 5 | `traffic cones on the road` | an uncommon object, answered — this query was **refused** until `v1.4` | 10 hits / 6 clips | [view](https://smith.langchain.com/public/7aaa18c0-d9e6-41d4-b9cf-cd1d62d966e3/r) |
| 6 | `a parked car to the front-right` | object + position + attribute — the fullest constraint the parser builds | 10 hits / 7 clips | [view](https://smith.langchain.com/public/fd6851e8-f3c9-4ce3-ba70-fd8f5e024689/r) |
| 7 | `a bus on fire` | **refused** — every noun is in the archive, the situation is not | 0 hits | [view](https://smith.langchain.com/public/2758a588-f90b-45c8-b020-ae77c8a8c599/r) |
| 8 | `a vehicle cutting into our lane` | **out of scope, and still answered** — see below | 10 hits / 9 clips | [view](https://smith.langchain.com/public/2db825d1-8a57-4d2d-9471-2062a326b565/r) |

**Two rows changed behaviour since the `v1.2` capture, and both are the point of recapturing.**

**Trace 5 was the flagship honest refusal and is now an ordinary answer.** It refused
`traffic cones on the road` on an archive holding 241 captions that name them, because the rule read
"the detector cannot emit this class" as "the corpus does not hold this" — different claims, and the
second was false. Issue #112, fixed in #113 (2026-08-18). The old trace published the very bug the
next release fixed; **trace 7** is now the example of a refusal that is correct.

**Trace 8 no longer shows retrieval being skipped.** On a corpus with no source video a motion query
is refused outright, and that is what `v1.2` captured. The merged corpus carries Hanoi's 24 CC BY
clips, so the same query is now *answered* — 10 hits with deep links into the footage at the right
second, plus an explicit caveat that a single frame cannot confirm the manoeuvre. The band is not
bypassed: those hits score 0.3501–0.5076 against `tau_reject` 0.30. The out-of-scope flag is still
set and still shown; what changed is that the honest answer became "here is the footage, judge it
yourself" rather than "cannot answer".

**One known instability, measured rather than implied.** Trace 2's query fails roughly **1 time in
10** on the deployed key — the model runs past `max_tokens` without closing its structured output and
the search answers "Search is temporarily unavailable". Measured in-container on 2026-08-31:
`a pedestrian to the front-left` 18/20, six canary queries 60/60. It is the residue of the `v1.6`
outage rather than anything new, and `_parse` now retries a length-capped response twice, which takes
it to roughly 1 in 1,000. `scripts/measure/measure_parser_stability.py` is the harness; run it against the
key the box uses, since the same prompt has scored 12/12 on one OpenAI project and 2/6 on another.

Regenerate with `python scripts/ops/capture_traces.py`, then `--share` to publish the links (both need
`LANGSMITH_*` in `.env`). Point `ARTIFACTS_DIR` at the corpus the box serves, or the traces describe
a set nobody can search. LangSmith has **no project-level public sharing** — only per-run — so a new
run produces eight new links and this table is replaced wholesale.

**Re-run these whenever the corpus or the retrieval behaviour changes.** The links resolve forever,
so stale ones keep serving traces of a build that no longer ships — worse than no links, because they
look current. Regenerated three times so far: at 404 → 6,858 frames, on 2026-08-14 for `v1.2`, and on
2026-08-31 for `v1.9`, where the second and third each found a row whose described behaviour the
product no longer had.

## Layout

```
src/
  agents/         graph.py · state.py · nodes/search_nodes.py · tools/scene_tools.py
  api/routes.py   HTTP layer
  models/         Pydantic request/response
  services/
    llm.py        the one LLM call: natural language → structured constraint
    search/       encoder · index · filters · diversity · rejection · service
scripts/
  promote_artifacts.py    ingest: research outputs → the artifacts the service reads
  build_test_fixtures.py  precomputed query vectors, so CI needs no model
experiments/      M1 + M2 research. The evidence behind every number above; not imported by src/
data/artifacts/   frames · metadata · captions · provenance — committed, 4.1 MB. The matrices and
                  thumbnails are fetched, not committed
tests/            390 tests, 88% coverage on src/
docs/             architecture · api contract · deploy · tester guides · task briefs
```

`experiments/` and `src/` are deliberately separate. The research package stays exactly where it was
measured, and the product promotes what it needs with the experiment id attached to each module.

## Data

[nuScenes](https://www.nuscenes.org/) `v1.0-trainval` — 170 driving clips, 6,858 CAM_FRONT keyframes,
Boston and Singapore, July–November 2018. Day and night, wet and dry roads; **no snow, no rural or desert
roads, no emergency vehicles**, which is exactly why those make good tests of the rejection path.

nuScenes is released under **CC BY-NC-SA 4.0**. The downscaled thumbnails and the embedding
matrices are derivative works redistributed under the same licence, with attribution to nuScenes
(Motional), from
[`P-057-RisingStar/scenesearch-assets`](https://huggingface.co/datasets/P-057-RisingStar/scenesearch-assets).
Full-resolution frames are not redistributed here.

## Team

| Member | Role |
|---|---|
| Nguyễn Hoàng Minh | Lead, PM |
| Trần Nguyễn Anh Minh | Retrieval research (M1/M2), backend, agent |
| Nguyễn Hữu Hiếu| Keyframe extract research, deploy|
| Nguyễn Gia Thiều| Frontend|
## Releases

| Release | Commit | Deployed | What it is |
|---|---|---|---|
| [`v1.6.1`](../../releases/tag/v1.6.1) | `ee02d3e` | 2026-08-24 → now | **Current.** The parse is two concurrent LLM calls: the constraint, and a separate check for a modifier the vocabulary cannot express. Splitting them is what fixed `v1.6` — see the row below. Measured on the deployed key, twice: the canary query 12/12 |
| [`v1.6`](../../releases/tag/v1.6) | `63169c1` | 2026-08-23, ~40 min | **Rolled back — do not deploy.** Every product route had acquired a login guard on `main` and this release opened them again, which is why its content ships in `v1.6.1`. But it also folded the modifier rule into the parser prompt, growing it 8,489 → 10,428 characters, and the model began repeating categories until it exceeded `max_tokens`: every `a pedestrian on the right` search answered *"Search is temporarily unavailable"* |
| [`v1.5`](../../releases/tag/v1.5) | `1f0f853` | 2026-08-21 → 2026-08-24, minus `v1.6`'s ~40 min | `front_left` / `front_right` became the outer thirds of the picture rather than a ±30° bearing — the outer **3.2%** of this camera's frame — so `a pedestrian on the right` went from 1 hit in 10 to 10. Corpus re-redacted from the new detector's boxes and republished as `43f8cbf1` |
| [`v1.4`](../../releases/tag/v1.4) | `cec68d0` | 2026-08-18 → 2026-08-21 | Queries naming traffic cones, barriers or construction vehicles are answered instead of refused — the parser's vocabulary now matches the detector's six (issue #112). `/status` reports which rejection band the corpus was fitted against. First image built from the committed frontend lockfile |
| [`v1.3`](../../releases/tag/v1.3) | `e80839c` | 2026-08-17 → 2026-08-18 | UI only — contrast, clear button, responsive layout. `src/` executable logic identical to `v1.2` under an AST comparison, so `v1.2` stayed the measurement baseline |
| [`v1.2`](../../releases/tag/v1.2) | `1e04725` | 2026-08-15 → 2026-08-17 | Each result carries the frame's own caption — the text the rejection check scored — and `/health` names the running build |
| [`v1.1`](../../releases/tag/v1.1) | `f06e0f1` | **never** | Superseded by `v1.2` the same day, before the box was rebuilt. Its commits all ship inside `v1.2`: endpoint lockdown, Vietnamese queries, scene tags restored, the corrected band, refusals for categories the corpus cannot hold |
| [`v1.0`](../../releases/tag/v1.0) | `128999f` | 2026-08-09 → 2026-08-15 | First live deployment |

Full history, including which build served when:
[`docs/deploy.md` § Deployment history](docs/deploy.md#deployment-history).

**Versions are tags, never branch names.** A deployed box tracks `production`, which carries no
version and moves; the record of what v1.0 was is the `v1.0` tag itself. The earlier scheme had a
version-named branch acting as a rolling pointer, which cannot be honest in both halves — either the
name lies or the branch never moves. Each tag is also the only fixed baseline an experiment can be a
delta against. Details: [`docs/deploy.md`](docs/deploy.md) § What a box tracks.

## Project journal

[`JOURNAL.md`](JOURNAL.md) — weekly · [`WORKLOG.md`](WORKLOG.md) — daily.
Both were written as the work happened, including the conclusions that were later overturned.
