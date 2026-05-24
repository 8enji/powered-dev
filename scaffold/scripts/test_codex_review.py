"""Tests for the codex_review helper."""
from pathlib import Path

import pytest
from codex_review import parse_arguments, ParsedArgs, review_paths, ReviewPaths


def test_parse_empty_on_main_is_local():
    parsed = parse_arguments("", current_branch="main")
    assert parsed.mode == "local"
    assert parsed.identifier is None
    assert parsed.focus == ""


def test_parse_empty_on_master_is_local():
    parsed = parse_arguments("", current_branch="master")
    assert parsed.mode == "local"


def test_parse_empty_on_head_is_local():
    parsed = parse_arguments("", current_branch="HEAD")
    assert parsed.mode == "local"


def test_parse_empty_on_feature_branch_is_pr_current():
    parsed = parse_arguments("", current_branch="feature/foo")
    assert parsed.mode == "pr-current"
    assert parsed.identifier is None
    assert parsed.focus == ""


def test_parse_local_keyword():
    parsed = parse_arguments("local", current_branch="feature/foo")
    assert parsed.mode == "local"
    assert parsed.focus == ""


def test_parse_local_keyword_with_focus():
    parsed = parse_arguments("local check error handling", current_branch="feature/foo")
    assert parsed.mode == "local"
    assert parsed.focus == "check error handling"


def test_parse_numeric_pr():
    parsed = parse_arguments("1234", current_branch="feature/foo")
    assert parsed.mode == "pr-explicit"
    assert parsed.identifier == "1234"


def test_parse_owner_repo_pr():
    parsed = parse_arguments("anthropics/powered-dev#42", current_branch="main")
    assert parsed.mode == "pr-explicit"
    assert parsed.identifier == "anthropics/powered-dev#42"


def test_parse_github_url():
    parsed = parse_arguments(
        "https://github.com/anthropics/powered-dev/pull/42",
        current_branch="main",
    )
    assert parsed.mode == "pr-explicit"
    assert parsed.identifier == "https://github.com/anthropics/powered-dev/pull/42"


def test_parse_non_pr_token_with_focus_is_local():
    parsed = parse_arguments("review the new auth code", current_branch="main")
    assert parsed.mode == "local"
    assert parsed.focus == "review the new auth code"


def test_parse_focus_carries_through_pr_mode():
    parsed = parse_arguments("1234 focus on the migration", current_branch="main")
    assert parsed.mode == "pr-explicit"
    assert parsed.identifier == "1234"
    assert parsed.focus == "focus on the migration"


def test_parse_tab_separated_args_splits_correctly():
    """Whitespace separator includes tab — matches the slash-command contract."""
    parsed = parse_arguments("1234\tfocus on auth", current_branch="main")
    assert parsed.mode == "pr-explicit"
    assert parsed.identifier == "1234"
    assert parsed.focus == "focus on auth"


def test_review_paths_pr_layout(tmp_path):
    paths = review_paths("pr", "123", tmp_root=tmp_path)
    assert paths.review_dir == tmp_path / "codex-review-pr-123"
    assert paths.state == paths.review_dir / "state.json"
    assert paths.prompt == paths.review_dir / "prompt.txt"
    assert paths.status == paths.review_dir / "status"
    assert paths.jsonl == paths.review_dir / "codex.jsonl"
    assert paths.last_message == paths.review_dir / "last-message.json"
    assert paths.touched_files == paths.review_dir / "touched-files"
    assert paths.event == paths.review_dir / "event"


def test_review_paths_local_layout(tmp_path):
    paths = review_paths("local", "20260524T120000Z-abc1234", tmp_root=tmp_path)
    assert paths.review_dir == tmp_path / "codex-review-local-20260524T120000Z-abc1234"
    assert paths.state == paths.review_dir / "state.json"


def test_review_paths_creates_directory(tmp_path):
    paths = review_paths("pr", "456", tmp_root=tmp_path, create=True)
    assert paths.review_dir.is_dir()


def test_review_paths_does_not_create_by_default(tmp_path):
    paths = review_paths("pr", "789", tmp_root=tmp_path)
    assert not paths.review_dir.exists()


def test_latest_pointer_path(tmp_path):
    paths = review_paths("pr", "123", tmp_root=tmp_path)
    assert paths.latest_pointer == tmp_path / "codex-review.latest"


from codex_review import validate_findings_payload


def test_validate_well_formed_payload():
    text = '{"summary": "Looks good", "findings": []}'
    parsed, err = validate_findings_payload(text)
    assert err is None
    assert parsed == {"summary": "Looks good", "findings": []}


def test_validate_payload_with_findings():
    text = (
        '{"summary": "Two issues", "findings": ['
        '{"path": "a.py", "line": 1, "side": "RIGHT", "severity": "minor", "body": "x"}'
        ']}'
    )
    parsed, err = validate_findings_payload(text)
    assert err is None
    assert len(parsed["findings"]) == 1


def test_validate_rejects_non_json():
    parsed, err = validate_findings_payload("not json at all")
    assert parsed is None
    assert err is not None
    assert "JSON" in err


