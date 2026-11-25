"""CLI entry point wrapper for running the adaptive keyframe extraction pipeline (FR-01.2).

Delegates to scripts/ingest/run_keyframing.py.
"""

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.ingest.run_keyframing import main  # noqa: E402

if __name__ == "__main__":
    main()
