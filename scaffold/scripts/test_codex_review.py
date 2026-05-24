"""Tests for the codex_review helper."""
import pytest
from codex_review import parse_arguments, ParsedArgs


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