def test_validate_rejects_missing_summary():
    parsed, err = validate_findings_payload('{"findings": []}')
    assert parsed is None
    assert "summary" in err


def test_validate_rejects_non_string_summary():
    parsed, err = validate_findings_payload('{"summary": 42, "findings": []}')
    assert parsed is None
    assert "summary" in err


def test_validate_rejects_non_array_findings():
    parsed, err = validate_findings_payload('{"summary": "x", "findings": "oops"}')
    assert parsed is None
    assert "findings" in err


from codex_review import filter_findings


def test_filter_keeps_findings_in_touched_set():
    findings = [
        {"path": "a.py", "line": 1, "side": "RIGHT", "severity": "minor", "body": "x"},
        {"path": "b.py", "line": 2, "side": "RIGHT", "severity": "major", "body": "y"},
    ]
    kept, dropped = filter_findings(findings, ["a.py", "b.py"])
    assert len(kept) == 2
    assert dropped == 0


def test_filter_drops_findings_outside_touched():
    findings = [
        {"path": "a.py", "line": 1, "side": "RIGHT", "severity": "minor", "body": "x"},
        {"path": "outside.py", "line": 2, "side": "RIGHT", "severity": "major", "body": "y"},
    ]
    kept, dropped = filter_findings(findings, ["a.py"])
    assert len(kept) == 1
    assert kept[0]["path"] == "a.py"
    assert dropped == 1


def test_filter_empty_findings():
    kept, dropped = filter_findings([], ["a.py"])
    assert kept == []
    assert dropped == 0


def test_filter_empty_touched_drops_everything():
    findings = [{"path": "a.py", "line": 1, "side": "RIGHT", "severity": "minor", "body": "x"}]
    kept, dropped = filter_findings(findings, [])
    assert kept == []
    assert dropped == 1


from codex_review import compute_event, severity_histogram


def test_event_critical_triggers_request_changes():
    findings = [
        {"path": "a.py", "line": 1, "side": "RIGHT", "severity": "minor", "body": "x"},
        {"path": "b.py", "line": 2, "side": "RIGHT", "severity": "critical", "body": "y"},
    ]
    assert compute_event(findings) == "REQUEST_CHANGES"


def test_event_no_critical_is_comment():
    findings = [
        {"path": "a.py", "line": 1, "side": "RIGHT", "severity": "minor", "body": "x"},
        {"path": "b.py", "line": 2, "side": "RIGHT", "severity": "major", "body": "y"},
    ]
    assert compute_event(findings) == "COMMENT"


def test_event_empty_findings_is_comment():
    assert compute_event([]) == "COMMENT"


def test_histogram_all_severities():
    findings = [
        {"severity": "critical"} | {"path": "a", "line": 1, "side": "RIGHT", "body": "x"},
        {"severity": "critical"} | {"path": "a", "line": 1, "side": "RIGHT", "body": "x"},
        {"severity": "major"}    | {"path": "a", "line": 1, "side": "RIGHT", "body": "x"},
        {"severity": "minor"}    | {"path": "a", "line": 1, "side": "RIGHT", "body": "x"},
        {"severity": "minor"}    | {"path": "a", "line": 1, "side": "RIGHT", "body": "x"},
        {"severity": "minor"}    | {"path": "a", "line": 1, "side": "RIGHT", "body": "x"},
        {"severity": "nit"}      | {"path": "a", "line": 1, "side": "RIGHT", "body": "x"},
    ]
    assert severity_histogram(findings) == "2 critical · 1 major · 3 minor · 1 nit"


def test_histogram_missing_severities_show_zero():
    findings = [
        {"severity": "minor"} | {"path": "a", "line": 1, "side": "RIGHT", "body": "x"},
    ]
    assert severity_histogram(findings) == "0 critical · 0 major · 1 minor · 0 nit"


def test_histogram_empty_findings():
    assert severity_histogram([]) == "0 critical · 0 major · 0 minor · 0 nit"


from codex_review import render_local_report


def test_render_local_report_includes_frontmatter_and_summary():
    report = render_local_report(
        review_id="20260524T120000Z-abc1234",
        event="COMMENT",
        dropped=0,
        summary="Found two minor issues.",
        findings=[],
        date="2026-05-24",
    )
    assert report.startswith("---\n")
    assert "status: done" in report
    assert "type: report" in report
    assert "date: 2026-05-24" in report
    assert "summary: Codex local review for 20260524T120000Z-abc1234" in report
    assert "# Codex local review 20260524T120000Z-abc1234" in report
    assert "**Event:** COMMENT" in report
    assert "Found two minor issues." in report


def test_render_local_report_with_findings():
    findings = [
        {"path": "a.py", "line": 10, "side": "RIGHT", "severity": "major", "body": "bug here"},
    ]
    report = render_local_report(
        review_id="rid",
        event="REQUEST_CHANGES",
        dropped=0,
        summary="One major.",
        findings=findings,
        date="2026-05-24",
    )
    assert "**Event:** REQUEST_CHANGES" in report
    assert "**Findings:** 0 critical · 1 major · 0 minor · 0 nit" in report
    assert "## [major] a.py:10" in report
    assert "bug here" in report


