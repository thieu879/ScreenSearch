# `scripts/` — the index

Ninety-seven files. This page says what each one is, what it needs to run, and
where its output goes. **Two things to read before you touch anything here:** the environment table
below, and § Why the layout is flat — the second one is what makes a tidy-up expensive.

- Adding a script? Put it at the top level unless it belongs to a group that already has a folder,
  add a row here, and read § Why the layout is flat first — the header a nested file needs is not
  boilerplate.
- Something looks broken? Check the **Needs** column before concluding it is. Most of these do not
  run in `.venv`, and an IDE pointed at `.venv` underlines their imports in red while they work
  perfectly. On 2026-08-06 that appearance led to 892 lines of working, tested ingest code being
  deleted as dead. `pyrightconfig.json` now supplies the runtime `sys.path` entries so the red mostly
  stops; this page is the part that survives someone opening the repo in a different editor.

## Two environments, deliberately

| | `.venv` | `C:/Users/Precision/ssv` |
|---|---|---|
| Purpose | serves the API, runs the test suite | ingest, measurement, anonymisation |
| Has | FastAPI, pydantic, cv2, numpy, PIL, MiniLM | CUDA (P2000), nuScenes devkit, torch, ultralytics, `scenesearch` |
| Lacks | CUDA, devkit, `scenesearch` | **pydantic** — so nothing here may import `src.config` |

`scenesearch` is the research package at `experiments/m1/scenesearch/`. It is in this repository. The
scripts that use it insert that path themselves at runtime, which is why a language server cannot see it.

That `ssv` has no pydantic is the reason `ingest_folder.py` duplicates constants such as `CAPTION_DIM`
instead of importing them, and why `scripts/_fov.py` exists rather than living under `src/`. Both
duplications are asserted against their real definitions in the test suite, so they cannot drift silently.

**The `Needs` column below is derived from each file's imports**, not from someone's memory:

| Value | Means | So it runs in |
|---|---|---|
| `—` | stdlib, or numpy/PIL/yaml/requests only | either |
| `src` | imports `src.*`, so it needs pydantic | `.venv` |
| `devkit` | imports `nuscenes` | `ssv` |
| `models` | imports torch / transformers / ultralytics / open_clip | `ssv` |
| `cv2` | needs OpenCV | either — `.venv` has had cv2 since 2026-08-06 |
| `HF` | talks to the Hugging Face Hub | either, needs network |
| `+m1` | also puts `experiments/m1` on `sys.path` for the `scenesearch` package | — |

⚠ Three scripts want **both** `src` and an `ssv`-only library — `measure/measure_query_language.py`,
`measure/measure_scene_tag_lift.py` and `tag_scenes.py`. They have all run, so one of the two environments
holds more than this table says. Check before trusting a timing from either.

## Why the layout is flat

**It is not untidy — it is the module namespace, and grouping these files into folders is a real
change rather than a cosmetic one.** Scripts import each other by *bare module name*:

```python
from _console import use_utf8        # ingest_folder.py:81
from anonymise import redact         # promote_artifacts.py:237
from promote_artifacts import M1     # backfill_instances.py:44
```

There is no `__init__.py` anywhere here. What makes those resolve is that each script puts
`<repo>/scripts` on `sys.path` itself, so this directory *is* a flat namespace. As of 2026-08-31 that
is **76 cross-import edges across 44 files**, plus **10 test files** that import scripts the same way.

Worse, **69 of the 84 Python files compute the repo root by counting directory levels**:

