# docs/ — what is in here

`docs/` looks like 72 files. **46 of them are `guide/`**, which is vendored course material,
untouched since the initial commit and not ours to edit. The 25 below are the project's own.

**Every doc carries a status banner at the top** — ✅ done, 🟡 open, ⏸ blocked, ⏳ awaiting a
decision, 📌 historical, ⚠️ contains a known-wrong figure. Read the banner before the body; several
of these were written against an earlier corpus and are correct only in that context.

## Why some of these are in folders and some are not

**Foldered = how the work went. Flat = what the code points at.** That is the whole rule, and it is
not a stylistic one.

Grouping *everything* was measured and rejected on 2026-08-15, then re-measured on 2026-08-18 — and
the second measurement **overturned the first's decisive argument** rather than repeating it. That
argument was: `eval/results/control_baseline.json` names `keyframe-storage-design.md`, so moving the
file means editing a measurement record. The record turns out to name it by **bare filename inside a
prose note**, not by path, so nothing breaks and no record is touched. A bare name survives a move;
only a path does not.

What actually constrains a move is therefore narrower than believed: **path-form references in
non-markdown files**, counted per doc. Eighteen of the 21 docs cost between 0 and 3 lines and were
moved. Three stay flat:

| Stays flat | Why |
|---|---|
| [`architecture_diagram.md`](architecture_diagram.md) | **The only doc that genuinely cannot move.** The guide names `docs/architecture_diagram.md` as a graded path |
| [`api-contract.md`](api-contract.md) | 8 path references across `.env.example`, two `FE/` modules, four `src/` docstrings and a test. Cheap to move, but it is also the doc people reach for most |
| [`deploy.md`](deploy.md) | 13 path references, **five of them in `deploy/`** — `docker-compose.prod.yml` and two systemd units. A docs tidy-up should not appear in a diff beside the deploy stack |

The one genuine functional dependency in the whole tree was `scripts/publish_assets.py`, which
*opens* its doc at runtime (`CARD = os.path.join(...)`) rather than merely citing it. That constant
was updated with the move and the path verified.

| Folder | What lives here |
|---|---|
| [`planning/`](planning) | Where the work came from — the schedule, the assignment spec, the split between four people, and the brief that defined the corpus |
| [`reference/`](reference) | Design notes kept current: how key-frames are chosen and stored, what the published corpus contains, and what happens when it grows |
| [`tasks/`](tasks) | One file per piece of work, opened when started and kept after closing |
| [`handover/`](handover) | Written by one team member for another, with something the receiver has to decide or implement |
| [`user-testing/`](user-testing) | Scripts and guides for putting the product in front of real people |

## Flat — read these first, and they stay at this level on purpose

| Doc | What it answers |
|---|---|
| [`api-contract.md`](api-contract.md) | Every endpoint, and every state the frontend must handle. The authority; [`../.claude/rules/api-contract.md`](../.claude/rules/api-contract.md) only summarises it |
| [`architecture_diagram.md`](architecture_diagram.md) | The Mermaid system diagram. **Graded deliverable** — the guide names this exact path |
| [`deploy.md`](deploy.md) | How the Google Cloud box is built and what it tracks. § *What a box tracks* is the reasoning behind the `production` branch |
| [`hanoi-moments-demo.md`](hanoi-moments-demo.md) | How to run the moment-clip demo on a machine that has never had it. `make run-hanoi` and `make moments` exist because the corpus, the clips and the tracks are all gitignored — with the default artifacts every `moment` is null and the feature looks broken rather than absent |
| [`PRD_v1.10.vi.md`](PRD_v1.10.vi.md) / [`PRD_v1.10.en.md`](PRD_v1.10.en.md) | **What the product actually is**, as of `v1.10`. Supersedes `Gate1/PRD.md`, which was wrong in eleven places and silent on the feature that most defines the product — refusal and confidence. Anything unbuilt is marked as such rather than described. § 3.12 is the 2026-09-01 audit of every figure the product displays without a measurement behind it, with the decision on each: the invented and the hardcoded come out, the derived stay. Three admin screens, agreed and not yet done |
| [`Brief_v1.10.vi.md`](Brief_v1.10.vi.md) / [`Brief_v1.10.en.md`](Brief_v1.10.en.md) | **Why the product exists and what it is built from.** Supersedes `Gate1/Brief.md`, whose stack — CLIP/BLIP, YOLO, Qdrant, Next.js — is not the one that shipped; § Technology gives the measurement behind each of the four substitutions |

## `reference/` — design notes with measurements behind them