def test_render_local_report_notes_dropped_findings():
    report = render_local_report(
        review_id="rid",
        event="COMMENT",
        dropped=3,
        summary="x",
        findings=[],
        date="2026-05-24",
    )
    assert "3 finding(s) referenced files outside the local diff and were dropped" in report


from codex_review import render_pr_review_body, build_review_comments


def test_pr_review_body_includes_summary_and_histogram():
    body = render_pr_review_body(
        model="gpt-5",
        reasoning="high",
        summary="Two issues found.",
        histogram="0 critical · 1 major · 1 minor · 0 nit",
        dropped=0,
    )
    assert "## Codex review" in body
    assert "Model: gpt-5, Reasoning: high" in body
    assert "Two issues found." in body
    assert "**Findings:** 0 critical · 1 major · 1 minor · 0 nit" in body
    assert "dropped" not in body


def test_pr_review_body_notes_dropped():
    body = render_pr_review_body(
        model="gpt-5",
        reasoning="high",
        summary="x",
        histogram="0 critical · 0 major · 0 minor · 0 nit",
        dropped=2,
    )
    assert "2 finding(s) referenced files outside the diff and were dropped" in body


def test_pr_review_body_default_model_strings():
    body = render_pr_review_body(
        model="default",
        reasoning="default",
        summary="x",
        histogram="0 critical · 0 major · 0 minor · 0 nit",
        dropped=0,
    )
    assert "Model: default, Reasoning: default" in body


def test_build_review_comments_shape():
    findings = [
        {"path": "a.py", "line": 1, "side": "RIGHT", "severity": "major", "body": "bug"},
        {"path": "b.py", "line": 5, "side": "LEFT", "severity": "nit", "body": "style"},
    ]
    comments = build_review_comments(findings)
    assert comments == [
        {"path": "a.py", "line": 1, "side": "RIGHT", "body": "**[major]** bug"},
        {"path": "b.py", "line": 5, "side": "LEFT", "body": "**[nit]** style"},
    ]


def test_build_review_comments_empty():
    assert build_review_comments([]) == []


from codex_review import read_codex_config


def test_codex_config_reads_quoted_values(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'model = "gpt-5-codex"\n'
        'model_reasoning_effort = "high"\n'
        'other_key = "ignored"\n',
        encoding="utf-8",
    )
    out = read_codex_config(cfg)
    assert out == {"model": "gpt-5-codex", "reasoning": "high"}


def test_codex_config_reads_unquoted_values(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "model = gpt-5\n"
        "model_reasoning_effort = medium\n",
        encoding="utf-8",
    )
    out = read_codex_config(cfg)
    assert out == {"model": "gpt-5", "reasoning": "medium"}


def test_codex_config_missing_file_returns_defaults(tmp_path):
    out = read_codex_config(tmp_path / "nonexistent.toml")
    assert out == {"model": "default", "reasoning": "default"}


