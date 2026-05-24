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


_PASSING_STATES = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED", "STALE"})
_FAILING_STATES = frozenset({
    "FAILURE", "ERROR", "CANCELLED", "TIMED_OUT",
    "ACTION_REQUIRED", "STARTUP_FAILURE",
})


def _classify_checks(checks: list[dict]) -> str:
    """Coarse-grain a list of check dicts into 'empty' / 'failing' / 'pending' / 'passing'.

    Unknown states are conservatively treated as pending so we don't declare
    green-light on a state we haven't seen before.
    """
    if not checks:
        return "empty"
    has_failure = False
    has_pending = False
    for c in checks:
        state = c.get("state", "")
        if state in _FAILING_STATES:
            has_failure = True
        elif state not in _PASSING_STATES:
            has_pending = True
    if has_failure:
        return "failing"
    if has_pending:
        return "pending"
    return "passing"


def _gh_checks_json(pr: int, required_only: bool) -> list[dict]:
    """Call `gh pr checks <pr> [--required] --json name,state`. Return [] on any failure.

    Times out after 30s; timeout is treated as another graceful-degradation case
    so a stalled `gh` invocation doesn't hang the calling slash command.
    """
    cmd = ["gh", "pr", "checks", str(pr), "--json", "name,state"]
    if required_only:
        cmd.append("--required")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
    except subprocess.TimeoutExpired:
        return []
    if not result.stdout.strip():
        return []
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return parsed


def _next_action(pr: int) -> str:
    exit_code = _read_exit_code(pr)
    mode = "all" if _is_all_mode(pr) else "required"

    if exit_code is None:
        return f"redispatch-{mode}"

    if exit_code == 0:
        return "done-green"

    checks_in_mode = _gh_checks_json(pr, required_only=(mode == "required"))
    classification = _classify_checks(checks_in_mode)

    if classification == "passing":
        return "done-green"
    if classification == "failing":
        return "done-red"
    if classification == "pending":
        return f"redispatch-{mode}"

    # classification == "empty"
    if mode == "required":
        all_checks = _gh_checks_json(pr, required_only=False)
        if all_checks:
            return "ask-non-required"
    if _read_retries(pr) >= MAX_RETRIES:
        return "retries-exhausted"
    _bump_retries(pr)
    return f"redispatch-{mode}-after-15s"


def _wipe_state(pr: int) -> None:
    for path in (_status_path(pr), _retries_path(pr), _all_mode_marker_path(pr)):
        path.unlink(missing_ok=True)


def _cmd_start(pr: int) -> None:
    _wipe_state(pr)


def _cmd_next_action(pr: int) -> None:
    print(_next_action(pr))


def _cmd_switch_mode(pr: int, to: str) -> None:
    if to != "all":
        print(f"ship_ci: switch-mode --to only supports 'all', got {to!r}", file=sys.stderr)
        sys.exit(2)
    _all_mode_marker_path(pr).write_text("")
    _status_path(pr).unlink(missing_ok=True)
    _retries_path(pr).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ship CI watch helper")
    sub = parser.add_subparsers(dest="command", required=True)

    start_p = sub.add_parser("start", help="Wipe ship state files for a PR")
    start_p.add_argument("--pr", type=int, required=True)

    next_p = sub.add_parser("next-action", help="Classify the next ship action from CI state")
    next_p.add_argument("--pr", type=int, required=True)

    switch_p = sub.add_parser("switch-mode", help="Switch ship watch mode (required → all)")
    switch_p.add_argument("--pr", type=int, required=True)
    switch_p.add_argument("--to", required=True, choices=["all"])

    args = parser.parse_args(argv)
    if args.command == "start":
        _cmd_start(args.pr)
    elif args.command == "next-action":
        _cmd_next_action(args.pr)
    elif args.command == "switch-mode":
        _cmd_switch_mode(args.pr, args.to)


if __name__ == "__main__":
    main()
