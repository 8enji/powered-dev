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
