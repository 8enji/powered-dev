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
