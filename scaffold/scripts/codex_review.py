"""Codex review orchestration helper.

Owns shared logic between PR mode and local-change mode for /request-codex-review:
state persistence, prompt assembly, schema validation, touched-files filtering,
severity histogram, event computation, and output rendering.

CLI entry points (`prepare` and `finish`) are invoked by the slash command.
Pure functions are exposed for direct testing.
"""
from __future__ import annotations

import json
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


def validate_findings_payload(text: str) -> tuple[dict | None, str | None]:
    """Parse and validate codex's last-message output.

    Returns (parsed_dict, None) on success, or (None, error_message) on failure.
    Failure modes mirror the previous shell `jq -e` check: not JSON, missing summary,
    non-string summary, non-array findings.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"output is not valid JSON: {e.msg}"

    if not isinstance(data, dict):
        return None, "output must be a JSON object"

    summary = data.get("summary")
    if not isinstance(summary, str):
        return None, "missing or non-string `summary` field"

    findings = data.get("findings")
    if not isinstance(findings, list):
        return None, "missing or non-array `findings` field"

    return data, None


def filter_findings(
    findings: list[dict], touched_files: list[str]
) -> tuple[list[dict], int]:
    """Drop findings whose `path` is not in the touched-files diff set.

    Returns (kept_findings, dropped_count). Mirrors the previous shell `jq` filter
    that compared each finding's path against the diff's --name-only output.
    """
    touched = set(touched_files)
    kept = [f for f in findings if f.get("path") in touched]
    dropped = len(findings) - len(kept)
    return kept, dropped


def compute_event(findings: list[dict]) -> str:
    """Decide the GitHub review event: REQUEST_CHANGES if any critical, else COMMENT."""
    for f in findings:
        if f.get("severity") == "critical":
            return "REQUEST_CHANGES"
    return "COMMENT"


def severity_histogram(findings: list[dict]) -> str:
    """Produce 'X critical · Y major · Z minor · W nit' summary string."""
    counts = {"critical": 0, "major": 0, "minor": 0, "nit": 0}
    for f in findings:
        sev = f.get("severity")
        if sev in counts:
            counts[sev] += 1
    return (
        f"{counts['critical']} critical · {counts['major']} major · "
        f"{counts['minor']} minor · {counts['nit']} nit"
    )


def render_local_report(
    *,
    review_id: str,
    event: str,
    dropped: int,
    summary: str,
    findings: list[dict],
    date: str,
) -> str:
    """Render the local-mode markdown report (with frontmatter)."""
    histo = severity_histogram(findings)
    lines = [
        "---",
        "status: done",
        "type: report",
        f"date: {date}",
        f"summary: Codex local review for {review_id}",
        "---",
        "",
        f"# Codex local review {review_id}",
        "",
        f"**Event:** {event}",
        "",
        f"**Findings:** {histo}",
        "",
        summary,
        "",
    ]
    if dropped > 0:
        lines.append(
            f"_Note: {dropped} finding(s) referenced files outside the local diff "
            "and were dropped._"
        )
        lines.append("")
    for f in findings:
        lines.append(f"## [{f['severity']}] {f['path']}:{f['line']}")
        lines.append("")
        lines.append(f["body"])
        lines.append("")
    return "\n".join(lines) + "\n"


def render_pr_review_body(
    *,
    model: str,
    reasoning: str,
    summary: str,
    histogram: str,
    dropped: int,
) -> str:
    """Render the body field for the GitHub PR review payload."""
    lines = [
        "## Codex review",
        "",
        f"_Generated by Codex via `/request-codex-review`. Model: {model}, Reasoning: {reasoning}._",
        "",
        summary,
        "",
        f"**Findings:** {histogram}",
    ]
    if dropped > 0:
        lines.append("")
        lines.append(
            f"_Note: {dropped} finding(s) referenced files outside the diff and were dropped._"
        )
    return "\n".join(lines)


def build_review_comments(findings: list[dict]) -> list[dict]:
    """Convert findings into GitHub PR review-comment payload items."""
    return [
        {
            "path": f["path"],
            "line": f["line"],
            "side": f["side"],
            "body": f"**[{f['severity']}]** {f['body']}",
        }
        for f in findings
    ]


_CONFIG_LINE_RE = re.compile(r'^([a-zA-Z_]+)\s*=\s*"?([^"]+?)"?\s*$')


def read_codex_config(path: Path) -> dict[str, str]:
    """Read `model` and `model_reasoning_effort` from ~/.codex/config.toml.

    Mirrors the previous shell `grep -E '...' | sed -E '...'` pipeline. Takes the
    first occurrence of each key so values inside `[profile.*]` sections don't
    shadow the top-level defaults. Missing file or keys → 'default'.
    """
    result = {"model": "default", "reasoning": "default"}
    if not path.exists():
        return result
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        m = _CONFIG_LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "model" and "model" not in seen:
            result["model"] = val
            seen.add("model")
        elif key == "model_reasoning_effort" and "reasoning" not in seen:
            result["reasoning"] = val
            seen.add("reasoning")
    return result


_METADATA_BLOCK_KEYS = {"Touched files", "Diffs available on disk"}


def render_prompt(
    *,
    mode: Literal["pr", "local"],
    metadata: dict[str, str],
    prompt_source: Path,
) -> str:
    """Build the rendered codex prompt: metadata header + static source body.

    `metadata` keys ending up as `## <key>` block headers (e.g. 'Touched files')
    are rendered as section blocks; everything else is a `- key: value` bullet.
    """
    heading = "## PR metadata" if mode == "pr" else "## Local review metadata"
    bullets: list[str] = []
    blocks: list[tuple[str, str]] = []
    for k, v in metadata.items():
        if k in _METADATA_BLOCK_KEYS:
            blocks.append((k, v))
        else:
            bullets.append(f"- {k}: {v}")
    parts = [heading, *bullets]
    for title, body in blocks:
        parts.extend(["", f"## {title}", body])
    parts.extend(["", prompt_source.read_text(encoding="utf-8")])
    return "\n".join(parts)


import subprocess


@dataclass(frozen=True)
class LocalEvidence:
    touched_files: list[str]
    base_ref: str  # empty string if no base ref was detected


_BASE_REF_CANDIDATES = ("origin/main", "origin/master", "main", "master")


def _run_git(repo: Path, args: list[str]) -> str:
    """Run git capturing stdout; return text (utf-8). Empty string on non-zero exit."""
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    return res.stdout if res.returncode == 0 else ""


def _detect_base_ref(repo: Path) -> str:
    for candidate in _BASE_REF_CANDIDATES:
        res = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", candidate],
            capture_output=True,
        )
        if res.returncode == 0:
            return candidate
    return ""


def collect_local_evidence(repo_root: Path, review_dir: Path) -> LocalEvidence:
    """Capture staged/unstaged/untracked/committed changes into the review directory.

    Writes these files into `review_dir`:
      - staged-files, unstaged-files, untracked-files, committed-files (newline-separated)
      - staged.diff, unstaged.diff, committed.diff (unified-diff text)

    Returns the sorted-unique union of touched files plus the detected base ref.
    """
    review_dir.mkdir(parents=True, exist_ok=True)

    staged = _run_git(repo_root, ["diff", "--cached", "--name-only"])
    unstaged = _run_git(repo_root, ["diff", "--no-ext-diff", "--name-only"])
    untracked = _run_git(repo_root, ["ls-files", "--others", "--exclude-standard"])
    staged_diff = _run_git(repo_root, ["diff", "--cached"])
    unstaged_diff = _run_git(repo_root, ["diff", "--no-ext-diff"])
    base_ref = _detect_base_ref(repo_root)
    if base_ref:
        committed = _run_git(repo_root, ["diff", "--name-only", f"{base_ref}...HEAD"])
        committed_diff = _run_git(repo_root, ["diff", f"{base_ref}...HEAD"])
    else:
        committed = ""
        committed_diff = ""

    (review_dir / "staged-files").write_text(staged, encoding="utf-8")
    (review_dir / "unstaged-files").write_text(unstaged, encoding="utf-8")
    (review_dir / "untracked-files").write_text(untracked, encoding="utf-8")
    (review_dir / "committed-files").write_text(committed, encoding="utf-8")
    (review_dir / "staged.diff").write_text(staged_diff, encoding="utf-8")
    (review_dir / "unstaged.diff").write_text(unstaged_diff, encoding="utf-8")
    (review_dir / "committed.diff").write_text(committed_diff, encoding="utf-8")

    touched: set[str] = set()
    for text in (staged, unstaged, untracked, committed):
        for line in text.splitlines():
            if line.strip():
                touched.add(line.strip())
    return LocalEvidence(touched_files=sorted(touched), base_ref=base_ref)


from typing import Callable

CommandRunner = Callable[[list[str]], tuple[str, int]]


@dataclass(frozen=True)
class PRMetadata:
    pr: str
    pr_url: str
    owner: str
    repo: str
    base: str
    head_sha: str
    title: str


def _default_runner(cmd: list[str]) -> tuple[str, int]:
    res = subprocess.run(cmd, capture_output=True, text=True)
    return (res.stdout, res.returncode)


_PR_FIELDS = "number,url,headRefOid,baseRefName,headRefName,isCrossRepository,title"


def _split_identifier(identifier: str) -> tuple[str, str, str] | None:
    """Return (owner, repo, pr) for `owner/repo#N` or GitHub URL; None otherwise."""
    m = re.match(r"^([^/\s]+)/([^/\s#]+)#(\d+)$", identifier)
    if m:
        return m.group(1), m.group(2), m.group(3)
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", identifier)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None


def resolve_pr_metadata(
    *,
    identifier: str | None,
    runner: CommandRunner = _default_runner,
) -> PRMetadata:
    """Resolve PR metadata via `gh`.

    identifier=None → current-branch mode (`gh pr view` with no args).
    identifier numeric → use current repo's owner/name (gh repo view).
    identifier `owner/repo#N` or URL → extract directly.

    Raises LookupError if `gh pr view` reports no PR.
    """
    if identifier is None:
        out, rc = runner(["gh", "pr", "view", "--json", _PR_FIELDS])
        if rc != 0:
            raise LookupError("No open PR for the current branch.")
        pr_data = json.loads(out)
        out2, rc2 = runner(["gh", "repo", "view", "--json", "owner,name"])
        if rc2 != 0:
            raise LookupError("Could not resolve current repository.")
        repo_data = json.loads(out2)
        owner = repo_data["owner"]["login"]
        repo = repo_data["name"]
    else:
        parts = _split_identifier(identifier)
        if parts is not None:
            owner, repo, pr_number = parts
            out, rc = runner(
                ["gh", "pr", "view", pr_number, "-R", f"{owner}/{repo}", "--json", _PR_FIELDS]
            )
            if rc != 0:
                raise LookupError(f"PR {identifier} not found.")
            pr_data = json.loads(out)
        elif identifier.isdigit():
            out, rc = runner(["gh", "repo", "view", "--json", "owner,name"])
            if rc != 0:
                raise LookupError("Could not resolve current repository.")
            repo_data = json.loads(out)
            owner = repo_data["owner"]["login"]
            repo = repo_data["name"]
            out2, rc2 = runner(
                ["gh", "pr", "view", identifier, "-R", f"{owner}/{repo}", "--json", _PR_FIELDS]
            )
            if rc2 != 0:
                raise LookupError(f"PR #{identifier} not found.")
            pr_data = json.loads(out2)
        else:
            raise ValueError(f"Unrecognized PR identifier: {identifier!r}")

    return PRMetadata(
        pr=str(pr_data["number"]),
        pr_url=pr_data["url"],
        owner=owner,
        repo=repo,
        base=pr_data["baseRefName"],
        head_sha=pr_data["headRefOid"],
        title=pr_data["title"],
    )


def setup_pr_worktree(invoking_repo: Path, worktree_path: Path, pr_sha_or_ref: str) -> None:
    """Create a git worktree at `worktree_path` checked out to the PR head.

    Removes any prior worktree at this path first. Caller is responsible for cleanup.
    `pr_sha_or_ref` can be a refspec name (e.g. `refs/remotes/origin/pr-123-head`) or SHA.
    """
    listing = _run_git(invoking_repo, ["worktree", "list", "--porcelain"])
    if f"worktree {worktree_path}" in listing:
        subprocess.run(
            ["git", "-C", str(invoking_repo), "worktree", "remove", "--force", str(worktree_path)],
            capture_output=True,
        )
    if worktree_path.exists():
        subprocess.run(["rm", "-rf", str(worktree_path)], capture_output=True)
    subprocess.run(
        ["git", "-C", str(invoking_repo), "worktree", "add", str(worktree_path), pr_sha_or_ref],
        check=True,
        capture_output=True,
    )


def cleanup_pr_worktree(invoking_repo: Path, worktree_path: Path) -> None:
    """Remove the worktree if it exists. Best-effort: failures are swallowed."""
    if not worktree_path.exists():
        return
    subprocess.run(
        ["git", "-C", str(invoking_repo), "worktree", "remove", "--force", str(worktree_path)],
        capture_output=True,
    )
    subprocess.run(["rm", "-rf", str(worktree_path)], capture_output=True)


def collect_pr_touched_files(repo: Path, base: str, review_dir: Path) -> list[str]:
    """Run `git diff origin/<base>...HEAD --name-only` and persist + return the list."""
    review_dir.mkdir(parents=True, exist_ok=True)
    out = _run_git(repo, ["diff", f"origin/{base}...HEAD", "--name-only"])
    # Fall back to local base (no `origin/` prefix) if the remote-tracking ref isn't there.
    if not out.strip():
        out = _run_git(repo, ["diff", f"{base}...HEAD", "--name-only"])
    touched = sorted({line.strip() for line in out.splitlines() if line.strip()})
    (review_dir / "touched-files").write_text("\n".join(touched) + ("\n" if touched else ""), encoding="utf-8")
    return touched