def test_codex_config_missing_keys_use_defaults(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('model = "gpt-5"\n', encoding="utf-8")
    out = read_codex_config(cfg)
    assert out == {"model": "gpt-5", "reasoning": "default"}


def test_codex_config_takes_first_match(tmp_path):
    """If a key appears twice (e.g. inside a [profile] section), take the first occurrence."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'model = "first"\n'
        "[profiles.alt]\n"
        'model = "second"\n',
        encoding="utf-8",
    )
    out = read_codex_config(cfg)
    assert out["model"] == "first"


from codex_review import render_prompt


def test_render_prompt_pr_mode(tmp_path):
    source = tmp_path / "review-prompt.md"
    source.write_text("## Static prompt\n\nReview the diff.\n", encoding="utf-8")
    rendered = render_prompt(
        mode="pr",
        metadata={
            "Title": "Add auth",
            "Base": "origin/main",
            "Head SHA": "abc123",
            "Focus (from invoker, may be empty)": "",
        },
        prompt_source=source,
    )
    assert rendered.startswith("## PR metadata")
    assert "- Title: Add auth" in rendered
    assert "- Base: origin/main" in rendered
    assert "- Head SHA: abc123" in rendered
    assert "- Focus (from invoker, may be empty): " in rendered
    assert "## Static prompt" in rendered
    assert "Review the diff." in rendered


def test_render_prompt_local_mode(tmp_path):
    source = tmp_path / "review-prompt.md"
    source.write_text("Static body.\n", encoding="utf-8")
    rendered = render_prompt(
        mode="local",
        metadata={
            "Review ID": "rid-123",
            "Base ref": "origin/main",
            "Head SHA": "abc",
            "Focus (from invoker, may be empty)": "auth code",
            "Touched files": "a.py\nb.py",
            "Diffs available on disk": (
                "- Staged diff: /tmp/codex-review-local-rid-123/staged.diff\n"
                "- Unstaged diff: /tmp/codex-review-local-rid-123/unstaged.diff"
            ),
        },
        prompt_source=source,
    )
    assert rendered.startswith("## Local review metadata")
    assert "- Review ID: rid-123" in rendered
    assert "- Focus (from invoker, may be empty): auth code" in rendered
    assert "## Touched files\na.py\nb.py" in rendered
    assert "## Diffs available on disk" in rendered
    assert "Static body." in rendered


def test_render_prompt_with_no_metadata_still_includes_source(tmp_path):
    source = tmp_path / "review-prompt.md"
    source.write_text("Body only.\n", encoding="utf-8")
    rendered = render_prompt(mode="pr", metadata={}, prompt_source=source)
    assert "Body only." in rendered


import subprocess
from codex_review import collect_local_evidence, LocalEvidence


def _init_repo(path):
    """Initialize a tiny git repo with one committed file on main."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@x"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], check=True)
    (path / "base.py").write_text("print('base')\n")
    subprocess.run(["git", "-C", str(path), "add", "base.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


def test_collect_local_evidence_finds_staged_and_unstaged(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    review_dir = tmp_path / "review"
    review_dir.mkdir()

    (repo / "staged.py").write_text("a\n")
    subprocess.run(["git", "-C", str(repo), "add", "staged.py"], check=True)
    (repo / "base.py").write_text("modified\n")
    (repo / "untracked.py").write_text("u\n")

    ev = collect_local_evidence(repo, review_dir)
    assert isinstance(ev, LocalEvidence)
    assert "staged.py" in ev.touched_files
    assert "base.py" in ev.touched_files
    assert "untracked.py" in ev.touched_files
    assert (review_dir / "staged.diff").exists()
    assert (review_dir / "unstaged.diff").exists()


def test_collect_local_evidence_returns_empty_when_clean(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    review_dir = tmp_path / "review"
    review_dir.mkdir()

    ev = collect_local_evidence(repo, review_dir)
    assert ev.touched_files == []


def test_collect_local_evidence_picks_base_ref(tmp_path):
    """Local-mode base ref preference: origin/main > origin/master > main > master."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    ev = collect_local_evidence(repo, review_dir)
    assert ev.base_ref == "main"


def test_collect_local_evidence_includes_committed_branch_changes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature"], check=True)
    (repo / "branch.py").write_text("b\n")
    subprocess.run(["git", "-C", str(repo), "add", "branch.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "feat"], check=True)

    ev = collect_local_evidence(repo, review_dir)
    assert "branch.py" in ev.touched_files
    assert (review_dir / "committed.diff").read_text().strip() != ""


import json
from codex_review import resolve_pr_metadata, PRMetadata


class _FakeRunner:
    """Records calls and returns canned (stdout, stderr, exit_code) per cmd list."""
    def __init__(self, responses):
        # responses: list of (pattern_list, (stdout, stderr, exit_code))
        # or for backward compat: (pattern_list, (stdout, exit_code)) — promote to ("", stderr=...)
        self.responses = []
        for pattern, response in responses:
            if len(response) == 2:
                self.responses.append((pattern, (response[0], "", response[1])))
            else:
                self.responses.append((pattern, response))
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        for pattern, response in self.responses:
            if all(p in cmd for p in pattern):
                return response
        return ("", "", 1)


def test_resolve_pr_current_branch_success():
    pr_json = {
        "number": 42,
        "url": "https://github.com/o/r/pull/42",
        "headRefOid": "abc",
        "baseRefName": "main",
        "headRefName": "feature",
        "isCrossRepository": False,
        "title": "Add thing",
    }
    repo_json = {"owner": {"login": "anthropics"}, "name": "powered-dev"}
    runner = _FakeRunner([
        (["gh", "pr", "view"], (json.dumps(pr_json), 0)),
        (["gh", "repo", "view"], (json.dumps(repo_json), 0)),
    ])
    meta = resolve_pr_metadata(identifier=None, runner=runner)
    assert isinstance(meta, PRMetadata)
    assert meta.pr == "42"
    assert meta.owner == "anthropics"
    assert meta.repo == "powered-dev"
    assert meta.base == "main"
    assert meta.head_sha == "abc"
    assert meta.title == "Add thing"


def test_resolve_pr_explicit_numeric():
    pr_json = {
        "number": 1234,
        "url": "https://github.com/o/r/pull/1234",
        "headRefOid": "deadbeef",
        "baseRefName": "main",
        "headRefName": "topic",
        "isCrossRepository": False,
        "title": "x",
    }
    repo_json = {"owner": {"login": "o"}, "name": "r"}
    runner = _FakeRunner([
        (["gh", "repo", "view"], (json.dumps(repo_json), 0)),
        (["gh", "pr", "view", "1234"], (json.dumps(pr_json), 0)),
    ])
    meta = resolve_pr_metadata(identifier="1234", runner=runner)
    assert meta.pr == "1234"
    assert meta.head_sha == "deadbeef"


def test_resolve_pr_explicit_url_extracts_owner_repo_pr():
    pr_json = {
        "number": 99,
        "url": "https://github.com/foo/bar/pull/99",
        "headRefOid": "f00",
        "baseRefName": "main",
        "headRefName": "x",
        "isCrossRepository": False,
        "title": "t",
    }
    runner = _FakeRunner([
        (["gh", "pr", "view", "99", "-R", "foo/bar"], (json.dumps(pr_json), 0)),
    ])
    meta = resolve_pr_metadata(
        identifier="https://github.com/foo/bar/pull/99",
        runner=runner,
    )
    assert meta.owner == "foo"
    assert meta.repo == "bar"
    assert meta.pr == "99"


def test_resolve_pr_owner_repo_hash_form():
    pr_json = {
        "number": 7,
        "url": "https://github.com/o/r/pull/7",
        "headRefOid": "abc",
        "baseRefName": "main",
        "headRefName": "x",
        "isCrossRepository": False,
        "title": "t",
    }
    runner = _FakeRunner([
        (["gh", "pr", "view", "7", "-R", "o/r"], (json.dumps(pr_json), 0)),
    ])
    meta = resolve_pr_metadata(identifier="o/r#7", runner=runner)
    assert meta.owner == "o"
    assert meta.repo == "r"
    assert meta.pr == "7"


def test_resolve_pr_no_pr_on_current_branch_raises():
    runner = _FakeRunner([(["gh", "pr", "view"], ("", 1))])
    with pytest.raises(LookupError):
        resolve_pr_metadata(identifier=None, runner=runner)


def test_resolve_pr_no_pr_branch_raises_specific_subclass():
    """gh stderr signal "no pull requests found" surfaces as NoPRForBranchError, a subclass."""
    from codex_review import NoPRForBranchError
    runner = _FakeRunner([
        (["gh", "pr", "view"], ("", "no pull requests found for branch \"feature\"\n", 1)),
    ])
    with pytest.raises(NoPRForBranchError):
        resolve_pr_metadata(identifier=None, runner=runner)
    # And it's still catchable as LookupError for backward compat:
    runner2 = _FakeRunner([
        (["gh", "pr", "view"], ("", "no pull requests found for branch \"x\"\n", 1)),
    ])
    with pytest.raises(LookupError):
        resolve_pr_metadata(identifier=None, runner=runner2)


def test_resolve_pr_auth_failure_is_generic_lookup_error():
    """Auth/network errors surface as plain LookupError, NOT NoPRForBranchError."""
    from codex_review import NoPRForBranchError
    runner = _FakeRunner([
        (["gh", "pr", "view"], ("", "authentication required: run 'gh auth login'\n", 4)),
    ])
    with pytest.raises(LookupError) as exc_info:
        resolve_pr_metadata(identifier=None, runner=runner)
    assert not isinstance(exc_info.value, NoPRForBranchError)
    assert "authentication required" in str(exc_info.value)


from codex_review import setup_pr_worktree, collect_pr_touched_files


def test_setup_pr_worktree_creates_dir(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "pr-source"], check=True)
    (repo / "pr.py").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "pr.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "pr"], check=True)
    pr_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "main"], check=True)

    wt = tmp_path / "worktree"
    setup_pr_worktree(repo, wt, pr_sha)
    assert (wt / "pr.py").exists()


def test_collect_pr_touched_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature"], check=True)
    (repo / "added.py").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "added.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "feat"], check=True)

    review_dir = tmp_path / "review"
    review_dir.mkdir()
    touched = collect_pr_touched_files(repo, "main", review_dir)
    assert "added.py" in touched
    assert (review_dir / "touched-files").read_text().strip() == "added.py"


import os
import sys
from codex_review import main as codex_main


def test_prepare_local_mode_writes_state_and_prompt(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "new.py").write_text("x\n")
    # Provide minimal prompt source + schema so prepare can resolve them.
    prompt_source = tmp_path / "review-prompt.md"
    prompt_source.write_text("body\n", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")

    monkeypatch.chdir(repo)
    monkeypatch.setenv("CODEX_REVIEW_TMP_ROOT", str(tmp_path / "tmp"))
    monkeypatch.setenv("CODEX_REVIEW_PROMPT_SOURCE", str(prompt_source))
    monkeypatch.setenv("CODEX_REVIEW_SCHEMA_PATH", str(schema))

    rc = codex_main(["prepare", ""])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    review_dir = Path(out)
    assert review_dir.is_dir()
    assert (review_dir / "state.json").exists()
    assert (review_dir / "prompt.txt").exists()
    state = json.loads((review_dir / "state.json").read_text())
    assert state["mode"] == "local"
    latest = (tmp_path / "tmp" / "codex-review.latest").read_text().strip()
    assert latest == str(review_dir)


def test_prepare_local_exits_nonzero_on_no_changes(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    prompt_source = tmp_path / "review-prompt.md"
    prompt_source.write_text("body\n", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")

    monkeypatch.chdir(repo)
    monkeypatch.setenv("CODEX_REVIEW_TMP_ROOT", str(tmp_path / "tmp"))
    monkeypatch.setenv("CODEX_REVIEW_PROMPT_SOURCE", str(prompt_source))
    monkeypatch.setenv("CODEX_REVIEW_SCHEMA_PATH", str(schema))

    rc = codex_main(["prepare", ""])
    assert rc != 0
    err = capsys.readouterr().err
    assert "No local changes" in err


def test_prepare_clears_stale_review_dir(tmp_path, monkeypatch):
    """A stale file from a prior run for the same key must not leak into the new run."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "new.py").write_text("x\n")
    prompt_source = tmp_path / "review-prompt.md"
    prompt_source.write_text("body\n", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")

    # Freeze the timestamp so the review_id is deterministic across both calls.
    from datetime import datetime, timezone
    fixed = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)

    class _FixedDT:
        @staticmethod
        def now(tz=None):
            return fixed

    monkeypatch.setattr("codex_review.datetime", _FixedDT)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CODEX_REVIEW_TMP_ROOT", str(tmp_path / "tmp"))
    monkeypatch.setenv("CODEX_REVIEW_PROMPT_SOURCE", str(prompt_source))
    monkeypatch.setenv("CODEX_REVIEW_SCHEMA_PATH", str(schema))

    rc = codex_main(["prepare", ""])
    assert rc == 0
    review_dir = Path((tmp_path / "tmp" / "codex-review.latest").read_text().strip())
    stale = review_dir / "stale-file"
    stale.write_text("old data", encoding="utf-8")
    assert stale.exists()

    rc2 = codex_main(["prepare", ""])
    assert rc2 == 0
    assert not stale.exists()  # prior run's leftover got wiped


def test_prepare_falls_back_to_local_on_no_pr_for_branch(tmp_path, monkeypatch):
    """Feature branch + empty args + no PR → local mode fallback (invariant #1)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    # Move off main onto a feature branch with at least one local change.
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-q", "-b", "feature/foo"], check=True
    )
    (repo / "new.py").write_text("x\n")
    prompt_source = tmp_path / "review-prompt.md"
    prompt_source.write_text("body\n", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")

    # Patch _default_runner to simulate gh reporting "no PR for branch".
    def fake_runner(cmd):
        if cmd[:3] == ["gh", "pr", "view"]:
            return ("", "no pull requests found for branch \"feature/foo\"\n", 1)
        return ("", "", 1)
    monkeypatch.setattr("codex_review._default_runner", fake_runner)

    monkeypatch.chdir(repo)
    monkeypatch.setenv("CODEX_REVIEW_TMP_ROOT", str(tmp_path / "tmp"))
    monkeypatch.setenv("CODEX_REVIEW_PROMPT_SOURCE", str(prompt_source))
    monkeypatch.setenv("CODEX_REVIEW_SCHEMA_PATH", str(schema))

    rc = codex_main(["prepare", ""])
    assert rc == 0
    review_dir = Path((tmp_path / "tmp" / "codex-review.latest").read_text().strip())
    state = json.loads((review_dir / "state.json").read_text())
    assert state["mode"] == "local"


def test_prepare_returns_error_on_gh_auth_failure(tmp_path, monkeypatch, capsys):
    """Auth failure (not no-PR) surfaces an error, does NOT fall back to local."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-q", "-b", "feature/foo"], check=True
    )
    (repo / "new.py").write_text("x\n")
    prompt_source = tmp_path / "review-prompt.md"
    prompt_source.write_text("body\n", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")

    def fake_runner(cmd):
        if cmd[:3] == ["gh", "pr", "view"]:
            return ("", "authentication required: run 'gh auth login'\n", 4)
        return ("", "", 1)
    monkeypatch.setattr("codex_review._default_runner", fake_runner)

    monkeypatch.chdir(repo)
    monkeypatch.setenv("CODEX_REVIEW_TMP_ROOT", str(tmp_path / "tmp"))
    monkeypatch.setenv("CODEX_REVIEW_PROMPT_SOURCE", str(prompt_source))
    monkeypatch.setenv("CODEX_REVIEW_SCHEMA_PATH", str(schema))

    rc = codex_main(["prepare", ""])
    assert rc == 2
    err = capsys.readouterr().err
    assert "authentication required" in err.lower() or "gh pr view" in err.lower()


def test_finish_local_writes_report(tmp_path, monkeypatch, capsys):
    """Simulate a successful local codex run and verify the report is written."""
    review_dir = tmp_path / "tmp" / "codex-review-local-test"
    review_dir.mkdir(parents=True)
    review_id = "test-review-id"
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "scripts").mkdir()
    # Stub docs_index.py so the post-write hook doesn't fail.
    (repo / "scripts" / "docs_index.py").write_text(
        "import sys\nif __name__ == '__main__': sys.exit(0)\n",
        encoding="utf-8",
    )

    (review_dir / "state.json").write_text(json.dumps({
        "mode": "local",
        "review_id": review_id,
        "review_root": str(repo),
        "base_ref": "main",
        "report_path": f"docs/superpowers/reports/codex-review-{review_id}.md",
        "schema_path": "",
        "focus": "",
    }))
    (review_dir / "touched-files").write_text("a.py\n", encoding="utf-8")
    (review_dir / "last-message.json").write_text(json.dumps({
        "summary": "All good with one minor.",
        "findings": [
            {"path": "a.py", "line": 1, "side": "RIGHT", "severity": "minor", "body": "x"},
        ],
    }))
    (review_dir / "status").write_text("__CODEX_EXIT__=0\n", encoding="utf-8")
    (tmp_path / "tmp" / "codex-review.latest").write_text(str(review_dir), encoding="utf-8")

    monkeypatch.chdir(repo)
    monkeypatch.setenv("CODEX_REVIEW_TMP_ROOT", str(tmp_path / "tmp"))
    rc = codex_main(["finish"])
    assert rc == 0
    report = repo / "docs" / "superpowers" / "reports" / f"codex-review-{review_id}.md"
    assert report.exists()
    body = report.read_text()
    assert "All good with one minor." in body
    assert "## [minor] a.py:1" in body


def test_finish_local_codex_nonzero_exits_with_error(tmp_path, monkeypatch, capsys):
    review_dir = tmp_path / "tmp" / "codex-review-local-fail"
    review_dir.mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (review_dir / "state.json").write_text(json.dumps({
        "mode": "local", "review_id": "x", "review_root": str(repo),
        "base_ref": "", "report_path": "", "schema_path": "", "focus": "",
    }))
    (review_dir / "status").write_text("__CODEX_EXIT__=1\n", encoding="utf-8")
    (review_dir / "codex.jsonl").write_text("some error output\n", encoding="utf-8")
    (tmp_path / "tmp" / "codex-review.latest").write_text(str(review_dir), encoding="utf-8")

    monkeypatch.chdir(repo)
    monkeypatch.setenv("CODEX_REVIEW_TMP_ROOT", str(tmp_path / "tmp"))
    rc = codex_main(["finish"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "exit code 1" in err.lower() or "exit code: 1" in err.lower()


def test_finish_local_degraded_json_writes_raw(tmp_path, monkeypatch):
    review_dir = tmp_path / "tmp" / "codex-review-local-bad"
    review_dir.mkdir(parents=True)
    review_id = "bad-id"
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "docs_index.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    (review_dir / "state.json").write_text(json.dumps({
        "mode": "local", "review_id": review_id, "review_root": str(repo),
        "base_ref": "", "report_path": f"docs/superpowers/reports/codex-review-{review_id}.md",
        "schema_path": "", "focus": "",
    }))
    (review_dir / "touched-files").write_text("a.py\n", encoding="utf-8")
    (review_dir / "last-message.json").write_text("not json at all", encoding="utf-8")
    (review_dir / "status").write_text("__CODEX_EXIT__=0\n", encoding="utf-8")
    (tmp_path / "tmp" / "codex-review.latest").write_text(str(review_dir), encoding="utf-8")

    monkeypatch.chdir(repo)
    monkeypatch.setenv("CODEX_REVIEW_TMP_ROOT", str(tmp_path / "tmp"))
    rc = codex_main(["finish"])
    assert rc == 0
    report = repo / "docs" / "superpowers" / "reports" / f"codex-review-{review_id}.md"
    body = report.read_text()
    assert "did not produce schema-conforming JSON" in body
    assert "not json at all" in body


def test_finish_pr_submits_review(tmp_path, monkeypatch):
    review_dir = tmp_path / "tmp" / "codex-review-pr-42"
    review_dir.mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (review_dir / "state.json").write_text(json.dumps({
        "mode": "pr", "pr": "42",
        "pr_url": "https://github.com/o/r/pull/42",
        "owner": "o", "repo": "r", "base": "main",
        "head_sha": "abc123", "title": "T",
        "review_root": str(repo), "worktree_path": "",
        "invoking_repo": str(repo), "schema_path": "", "focus": "",
    }))
    (review_dir / "touched-files").write_text("a.py\n", encoding="utf-8")
    (review_dir / "last-message.json").write_text(json.dumps({
        "summary": "Looks fine.",
        "findings": [
            {"path": "a.py", "line": 3, "side": "RIGHT", "severity": "major", "body": "fix me"},
        ],
    }))
    (review_dir / "status").write_text("__CODEX_EXIT__=0\n", encoding="utf-8")
    (tmp_path / "tmp" / "codex-review.latest").write_text(str(review_dir), encoding="utf-8")

    captured = {}
    def fake_runner(cmd):
        if cmd[:3] == ["gh", "api", "-X"]:
            input_idx = cmd.index("--input") + 1
            captured["payload"] = json.loads(Path(cmd[input_idx]).read_text())
            return (json.dumps({"html_url": "https://github.com/o/r/pull/42#review-1"}), "", 0)
        return ("", "", 0)

    monkeypatch.setattr("codex_review._default_runner", fake_runner)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CODEX_REVIEW_TMP_ROOT", str(tmp_path / "tmp"))
    rc = codex_main(["finish"])
    assert rc == 0
    assert captured["payload"]["event"] == "COMMENT"
    assert "Looks fine." in captured["payload"]["body"]
    assert captured["payload"]["commit_id"] == "abc123"
    assert len(captured["payload"]["comments"]) == 1
    assert captured["payload"]["comments"][0]["body"].startswith("**[major]**")


def test_finish_pr_critical_triggers_request_changes(tmp_path, monkeypatch):
    review_dir = tmp_path / "tmp" / "codex-review-pr-43"
    review_dir.mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (review_dir / "state.json").write_text(json.dumps({
        "mode": "pr", "pr": "43",
        "pr_url": "https://github.com/o/r/pull/43",
        "owner": "o", "repo": "r", "base": "main",
        "head_sha": "abc", "title": "T",
        "review_root": str(repo), "worktree_path": "",
        "invoking_repo": str(repo), "schema_path": "", "focus": "",
    }))
    (review_dir / "touched-files").write_text("a.py\n", encoding="utf-8")
    (review_dir / "last-message.json").write_text(json.dumps({
        "summary": "Critical issue.",
        "findings": [
            {"path": "a.py", "line": 1, "side": "RIGHT", "severity": "critical", "body": "boom"},
        ],
    }))
    (review_dir / "status").write_text("__CODEX_EXIT__=0\n", encoding="utf-8")
    (tmp_path / "tmp" / "codex-review.latest").write_text(str(review_dir), encoding="utf-8")

    captured = {}
    def fake_runner(cmd):
        if cmd[:3] == ["gh", "api", "-X"]:
            input_idx = cmd.index("--input") + 1
            captured["payload"] = json.loads(Path(cmd[input_idx]).read_text())
            return (json.dumps({"html_url": "u"}), "", 0)
        return ("", "", 0)
    monkeypatch.setattr("codex_review._default_runner", fake_runner)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CODEX_REVIEW_TMP_ROOT", str(tmp_path / "tmp"))
    rc = codex_main(["finish"])
    assert rc == 0
    assert captured["payload"]["event"] == "REQUEST_CHANGES"


def test_finish_pr_422_retries_body_only(tmp_path, monkeypatch):
    review_dir = tmp_path / "tmp" / "codex-review-pr-44"
    review_dir.mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (review_dir / "state.json").write_text(json.dumps({
        "mode": "pr", "pr": "44",
        "pr_url": "u", "owner": "o", "repo": "r", "base": "main",
        "head_sha": "abc", "title": "T",
        "review_root": str(repo), "worktree_path": "",
        "invoking_repo": str(repo), "schema_path": "", "focus": "",
    }))
    (review_dir / "touched-files").write_text("a.py\n", encoding="utf-8")
    (review_dir / "last-message.json").write_text(json.dumps({
        "summary": "x",
        "findings": [
            {"path": "a.py", "line": 1, "side": "RIGHT", "severity": "minor", "body": "y"},
        ],
    }))
    (review_dir / "status").write_text("__CODEX_EXIT__=0\n", encoding="utf-8")
    (tmp_path / "tmp" / "codex-review.latest").write_text(str(review_dir), encoding="utf-8")

    calls = []
    def fake_runner(cmd):
        if cmd[:3] == ["gh", "api", "-X"]:
            input_idx = cmd.index("--input") + 1
            payload = json.loads(Path(cmd[input_idx]).read_text())
            calls.append(payload)
            if len(calls) == 1:
                # First attempt: simulate gh emitting a 422 to stderr.
                return ("", "HTTP 422: Unprocessable Entity (comments)", 1)
            return (json.dumps({"html_url": "u"}), "", 0)
        return ("", "", 0)
    monkeypatch.setattr("codex_review._default_runner", fake_runner)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CODEX_REVIEW_TMP_ROOT", str(tmp_path / "tmp"))
    rc = codex_main(["finish"])
    assert rc == 0
    assert len(calls) == 2
    # Second call must be body-only with event=COMMENT.
    assert calls[1]["comments"] == []
    assert calls[1]["event"] == "COMMENT"


def test_end_to_end_local_review(tmp_path, monkeypatch):
    """prepare → write fake codex output → finish → report exists."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "docs_index.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    (repo / "feature.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    prompt_source = tmp_path / "review-prompt.md"
    prompt_source.write_text("body\n", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")

    monkeypatch.chdir(repo)
    monkeypatch.setenv("CODEX_REVIEW_TMP_ROOT", str(tmp_path / "tmp"))
    monkeypatch.setenv("CODEX_REVIEW_PROMPT_SOURCE", str(prompt_source))
    monkeypatch.setenv("CODEX_REVIEW_SCHEMA_PATH", str(schema))

    # 1. prepare
    rc = codex_main(["prepare", ""])
    assert rc == 0
    review_dir = Path((tmp_path / "tmp" / "codex-review.latest").read_text().strip())
    assert (review_dir / "state.json").exists()
    assert (review_dir / "prompt.txt").exists()

    # 2. Simulate codex writing its output.
    (review_dir / "last-message.json").write_text(json.dumps({
        "summary": "Smoke test summary.",
        "findings": [
            {"path": "feature.py", "line": 1, "side": "RIGHT",
             "severity": "minor", "body": "consider a docstring"},
        ],
    }), encoding="utf-8")
    (review_dir / "status").write_text("__CODEX_EXIT__=0\n", encoding="utf-8")

    # 3. finish
    rc2 = codex_main(["finish"])
    assert rc2 == 0
    state = json.loads((review_dir / "state.json").read_text())
    report = repo / state["report_path"]
    assert report.exists()
    body = report.read_text()
    assert "Smoke test summary." in body
    assert "## [minor] feature.py:1" in body
    assert "**Findings:** 0 critical · 0 major · 1 minor · 0 nit" in body