| Doc | What it answers |
|---|---|
| [`corpus-growth.md`](reference/corpus-growth.md) | What happens when the archive grows — what is incremental, what re-derives itself, and the one thing (the band) that silently stops being true. Read § 4 before serving a corpus nobody re-fitted |
| [`database-at-scale.md`](reference/database-at-scale.md) | Should the vectors, thumbnails and frame rows live in Supabase? Three assets, three answers — and the argument that what breaks first at scale is corpus *versioning*, not storage. 🟡 A recommendation; § 3 gives the trigger conditions for acting on it |
| [`keyframe-storage-design.md`](reference/keyframe-storage-design.md) | Key-frame selection and storage, the Phase 5 design. `eval/results/control_baseline.json` cites its § 3 by name |
| [`assets-dataset-card.md`](reference/assets-dataset-card.md) | What the published corpus contains, and what was redacted from it. **`scripts/publish_assets.py` opens this file by path** — if you move it again, move the `CARD` constant with it |

## `planning/` — where the work came from

| Doc | What it answers |
|---|---|
| [`RETRIEVAL_KEYFRAME_PLAN.md`](planning/RETRIEVAL_KEYFRAME_PLAN.md) | **The authoritative schedule** — phase structure, dates, and a status box saying which dates held. Moved out of the repo root 2026-08-18 |
| [`RAV14_System_Requirements.md`](planning/RAV14_System_Requirements.md) | The originating RAV-14 assignment spec (Vietnamese). Moved out of the repo root 2026-08-15 |
| [`footage-sourcing-brief.md`](planning/footage-sourcing-brief.md) | What the ten clips must look like — FOV, licensing, privacy |
| [`work-split.md`](planning/work-split.md) | Who owns what, and what is left |

See also [`../Gate1/`](../Gate1) for the Gate 1 submission bundle — Brief, PRD, and the UI and
wireframe images. **The Gate 1 Brief and PRD are kept as the submitted record and are not edited**;
what the product became is `PRD_v1.10.*` and `Brief_v1.10.*` in the flat table above. **Those two carry
the release number rather than the word "final"**, and are renamed with their content at the next
release — one live PRD at a time, with the history in git rather than in filenames. Each Gate 1 file
carries a one-line pointer to its successor, which is the only change made to them.

## `handover/` — written by one of us for another

| Doc | What it answers |
|---|---|
| [`golden-set-schema-decisions-vi.md`](handover/golden-set-schema-decisions-vi.md) | Minh → Hiếu, 08-17. Three schema decisions for the CVAT golden set that expire as labelling proceeds — refusal queries in the pool, graded vs binary, a double-labelled slice (Vietnamese). **Still unmade.** Rationale in [`../experiments/retrieval-methods-landscape.md`](../experiments/retrieval-methods-landscape.md) |
| [`keyframe-handoff-contract.md`](handover/keyframe-handoff-contract.md) | Hiếu → Minh. The interface between the extractor and ingest — cited from `scripts/ingest_folder.py` and `scripts/ingest/run_keyframing.py` |

## `tasks/` — one file per piece of work, kept after closing

The closed ones are deliberately **not** deleted: their § 1 sections describe an earlier corpus or
date and are correct in context, and the reasoning is worth more than the tidiness of removing them.

