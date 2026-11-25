"""Make script output survive a Windows console.

These scripts' docstrings carry `§`, `—`, `±` and `≤`, and `argparse(description=__doc__)` prints
them on `--help`. On this machine the research interpreter's stdout is cp1252, which cannot encode
any of them: `--help` raised `UnicodeEncodeError` and ordinary output rendered `—` as `?`.

Reconfiguring is preferable to stripping the characters. The alternative is writing documentation
around a terminal's limitations, and the docstrings are the primary explanation of what these
scripts do — `errors="replace"` degrades one glyph, an ASCII-only rewrite degrades the prose.

Import for the side effect, before any printing:

    from _console import use_utf8   # noqa: F401
"""

from __future__ import annotations

import sys


def use_utf8() -> None:
    """Switch stdout/stderr to UTF-8, replacing anything the console still cannot show.

    A no-op where the streams are already UTF-8 (Linux, the Docker image, CI) and where they have
    been redirected to something without `reconfigure`, so it is safe to call unconditionally.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


use_utf8()
