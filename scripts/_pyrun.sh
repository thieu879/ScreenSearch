#!/usr/bin/env bash
# Cross-platform Python launcher for AI log hooks.
# Preference order: project venv (.venv or venv) > python3/python/py on
# PATH (skipping the Windows Store's python3/python stub launchers,
# which sit on PATH and "exist" per `command -v` but only print an
# install prompt) > common Windows install locations across a few
# common drive letters, including uv-managed installs (Git Bash
# launched by some hooks gets a stripped PATH that omits the Windows
# Python directory, and not everyone installs on C:). Among whatever's
# found, prefers the first candidate with python-dotenv importable —
# submit_log.py needs it to read AI_LOG_SERVER / AI_LOG_API_KEY from
# .env. Without this, a bare python3 with no packages (e.g. MSYS2's
# Git-Bash-bundled Python) could win the old "first found" race and
# silently skip .env loading.
#
# Candidates are tracked as parallel arrays (cmd + optional extra arg)
# rather than single strings, so a path containing spaces (e.g.
# "/c/Program Files/Python312/python.exe") and a two-word launcher
# (`py -3`) can both be invoked without unquoted word-splitting breaking
# the former.
#
# Designed to be sourced or called as: bash scripts/_pyrun.sh <script> [args...]
#
# Exits 0 silently if no Python is found — hooks must never block the AI tool.
set -u

CAND_CMD=()
CAND_ARG=()

add_candidate() {
  CAND_CMD+=("$1")
  CAND_ARG+=("${2:-}")
}

# Project virtualenv first, if present.
for venv_py in .venv/Scripts/python.exe .venv/bin/python venv/Scripts/python.exe venv/bin/python; do
  [ -x "$venv_py" ] && add_candidate "$venv_py"
done

# python3 / python on PATH — but skip the Windows Store stub launcher.
if command -v python3 >/dev/null 2>&1 && ! command -v python3 | grep -qi "WindowsApps"; then
  add_candidate "python3"
fi
if command -v python >/dev/null 2>&1 && ! command -v python | grep -qi "WindowsApps"; then
  add_candidate "python"
fi
command -v py >/dev/null 2>&1 && add_candidate "py" "-3"

shopt -s nullglob 2>/dev/null || true
for drive in c d e; do
  for cand in \
    "/$drive/Users"/*/AppData/Local/Programs/Python/Python*/python.exe \
    "/$drive/Users"/*/AppData/Local/uv/python/*/python.exe \
    "/$drive/Program Files/Python"*/python.exe \
    "/$drive/Program Files (x86)/Python"*/python.exe \
    "/$drive/Python"*/python.exe; do
    [ -x "$cand" ] && add_candidate "$cand"
  done
done
shopt -u nullglob 2>/dev/null || true

[ ${#CAND_CMD[@]} -eq 0 ] && exit 0

# Runs a candidate by index, forwarding remaining args to it.
run_candidate() {
  local idx="$1"
  shift
  if [ -n "${CAND_ARG[$idx]}" ]; then
    "${CAND_CMD[$idx]}" "${CAND_ARG[$idx]}" "$@"
  else
    "${CAND_CMD[$idx]}" "$@"
  fi
}

# Find the first candidate with python-dotenv importable. Stops at the
# first hit rather than probing every candidate — each probe spawns a
# process, which is slow on Windows, and there's no benefit to checking
# candidates we'll never use.
CHOSEN=-1
for i in "${!CAND_CMD[@]}"; do
  if run_candidate "$i" -c "import dotenv" >/dev/null 2>&1; then
    CHOSEN=$i
    break
  fi
done
# None have dotenv — fall back to the first candidate so scripts that
# don't need it (log_hook.py, log_antigravity.py) still run.
[ "$CHOSEN" -ge 0 ] || CHOSEN=0

# Fallback order for the exec attempt below: CHOSEN first, then every
# other discovered candidate, in original discovery order. Built with no
# extra subprocess spawns — this is just index bookkeeping.
ORDER=("$CHOSEN")
for i in "${!CAND_CMD[@]}"; do
  [ "$i" = "$CHOSEN" ] || ORDER+=("$i")
done

# Try each in turn: `command -v`/-x only proved a candidate was runnable
# at discovery time, not that it still is now. `execfail` makes a failed
# *exec* (e.g. the path was deleted, permissions changed) return control
# here instead of killing the shell, so we fall through to the next
# candidate rather than dying on a stale one.
#
# This does NOT protect against an interpreter that starts successfully
# and then crashes mid-run (e.g. a missing DLL) — once exec hands off
# the process, control can't return here even if the new process later
# exits nonzero. That's intentional: the scripts this launches
# (submit_log.py in particular) aren't safely retryable — it POSTs to
# the grading server before archiving, so blindly re-running it under a
# different interpreter on any nonzero exit risks a duplicate
# submission, which is worse than the rare crash this would guard
# against. The outer pre-push hook wraps every call in `|| true`, so a
# crash here never blocks the actual push — only that push's log
# submission is skipped, matching this script's "never block" contract.
shopt -s execfail 2>/dev/null || true
for i in "${ORDER[@]}"; do
  if [ -n "${CAND_ARG[$i]}" ]; then
    exec "${CAND_CMD[$i]}" "${CAND_ARG[$i]}" "$@"
  else
    exec "${CAND_CMD[$i]}" "$@"
  fi
done

# Every candidate failed to even spawn — never block the caller.
exit 0