| Doc | Status |
|---|---|
| [`task-find-10-clips.md`](tasks/task-find-10-clips.md) | **Closed 2026-08-11** (recorded 08-18) — 24 clips / 190 min at `02_build/data/first_release/`, ingested as `data/staging/hanoi` (2,211 frames). All Hanoi, one channel: a deliberate departure from the brief's § 5 spread. Its band is still nuScenes-inherited, so promoting it needs the 08-22 re-fit |
| [`task-caption-fusion.md`](tasks/task-caption-fusion.md) | **Open, and the measurement already answered the main question no.** Ranking on the caption index costs the rejection band at every alpha; display-only fusion is the survivor. Nothing merges into `src/` before the 08-22 re-band. Evidence: [`../eval/results/fusion_sweep_nuscenes.json`](../eval/results/fusion_sweep_nuscenes.json) |
| [`task-video-grouping.md`](tasks/task-video-grouping.md) | **Open**, blocks nothing. One row per clip with the rest reachable. Free on nuScenes only because clips are ~20 s — re-run the measurement before believing it of a longer corpus. Evidence: [`../eval/results/head_diversity_nuscenes.json`](../eval/results/head_diversity_nuscenes.json) |
| [`task-publish-detector-swap.md`](tasks/task-publish-detector-swap.md) | **Open, and it is a decision rather than a chore.** The detector swap (#126) re-derived the corpus and re-redacted `data/thumbs`, but the Hub and the box still serve the `mobilenet_v3` set — local says 3,145 frames carry a region, published says 2,616. `verify_privacy_assets.py` passes on **both**, because it compares a corpus against its own certificate. Republishing closes **599 frames** where the annotations confirm a visible pedestrian and the published thumbnail has no redaction at all. § 2 is the sequence, § 3 is what to weigh first: it is a public republish and a production deploy twelve days before Demo Day |
| [`task-stationary-runs.md`](tasks/task-stationary-runs.md) | **Done 2026-08-19.** Hanoi had 133 of 196 near-duplicate runs crossing a scene boundary, so the diversity cap admitted 2 frames from *each* bucket a stopped vehicle straddled and one moment could fill all ten result slots. Fixed by [`../scripts/regroup_scenes.py`](../scripts/regroup_scenes.py), which unions the buckets a run spans: Hanoi 569 → 384 groups, runs over 2 slots **133 → 0**, **0 frames deleted**, fingerprint unchanged. A **no-op on the served nuScenes corpus** — identical partition — because the merge only ever coarsens. Read § 3 before adding any deletion rule, and § 6.1 for why the first formulation would have made the live corpus worse. Evidence: [`../eval/results/stationary_runs_hanoi.json`](../eval/results/stationary_runs_hanoi.json) (before) / [`../eval/results/stationary_runs_hanoi_regrouped.json`](../eval/results/stationary_runs_hanoi_regrouped.json) (after) |
| [`task-idea2-open-vocab-detection.md`](tasks/task-idea2-open-vocab-detection.md) | **Decision open** — open-vocab detection was dropped for removing the declared vocabulary the category refusals stood on; PR #113 removed that refusal, so the objection died and the verdict is `VOID` in the landscape doc. Carries the cost nobody had written down: swapping the detector **reissues the privacy certificate**, because person boxes become head bands and those are 89% of redacted area. § 6 is a 200-frame spike that settles it; § 7 adds the acceptance criterion the original write-up missed (`person` recall, not retrieval recall) |
| [`task-promote-to-production.md`](tasks/task-promote-to-production.md) | **Closed 2026-08-15** — box promoted to `production` at `v1.2-16-gaf3c1da`; six deploys since, `v1.6.1` current (`v1.6` was rolled back the same day it shipped). Its § 3 commands are superseded — the box has no GitHub credential, so promoting uses a `git bundle` ([`deploy.md`](deploy.md)) |
| [`task-repoint-deploy-to-release.md`](tasks/task-repoint-deploy-to-release.md) | **Closed 2026-08-15** — same promote |
| [`review-controls-restore.md`](tasks/review-controls-restore.md) | **Closed 2026-08-14** — `ReviewBar` rendered, verdicts recorded against the same `(query, frame)` pair the cards use |

Both measurement scripts name their task doc: `scripts/measure/measure_caption_fusion.py` and
`scripts/measure/measure_head_diversity.py` were updated when these moved.

## `user-testing/` — putting it in front of real people

Run 1 gathers product opinion on the nuScenes corpus; run 2 re-fits the band after the Hanoi
promotion. They are deliberately separate — see the protocol for why.

| Doc | What it is |
|---|---|
| [`feedback-session-protocol.md`](user-testing/feedback-session-protocol.md) | Protocol and judgement sheet for run 2. Cited from `FE/src/components/sceneSearch/StartState/StartState.tsx` |
| [`feedback-run1-script-vi.md`](user-testing/feedback-run1-script-vi.md) | Facilitator script for run 1 (Vietnamese) |
| [`tester-guide-vi.md`](user-testing/tester-guide-vi.md) | Ten-minute tester guide (Vietnamese) |
| [`tester-guide-vi-full.md`](user-testing/tester-guide-vi-full.md) | The long version (Vietnamese) |

## `guide/` — vendored, do not edit

46 files of course material, unchanged since the initial commit. `CLAUDE.md` and
[`../.claude/rules/`](../.claude/rules) distil the parts that affect day-to-day work, so read those
first and come here only for the source.

## Deliverables that live outside `docs/`

Graded artifacts are spread across the repo by the template's original layout. The organisers permit
any structure provided every graded component is present, but these paths are referenced from code,
CI and the deploy, so they have not been moved:

| Deliverable | Path |
|---|---|
| Journal / worklog | [`../JOURNAL.md`](../JOURNAL.md), [`../WORKLOG.md`](../WORKLOG.md) |
| Evaluation report | [`../eval/results/report.md`](../eval/results/report.md) |
| Pitch deck | [`../presentation/`](../presentation) |
| Architecture prose | [`../ARCHITECTURE.md`](../ARCHITECTURE.md) |

⚠️ The guide and the Demo Day rubric **disagree** on where the journal, worklog and pitch deck
belong — root vs `docs/`, `.pptx` vs `.pdf`. That is still open with the coach, and is the reason
none of them were moved during the 2026-08-15 tidy. See
[`../.claude/rules/deliverables.md`](../.claude/rules/deliverables.md).
