"""Codex review orchestration helper.

Owns shared logic between PR mode and local-change mode for /request-codex-review:
state persistence, prompt assembly, schema validation, touched-files filtering,
severity histogram, event computation, and output rendering.

CLI entry points (`prepare` and `finish`) are invoked by the slash command.
Pure functions are exposed for direct testing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


Mode = Literal["local", "pr-current", "pr-explicit"]


@dataclass(frozen=True)
class ParsedArgs:
    mode: Mode
    identifier: str | None  # PR number, owner/repo#N, or URL for pr-explicit; None otherwise
    focus: str               # text after the first whitespace token


_LOCAL_BRANCHES = frozenset({"main", "master", "HEAD"})
_PR_URL_RE = re.compile(r"^https://github\.com/[^/]+/[^/]+/pull/\d+")
_OWNER_REPO_RE = re.compile(r"^[^/\s]+/[^/\s#]+#\d+$")


def parse_arguments(arg_string: str, current_branch: str) -> ParsedArgs:
    """Parse the slash-command $ARGUMENTS into a structured mode + focus."""
    stripped = arg_string.strip()
    if not stripped:
        if current_branch in _LOCAL_BRANCHES:
            return ParsedArgs(mode="local", identifier=None, focus="")
        return ParsedArgs(mode="pr-current", identifier=None, focus="")

    parts = stripped.split(None, 1)
    first = parts[0]
    focus = parts[1].strip() if len(parts) > 1 else ""

    if first in ("local", "--local"):
        return ParsedArgs(mode="local", identifier=None, focus=focus)

    if first.isdigit():
        return ParsedArgs(mode="pr-explicit", identifier=first, focus=focus)

    if _OWNER_REPO_RE.match(first) or _PR_URL_RE.match(first):
        return ParsedArgs(mode="pr-explicit", identifier=first, focus=focus)

    # Non-PR token with no PR shape — treat the whole string as a local focus prompt.
    return ParsedArgs(mode="local", identifier=None, focus=stripped)


@dataclass(frozen=True)
class ReviewPaths:
    review_dir: Path
    state: Path
    prompt: Path
    status: Path
    jsonl: Path
    last_message: Path
    touched_files: Path
    event: Path
    review_root: Path           # holds the path to where codex should `cd` (PR worktree or repo root)
    dispatch_env: Path          # `key=value\n` pairs the slash command sources
    latest_pointer: Path        # /tmp/codex-review.latest


def review_paths(
    kind: Literal["pr", "local"],
    key: str,
    *,
    tmp_root: Path = Path("/tmp"),
    create: bool = False,
) -> ReviewPaths:
    """Compute the per-review directory layout.

    All artifacts for one review live under `<tmp_root>/codex-review-<kind>-<key>/`.
    The latest-pointer file lives at `<tmp_root>/codex-review.latest` and stores the
    most recent review_dir path so the wake handler can find it without env vars.
    """
    review_dir = tmp_root / f"codex-review-{kind}-{key}"
    if create:
        review_dir.mkdir(parents=True, exist_ok=True)
    return ReviewPaths(
        review_dir=review_dir,
        state=review_dir / "state.json",
        prompt=review_dir / "prompt.txt",
        status=review_dir / "status",
        jsonl=review_dir / "codex.jsonl",
        last_message=review_dir / "last-message.json",
        touched_files=review_dir / "touched-files",
        event=review_dir / "event",
        review_root=review_dir / "review-root",
        dispatch_env=review_dir / "dispatch.env",
        latest_pointer=tmp_root / "codex-review.latest",
    )
