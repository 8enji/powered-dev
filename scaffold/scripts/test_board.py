"""Tests for board.py."""

from pathlib import Path
from unittest import mock

import board
from board import (
    check_branch_active,
    lint_backlog,
)


def _make_plan(plans_dir: Path, name: str, status: str, branch: str, tier: str = "lite", spec: str | None = None) -> Path:
    plans_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nstatus: {status}\ntype: plan\ndate: 2026-05-21\nsummary: {name}\nbranch: {branch}\ntier: {tier}\n"
    if spec:
        content += f"related:\n  spec: {spec}\n"
    content += "---\n\n# Plan\n"
    p = plans_dir / f"2026-05-21-{name.lower().replace(' ', '-')}.md"
    p.write_text(content)
    return p


def _make_backlog(board_dir: Path, entries: list[str]) -> Path:
    board_dir.mkdir(parents=True, exist_ok=True)
    content = "\n".join(f"## {e}\n\nNotes for {e}.\n" for e in entries)
    p = board_dir / "backlog.md"
    p.write_text(content)
    return p


def test_lint_backlog_unique(tmp_path):
    board = tmp_path / "docs" / "board"
    _make_backlog(board, ["Task A", "Task B"])
    errors = lint_backlog(board / "backlog.md")
    assert errors == []


def test_lint_backlog_duplicate(tmp_path):
    board = tmp_path / "docs" / "board"
    _make_backlog(board, ["Task A", "Task A"])
    errors = lint_backlog(board / "backlog.md")
    assert len(errors) == 1
    assert "duplicate" in errors[0]


def test_check_branch_active_blocks(tmp_path):
    plans = tmp_path / "docs" / "superpowers" / "plans"
    _make_plan(plans, "WIP", "active", "feature/wip")
    rc, msg = check_branch_active("feature/wip", plans_root=plans)
    assert rc == 1
    assert "active" in msg.lower()


def test_check_branch_active_passes(tmp_path):
    plans = tmp_path / "docs" / "superpowers" / "plans"
    _make_plan(plans, "Done", "done", "feature/done")
    rc, _ = check_branch_active("feature/done", plans_root=plans)
    assert rc == 0


def test_check_branch_no_match(tmp_path):
    plans = tmp_path / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True)
    rc, _ = check_branch_active("feature/nonexistent", plans_root=plans)
    assert rc == 0


def test_start_rejects_duplicate_active_plan(tmp_path):
    """_cmd_start should exit(1) if the branch already has an active plan."""
    plans = tmp_path / "plans"
    _make_plan(plans, "Existing", "active", "feature/dup")

    backlog = tmp_path / "board" / "backlog.md"
    backlog.parent.mkdir(parents=True)
    backlog.write_text("## New Task\n\nSome notes.\n")

    with (
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "BACKLOG_PATH", backlog),
        mock.patch.object(board, "BOARD_ROOT", tmp_path / "board"),
        mock.patch.object(board, "_current_branch", return_value="feature/dup"),
    ):
        import pytest
        with pytest.raises(SystemExit) as exc_info:
            board._cmd_start("New Task", "lite")
        assert exc_info.value.code == 1


def test_start_stages_backlog_plan_and_index_without_in_flight(tmp_path):
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    backlog = tmp_path / "docs" / "board" / "backlog.md"
    backlog.parent.mkdir(parents=True)
    backlog.write_text("## New Task\n\nSome notes.\n")
    in_flight = tmp_path / "docs" / "board" / "in-flight.md"

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "BACKLOG_PATH", backlog),
        mock.patch.object(board, "BOARD_ROOT", backlog.parent),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "IN_FLIGHT_PATH", in_flight, create=True),
        mock.patch.object(board, "_current_branch", return_value="feature/new"),
        mock.patch.object(board, "_today", return_value="2026-05-21"),
        mock.patch.object(board, "_git_add") as git_add,
    ):
        board._cmd_start("New Task", "lite")

    staged = git_add.call_args.args[0]
    assert backlog in staged
    assert plans / "2026-05-21-new-task.md" in staged
    assert index in staged
    assert in_flight not in staged
    assert not in_flight.exists()


def test_finish_stages_plan_and_index_without_in_flight(tmp_path):
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    index = docs / "INDEX.md"
    plan = _make_plan(plans, "Active Task", "active", "feature/active")
    in_flight = tmp_path / "docs" / "board" / "in-flight.md"

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "BOARD_ROOT", in_flight.parent),
        mock.patch.object(board, "IN_FLIGHT_PATH", in_flight, create=True),
        mock.patch.object(board, "_current_branch", return_value="feature/active"),
        mock.patch.object(board, "_git_add") as git_add,
    ):
        board._cmd_finish()

    staged = git_add.call_args.args[0]
    assert plan in staged
    assert index in staged
    assert in_flight not in staged
    assert not in_flight.exists()
