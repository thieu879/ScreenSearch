.PHONY: run run-hanoi moments moments-review test assets lint format format-check typecheck check privacy-gate clean

# The vector matrices and thumbnails are not in git — see .gitignore. `run` and `test` depend on
# this so a fresh clone works with no extra step to forget: without the index the service starts and
# answers nothing, and the failure (a 503 from /status) looks like a bug rather than a missing
# download. `--if-missing` makes it a no-op with no network call once the files are there, so this
# costs nothing on every subsequent invocation.
assets:
	python scripts/fetch_assets.py --if-missing

# --no-proxy-headers matters most here, not in production: a Cloudflare tunnel connects from
# 127.0.0.1, which is exactly the address uvicorn trusts by default, so with it on any tunnel
# visitor can forge X-Forwarded-For and reset their own rate limit. See ratelimit.py:client_key.
run: assets
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8000 --no-proxy-headers

# The Hanoi demo, which `make run` cannot give you: the served corpus is nuScenes, and the moment
# clips are cut from Hanoi frames, so with the default artifacts every `moment` is null and the
# feature looks broken rather than absent. Three env vars is three chances to forget one — this is
# them, written down.
#
# It deliberately does NOT depend on `assets`: that fetches the *nuScenes* index, which this target
# does not use, and on a machine with no local Hanoi corpus the honest failure is the startup error
# rather than a silent fall-back to the wrong archive.
run-hanoi:
	ARTIFACTS_DIR=data/staging/hanoi/artifacts THUMBS_DIR=data/staging/hanoi/thumbs MOMENTS_DIR=data/moments uvicorn src.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers

# Write the tracked vehicles and their distances into the moment manifest. Idempotent, and it does
# NOT rebuild the clips — the privacy convergence loop and the human clearance that certified them
# stay untouched. Needs `data/moments/moments.json` and the frames in `data/moments_work/`, neither
# of which is in git, so on a fresh machine this is the step that fails first and loudly.
moments:
	python scripts/moments/annotate_moment_tracks.py

# The local review page for the Tier 3 firing tracks. Writes into gitignored `data/`, beside the
# unredacted frames it points at — never into `eval/review/`, and never shared.
moments-review:
	python scripts/moments/build_review_page.py

# Coverage runs on the default target, not as an opt-in `make coverage` nobody remembers to call.
# The rubric asks for ≥60% as *evidence*, and evidence that has to be requested goes stale: § 6 of
# eval/results/report.md carried "90 passed / 614 stmts / 85%" until 2026-08-14, by which point the
# suite was 390 tests over 1,515 statements. The figure was not wrong when written — it was just
# never regenerated, because nothing regenerated it.
#
# --cov-fail-under is deliberately absent. Picking a threshold is a team decision, and a gate added
# in the same change that first prints the number gates on a figure nobody has looked at yet.
test: assets
	pytest tests/ -v --cov=src --cov-report=term-missing

lint:
	ruff check src/ tests/ scripts/

# `scripts/` is in scope as of 2026-08-16, when the one-off reformat made it clean and CI started
# enforcing `ruff format --check` over the same three directories. The old comment here said the
# opposite, and it was right at the time: widening a rewrite-in-place target to a directory that was
# not clean would have made `make check` mutate files on the next run.
#
# This target still rewrites in place. That is fine when you ask for it by name and is the reason it
# is no longer what `check` runs — see `format-check` below.
format:
	ruff format src/ tests/ scripts/

# What `check` runs, and what CI runs. Reports drift and exits non-zero; never edits a file.
#
# The distinction is the whole fix. `make check` used to call `format`, so running it before a
# two-line commit silently rewrote 52 files and turned the diff into something nobody could review —
# which is why `CLAUDE.md` had to carry a rule telling people not to run their own check target.
# A gate that repairs the thing it is measuring is not a gate.
format-check:
	ruff format --check src/ tests/ scripts/

typecheck:
	mypy src/

# Fails when a local corpus exists and is not certified; skips when there is no corpus to check.
# The skip is not a softened gate — the gate that cannot be skipped lives in `publish_assets.py`,
# which refuses to upload an uncleared directory. This target catches the other case: a developer
# whose `data/thumbs` has drifted from the certificate that describes it, on the machine where that
# drift starts. CI has no corpus and legitimately has nothing to verify.
privacy-gate:
	@if [ -d data/thumbs ] && [ -n "$$(ls -A data/thumbs 2>/dev/null)" ]; then \
		python scripts/verify_privacy_assets.py --artifacts data/artifacts --thumbs data/thumbs; \
	else \
		echo "[privacy] no local corpus in data/thumbs — nothing to verify"; \
	fi

# `format-check`, not `format`. As of 2026-08-16 this target is safe to run before a commit again:
# it reports and never rewrites, so the diff you review is the diff you wrote.
check: lint format-check test privacy-gate

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
