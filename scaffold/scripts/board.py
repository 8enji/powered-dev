"""Board lifecycle automation.

Manages the powered-dev task board:
  - Lints backlog for duplicate entries
  - Checks merge/PR gates (blocks if branch has active plan)
  - Starts and finishes tasks (scaffold stubs, move backlog entries)

Usage:
    python board.py lint-backlog
    python board.py start "Task title" [--tier lite|full]
    python board.py finish
    python board.py abandon
    python board.py set-pr --pr <int> --branch <branch>
    python board.py check-merge <branch>
    python board.py check-pr <branch>
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import docs_index
from frontmatter import parse_frontmatter

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = REPO_ROOT / "docs" / "superpowers"
BOARD_ROOT = REPO_ROOT / "docs" / "board"
PLANS_ROOT = DOCS_ROOT / "plans"
SPECS_ROOT = DOCS_ROOT / "specs"
BACKLOG_PATH = BOARD_ROOT / "backlog.md"
INDEX_PATH = DOCS_ROOT / "INDEX.md"

# ---------------------------------------------------------------------------
# Plan stub templates
# ---------------------------------------------------------------------------

_PLAN_STUB_FULL = """---
status: active
type: plan
date: {date}
summary: {title}
branch: {branch}
tier: full
related:
  spec: {spec_filename}
---

# {title}
"""

_PLAN_STUB_LITE = """---
status: active
type: plan
date: {date}
summary: {title}
branch: {branch}
tier: lite
---

# {title}
"""

_SPEC_STUB = """---
status: active
type: spec
date: {date}
summary: {title}
---

# {title}
"""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    """Return today's UTC date as YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _current_branch() -> str:
    """Return the current git branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _slugify(title: str) -> str:
    """Convert title to lowercase-hyphenated slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def _git_add(paths: list[Path]) -> None:
    """Stage the given file paths silently."""
    str_paths = [str(p) for p in paths]
    subprocess.run(["git", "add"] + str_paths, capture_output=True, check=False)


# ---------------------------------------------------------------------------
# Core: collect plans
# ---------------------------------------------------------------------------