```python
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

`ROOT` is not only used for `sys.path`. It is the base for *data paths* — `anonymise.py:347` defaults
`--thumbs` to `os.path.join(ROOT, "data", "thumbs")`. Move a file one level deeper without editing it
and `ROOT` becomes `scripts/`, so the script writes to `scripts/data/thumbs`, a path it will happily
create. The import error would be loud; that one is not.

`scripts/ingest/run_keyframing.py` shows the correct handling for a nested file — three `dirname`s,
plus an explicit re-add of `scripts/` — and `scripts/run_keyframing.py` is the shim that keeps the old
path working. Follow both if you nest anything.

**`measure/`, `band/`, `moments/` and `ops/` are the worked examples.** Forty-four files moved on 2026-08-31 with the suite unchanged at
581 passed. What it cost: the `ROOT` line in all twenty, an explicit `scripts/` insert in all twenty
(seventeen had been relying on `sys.path[0]`), six import sites repointed at the `measure` package, and
76 path references across 43 files. One file, `measure_parser.py`, had a *second* path insert that did
not go through `ROOT` — it was caught by running every script with `--help`, not by the test suite, which
is the check to repeat for the next group.

Outside this directory, these name script paths and break if one moves: `Dockerfile:162`,
`.dockerignore:27`, `Makefile:9,33,38,83`, `.github/workflows/ci.yml:105`, `ruff.toml:10-11`,
`deploy/scenesearch-backup.service:30`, `pyrightconfig.json`, twelve AI-log hook entries across
`.claude/`, `.codex/`, `.cursor/`, `.gemini/` and `.github/hooks/`, and — as committed provenance
records rather than as code — `data/artifacts/provenance.json` plus three files in `eval/results/`.

## The corpus pipeline, in order

| Script | Needs | What it does |
|---|---|---|
| `ingest/run_keyframing.py` | `cv2`, `src` | video → keyframes (LMSKE or HSV+heartbeat) + `frames.json`. **Requires `--fov`** |
| `ingest_folder.py` | `—` +m1 | frames + `frames.json` → a searchable corpus: detect, caption, embed, redact, provenance. The devkit-free path (M2_DESIGN §10.5) |
| `run_ingest.py` | `—` +m1 | the nuScenes path. `ingest_folder` imports its `stage_detect` / `stage_caption` / `stage_embed` |
| `regroup_scenes.py` | `—` | widens each `scene_id` to cover the near-duplicate run it sits in, so the diversity cap sees one stopped moment as one group. Called by `ingest_folder`; standalone it relabels a corpus without a re-ingest. **Merges only, never splits** — a no-op on short-clip corpora like nuScenes |
| `tag_scenes.py` | `src` ⚠ | SigLIP2 zero-shot scene tags (`time` only — `weather` measured 76.3% and was not shipped) |
| `promote_artifacts.py` | `devkit` +m1 | research outputs → `data/artifacts/`, and writes the redacted thumbnails |
| `verify_privacy_assets.py` | `—` | **the gate.** `make check` runs it; exits non-zero on an uncertified corpus |
| `publish_assets.py` | `HF` | uploads to Hugging Face. **Refuses an uncleared thumbnail directory, and has no `--force` — do not add one** |
| `fetch_assets.py` | `HF` | pulls the artifacts a fresh clone needs. The one script the Docker image contains |

## Privacy and redaction

| Script | Needs | What it does |
|---|---|---|
| `anonymise.py` | `—` +m1 | face / plate / head-band mosaic at source resolution. **The only writer into `data/thumbs` besides `promote_artifacts.write_thumbnails`** |
| `privacy_detector.py` | `models` | the dedicated YOLOv11n face and plate detectors |
| `verify_privacy_assets.py` | `—` | the release gate — complete, provenance-backed privacy coverage |
| `moments/adjudicate_moment_boxes.py` | `—` | shows every box that survived a clip's output scan, so a person can say whether it leaks |
| `measure/measure_anonymisation_detector.py` | `—` | what a detector swap costs the redaction, measured before anything is republished |
| `measure/measure_face_leaks.py` | `—` | does a face survive legibly in the thumbnails the product actually serves? |
| `measure/measure_redaction_gap.py` | `—` +m1 | what the shipped detector misses that the candidate finds, judged by an independent answer key |
| `review_rejected_frames.py` | `cv2` | writes the quality gate's rejects back out as JPEGs, so a human can see what was deleted |

## Bands — [`band/`](band/README.md)

**Moved into `scripts/band/` on 2026-08-31.** The **rejection** band (`tau_reject` / `tau_confident`)
and the **spatial** band (`front_left` / `front_right`) are different things fitted by different
scripts, and only the first is stamped on the corpus — [`band/README.md`](band/README.md) has the
comparison table and the three things that catch people. The re-fit itself stayed in
[`measure/`](measure/README.md); this folder holds the *stamp*.

| Script | Needs | What it does |
|---|---|---|
| `measure/measure_rejection_band.py` | `src` +m1 | re-fit `tau_reject` / `tau_confident` on a corpus with no ground truth — M2_DESIGN §10.3, §10.6 |
| `band/stamp_rejection_band.py` | `src` | record the fitted band on the corpus itself — the write half of `band.py`. Named in `provenance.json` |
| `band/sample_band_review.py` | `—` | draw the sample a human needs to decide what "on the right" should mean |
| `band/make_band_review_page.py` | `—` | that sample as one keyboard-driven page — 56 frames, 56 keystrokes |
| `band/fit_spatial_band.py` | `—` | fit the left/centre/right cut from the answered sample, and price it against the corpus |
| `band/reband_relations.py` | `—` +m1 | re-derive `relations` in a corpus's `metadata.jsonl` from the boxes already in it |
| `band/check_gold_projection.py` | `—` +m1 | check the gold's projected offsets against the detector's pixels — two sources, one geometry |
| `band/cache_annotation_gold.py` | `devkit` +m1 | persist the annotation-derived gold, so changing a definition has a fixed thing to diff against |

## Measurement — [`measure/`](measure/README.md)

**Moved into `scripts/measure/` on 2026-08-31**, the first group to be nested. All twenty-four write into
`eval/results/`, and none is on the serving path. Check which environment you are in before comparing
timings — doing this wrong has inverted a conclusion twice. Import one as `measure.measure_x`;
[`measure/README.md`](measure/README.md) has the header block a file in there needs.

| Script | Needs | The question it answers |
|---|---|---|
| `measure/measure_detector.py` | `devkit` +m1 | per-fact precision and recall of the object detector — M2_DESIGN §9.3 |
| `measure/measure_instance_precision.py` | `—` | reconcile the review's "nothing there" answers with what the annotations say is there |
| `measure/measure_parser.py` | `src` | `parse_constraint` against the gold constraints the retrieval numbers were measured with |
| `measure/measure_parser_stability.py` | `src` | is the parser's system prompt *stable*, not just correct once? The harness from the `v1.6` outage |
| `measure/measure_query_language.py` | `src`, `models` ⚠ | does SigLIP2 read Vietnamese as well as English? |
| `measure/measure_recall_depth.py` | `src` +m1 | how deep must an engineer scroll before the archive has given them what they asked for? |
| `measure/measure_scene_tagger.py` | `src` +m1 | SigLIP2 as a zero-shot classifier for time and weather — M2_DESIGN §11.3 |
| `measure/measure_scene_tag_lift.py` | `src`, `devkit` ⚠ | does the §11.2 scene tag actually improve retrieval? The A/B that justified shipping it |
| `measure/measure_fov_sensitivity.py` | `devkit` +m1 | how wrong the spatial filter goes when FOV is guessed — M2_DESIGN §10.5. **Measures the retired bearing band**, so it answers a question about a rule nothing uses |
| `measure/measure_caption_fusion.py` | `src` +m1 | what fusing the caption index into the ranking would cost the band |
| `measure/measure_caption_disagreement.py` | `src` | can the image vector veto a hallucinated caption? — issue #92, on both corpora |
| `measure/measure_florence_large.py` | `models` +m1 | does a bigger captioner fix #92? Measured: no |
| `measure/measure_head_diversity.py` | `src` | what the same-clip frames in a result page actually are — the evidence for video-level grouping |
| `measure/measure_stationary_runs.py` | `—` | which near-duplicate runs are a stopped world, and which a stopped *car* |
| `measure/measure_temporal_source.py` | `src` | does a motion query survive the caption gate, and can every hit name the footage it came from? |
| `measure/measure_manoeuvres.py` | `—` +m1 | tell a cut-in from an overtake using the boxes alone, scored against the interval gold (Tier 3) |
| `measure/audit_scenes.py` | `—` | audit nuScenes scene descriptions before committing to a blob download |
| `probe_hanoi_frames.py` | `cv2` +m1 | what the ego vehicle does to the detector, measured before a corpus is built on top of it |
| `check_documented_absences.py` | `src` | try to falsify the corpus's documented absences, before the demo does it for us |
| `measure/record_baseline.py` | `—` | assemble the control-tag baseline record — one file that names one build |

## Moments — [`moments/`](moments/README.md)

**Moved into `scripts/moments/` on 2026-08-31.** Built on `feature/temporal-deeplink-hanoi`.
`data/moments/` is gitignored, so the clips reach a box through a mount rather than the image —
`[]` where nothing is mounted, and **ten on production since the merged corpus landed** (verified
2026-08-31). Import a sibling as `moments.<name>`; [`moments/README.md`](moments/README.md) has the
header block, the two deferred imports that `--help` cannot reach, and what the privacy gate does.

| Script | Needs | What it does |
|---|---|---|
| `moments/propose_moments.py` | `src` | draw a review sample of candidate moments, and ask a human one question about each |
| `moments/build_moment_clips.py` | `—` +m1 | cut the reviewed moments out of the source footage, redact them, and prove the output is redacted |
| `moments/extract_moment_frames.py` | `—` +m1 | frames and detector boxes for the reviewed windows Tier 2 built no clip of |
| `moments/annotate_moment_tracks.py` | `—` +m1 | write the tracked vehicles, and how close each came, into the moment manifest |
| `moments/extract_note_events.py` | `—` | move the intervals a reviewer wrote in prose into `events`, and report everything it cannot |
| `moments/merge_firing_verdicts.py` | `—` | fold the adjudicated firing tracks back into the gold, as intervals |
| `moments/build_review_page.py` | `—` +m1 | the firing-track sheet as something you can actually sit down and answer |
| `moments/smoke_review_page.js` | node | *executes* the review page rather than parsing it — a page that parses can still be broken |

## Corpus surgery — backfills, merges, stamps

Additive by construction: each rebuilds a derived key from a **cache** rather than re-running a model,
and refuses to write if a single pre-existing key moves. That guard is not ceremony — on 2026-08-12 the
first version compared only a named pair, reported them bit-identical, and dropped `scene` from all
6,858 frames.

| Script | Needs | What it does |
|---|---|---|
| `backfill_instances.py` | `devkit` +m1 | per-instance geometry into an already-promoted `metadata.jsonl` (nuScenes) |
| `backfill_instances_ingest.py` | `—` +m1 | the same for `ingest_folder` corpora. Imports the guard rather than copying it |
| `backfill_detector_vocab.py` | `src` +m1 | declare the detector's category vocabulary on a corpus ingested before the field existed |
| `swap_detector.py` | `devkit` +m1 | re-derive `metadata.jsonl` from a different detector's **cached** boxes. `--control` first, always — reporting is the default and `--write` is opt-in. **It changes what gets redacted**: the `person` boxes it swaps are what `anonymise.py` turns into head bands, so re-run that with the same `--retrieval-cache`, re-verify, and republish. Named in `provenance.json` |
| `merge_corpora.py` | `—` | append one corpus's artifacts to another's, so one service can search both |
| `band/merge_judgment_sets.py` | `—` | combine two corpora's judgment sets into one that is honest about a merged corpus — listed under [`band/`](band/README.md), since it feeds the re-fit |
| `stamp_corpus_name.py` | `—` | record what a corpus *is*, on artifacts built before anything wrote it down |
| `build_video_manifest.py` | `—` | map a corpus's `video_id`s back to the footage they came from — the join nothing recorded |

## Golden set — the CVAT annotation round

No module docstrings; the path constants in each file's header say what it reads and writes. All
under `data/golden/`.

| Script | Needs | What it does |
|---|---|---|
| `golden/prepare_pool.py` | `yaml` | queries → the pooled candidate set to annotate |
| `golden/prepare_cvat_package.py` | `—` | pool → CVAT image package + task CSV |
| `golden/prepare_cvat_package_prefixed.py` | `yaml` | the same, with query-prefixed filenames |
| `golden/prepare_supplementary_pool.py` | `yaml` | a second pool, drawn against the **live** API |
| `golden/prepare_supplementary_package.py` | `—` | that second pool as a CVAT package |
| `golden/parse_cvat_xml.py` | `—` | CVAT XML → raw annotations + qrels |
| `golden/evaluate.py` | `yaml` | score retrieval against the qrels |

## Keyframe extraction, and its benchmarks

`scripts/ingest/README.md` is the detailed page. **Its "<15 MB RAM" claim is false** — off by ~160× —
and the 2026-08-10 move to 10–20 minute clips makes the O(n²) redundancy pass live, so 24.4 s per
video-minute is a lower bound.

| Script | Needs | What it does |
|---|---|---|
| `ingest/run_keyframing.py` | `cv2`, `src` | the extractor CLI (FR-01.2) |
| `run_keyframing.py` | `—` | back-compat shim re-exporting the above. **The precedent for nesting anything here** |
| `ingest/eval_keyframing.py` | `src` | benchmark suite runner |
| `ingest/eval_summe.py` | `src` | the same, on SumMe |
| `ingest/fetch_bdd100k_samples.py` | `cv2` | fetch BDD100K sample videos + ground-truth event metadata |
| `ingest/fetch_summe_samples.py` | `cv2` | download SumMe, extract sample videos + GT, export parsed annotations |

## Deploy and ops — [`ops/`](ops/README.md)

**Moved into `scripts/ops/` on 2026-08-31.** The two that matter are `preflight_release.py`
(before traffic moves) and `verify_deploy.py` (after) — both exist because `/health` and `/status`
were green throughout the `v1.6` outage. [`ops/README.md`](ops/README.md) also records that the
nightly backup has never run, and why installing the unit alone will not fix it.

| Script | Needs | What it does |
|---|---|---|
| `ops/preflight_release.py` | `src` | preflight a built image in a throwaway container, **before any traffic moves**. Added after the `v1.6` outage, where `/health` and `/status` were green while every search failed — neither touches the LLM |
| `ops/verify_deploy.py` | `—` | post-deploy verification against the Live URL. Run from anywhere; no box access needed |
| `ops/backup_reviews.py` | `—` | snapshot the review database via sqlite's online backup API — `cp` and `tar` can return a database that opens cleanly and has lost its last rows. Run nightly by `deploy/scenesearch-backup.service`. **That unit is `cp`'d into `/etc/systemd/system/`, so editing the repo's copy does not update the box** |
| `ops/load_frames_to_db.py` | `src` | mirror a promoted corpus into the PostgreSQL `frames` table |
| `ops/seed_admin.py` | `src` | seed initial admin and test accounts. **Still ships two public passwords**, so any *fresh* database gets them |
| `ops/capture_traces.py` | `src` | the LangSmith traces for deliverable #4. LangSmith shares per run, never per project, so `--share` produces new links and the README table is replaced wholesale each time |
| `ops/build_test_fixtures.py` | `—` +m1 | precompute query embeddings for the fidelity test |

## AI-usage logging — do not run these by hand

> ⚠ `log_hook.py`, `log_antigravity.py`, `log_manual.py`, `submit_log.py`, `setup_hooks.*` and
> `_pyrun.*` are driven by the pre-push hook and by twelve entries across `.claude/settings.json`,
> `.codex/hooks.json`, `.cursor/hooks.json`, `.gemini/settings.json` and `.github/hooks/hooks.json`.
> **Do not run them manually** — fake entries pollute a graded log — do not edit `.ai-log/`, and never
> push with `--no-verify`. **Do not move or rename them either:** every hook entry names the path, and
> `pre-push` wraps its calls in `|| true`, so a wrong path stops the logging *silently*.
> `ruff.toml:10-11` also excludes them by a path glob that assumes this directory.
> See [`ai-logging.md`](../.claude/rules/ai-logging.md).

| File | What it is |
|---|---|
| `log_hook.py` | the shared hook logger — Claude Code, Gemini CLI, Codex, Cursor, Copilot |
| `log_antigravity.py` | scans the Antigravity IDE's brain directory for the exact user-typed prompts |
| `log_manual.py` | for a web tool with no hooks (ChatGPT, etc.) — see `.agents/workflows/log.md` |
| `submit_log.py` | POSTs `.ai-log/session.jsonl`, appends it to `archive/`, unlinks it. **The outbox is not the record — the archive is** |
| `_pyrun.sh` / `_pyrun.cmd` | cross-platform Python launcher for the above. Exits 0 silently if no Python is found — a hook must never block the tool |
| `setup_hooks.sh` / `setup_hooks.ps1` | install the pre-push hook. Run once after cloning |

## Dev setup and shared helpers

| File | What it is |
|---|---|
| `setup.sh` | first-run developer setup |
| `_console.py` | makes script output survive a Windows console. Imported for effect by ~25 scripts |
| `_fov.py` | the declared field of view, and the one check that must run before any of it is believed. Lives here rather than under `src/` because `ingest_folder.py` runs where there is no pydantic |

## Usage

```powershell
# 1. extract — writes frames + frames.json, and nothing into data/thumbs
python scripts/ingest/run_keyframing.py --video data/raw_videos/clip.mp4 --fov 120

