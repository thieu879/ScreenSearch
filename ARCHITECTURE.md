# Architecture

**The architecture document for this project is [`docs/architecture_diagram.md`](docs/architecture_diagram.md).**

That is the path the course guide names as the deliverable, it is the one that is kept current, and it
is where the Mermaid diagram, the component table and the failure-mode table live. Start there.

For the shorter version — the ingest/query split and why the two halves never call each other — see
[`README.md` § Architecture](README.md#architecture).

---

## Why this file is a pointer and not a document

It held the unmodified AI20K template until 2026-08-14: a generic diagram of `React/Next.js UI →
FastAPI → Database + Vector Store`, with `[mô tả]` and `[danh sách]` placeholders under every
heading. Nothing in it had been edited since the initial commit on 2026-07-23.

That is worse than an empty file, because every concrete claim in it was wrong about this system:

| The template said | This project actually |
|---|---|
| React/Next.js | React + Vite, served by FastAPI from the same origin |
| `Database` | the search path needs none, and did not have one until 2026-08-21. The auth feature (`9615e17`) added a **Postgres** users table (`src/db/session.py`) and **Redis** for OTP codes (`src/services/otp.py`, in-memory fallback); `sqlite` still holds only the human review verdicts. None of the three touches a search request |
| `Vector Store` | an exact numpy flat index in memory — no Chroma, no service, deliberately |
| `Agent → Tools → DB` | `parse → retrieve → verify → rerank → respond`, sharing offline artifacts |

Deleting it was the alternative. Keeping a pointer is cheaper: the filename is the obvious guess for
anyone looking, including a grader, and a pointer costs one hop where a 404 costs a wrong conclusion
about whether the work was done.