def _collect_plans(plans_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Return list of (path, frontmatter_dict) for all plans with frontmatter."""
    results: list[tuple[Path, dict[str, Any]]] = []
    if not plans_root.is_dir():
        return results
    for p in sorted(plans_root.glob("*.md")):
        fm = parse_frontmatter(p)
        if fm is not None:
            results.append((p, fm))
    return results


def lint_backlog(backlog_path: Path) -> list[str]:
    """Check ## title uniqueness in backlog, skipping HTML comment blocks.

    Returns list of error strings (empty = OK).
    """
    if not backlog_path.exists():
        return []

    text = backlog_path.read_text(encoding="utf-8")
    errors: list[str] = []
    seen: dict[str, int] = {}

    # Strip HTML comment blocks <!-- ... --> before parsing titles
    stripped = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    for line in stripped.splitlines():
        m = re.match(r"^##\s+(.+)", line)
        if m:
            title = m.group(1).strip()
            if title in seen:
                errors.append(f"duplicate backlog entry: '{title}'")
            else:
                seen[title] = 1

    return errors


# ---------------------------------------------------------------------------
# Public API: check_branch_active
# ---------------------------------------------------------------------------

def check_branch_active(branch: str, plans_root: Path | None = None) -> tuple[int, str]:
    """Return (exit_code, message). Exit 1 if branch has an active plan.

    The plans_root kwarg defaults to PLANS_ROOT but allows test override.
    """
    root = plans_root if plans_root is not None else PLANS_ROOT
    all_plans = _collect_plans(root)

    for path, fm in all_plans:
        if fm.get("branch") == branch and fm.get("status") == "active":
            summary = fm.get("summary", path.stem)
            msg = (
                f"Branch '{branch}' has an active plan: '{summary}'. "
                f"Run `board.py finish` or `board.py abandon` before merging."
            )
            return 1, msg

    return 0, f"No active plan found for branch '{branch}'."


# ---------------------------------------------------------------------------
# Internal: _find_backlog_entry / _remove_backlog_entry
# ---------------------------------------------------------------------------

def _find_backlog_entry(backlog_path: Path, title: str) -> tuple[int, int] | None:
    """Return (start, end) byte offsets of the matching ## title entry.

    An entry runs from its ## heading to just before the next ## heading (or EOF).
    HTML comment blocks are skipped during title matching.
    Returns None if not found.
    """
    text = backlog_path.read_text(encoding="utf-8")
    # Find all ## headings (not inside HTML comment blocks)
    # We'll work on lines to find heading positions
    lines = text.splitlines(keepends=True)
    pos = 0
    headings: list[tuple[str, int, int]] = []  # (title, byte_start, line_idx)

    in_comment = False
    for i, line in enumerate(lines):
        # Track HTML comment state
        if "<!--" in line:
            in_comment = True
        if "-->" in line:
            in_comment = False
            pos += len(line.encode("utf-8"))
            continue
        if not in_comment:
            m = re.match(r"^##\s+(.+)", line)
            if m:
                headings.append((m.group(1).strip(), pos, i))
        pos += len(line.encode("utf-8"))

    # Find the target heading
    for idx, (heading_title, byte_start, line_idx) in enumerate(headings):
        if heading_title == title:
            # Entry ends at the start of the next heading, or EOF
            if idx + 1 < len(headings):
                _, next_start, _ = headings[idx + 1]
                return byte_start, next_start
            else:
                return byte_start, len(text.encode("utf-8"))

    return None


def _remove_backlog_entry(backlog_path: Path, title: str) -> None:
    """Remove the named entry from backlog and normalize trailing newlines."""
    offsets = _find_backlog_entry(backlog_path, title)
    if offsets is None:
        raise ValueError(f"Backlog entry not found: '{title}'")

    raw = backlog_path.read_bytes()
    start, end = offsets
    new_raw = raw[:start] + raw[end:]
    # Normalize: collapse multiple trailing newlines to exactly two
    text = new_raw.decode("utf-8")
    text = re.sub(r"\n{3,}$", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    backlog_path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI command implementations
# ---------------------------------------------------------------------------

def _regen_index() -> None:
    """Regenerate INDEX.md using docs_index.build_index()."""
    content = docs_index.build_index(DOCS_ROOT)
    INDEX_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote {INDEX_PATH}")


def _cmd_lint_backlog() -> None:
    """CLI wrapper for lint_backlog."""
    errors = lint_backlog(BACKLOG_PATH)
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        sys.exit(1)
    else:
        print("OK — backlog has no duplicate entries")


def _cmd_check_merge(branch: str) -> None:
    """Check if branch can be merged. Exits 1 if there's an active plan."""
    rc, msg = check_branch_active(branch)
    print(msg)
    sys.exit(rc)


def _cmd_check_pr(branch: str) -> None:
    """Check gate for GitHub Actions PRs. Uses ::error:: prefix on failure."""
    rc, msg = check_branch_active(branch)
    if rc != 0:
        print(f"::error::{msg}")
    else:
        print(msg)
    sys.exit(rc)


def _flip_status_in_file(path: Path, new_status: str) -> None:
    """Regex replace status: X in frontmatter."""
    text = path.read_text(encoding="utf-8")
    new_text = re.sub(r"^status:.*$", f"status: {new_status}", text, count=1, flags=re.MULTILINE)
    path.write_text(new_text, encoding="utf-8")


def _edit_frontmatter_related(path: Path, mutator) -> None:
    """Apply mutator to the file's `related` dict and rewrite the frontmatter block.

    mutator: Callable[[dict[str, Any]], dict[str, Any]] — receives the current
    related dict (empty dict if absent), returns the new related dict.

    Preserves all non-related frontmatter lines and the body verbatim. The
    `related:` block is fully rewritten using `key: value` for scalars and
    `key: [v1, v2]` for lists.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")

    if not lines or lines[0] != "---":
        return  # No frontmatter; nothing to edit
    fm_end = None
    for i in range(1, len(lines)):
        if lines[i] == "---":
            fm_end = i
            break
    if fm_end is None:
        return  # Malformed frontmatter

    related_start = None
    related_end = None
    for i in range(1, fm_end):
        if re.match(r"^related\s*:\s*$", lines[i]):
            related_start = i
            j = i + 1
            while j < fm_end:
                if lines[j].startswith("  ") or lines[j].strip() == "":
                    j += 1
                else:
                    break
            related_end = j
            break

    fm = parse_frontmatter(path) or {}
    current = fm.get("related")
    current_related: dict[str, Any] = current if isinstance(current, dict) else {}

    new_related = mutator(dict(current_related))

    if new_related:
        related_lines = ["related:"]
        for k, v in new_related.items():
            if isinstance(v, list):
                rendered = "[" + ", ".join(str(item) for item in v) + "]"
                related_lines.append(f"  {k}: {rendered}")
            else:
                related_lines.append(f"  {k}: {v}")
    else:
        related_lines = []

    if related_start is not None:
        new_lines = lines[:related_start] + related_lines + lines[related_end:]
    else:
        new_lines = lines[:fm_end] + related_lines + lines[fm_end:]

    path.write_text("\n".join(new_lines), encoding="utf-8")


def _set_related_scalar(path: Path, key: str, value: Any) -> None:
    """Set `related.<key>: <value>` in the file's frontmatter. Idempotent."""
    def mutator(d: dict[str, Any]) -> dict[str, Any]:
        d[key] = value
        return d
    _edit_frontmatter_related(path, mutator)


def _append_related_list(path: Path, key: str, value: int) -> None:
    """Append `value` to the list at `related.<key>`, deduplicated. Idempotent.

    Compares as strings since parsed values come back as strings.
    """
    def mutator(d: dict[str, Any]) -> dict[str, Any]:
        existing = d.get(key, [])
        if not isinstance(existing, list):
            existing = [existing] if existing else []
        if str(value) not in [str(x) for x in existing]:
            existing.append(value)
        d[key] = existing
        return d
    _edit_frontmatter_related(path, mutator)


def _find_active_plan_for_branch(branch: str) -> tuple[Path, dict[str, Any]] | None:
    """Find the one active plan for a branch. Returns (path, fm) or None."""
    all_plans = _collect_plans(PLANS_ROOT)
    for path, fm in all_plans:
        if fm.get("branch") == branch and fm.get("status") == "active":
            return path, fm
    return None


def _find_done_plans_for_branch(branch: str) -> list[tuple[Path, dict[str, Any]]]:
    """Return all plans whose branch matches and whose status is `done`."""
    all_plans = _collect_plans(PLANS_ROOT)
    return [
        (path, fm)
        for path, fm in all_plans
        if fm.get("branch") == branch and fm.get("status") == "done"
    ]


def _other_active_plans_reference_spec(plan_to_exclude: Path, spec_name: str) -> bool:
    """Check if any other active plan references the given spec."""
    all_plans = _collect_plans(PLANS_ROOT)
    for path, fm in all_plans:
        if path == plan_to_exclude:
            continue
        if fm.get("status") != "active":
            continue
        related = fm.get("related")
        if isinstance(related, dict) and related.get("spec") == spec_name:
            return True
    return False


def _finish_or_abandon(new_status: str) -> None:
    """Flip plan (and linked spec if full tier and not shared), regenerate index, git add."""
    branch = _current_branch()
    result = _find_active_plan_for_branch(branch)
    if result is None:
        print(f"ERROR: No active plan found for branch '{branch}'.")
        sys.exit(1)

    plan_path, fm = result
    tier = fm.get("tier", "lite")
    touched: list[Path] = [plan_path]

    # Flip the plan status
    _flip_status_in_file(plan_path, new_status)
    print(f"Updated {plan_path.name}: status -> {new_status}")

    # For full tier, also flip the spec if not shared
    if tier == "full":
        related = fm.get("related")
        if isinstance(related, dict) and "spec" in related:
            spec_name = related["spec"]
            spec_path = SPECS_ROOT / spec_name
            if spec_path.exists():
                if not _other_active_plans_reference_spec(plan_path, spec_name):
                    _flip_status_in_file(spec_path, new_status)
                    print(f"Updated {spec_path.name}: status -> {new_status}")
                    touched.append(spec_path)
                else:
                    print(f"Skipping spec {spec_name} — referenced by another active plan.")

    _regen_index()
    touched.append(INDEX_PATH)

    _git_add(touched)
    print(f"Done. Run `git commit` to finalize.")


def _cmd_finish() -> None:
    """Mark the active plan as done."""
    _finish_or_abandon("done")


def _cmd_abandon() -> None:
    """Mark the active plan as abandoned."""
    _finish_or_abandon("abandoned")


def _cmd_set_pr(pr: int, branch: str) -> None:
    """Backfill a PR number onto the done plan for `branch` and its linked spec.

    - Requires pr > 0.
    - Requires exactly one done plan on the branch.
    - Writes related.pr on the plan.
    - For full tier, appends to related.prs on the linked spec (if it exists on disk).
    - Regenerates INDEX.md and stages the touched files.
    """
    if pr <= 0:
        print(f"ERROR: --pr must be a positive integer, got {pr}.", file=sys.stderr)
        sys.exit(1)

    matches = _find_done_plans_for_branch(branch)
    if not matches:
        print(f"ERROR: No done plan found for branch '{branch}'.", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"ERROR: Multiple done plans on branch '{branch}' — refusing to ambiguously assign PR.", file=sys.stderr)
        for path, _ in matches:
            print(f"  - {path.name}", file=sys.stderr)
        sys.exit(1)

    plan_path, fm = matches[0]
    touched: list[Path] = []

    _set_related_scalar(plan_path, "pr", pr)
    print(f"Updated {plan_path.name}: related.pr -> {pr}")
    touched.append(plan_path)

    tier = fm.get("tier", "lite")
    if tier == "full":
        related = fm.get("related")
        if isinstance(related, dict) and "spec" in related:
            spec_name = related["spec"]
            spec_path = SPECS_ROOT / spec_name
            if spec_path.exists():
                _append_related_list(spec_path, "prs", pr)
                print(f"Updated {spec_path.name}: appended {pr} to related.prs")
                touched.append(spec_path)
            else:
                print(f"Skipping spec {spec_name} — file does not exist.")

    _regen_index()
    touched.append(INDEX_PATH)

    _git_add(touched)
    print(f"Done. Run `git commit` to finalize.")


def _cmd_start(title: str, tier: str) -> None:
    """Start a task: scaffold plan stub (+ spec stub for full tier),
    remove from backlog if the title matches an entry, regenerate index,
    git add touched files.
    """
    # Validate tier
    if tier not in ("lite", "full"):
        print(f"ERROR: Invalid tier '{tier}'. Must be 'lite' or 'full'.")
        sys.exit(1)

    # Look up the entry in the backlog if it exists. A missing file or
    # missing entry means this is an ad hoc task — fine, just skip the
    # removal step later.
    backlog_match = (
        BACKLOG_PATH.exists()
        and _find_backlog_entry(BACKLOG_PATH, title) is not None
    )
    if not backlog_match:
        print(f"No matching backlog entry for '{title}' — creating ad hoc task.")

    branch = _current_branch()

    existing = _find_active_plan_for_branch(branch)
    if existing is not None:
        plan_path, fm = existing
        print(f"ERROR: Branch '{branch}' already has an active plan: '{fm.get('summary', plan_path.stem)}'.")
        print("Finish or abandon the current task before starting a new one.")
        sys.exit(1)

    date = _today()
    slug = _slugify(title)
    touched: list[Path] = []

    # Scaffold spec stub (full tier only)
    spec_filename: str | None = None
    if tier == "full":
        spec_filename = f"{date}-{slug}-design.md"
        spec_path = SPECS_ROOT / spec_filename
        if spec_path.exists():
            print(f"ERROR: Spec file already exists: {spec_path}")
            sys.exit(1)
        SPECS_ROOT.mkdir(parents=True, exist_ok=True)
        spec_content = _SPEC_STUB.format(date=date, title=title)
        spec_path.write_text(spec_content, encoding="utf-8")
        print(f"Created {spec_path}")
        touched.append(spec_path)

    # Scaffold plan stub
    plan_filename = f"{date}-{slug}.md"
    plan_path = PLANS_ROOT / plan_filename
    if plan_path.exists():
        print(f"ERROR: Plan file already exists: {plan_path}")
        sys.exit(1)
    PLANS_ROOT.mkdir(parents=True, exist_ok=True)

    if tier == "full" and spec_filename:
        plan_content = _PLAN_STUB_FULL.format(
            date=date,
            title=title,
            branch=branch,
            spec_filename=spec_filename,
        )
    else:
        plan_content = _PLAN_STUB_LITE.format(date=date, title=title, branch=branch)

    plan_path.write_text(plan_content, encoding="utf-8")
    print(f"Created {plan_path}")
    touched.append(plan_path)

    # Remove from backlog only if we matched an entry
    if backlog_match:
        _remove_backlog_entry(BACKLOG_PATH, title)
        print(f"Removed '{title}' from backlog.")
        touched.append(BACKLOG_PATH)

    # Regenerate index
    _regen_index()
    touched.append(INDEX_PATH)

    # Git add all touched files
    _git_add(touched)
    print(f"Staged {len(touched)} file(s). Run `git commit` to finalize.")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Board lifecycle automation")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("lint-backlog", help="Check backlog for duplicate entries")

    start_p = sub.add_parser(
        "start",
        help="Start a task: scaffold stubs from a backlog entry or an ad hoc title",
    )
    start_p.add_argument(
        "title",
        help="Task title (matches a backlog entry if present, otherwise creates an ad hoc task)",
    )
    start_p.add_argument(
        "--tier",
        choices=["lite", "full"],
        default="lite",
        help="Plan tier: lite (plan only) or full (spec + plan)",
    )

    sub.add_parser("finish", help="Mark active plan as done")
    sub.add_parser("abandon", help="Mark active plan as abandoned")

    set_pr_p = sub.add_parser(
        "set-pr",
        help="Backfill a PR number onto the done plan for a branch (and its spec)",
    )
    set_pr_p.add_argument("--pr", type=int, required=True, help="GitHub PR number (positive int)")
    set_pr_p.add_argument("--branch", required=True, help="Branch name whose done plan to update")

    check_merge_p = sub.add_parser("check-merge", help="Gate for git merge")
    check_merge_p.add_argument("branch", help="Branch name to check")

    check_pr_p = sub.add_parser("check-pr", help="Gate for GitHub Actions PR check")
    check_pr_p.add_argument("branch", help="Branch name to check")

    args = parser.parse_args(argv)

    if args.command == "lint-backlog":
        _cmd_lint_backlog()
    elif args.command == "start":
        _cmd_start(args.title, args.tier)
    elif args.command == "finish":
        _cmd_finish()
    elif args.command == "abandon":
        _cmd_abandon()
    elif args.command == "set-pr":
        _cmd_set_pr(args.pr, args.branch)
    elif args.command == "check-merge":
        _cmd_check_merge(args.branch)
    elif args.command == "check-pr":
        _cmd_check_pr(args.branch)


if __name__ == "__main__":
    main()