# 2. ingest that folder — the sidecar supplies timestamps and FOV, so no --fov needed here
C:/Users/Precision/ssv/Scripts/python.exe scripts/ingest_folder.py `
    --frames data/extracted_keyframes/clip --workdir data/work/clip --out data/staging/clip

# 3. the release gate
python scripts/verify_privacy_assets.py --artifacts data/staging/clip/artifacts `
    --thumbs data/staging/clip/thumbs
```

`--fov` is declared, never measured. `_fov.check_fov` refuses values at or below 60°, and **its stated
reason is now void**: the message describes the retired ±30° bearing band, whereas the shipped rule is
a pixel offset over image width, which FOV does not enter. The guard may still be right for a different
reason — at a narrow FOV "the left third of the picture" is a much narrower slice of the world — but
that argument has not been made and does not obviously land on 60°. **Do not just delete it**: it is
the only thing standing between a wrongly-declared lens and a corpus. See
`docs/handover/keyframe-handoff-contract.md` §2 for how to declare FOV for footage with no lens data.

## Never write into `data/thumbs`

It is `settings.thumbs_dir` — the directory the API serves to the browser — so anything placed there
is published. Only `promote_artifacts.write_thumbnails` and `anonymise.py` may write there, and both
mosaic faces, plates and person head bands at source resolution *before* downscaling. Extraction
writes full-resolution frames to `data/extracted_keyframes/` and stops.

This is not hypothetical: `run_keyframing.py` once wrote thumbnails directly, `878eafb` committed two
of them, and the unredacted set reached the public Hugging Face repo by that route.

**The head band is not optional** — 68% of frames with a person yield no detectable face, and on
nuScenes head bands supply 89% of the redacted area.
