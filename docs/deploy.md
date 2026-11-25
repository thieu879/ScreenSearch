# Deploying SceneSearch

Three documented paths.

**[Google Cloud's free trial](#c-google-cloud-free-trial-300--90-days) is the one to use now** — the
$300 runs 90 days from signup, which from early August covers Demo Day and the seven days after it
with about two months to spare, and it is the only path here that gives an unattended deployment a
real disk. Everything under `deploy/` runs on it unchanged.

**[Hugging Face Spaces](#a-hugging-face-spaces-9month)** is ~20 minutes of work against 1–2 hours
for a VM, and timed correctly costs $9 once — but the billing month has to be started late enough to
still be running on 09-08, and it has no persistent volume. **[Oracle Cloud Always
Free](#b-oracle-cloud-always-free-0)** is $0 forever and is the right answer if the project outlives
the course, provided you can get an A1 shape at all.

**Read [The review database](#the-review-database) before handing anyone a URL**, whichever path you
take. It is the one piece of state on the box that cannot be rebuilt, and one of the three paths
cannot keep it.

**Why not simply a free tier:** every free option tops out at **512 MB** (Koyeb, Render — HF
withdrew free CPU Basic and put the Docker SDK behind PRO in 2026-07). This service needs
~1–1.5 GB: torch imports at ~250 MB before SigLIP2's text tower (~440 MB) and MiniLM. Fitting
512 MB means exporting both towers to ONNX and dropping torch — real work, and the int8
quantisation it would likely need moves the measured numbers.

---

# A. Hugging Face Spaces ($9/month)

PRO includes Docker Spaces on CPU Basic (2 vCPU / 16 GB) with no hourly charge. Verify that is still
true before subscribing — HF changed this policy once already in 2026.

## Minimising the bill

Demo Day is **2026-09-01**, and the rubric requires the URL to stay up **7 days after** — through
**2026-09-08**. One billing month bought around **2026-08-18** covers to ~09-18: Demo Day plus ten
days of slack, for **$9 total**.

1. **Before ~Aug 18, spend nothing.** Develop locally and give your teammate a free HTTPS URL with a
   Cloudflare quick tunnel — no account, no card:

   ```bash
   make run                                          # terminal 1
   cloudflared tunnel --url http://localhost:8000    # terminal 2 -> https://<random>.trycloudflare.com
   ```

   The URL changes each restart, which is fine for integration. Put it in the frontend's env and in
   `CORS_ORIGINS`.

2. **Collect the user feedback (deliverable #10) on the tunnel, in early August.** It needs 3–5 real
   people and is the task most likely to slip — and slipping it is what drags the subscription into
   a second month.

3. **~Aug 18: subscribe, deploy, then immediately turn off auto-renew.** Access runs to the end of
   the period regardless, and cancelling at once removes the only way this becomes $18.

Everything else — LangSmith traces, the eval report, the pitch deck, the journal — needs no deploy
at all. Do those first.

## Deploying

**Org namespace is `P-057-RisingStar`**, not the display name. `whoami()` reports
`name="P-057-RisingStar"` and `fullname="AI20K-Build-Phase-Cohort-3-P-057-RisingStar"`; repo ids use
the former, and the longer one silently addresses nothing. Both live in the org rather than a
personal account, so a graded team deliverable is not tied to one login.

| repo | id |
|---|---|
| Space | `P-057-RisingStar/scenesearch` |
| corpus assets (dataset) | `P-057-RisingStar/scenesearch-assets` |

The dataset holds the search index (32 MB) and the thumbnails (274 MB as `thumbs.tar`, since they
went to 640 px on 2026-08-07 — this said 82 MB until 08-14 and § C's disk sizing already used the
real figure), neither of
which is in git — `docs/guide/chapter-09.md` allows no committed file over 10 MB. The image pulls
both at build time, so nothing is fetched per request; **the index pull is fatal and the thumbnail
pull is not**, since a service without an index cannot answer at all while one without thumbnails
merely shows broken images. Locally, `make run` fetches them.

**The thumbnails are pulled as one tarball, and that is load-bearing for this deploy.** The build is
anonymous on purpose — a public dataset means no credential inside the image — and the Hub 429s an
unauthenticated caller partway through 6,858 individual file requests. CI hit it first, at roughly
the 490th file after four and a half minutes; the same call sits on the path to this deploy, which
has a fixed date and no free way to retry. Measured unauthenticated, the tarball takes **23 s** for
the whole corpus, download and unpack together. If a future ingest grows the corpus, republish with
`scripts/publish_assets.py --thumbs <dir>` — the tarball is the default and the loose per-file
copies are now opt-in behind `--per-file`.

> ⚠️ **Republishing is not optional after a thumbnail change — it is a privacy control.** The
> deployed image fetches `thumbs.tar` from the Hub, not from this repo, so thumbnails regenerated
> locally reach nobody until the tarball is republished. Faces and licence plates were redacted on
> 2026-08-02 (`scripts/anonymise.py`); until `thumbs.tar` carries that pass, **any deployment serves
> the previous unredacted images**. Regenerate, then:
>
> ```
> python scripts/anonymise.py --dataroot <nuscenes>     # rewrite data/thumbs/ redacted
> python scripts/publish_assets.py --thumbs data/thumbs # push the tarball the deploy reads
> ```
>
> **Then bump `scripts/fetch_assets.py:REVISION` to the new dataset commit.** Publishing alone no
> longer changes what a build serves — the fetch is pinned, so a republished corpus reaches nobody
> until that line moves. That is the intended behaviour and it cuts both ways: it is what makes
> a tagged release reproducible, and it is what will make someone wonder why their freshly published
> corpus is not showing up. Get the sha from the dataset's commit history, or:
>
> ```
> curl -s https://huggingface.co/api/datasets/P-057-RisingStar/scenesearch-assets | python -c "import sys,json;print(json.load(sys.stdin)['sha'])"
> ```

**Do not create the Space before ~Aug 18.** There is no free path to test on: HF withdrew free CPU
Basic and put the Docker SDK behind PRO in 2026-07 (see the intro), so creating a Space at all starts
the clock on the one billing month this plan is built around. Use the Cloudflare tunnel for
integration and for the user-feedback sessions; it costs nothing and needs no account.

The cost of waiting is real and is accepted knowingly: every failure mode in
[§ If something is wrong](#if-something-is-wrong) is invisible locally and only shows up on a real
Space, and a 5.34 GB image with torch and baked weights is exactly the kind of build that fails its
first attempt. So budget the *first* deploy day for the deploy failing, not for it working — the
subscription window has ten days of slack after Demo Day precisely so that first attempt can go
wrong.

1. **huggingface.co/new-space** → owner the org above, SDK **Docker** (blank), hardware **CPU basic**,
   **Public**.
2. Settings → *Variables and secrets*:
   - secret `OPENAI_API_KEY`
   - `CORS_ORIGINS` is **not needed**: the image builds the frontend and FastAPI serves it from the
     same origin (`src/main.py:_mount_frontend`), so there is no second origin to allow. Set it only
     if something else ever calls the API cross-origin.
3. Push:

   ```bash
   git remote add space https://huggingface.co/spaces/P-057-RisingStar/scenesearch
   git push space main:main
   ```

   Username + a **write token** as the password (huggingface.co → Settings → Access Tokens), or
   `hf auth login` first and let the CLI hold it.

The Space reads `sdk: docker` and `app_port: 8000` from `README.md`'s frontmatter — without it the
Space routes to 7860 and serves nothing. Nothing under `deploy/` is used here; HF terminates TLS
itself.

**What the Space serves.** The image now builds `FE/` in its own node stage and FastAPI mounts the
result, so the Live URL is the product, not `/docs`. Before that stage existed the deploy would have
been an API and a JSON response — worth knowing if an older image is ever rebuilt.

First build is **15–25 min** (torch, plus ~500 MB of model weights baked in so cold starts do not
depend on the HF hub). Then verify with [§ Verify](#verify) below, and point UptimeRobot at
`/health` — Spaces sleep on inactivity.

---

# B. Oracle Cloud Always Free ($0)

Genuinely free, always on, 24 GB, and runs the image unchanged. Costs 1–2 hours of setup instead of
money, and the three Oracle-specific traps below are most of that time.

## What you need first

- An Oracle Cloud account (card required for identity verification; Always Free is not charged)
- A hostname. **A bare IP address cannot have a TLS certificate**, and without TLS a Vercel frontend
  cannot call this backend at all — browsers block mixed content. [DuckDNS](https://www.duckdns.org)
  gives a free subdomain in about a minute.
- Your `OPENAI_API_KEY`

## 1. Provision the instance

Compute → Instances → Create.

| Setting | Value |
|---|---|
| Image | Canonical Ubuntu 22.04 |
| Shape | **VM.Standard.A1.Flex** — 4 OCPU, 24 GB |
| SSH key | upload your public key |

> **"Out of host capacity" is the normal experience, not a mistake.** A1 (Ampere ARM) is heavily
> oversubscribed. Try a different availability domain, and retry — capacity frees up. Do **not**
> fall back to the AMD `E2.1.Micro` free shape: it has 1 GB, which is not enough.

Point your DuckDNS subdomain at the instance's public IP.

## 2. Open the ports — both firewalls

Oracle has **two** independent firewalls, and forgetting the second is the single most common way a
correctly deployed service stays unreachable.

**a. VCN security list** (in the console): Networking → Virtual Cloud Networks → your VCN → Security
Lists → add ingress rules for TCP **80** and **443** from `0.0.0.0/0`.

**b. The instance's own iptables.** Oracle's Ubuntu images ship with a restrictive `iptables` that
drops 80/443 regardless of what the security list says:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save        # survives reboot
```

## 3. Install Docker

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker
```

## 4. Deploy

```bash
git clone --branch production https://github.com/AI20K-Build-Phase-Cohort-3/P-057.git
cd P-057

cat > .env <<'EOF'
OPENAI_API_KEY=sk-...
DOMAIN=your-name.duckdns.org
CORS_ORIGINS=https://your-frontend.vercel.app
APP_ENV=production
EOF
chmod 600 .env

docker compose -f deploy/docker-compose.prod.yml up -d --build
```

**`--branch production` is the whole point of that branch** — see
[§ What a box tracks](#what-a-box-tracks). A bare `git clone` takes the default branch, `main`,
which is where daily work lands.

The first build takes **15–25 minutes** on 4 ARM cores: it compiles nothing but installs torch and
bakes ~500 MB of model weights into the image so cold starts do not depend on the HF hub. Watch it
with `docker compose -f deploy/docker-compose.prod.yml logs -f`.

Then make it survive reboots — Oracle reboots hosts for maintenance, and Compose's `restart:
unless-stopped` does not cover that:

```bash
sudo cp deploy/scenesearch.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now scenesearch
```

---

# C. Google Cloud free trial ($300 / 90 days)

A Compute Engine VM running the same `deploy/` stack as B. The credit is the reason to prefer it
right now, and the reasons are all about timing rather than money:

- **90 days from signup**, so a trial started 2026-08-07 runs to about **2026-11-05**. Demo Day is
  09-01 and the URL must stay up through 09-08. Compare A, where one billing month bought this early
  expires almost exactly on the deadline it is meant to cover.
- **No capacity lottery.** B's A1 shape is heavily oversubscribed and "out of host capacity" is its
  normal first experience — a poor property when the deploy has to be up by a particular weekend.
- **amd64.** The Dockerfile installs torch from PyTorch's CPU index on `TARGETARCH=amd64` and falls
  through to plain PyPI otherwise; B's ARM shapes take the fallback. Here the tested branch runs.
- A real disk, so the review volume from `deploy/docker-compose.prod.yml` behaves as intended.

> **Not Cloud Run**, despite it being the container-shaped product. Its filesystem is ephemeral, so
> the review database is back to being lost on every restart — the problem the volume exists to
> solve. Mounting a GCS bucket does not rescue it either: sqlite over gcsfuse handles locking badly.
> And a 5.3 GB image that loads the corpus and warms two text towers before it answers needs
> `min-instances=1` to be usable at all, which removes the scale-to-zero that was the only reason to
> choose Cloud Run over a VM.

## What you need first

- A Google account and a card. The trial verifies identity and **does not auto-charge** — the
  account stays capped until someone manually upgrades it, so do not.
- A hostname, for the same reason as B: **a bare IP cannot hold a TLS certificate**, and Caddy needs
  one to get a Let's Encrypt cert. [DuckDNS](https://www.duckdns.org) takes a minute.
- Your `OPENAI_API_KEY`.

## 1. Create the VM

Compute Engine → VM instances → Create instance.

| Setting | Value |
|---|---|
| Machine type | **e2-medium** (2 vCPU / 4 GB). `e2-standard-2` (8 GB) for headroom — both are far inside $300 for the window |
| Boot disk image | Ubuntu 22.04 LTS (x86/64) |
| Boot disk size | **50 GB** — see below |
| Firewall | tick **Allow HTTP traffic** and **Allow HTTPS traffic** |
| Network | give the instance a **static** external IP |

Two of those rows are the traps, and both fail late rather than immediately:

- **The default 10 GB boot disk is not enough.** The image is ~5.3 GB before the build layers that
  produce it and the 274 MB of assets pulled into it. A 10 GB disk dies of no space roughly twenty
  minutes into the first build, which reads as a broken Dockerfile rather than a full disk.
- **The external IP is ephemeral unless reserved.** It survives a reboot and *not* a stop/start —
  and the machine is stopped more than you would expect, since stopping it is how you stretch the
  credit. When it comes back with a new address the DuckDNS record points at nothing, and Caddy's
  certificate renewal fails with it.

Unlike B there is only **one** firewall: the VPC rules those two checkboxes create. Google's Ubuntu
images do not ship the restrictive local `iptables` that makes B's step 2 necessary.

Then point your DuckDNS subdomain at the reserved IP.

## 2. Install Docker

Identical to [B step 3](#3-install-docker) except the architecture in the apt source — `amd64` here,
not `arm64`:

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker
```

## 3. Deploy

Exactly [B step 4](#4-deploy) — same clone, same `.env`, same command:

```bash
git clone --branch production https://github.com/AI20K-Build-Phase-Cohort-3/P-057.git
cd P-057

cat > .env <<'EOF'
OPENAI_API_KEY=sk-...
DOMAIN=your-name.duckdns.org
APP_ENV=production
EOF
chmod 600 .env

docker compose -f deploy/docker-compose.prod.yml up -d --build
```

`CORS_ORIGINS` is not needed: the image builds the frontend and FastAPI serves it from the same
origin. First build is **15–25 minutes**, most of it torch and the ~500 MB of baked-in weights.

Then survive reboots — Google performs live migration but not every maintenance event is transparent,
and Compose's `restart: unless-stopped` does not cover a host restart:

```bash
sudo cp deploy/scenesearch.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now scenesearch
```

## Making the credit last

An `e2-medium` left running costs roughly $25–30/month against a $300 balance, so the window this
project needs is not close to the limit and the credit is not worth optimising. Two things are worth
doing anyway:

- **Set a budget alert** (Billing → Budgets & alerts) at, say, $50. It is the cheapest way to notice
  a mistake — a second forgotten instance, a GPU type picked by accident.
- **Do not upgrade the account** when Google offers. The trial ending pauses the VM; an upgraded
  account bills the card instead. Pausing is the failure mode you want, and the deadline that
  matters (09-08) is two months inside the trial regardless.

If the instance is stopped to save credit, remember the static IP is reserved and **an unattached
static IP is itself billed**. Release it only if the deployment is finished for good.

---

# Deployment history

What has actually been live, and when. Kept here because nothing else in the repo records it: git
shows which releases *exist*, never which ones *ran*, and "deployed once in August" and "served
continuously since August" look identical from the outside.

**Update this row when you promote.** It is two lines, it is the only place the answer lives, and
the question it answers — *which build was that tester using?* — is unanswerable afterwards.
**This was skipped for three promotes in a row** (`v1.5`, `v1.6`, `v1.6.1`) and backfilled on
2026-08-24 — which is how a table meant to record what *ran* came to disagree with the box it
describes. The `v1.6` row is the one that would have been lost: a release that served for forty
minutes and was pulled leaves no trace in git at all.

| Release | Live from | Until | Host | Notes |
|---|---|---|---|---|
| [`v1.0`](../../releases/tag/v1.0) `128999f` | 2026-08-09 | 2026-08-15 | Google Cloud VM + Caddy | First deployment. Nine open endpoints and, through `.env.example`, the retired `0.35 / 0.457` band |
| [`v1.1`](../../releases/tag/v1.1) `f06e0f1` | — | — | — | **Never deployed.** Superseded by `v1.2` the same day, before the box was rebuilt. Its commits all ship inside `v1.2` |
| [`v1.2`](../../releases/tag/v1.2) `1e04725` | 2026-08-15 | 2026-08-17 | Google Cloud VM + Caddy | The one row where the box ran *past* its tag: `production` was at `af3c1da`, so `/health` reported `v1.2-16-gaf3c1da`. Promoted by git bundle over the gcloud SSH channel — the box holds no GitHub credential. First build where `/health` named itself |
| [`v1.3`](../../releases/tag/v1.3) `e80839c` | 2026-08-17 | 2026-08-18 | Google Cloud VM + Caddy | UI only. Its image was built with `npm install`, the workaround `014ab00` later reverted |
| [`v1.4`](../../releases/tag/v1.4) `cec68d0` | 2026-08-18 | 2026-08-21 | Google Cloud VM + Caddy | Verified after the swap: `traffic cones on the road` returns 10 hits at `high` (it was refused under `v1.3`), and `/status` reports `rejection_band: "fitted"`. Build 2m09s warm; `chown -R /app` 61.7 s and image export 44.8 s remain the two costs |
| [`v1.5`](../../releases/tag/v1.5) `1f0f853` | 2026-08-21 | 2026-08-23 | Google Cloud VM + Caddy | The spatial re-band plus the re-redacted corpus (`43f8cbf1`). Verified on the running service: a frame from the 599 served byte-identical to the local copy (42,788 → 37,750 bytes), and `a pedestrian on the right` returned 10 hits at `high` across 6 scenes |
| [`v1.6`](../../releases/tag/v1.6) `63169c1` | 2026-08-23 | 2026-08-23 | Google Cloud VM + Caddy | **Live roughly 40 minutes, then rolled back — do not deploy this tag.** `/health` and `/status` were green throughout while every `a pedestrian on the right` search failed: neither endpoint touches the LLM. `openai.LengthFinishReasonError` — the parser prompt had grown past what the model handles without repeating itself. The rollback rebuild evicted page cache on this 3.9 GB box and the restarting container read its weights back out of swap for 6.5 minutes: **502 for over twenty minutes**. **The box went back to `v1.5`, which served again until `v1.6.1` the next day** — so `v1.5` has two separate stints and this table is the only place that is visible |
| [`v1.6.1`](../../releases/tag/v1.6.1) `ee02d3e` | 2026-08-24 | *(still serving)* | Google Cloud VM + Caddy | Same content as `v1.6` with the parse split into two concurrent calls. **Two steps added to the promote and both earned it**: the built image was preflighted in a throwaway container before traffic moved (`scripts/measure/measure_parser_stability.py --pipeline`, 6/6), and `sync; echo 3 > /proc/sys/vm/drop_caches` ran before `up -d` — 3,159 MB free instead of 275, healthy in 320 s, **no downtime**. Verified with real searches, not just `/health` |

From `v1.2` on, `/health` reports the running build directly:

```bash
curl -s https://scenesearch.duckdns.org/health
# {"status":"ok","version":"0.1.0","corpus_frames":6858,"release":"v1.2"}
```

That is the authoritative answer and this table is the history. Before `v1.2` there was no way to ask
a running box which build it was, which is why `v1.0`'s row had to be reconstructed from git and the
deploy notes rather than read off the service.

---

# What a box tracks

**A deployed box tracks `production`, never `main`.** `main` is where daily work lands — it takes
a merge most days — and a bare `git clone` of this repo checks out `main`, because that is the
default branch. So a box cloned the obvious way is one `git pull` away from serving whatever was
merged that afternoon, and the person who runs that pull is usually doing something else entirely,
like restarting after a reboot.

**The branch name carries no version, and that is deliberate** (changed 2026-08-14). It used to be
`release/v1.0`, which was self-contradictory: a name that asserts a version, on a pointer that
fast-forwards every time something ships. Either the name lies or the branch can never move, and
"promote `release/v1.0` to v1.2's code" was the shape the contradiction actually took.

**Versions live on tags, and each one is a GitHub Release.** A tag is immutable, so it is a record
of a build rather than a pointer at the newest one, and the Releases page is where the progression
`v1.0 → v1.1 → …` is legible to anyone who did not watch it happen. **`release/v1.0` has since been
deleted, and that is fine** — this said it was "frozen at `128999f` permanently" as a historical
record, but the `v1.0` tag *is* `128999f` (verified 2026-08-17), so the tag was always the thing
holding that record. A branch kept only to remember a commit is the redundancy this convention
removes.

That split also gives Phase 4/5 the baseline it needs: an experiment is a delta against a *fixed*
build, and a branch anyone can push to cannot be one.

**Moving a box that is already on `main` is its own task**, with its own doc:
[`task-repoint-deploy-to-release.md`](tasks/task-repoint-deploy-to-release.md). The Google Cloud VM is the
case it was written for. Do not improvise it — whether a rebuild is needed depends on which side of
`production` the box currently sits, and guessing costs either downtime or a stale container.

Promoting is therefore a separate, deliberate act. It is a fast-forward of `main`'s own history,
plus the tag that makes it a release rather than a push:

> ⚠️ **`git pull` on the box does not work and never has** — its remote is HTTPS with no stored
> credential, so `git fetch` there fails with `could not read Username`. The line below is kept
> because it is the shape of the promote; the box half is a **git bundle over the gcloud SSH
> channel**, which carries real objects *and tags*, so `git describe --tags` keeps working and
> `RELEASE` is a real version instead of `unknown`:
>
> ```bash
> git bundle create prod.bundle origin/production --tags        # ~16 MB for this repo
> scp -i ~/.ssh/google_compute_engine prod.bundle Precision@<ip>:/tmp/
> # on the box — the ref inside the bundle is refs/remotes/origin/production, NOT refs/heads/*.
> # Fetching refs/heads/production fails with "couldn't find remote ref"; `git bundle list-heads`
> # settles it in one command rather than a second guess.
> sudo -u hieuhau2903 git -C $R fetch /tmp/prod.bundle >     'refs/remotes/origin/production:refs/remotes/origin/production' '+refs/tags/*:refs/tags/*'
> sudo -u hieuhau2903 git -C $R merge --ff-only origin/production
> ```

```bash
git push origin main:production          # promote: refuses if it is not a fast-forward
git tag -a v1.2 -m "v1.2 - <one line>" && git push origin v1.2
gh release create v1.2 --title "v1.2 — <headline>" --notes "..."
ssh <host> 'cd P-057 && git pull && RELEASE=$(git describe --tags) \
    docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d --build'
```

> ⚠️ **`--env-file` is not optional either, and leaving it off takes the site down.**
>
> Compose resolves `.env` from the **project directory** — the directory holding the first `-f`
> file, so `deploy/` — and *not* from your shell's working directory. There is no `deploy/.env`; the
> real one is at the repo root. `${DOMAIN}` therefore interpolates to an empty string **from
> anywhere, the repo root included**, and Compose says so in a warning nobody reads:
> `The "DOMAIN" variable is not set. Defaulting to a blank string.`
>
> Caddy then gets `DOMAIN=`, and `{$DOMAIN:scenesearch.duckdns.org}` in the Caddyfile collapses the
> site-address line to a bare `{`. Caddy parses that as the **global options block**, where `encode`
> is not a valid directive, so it exits 1 and crash-loops on
> `Caddyfile:9: unrecognized global option: encode`.
>
> **It is latent, not new.** Caddy is rarely recreated — it had run two weeks untouched — so the
> broken interpolation sat there until an `up -d` recreated it and took the Live URL down for about
> four minutes during the `v1.8` promote (2026-08-31). Any `up -d`, by anyone, would have done it.
>
> Only `DOMAIN` and `RELEASE` use `${}`; everything else rides `env_file: ../.env` inside the
> service definition and has always worked. That is why the api container was fine and only Caddy
> died.
>
> **The Compose *project name* is not the thing to worry about here**, contrary to a note that used
> to live in `.claude/rules/current-work.md`. On Compose v5 it comes from the compose file's
> directory, so it is `deploy` whichever directory you invoke from — verified on the box with
> `docker compose config --format json` run from both. Running from the repo root does **not** spawn
> a second stack.

**`RELEASE` is not optional.** It bakes the build's name into the image, and `/health` reports it —
so a Discord bug report can be attributed to a build instead of to "whatever was live that week".
`.git` is dockerignored, so the container cannot work it out for itself. Skipping it leaves
`release: "unknown"`, which is deliberately ugly so the smoke test catches it.

**Tag every promote.** An untagged one leaves the deployed build nameable only as "whatever
`production` pointed at that week", which is exactly the state this convention replaced.

> ⚠️ **The box serves a staged corpus, so the command above is one `-f` short of what it needs.**
>
> Since 2026-08-31 production serves the **9,069-frame merge** (nuScenes + Hanoi) from a bind mount,
> not the 6,858-frame index baked into the image. That mount and the three env vars pointing at it
> live in `deploy/docker-compose.merged.yml`, which is a **second `-f`**:
>
> ```bash
> docker compose -f docker-compose.prod.yml -f docker-compose.merged.yml >     --env-file ../.env up -d
> ```
>
> Compose applies files left to right, so which corpus is served is which files you name. Dropping
> the second `-f` is **not an error** — the service starts cleanly, healthily, and answers about a
> corpus 2,211 frames smaller.
>
> **It does NOT report `corpus_mismatch`, and this page said it did until 2026-08-31.** The box sat
> in exactly that state for an hour that day and `/status` read `fitted`, with
> `"detail": "the shipped band was fitted on this corpus"` — because without the mount the service
> reads the *baked* `provenance.json` beside the *baked* index, and those two agree. Both halves are
> internally consistent, so nothing flags. A stamped band only catches a corpus that changed under
> it; it cannot catch a corpus that was swapped together with its own stamp.
>
> **The signals that do fire** are `corpus_frames: 6858`, `source_clips: 0` and — if the promote also
> skipped `RELEASE` — `release: "unknown"`. Check those three, not the band.

> ⚠️ **Preflight the built image before any traffic moves, and preflight it against the LLM.**
>
> `/health` and `/status` were both green for the forty minutes `v1.6` was live with every spatial
> search failing, because neither route touches the model. Run the parse in a throwaway container off
> the new image, with the box's own `.env` — the key matters, the same prompt has scored 12/12 on one
> OpenAI project and 2/6 on another:
>
> ```bash
> docker run --rm --env-file ../.env -e PYTHONPATH=/app >     -v /tmp/preflight_release.py:/app/preflight.py:ro >     --entrypoint python deploy-api:latest /app/preflight.py 20
> ```
>
> **Do not load the corpus in a preflight.** A second copy of the vectors alongside the live
> container is ~1 GB on a 3.9 GB box, which is the memory pressure `drop_caches` exists to avoid;
> read `provenance.json` instead. And note the preflight inherits `ARTIFACTS_DIR` from `.env`, where
> it is **not set** — so it reads the baked corpus unless you pass the merged path explicitly. That
> is worth knowing before you conclude anything about the band from one.
>
> **Afterwards, `scripts/ops/verify_deploy.py <release> <frames> <fingerprint>`** re-runs the same
> reasoning from outside: it checks `/health` and `/status` against values *you* supply, then
> makes the two searches neither route can make. Passing the expected corpus in rather than
> reading it from the file is the point — a deploy that quietly serves the wrong index would
> otherwise verify itself green against its own mistake.

> ⚠️ **`gcloud compute ssh --command` mangles `&&`.** On Windows it fails as
> `plink.exe exited with return code [1]`, which reads like an SSH or IAP problem and is not — the
> same command with `;` separators runs fine. Anything longer than a couple of statements should go
> over `gcloud compute scp` as a script and be run with `sudo bash /tmp/<script>.sh`, which also
> sidesteps the quoting. Note the repo on the box is owned by `hieuhau2903` and Docker needs root,
> so effectively every step here is `sudo`.

Two things make this cheaper than it looks, and one makes it more expensive than it looks:

- **The rebuild is mostly cache — but two of the three slow layers survive, not all three.**
  `Dockerfile`'s `COPY . .` busts on any changed file, and torch plus the ~500 MB of baked weights
  sit above it and survive. The `fetch_assets` index+thumbnail pull sits above `COPY . .` too, but
  **below `COPY scripts/fetch_assets.py`** — so it survives only while that one file is untouched,
  and *any* edit to it, including a pure reformat, re-runs the 307 MB download. That is not
  hypothetical: the v1.3 promote (2026-08-17) paid it because `ruff format` had rewrapped four call
  sites in `fetch_assets.py`. Minutes either way, not the 15–25 of a first build — the whole v1.3
  rebuild measured **123 s** on the e2-medium (2 vCPU), of which `chown -R /app` was 20.9 s,
  exporting the image 24.5 s, and the frontend's `npm install` + `vite build` the rest. Downtime is
  much shorter than the build: the old container serves until the image is ready, so only the
  recreate and the ~40 s corpus load are visible.
- **The corpus does not move with the code.** `scripts/fetch_assets.py:REVISION` pins the dataset, so
  promoting code cannot change what the box serves unless that line was part of the promotion. That
  is the same pin described under [§ A](#deploying), read from the other end.
- **The container restarts, so anything unexported restarts with it.** The verdicts survive on a VM
  — they live in the named volume, not the container — but the service is down for the rebuild, and
  on a Space there is no volume at all. Do not promote into a live feedback session.

**On promoting while feedback is coming in** — revised 2026-08-14. This used to say "do not promote
at all during the feedback window", which assumed a scheduled session with a fixed cohort. That is
not how feedback actually arrives: the demo link is permanently up and comments come in via Discord
whenever they come in, so there is no window to protect and no sample to split. Promote when it is
ready.

What survives the revision is the smaller problem underneath. With a moving build and continuous
feedback, a report is not attributable to a version — "it said nothing matches" could be the band,
a fixed bug, or a real gap in the archive, and nothing in the review table distinguishes them. The
tag and its Release are half the answer, because they date each build; surfacing the deployed
version in the UI is the other half, and is not built yet.

This costs one property worth naming: CI runs on pushes to `main` and on PRs targeting `main`
(`.github/workflows/ci.yml`), so a push to `production` triggers nothing. That is acceptable
*only* because the fast-forward carries commits CI already went green on. It stops being true the
moment someone commits directly to `production` — so don't.

---

# The review database

Everything else on the deployed box can be rebuilt: the code from git, the index and thumbnails from
the Hub, the model weights from the image. The human verdicts cannot. They exist only where they
were typed. **[Backing up the verdicts](#backing-up-the-verdicts) below is the part that acts on
that** — the volume described here keeps them across a redeploy and nothing more.

`deploy/docker-compose.prod.yml` therefore mounts a named volume at `/app/data/reviews` and points
`REVIEW_DB` into it. Two details of that are worth knowing before anyone edits it:

- **The mount is the subdirectory, not `data/`.** A volume over `data/` hides the index and the
  6,858 thumbnails the image fetched at build time, and the service then starts cleanly, reports
  healthy, and answers nothing.
- **`Dockerfile` creates `/app/data/reviews` before its `chown`.** Docker seeds a new named volume
  from the image path it covers, ownership included; with no such path in the image the volume comes
  up root-owned and the non-root container user cannot write to it. The symptom is a permission
  error on the first verdict of the session — and it cannot reproduce locally, where the equivalent
  mount is a host bind owned by the developer.

Without both, `docker compose up -d --build` — the last line of every redeploy above — discards the
verdicts along with the old container.

**On Hugging Face Spaces there is no volume**, so the buffer lasts only as long as the container.
That is tolerable for a supervised demo, where someone is present to hit Export, and not tolerable
for a window where testers arrive on their own: nobody is watching, and a restart takes the week's
judgments with it. If the feedback sessions run on a Space, export after each one.

**Seeding a deploy with judgments collected locally.** The local `data/reviews.db` is currently
empty — the 93 verdicts recorded on 2026-08-07 were the author's own dry run, not tester feedback,
and were deleted rather than left to be counted as evidence they were never going to be. So today
there is nothing to seed, and a fresh deploy correctly starts at zero. Keep the procedure to hand
anyway: the review window may yet produce local verdicts before the box exists.

```bash
scp data/reviews.db <host>:/tmp/seed.db
ssh <host> 'docker compose -f deploy/docker-compose.prod.yml cp /tmp/seed.db api:/app/data/reviews/reviews.db'
```

Do this **before** anyone is given the URL. The table is keyed `(query, frame_id)` and written
`INSERT OR REPLACE`, so copying over a database that already has verdicts silently keeps whichever
copy landed last — fine for an empty target, lossy for a populated one. Merging two populated
databases is a separate job:
`sqlite3 target.db "ATTACH 'other.db' AS o; INSERT OR REPLACE INTO reviews SELECT * FROM o.reviews;"`

> ⚠️ `docker compose config` prints `.env` in full, API keys included. It is the right way to check
> this file renders, and the wrong thing to run on a shared screen or paste into an issue.

## Backing up the verdicts

The named volume above survives `up -d --build`. It does not survive `down -v`, a mistyped prune, a
disk fault, or the trial ending — and until 2026-08-12 nothing on the box copied the verdicts
anywhere at all. The volume was the whole plan, and a volume is not a backup.

> 🔴 **This has never been done on the live box, checked 2026-08-31.** `systemctl is-enabled
> scenesearch-backup.service` returns *"No such file or directory"*, `deploy/backups/` is empty and
> the journal has no entries. **And the commands below are not sufficient on their own:**
> `.dockerignore` excludes `scripts/` from the image except `fetch_assets.py`, so
> `docker compose exec api python scripts/ops/backup_reviews.py` names a file the container does not
> have — `exec api ls scripts/` returns `fetch_assets.py` alone. Add a `!scripts/ops/backup_reviews.py`
> negation and a `COPY`, rebuild, *then* install the unit. Verify by running it once by hand and
> looking for a file, not by looking for a green unit.

**Set it up before the first tester, not after.** Two commands, once:

```bash
mkdir -p deploy/backups && sudo chown 1000:1000 deploy/backups   # the container runs as uid 1000
sudo cp deploy/scenesearch-backup.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now scenesearch-backup.timer
```

The `chown` is not optional and its absence is invisible until the first run: Docker creates a
missing bind-mount source root-owned, the non-root container user cannot write into it, and the
backup fails with EACCES where only `journalctl` will see it. Check both:

```bash
systemctl list-timers scenesearch-backup       # next run
sudo systemctl start scenesearch-backup        # run one now
journalctl -u scenesearch-backup -n 20         # {"ok": true, "rows": N, ...}
```

**Why the script and not `cp`.** `scripts/ops/backup_reviews.py` uses sqlite's online backup API, which
takes a read lock per step and yields a snapshot that is consistent by construction from a *live*
database. `cp`, `docker compose cp` and `tar` all read the file while the service may be mid-write,
and sqlite's format is only consistent between transactions: what you get back can be a database
that opens cleanly and has lost its last rows. The snapshot is then opened, `integrity_check`ed and
counted *before* retention prunes anything, so a run that produced an unreadable file cannot evict
the good copies behind it. Fourteen are kept, at a few hundred KB each.

**A bind mount is not off-box.** It survives every compose command; it does not survive losing the
VM. Pull a copy down after each feedback session — this is the step that actually protects a
session's work:

```bash
scp <host>:~/P-057/deploy/backups/reviews-*.db ./local-backups/
```

**Restoring.** Stop the service first, or the running process will write over what you restore:

```bash
docker compose -f deploy/docker-compose.prod.yml stop api
docker compose -f deploy/docker-compose.prod.yml cp \
    deploy/backups/reviews-20260812T030000Z.db api:/app/data/reviews/reviews.db
docker compose -f deploy/docker-compose.prod.yml start api
```

To merge rather than replace — two boxes, or a local session and a deployed one — use the `ATTACH`
one-liner above. `INSERT OR REPLACE` keeps whichever row landed last, so merging is lossy in one
direction and you have to decide which database is the target.

## Who may take the export

`GET /reviews/export` and the unscoped `GET /reviews/summary` require a **signed-in user — any
account, no role**. There is nothing to set up on the box: the gate is the ordinary login, so an
engineer signs in and the download works. The export controls do not render for a pseudonymous
tester, which is the point — a 401 rendered as a JSON page mid-session reads as a broken product.

**Not `Admin`, on purpose.** The export is the engineer's own output. Gating it on a role would mean
asking a colleague for permission to download the dataset you just built, and six of the eight
accounts on the box are role `User`.

What the gate protects is narrow and worth stating exactly: `?decision=all` returns every
`(query, frame_id, reviewer)` triple, which is precisely what `DELETE /reviews` requires. Left open,
the export does not just leak the research data, it hands out the means to erase it one call at a
time.

**This was `OPERATOR_TOKEN` until 2026-08-27**, a shared secret you handed to a browser by opening
the app once as `https://<host>/?operator_token=<token>`. That existed because the service had no
accounts. Once it had them, the token was a second and weaker credential beside a real one: the same
string for everybody, not revocable, attributable to nobody, and in Caddy's access log by design
because a download link cannot set a header. It also produced the symptom that got it noticed — a
signed-in Admin was told to paste a secret into a URL to download their own data.

**No box needs editing to land this.** Nothing reads `OPERATOR_TOKEN` any more and pydantic-settings
ignores undeclared keys, so a `.env` that still carries the line is simply carrying a dead one. It
can be dropped at the next edit. `src/api/security.py` holds the full reasoning.

**Also set `TRUST_PROXY_HEADERS=true` on this stack** — `deploy/docker-compose.prod.yml` already
does. The rate limits are per client address, and behind Caddy every request arrives from the
proxy's container address, so without it the first tester to search ten times locks out everyone
else. Set it only where a trusted proxy terminates the connection: on a bare `make run` or a tunnel
the header is whatever the client typed.

> ⚠️ **Start uvicorn with `--no-proxy-headers`** — the `Dockerfile` CMD and `make run` both do.
> uvicorn's own forwarded-header handling is *on by default*, trusts `127.0.0.1`, and overwrites the
> client address the limiter charges. A Cloudflare tunnel connects from 127.0.0.1, so with it on,
> any tunnel visitor can send `X-Forwarded-For` and be seen as whoever they typed: measured on
> 2026-08-12, six searches against a 2/minute limit all returned 200 with a forged address on each.
> `--forwarded-allow-ips=*` is not the fix — that path reads the *first* entry, which is the one the
> client writes. If you launch uvicorn by hand, pass the flag; `client_key` shares one bucket
> between all forged requests as a fallback, which is safe but blunt.

---

# Verify

Applies to either path — substitute your base URL.

```bash
BASE=https://your-name.duckdns.org      # or https://<user>-<space>.hf.space

curl $BASE/health
curl $BASE/api/v1/status

curl -X POST $BASE/api/v1/search \
     -H 'Content-Type: application/json' \
     -d '{"query": "a wet road at night", "top_k": 10}'
```

Walk the four behaviours end to end — each exercises a different path, and all four are what the
demo video should show:

| query | expected |
|---|---|
| `a wet road at night` | `matched: true`, `confidence: "high"`, ~5 distinct clips |
| `a pedestrian to the front-left` | `matched: true`, `confidence: "low"`, results **shown** with a caveat |
| `a bus on fire` | `matched: false`, a reason describing the archive |
| `a vehicle cutting into our lane` | `matched: false`, explained as out of scope |

# Keeping it up for the seven days the rubric requires

**Point UptimeRobot at `/health`** every 5 minutes either way, but for different reasons:

- **On a Space**, this is what stops it sleeping on inactivity. It is load-bearing.
- **On the VM**, nothing sleeps — the value is the alert when the service dies, which is the real
  risk over a week nobody is watching.

> **On Oracle, idle reclamation is the threat, and it is worth understanding.** Oracle may reclaim
> *idle* Always Free compute instances — broadly, sustained low CPU, network and memory over about a
> week. A demo nobody uses is exactly that shape, and it could be reclaimed during the very week the
> rubric asks it to stay up.
>
> The clean mitigation is to **upgrade the account to Pay As You Go**. Always Free resources stay
> free on a PAYG account and are exempt from reclamation; you are not charged as long as you stay
> within the Always Free shapes. Verify this in the console before relying on it — Oracle's rule,
> not ours, and it changes.

# Handing the URL to the frontend

Two things your teammate needs, and the second is easy to forget until it fails in production:

1. The base URL
2. **Their deployed origin must be in `CORS_ORIGINS`.** Vercel preview deployments get their own
   origins, so add those too if previews should work. On a Space, edit the variable and it restarts;
   on the VM, edit `.env` then `docker compose -f deploy/docker-compose.prod.yml up -d`.

Then put the Live URL in `README.md`, which the rubric checks.

# If something is wrong

| Symptom | Cause |
|---|---|
| **Space** build fails on `pip install torch` | it took the arm64 branch. HF is x86; `TARGETARCH` should be `amd64` |
| **Space** starts then 404s on everything | `app_port` missing from `README.md` frontmatter — it routed to 7860 |
| **Space** permission errors writing cache | container uid is not 1000; the Dockerfile pins `useradd -u 1000` |
| **VM**: `curl` hangs from outside, works over SSH | iptables — step 2b. The commonest one |
| **VM**: Caddy loops on certificate errors | DNS not pointing at the instance yet, or port 80 blocked (Let's Encrypt validates over 80) |
| `502` for the first ~90 s | expected — the corpus is loading and the encoders are warming. `/health` answers before `/status` does |
| `/status` returns `503` | artifacts missing. `data/artifacts/` is committed, so check the clone rather than regenerating |
| Search returns "temporarily unavailable" | `OPENAI_API_KEY` missing or invalid; the parse node is the only external call |
| Browser blocked / CORS error | the frontend origin is not in `CORS_ORIGINS` |
