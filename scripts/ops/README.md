# `scripts/ops/` — deploy, verify, and the things that touch the live box

Seven scripts that run against a deployment rather than a corpus. Nothing here is imported by
`src/`, nothing here has a test, and three of them take no `__file__` at all — they read the world
through arguments and the network.

[`../README.md`](../README.md) is the index for the whole directory. Read its § Why the layout is
flat before adding a file here.

## What each one does

| Script | Needs | What it does |
|---|---|---|
| `preflight_release.py` | `src` | run the parse in a throwaway container off a **built** image, before any traffic moves |
| `verify_deploy.py` | `—` | post-deploy verification against the Live URL. Run from anywhere; no box access needed |
| `backup_reviews.py` | `—` | snapshot the review database through sqlite's online backup API |
| `seed_admin.py` | `src` | seed initial admin and test accounts |
| `load_frames_to_db.py` | `src` | mirror a promoted corpus into the PostgreSQL `frames` table |
| `capture_traces.py` | `src` | the LangSmith traces for deliverable #4 |
| `build_test_fixtures.py` | `—` | precompute query embeddings for the fidelity test |

## The two that exist because `/health` lies

This is the whole reason this folder is not just "miscellaneous".

`/health` and `/status` were **both green** for the forty minutes `v1.6` was live with every spatial
search answering *"Search is temporarily unavailable"*, because neither route touches the model. So:

- **`preflight_release.py` runs before traffic moves**, in a throwaway container off the new image,
  with the box's own `.env` — the key matters, the same prompt has scored 12/12 on one OpenAI project
  and 2/6 on another. The image contains no `scripts/`, so it is mounted in:

  ```bash
  docker run --rm --env-file ../.env -e PYTHONPATH=/app \
    -v /tmp/preflight_release.py:/app/preflight.py:ro \
    --entrypoint python deploy-api /app/preflight.py 20
  ```

- **`verify_deploy.py` runs after**, from anywhere:

  ```bash
  python scripts/ops/verify_deploy.py v1.9.1 9069 6279d28247bb
  ```

  **Its expected values are arguments, not constants, and that is deliberate** — the failure it
  exists to catch is a deploy that serves a *different* corpus and reports itself healthy, so the
  expectation has to come from the person deploying rather than from whatever the file last said.

  **It works.** On 2026-08-31 a revert dropped `-f docker-compose.merged.yml` and the box served the
  baked 6,858-frame corpus for an hour while `/status` read `fitted`. This script fails all three of
  its checks in that state — `release`, `corpus_frames` and `fitted_for`. It simply was not run.
  Run it after **every** deploy.

## Two live-box facts you need before trusting this folder

**The backup has never run.** `scenesearch-backup.{service,timer}` are **not installed** on the box
(`systemctl is-enabled` → "No such file or directory"), `deploy/backups/` is empty and the journal
has no entries — checked 2026-08-31. It could not work if installed: `.dockerignore` keeps `scripts/`
out of the image except `fetch_assets.py`, so the unit's
`docker compose exec api python scripts/ops/backup_reviews.py` names a file the container does not
have. **Fixing it needs both halves** — install the unit *and* get the script into the image. Until
then the verdicts have no copy anywhere, and anything citing `deploy/backups` as a mitigation is
citing something that does not exist.

**`seed_admin.py` still ships two public passwords**, so any *fresh* database gets them. The two on
the live box were rotated on 2026-08-27 and both now `401`.

## Paths, and the one that is not like the others

Four of these take no `__file__` and moved unchanged. The three that derive a root now count **three**
dirnames — and note that `build_test_fixtures.py` and `capture_traces.py` call the variable `REPO`
rather than `ROOT`, so a search for the usual pattern misses them:

```python
# One level deeper than a top-level script, so the repo root counts three.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

**`seed_admin.py` is the exception and always was:** it does `sys.path.insert(0, ".")` — relative to
the **current working directory**, not to the file. Moving it changed nothing, and that is exactly
the problem: it must be run from the repo root or it cannot import `src`, and it will fail the same
way from any other directory whatever its own path is. Left alone rather than quietly fixed, because
changing how a seeding script resolves the app is not a tidy-up.
