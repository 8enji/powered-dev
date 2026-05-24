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
