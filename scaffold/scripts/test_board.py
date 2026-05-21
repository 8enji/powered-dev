"""Tests for board.py."""

from pathlib import Path

from board import (
    build_in_flight,
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


def test_build_in_flight_active(tmp_path):
    plans = tmp_path / "docs" / "superpowers" / "plans"
    _make_plan(plans, "Active Task", "active", "feature/active")
    _make_plan(plans, "Done Task", "done", "feature/done")
    result = build_in_flight(plans)
    assert "Active Task" in result
    assert "Done Task" not in result


def test_build_in_flight_empty(tmp_path):
    plans = tmp_path / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True)
    result = build_in_flight(plans)
    assert "_(none)_" in result


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
