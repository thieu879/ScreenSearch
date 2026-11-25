from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "AI20K Agent"
    app_env: Literal["development", "production", "test"] = "development"
    # Which build is running, reported by `/health` and shown in the UI. Baked at image build from
    # `Dockerfile`'s RELEASE arg, because `.git` is dockerignored and a container cannot ask git.
    #
    # It exists because feedback arrives continuously via Discord against a link that keeps being
    # redeployed, and `data/reviews` has no column naming the build a verdict came from. "It said
    # nothing matches" is unattributable without this — it could be a retired threshold, a bug since
    # fixed, or a real gap in the archive.
    #
    # `unknown` is deliberately an ugly value rather than a plausible default: a promote that forgets
    # to pass it should be obvious in the smoke test, not silently indistinguishable from a good one.
    release: str = "unknown"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = "http://localhost:3000"

    # LLM
    openai_api_key: str = ""
    google_api_key: str = ""
    model_name: str = "gemini-3.5-flash-lite"
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    # PostgreSQL connection.  Read by ``src/db/session.py`` to create the SQLAlchemy engine.
    # The default is a local development database; production overrides via ``.env``.
    database_url: str = "postgresql://postgres:12345678@localhost:5433/SceneSearch"

    # --- Authentication (JWT) ---
    # Secret used for signing JWTs. MUST be overridden in production via .env.
    jwt_secret_key: str = "change-me-in-production-use-a-strong-random-secret"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7
    # Cookie flags — Secure=true only behind HTTPS (production).
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    # --- Google OAuth ---
    google_client_id: str = ""
    google_client_secret: str = ""

    # --- Email (Gmail SMTP) & Redis ---
    mail_username: str = ""
    mail_password: str = ""
    mail_host: str = "smtp.gmail.com"
    mail_port: int = 587
    redis_url: str = "redis://localhost:6379/0"

    # Human review — M2 Brief §Chức năng chính. A plain filesystem path, not a URL, because there is
    # exactly one supported backend (stdlib sqlite) and a URL would invite pointing it at a server
    # this project has no driver for. Gitignored via `*.db`.
    review_db: str = "data/reviews.db"

    # --- Abuse limits (src/api/ratelimit.py) ---
    #
    # `OPERATOR_TOKEN` used to live here: a shared secret gating the review export and the
    # whole-table summary, back when the service had no accounts. Retired 2026-08-27 — those two
    # endpoints now require a signed-in user (any role), which is revocable and attributable where
    # a shared string is neither. `src/api/security.py` carries the full reasoning. A deployment whose `.env`
    # still sets the variable is unaffected: `extra="ignore"` above means an unread key is simply
    # ignored, so no box needs editing to land this.

    # Whether X-Forwarded-For may be believed. True only where a trusted proxy terminates the
    # connection — the deployed stack, where Caddy is the sole ingress and the API publishes no
    # port. False for `make run` and for a tunnel, where the header is whatever the client typed.
    trust_proxy_headers: bool = False

    # Per-client ceiling on the endpoints that buy a completion (`/search`, `/chat`). Ten a minute
    # is far above a person typing into a search box and far below a script.
    llm_rate_limit_per_minute: int = Field(default=10, ge=1)

    # The ceiling that actually protects the bill, because a per-client limit multiplies by however
    # many clients an attacker cares to be. 500 gpt-4o-mini parses is a few cents; the project's
    # whole budget is $5-10.
    llm_daily_cap: int = Field(default=500, ge=1)

    # Review writes are cheap, but the table is the one artifact here that cannot be rebuilt, and a
    # reviewing session is bursty — a tester judges ten cards in a row.
    write_rate_limit_per_minute: int = Field(default=60, ge=1)

    # Vector Store
    chroma_persist_dir: str = "./data/chroma"

    # --- SceneSearch: artifacts written by scripts/promote_artifacts.py ---
    # Set use_database_corpus=True to query frames, vectors, thumbnails and reviews directly from
    # PostgreSQL (DATABASE_URL) instead of reading local disk artifacts into RAM.
    use_database_corpus: bool = True
    artifacts_dir: str = "data/artifacts"
    thumbs_dir: str = "data/thumbs"
    # Redacted six-second cuts, built by `scripts/moments/build_moment_clips.py`. Absent on every deployed
    # box and meant to be: they are a local artifact for the demo, `data/` is gitignored, and the
    # service reports no moments rather than failing when the directory is not there.
    moments_dir: str = "data/moments"
    # Thumbnail *width* is deliberately not here. Nothing under `src/` resizes — the API serves
    # whatever bytes are on disk — and the three writers that do resize all run in the `ssv`
    # research environment, which has no pydantic-settings. The shared default lives beside the
    # other redaction geometry, in `scripts/anonymise.py: THUMB_WIDTH`.

    # Retrieval. `siglip` must match the encoder the vectors were built with, or queries land in a
    # different space than the corpus — provenance.json records which that was.
    siglip_model: str = "ViT-B-16-SigLIP2"
    siglip_pretrained: str = "webli"
    caption_text_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Rejection — M2_DESIGN §6.1, option B, as a band rather than one cutoff.
    #
    # §6.1 measured 0.457 as the best *single* threshold (balanced accuracy 0.806). Shipped as a
    # binary it refuses ~26% of real queries, including "a pedestrian to the front-left" — the query
    # the metadata filter most clearly improves. That trade is worse than it looks, because the two
    # errors are not symmetric: a wrongly shown result is self-correcting (the user sees it is wrong
    # and rephrases) while a wrongly refused one is invisible and final (they conclude the archive
    # lacks footage it holds, and stop looking).
    #
    # So two lines instead of one. RE-FIT 2026-08-02 for the 170-scene / 6,858-frame corpus
    # (trainval parts 9+10, query set v4, 19 real / 24 empty, k=5):
    #   score >= tau_confident   answer plainly                    (real: 68%,  empty: 13%)
    #   tau_reject <= s < tau_c  answer, flagged low confidence     (real: 32%)
    #   score <  tau_reject      refuse — nothing here matches      (real:  0%,  empty: 13%)
    #
    # The previous band (0.35 / 0.457) was fitted to nuScenes-mini and does NOT transfer, exactly as
    # M2_DESIGN §10.3 predicted: caption-similarity scores are a property of the corpus and the
    # captioner together, so a different archive shifts the whole distribution. Carried over
    # unchanged it would have refused q21 "a pedestrian to the front-left" at 0.330 — a real query,
    # and the one the metadata filter most clearly improves. That is precisely the error the band
    # exists to prevent, and it would have shipped silently.
    #
    # tau_reject keeps the method that set the old value rather than the value: 0.035 below the
    # weakest real query, margin left deliberately because fitting to the observed minimum overfits
    # 19 queries. Weakest is now q21 at 0.330, so 0.330 - 0.035 ≈ 0.30.
    #
    # tau_confident is 0.50 rather than the 0.467 the ablation reports as the best *single* cutoff.
    # 0.50 flags three more real queries as low-confidence and halves the empty queries shown
    # confidently, 5 -> 3. By the asymmetry above that trade is clearly worth taking: a caveat is
    # recoverable, confident-and-wrong is not.
    #
    # Known weakness, recorded rather than tuned around: 4 of the 5 remaining confidently-shown
    # empties are weather — fog, snow, snow-covered road, rainy night. `absent_environment` is
    # option B's weakest class (0.772), and a larger, more visually varied corpus produces captions
    # that mention weather-like things more often.
    tau_reject: float = 0.30
    tau_confident: float = 0.50
    verify_top_k: int = Field(default=5, ge=1, le=50)

    # Diversity — M2_DESIGN §7. The window is set per request from `top_k`, because it must equal
    # the number of results actually displayed; only the cap is global.
    diversity_cap: int = Field(default=2, ge=1)

    # How many results a search returns when the caller does not say. One number, read by
    # `SearchRequest.top_k` and by the graph's own fallback, so the API default and the default an
    # agent invocation gets can no longer drift apart — they were three separate `10` literals.
    #
    # **This is not a free knob, and the cost is the diversity window rather than the result count.**
    # `top_k` doubles as that window (see `services/search/diversity.py`), and reranking past the
    # displayed head costs ranking quality for no extra variety: at cap 2, relational lift measures
    # +0.113 at window 10 against +0.077 at window 50, while distinct-scenes@10 stays 5.50 either
    # way. So raising this trades measured precision for a longer page; it does not buy diversity.
    # The published `eval/results/` figures are all at 10, and a box set elsewhere is no longer
    # described by them.
    default_top_k: int = Field(default=10, ge=1, le=50)

    # LangSmith. Names only here; the key lives in the environment.
    langsmith_tracing: bool = False
    langsmith_project: str = "scenesearch"
    langsmith_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
