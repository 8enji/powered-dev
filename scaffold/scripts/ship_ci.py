"""Ship CI watch helper.

Tracks the state of `gh pr checks --watch` background runs and classifies
the next action for the /task-ship slash command. Replaces the inline
file-marker state machine that previously lived in task-ship.md.

Usage:
    python ship_ci.py start --pr <int>
    python ship_ci.py next-action --pr <int>
    python ship_ci.py switch-mode --pr <int> --to all
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

MAX_RETRIES = 5
TMP_DIR = Path("/tmp")


def _status_path(pr: int) -> Path:
    return TMP_DIR / f"ship-{pr}.status"


def _retries_path(pr: int) -> Path:
    return TMP_DIR / f"ship-{pr}.retries"


def _all_mode_marker_path(pr: int) -> Path:
    return TMP_DIR / f"ship-{pr}.all-status"


def _read_exit_code(pr: int) -> int | None:
    """Parse `__SHIP_EXIT__=<n>` from the status file. None if missing or malformed."""
    path = _status_path(pr)
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if line.startswith("__SHIP_EXIT__="):
            try:
                return int(line.split("=", 1)[1])
            except ValueError:
                return None
    return None


def _is_all_mode(pr: int) -> bool:
    return _all_mode_marker_path(pr).exists()


def _read_retries(pr: int) -> int:
    path = _retries_path(pr)
    if not path.exists():
        return 0
    try:
        return int(path.read_text().strip())
    except ValueError:
        return 0


def _bump_retries(pr: int) -> int:
    new = _read_retries(pr) + 1
    _retries_path(pr).write_text(f"{new}\n")
    return new


def _wipe_state(pr: int) -> None:
    for path in (_status_path(pr), _retries_path(pr), _all_mode_marker_path(pr)):
        path.unlink(missing_ok=True)


def _cmd_start(pr: int) -> None:
    _wipe_state(pr)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ship CI watch helper")
    sub = parser.add_subparsers(dest="command", required=True)

    start_p = sub.add_parser("start", help="Wipe ship state files for a PR")
    start_p.add_argument("--pr", type=int, required=True)

    args = parser.parse_args(argv)
    if args.command == "start":
        _cmd_start(args.pr)


if __name__ == "__main__":
    main()
