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
        mock.patch.object(board, "INDEX_PATH", index),
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
        mock.patch.object(board, "_current_branch", return_value="feature/active"),
        mock.patch.object(board, "_git_add") as git_add,
    ):
        board._cmd_finish()

    staged = git_add.call_args.args[0]
    assert plan in staged
    assert index in staged
    assert in_flight not in staged
    assert not in_flight.exists()


def test_board_module_has_no_in_flight_symbols():
    """Negative covenant: in-flight artifact and its helpers are fully removed."""
    for name in ("IN_FLIGHT_PATH", "AUTO_HEADER", "build_in_flight", "_fmt_inflight_entry"):
        assert not hasattr(board, name), f"board.{name} should be removed"


def test_start_creates_ad_hoc_when_title_absent_from_backlog(tmp_path):
    """Ad hoc lite: title arg is not in the backlog. Backlog untouched, plan scaffolded."""
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    backlog = tmp_path / "docs" / "board" / "backlog.md"
    backlog.parent.mkdir(parents=True)
    backlog.write_text("## Other Task\n\nSome notes.\n")

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "BACKLOG_PATH", backlog),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_current_branch", return_value="feature/adhoc"),
        mock.patch.object(board, "_today", return_value="2026-05-23"),
        mock.patch.object(board, "_git_add") as git_add,
    ):
        board._cmd_start("Ad Hoc Task", "lite")

    staged = git_add.call_args.args[0]
    assert plans / "2026-05-23-ad-hoc-task.md" in staged
    assert index in staged
    assert backlog not in staged
    assert backlog.read_text() == "## Other Task\n\nSome notes.\n"


def test_start_creates_ad_hoc_when_backlog_file_missing(tmp_path):
    """Ad hoc lite: backlog file does not exist. Scaffold plan without erroring."""
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    backlog = tmp_path / "docs" / "board" / "backlog.md"
    # Intentionally do NOT create backlog file or its parent dir

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "BACKLOG_PATH", backlog),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_current_branch", return_value="feature/adhoc"),
        mock.patch.object(board, "_today", return_value="2026-05-23"),
        mock.patch.object(board, "_git_add") as git_add,
    ):
        board._cmd_start("Ad Hoc Task", "lite")

    staged = git_add.call_args.args[0]
    assert plans / "2026-05-23-ad-hoc-task.md" in staged
    assert index in staged
    assert backlog not in staged
    assert not backlog.exists()


def test_start_full_tier_ad_hoc_creates_spec_and_plan(tmp_path):
    """Ad hoc full tier: spec and plan both scaffolded, backlog untouched."""
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    backlog = tmp_path / "docs" / "board" / "backlog.md"
    backlog.parent.mkdir(parents=True)
    backlog.write_text("## Other Task\n\nSome notes.\n")

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "BACKLOG_PATH", backlog),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_current_branch", return_value="feature/adhoc-full"),
        mock.patch.object(board, "_today", return_value="2026-05-23"),
        mock.patch.object(board, "_git_add") as git_add,
    ):
        board._cmd_start("Ad Hoc Feature", "full")

    staged = git_add.call_args.args[0]
    assert specs / "2026-05-23-ad-hoc-feature-design.md" in staged
    assert plans / "2026-05-23-ad-hoc-feature.md" in staged
    assert index in staged
    assert backlog not in staged


def test_set_related_scalar_creates_related_block_when_absent(tmp_path):
    """Plan has no related: block. _set_related_scalar inserts one."""
    p = tmp_path / "plan.md"
    p.write_text("---\nstatus: done\ntype: plan\ndate: 2026-05-24\nsummary: T\nbranch: b\ntier: lite\n---\n\n# Body\n")
    board._set_related_scalar(p, "pr", 42)
    text = p.read_text()
    assert "related:\n  pr: 42\n" in text
    # Body preserved
    assert "# Body" in text


def test_set_related_scalar_adds_key_to_existing_related(tmp_path):
    """Plan has related: with spec. _set_related_scalar adds pr alongside."""
    p = tmp_path / "plan.md"
    p.write_text(
        "---\nstatus: done\ntype: plan\ndate: 2026-05-24\nsummary: T\nbranch: b\ntier: full\n"
        "related:\n  spec: foo-design.md\n---\n\n# Body\n"
    )
    board._set_related_scalar(p, "pr", 42)
    text = p.read_text()
    assert "  spec: foo-design.md" in text
    assert "  pr: 42" in text


def test_set_related_scalar_replaces_existing_key(tmp_path):
    """Plan already has pr; _set_related_scalar overwrites it."""
    p = tmp_path / "plan.md"
    p.write_text(
        "---\nstatus: done\ntype: plan\ndate: 2026-05-24\nsummary: T\nbranch: b\ntier: lite\n"
        "related:\n  pr: 7\n---\n"
    )
    board._set_related_scalar(p, "pr", 42)
    text = p.read_text()
    assert "  pr: 42" in text
    assert "  pr: 7" not in text


def test_set_related_scalar_preserves_other_frontmatter_lines(tmp_path):
    """Non-related frontmatter keys, blank lines, and body are preserved."""
    original = (
        "---\nstatus: done\ntype: plan\ndate: 2026-05-24\nsummary: T\n"
        "branch: feature/x\ntier: full\nrelated:\n  spec: foo.md\n---\n\n# H1\n\nBody.\n"
    )
    p = tmp_path / "plan.md"
    p.write_text(original)
    board._set_related_scalar(p, "pr", 99)
    text = p.read_text()
    # Original lines unchanged
    for fragment in ("status: done", "type: plan", "date: 2026-05-24", "summary: T",
                     "branch: feature/x", "tier: full", "  spec: foo.md", "# H1", "Body."):
        assert fragment in text
    assert "  pr: 99" in text


def test_append_related_list_creates_list_when_absent(tmp_path):
    """Spec has no related.prs. _append_related_list creates it."""
    p = tmp_path / "spec.md"
    p.write_text("---\nstatus: done\ntype: spec\ndate: 2026-05-24\nsummary: T\n---\n")
    board._append_related_list(p, "prs", 42)
    text = p.read_text()
    assert "related:\n  prs: [42]\n" in text


def test_append_related_list_appends_to_existing_list(tmp_path):
    """Spec has related.prs: [42]. Appending 51 makes [42, 51]."""
    p = tmp_path / "spec.md"
    p.write_text("---\nstatus: done\ntype: spec\ndate: 2026-05-24\nsummary: T\nrelated:\n  prs: [42]\n---\n")
    board._append_related_list(p, "prs", 51)
    text = p.read_text()
    assert "  prs: [42, 51]" in text


def test_append_related_list_dedupes(tmp_path):
    """Appending 42 to [42] is a no-op."""
    p = tmp_path / "spec.md"
    original = "---\nstatus: done\ntype: spec\ndate: 2026-05-24\nsummary: T\nrelated:\n  prs: [42]\n---\n"
    p.write_text(original)
    board._append_related_list(p, "prs", 42)
    text = p.read_text()
    assert "  prs: [42]" in text
    assert "  prs: [42, 42]" not in text


def test_append_related_list_preserves_other_related_keys(tmp_path):
    """Spec has related.spec; appending to related.prs keeps spec."""
    p = tmp_path / "spec.md"
    p.write_text(
        "---\nstatus: done\ntype: spec\ndate: 2026-05-24\nsummary: T\n"
        "related:\n  spec: foo-design.md\n---\n"
    )
    board._append_related_list(p, "prs", 42)
    text = p.read_text()
    assert "  spec: foo-design.md" in text
    assert "  prs: [42]" in text


def test_find_done_plans_for_branch_returns_single_match(tmp_path):
    """One done plan on the branch — returned in a single-element list."""
    plans = tmp_path / "plans"
    plan = _make_plan(plans, "Done Task", "done", "feature/x")
    with mock.patch.object(board, "PLANS_ROOT", plans):
        result = board._find_done_plans_for_branch("feature/x")
    assert len(result) == 1
    assert result[0][0] == plan
    assert result[0][1].get("status") == "done"


def test_find_done_plans_for_branch_returns_empty_when_only_active(tmp_path):
    """Active plan on the branch — _find_done_plans_for_branch returns []."""
    plans = tmp_path / "plans"
    _make_plan(plans, "Active Task", "active", "feature/x")
    with mock.patch.object(board, "PLANS_ROOT", plans):
        result = board._find_done_plans_for_branch("feature/x")
    assert result == []


def test_find_done_plans_for_branch_returns_multiple_matches(tmp_path):
    """Two done plans on the branch — both returned (caller handles ambiguity)."""
    plans = tmp_path / "plans"
    _make_plan(plans, "First", "done", "feature/x")
    _make_plan(plans, "Second", "done", "feature/x")
    with mock.patch.object(board, "PLANS_ROOT", plans):
        result = board._find_done_plans_for_branch("feature/x")
    assert len(result) == 2


def test_find_done_plans_for_branch_ignores_other_branches(tmp_path):
    """A done plan on a different branch is not returned."""
    plans = tmp_path / "plans"
    _make_plan(plans, "On X", "done", "feature/x")
    _make_plan(plans, "On Y", "done", "feature/y")
    with mock.patch.object(board, "PLANS_ROOT", plans):
        result = board._find_done_plans_for_branch("feature/x")
    assert len(result) == 1
    assert result[0][1].get("summary") == "On X"


def test_set_pr_writes_plan_related_pr(tmp_path):
    """Lite tier, done plan on branch — set-pr writes related.pr."""
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    specs.mkdir(parents=True)
    plan = _make_plan(plans, "Done Lite", "done", "feature/x", tier="lite")

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_git_add") as git_add,
    ):
        board._cmd_set_pr(pr=42, branch="feature/x")

    text = plan.read_text()
    assert "related:\n  pr: 42\n" in text
    staged = git_add.call_args.args[0]
    assert plan in staged
    assert index in staged


def test_set_pr_appends_to_spec_prs_for_full_tier(tmp_path):
    """Full tier, done plan + linked spec — set-pr writes plan.pr and appends spec.prs."""
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    specs.mkdir(parents=True)
    spec_path = specs / "2026-05-21-done-full-design.md"
    spec_path.write_text("---\nstatus: done\ntype: spec\ndate: 2026-05-21\nsummary: Done Full\n---\n")
    plan = _make_plan(plans, "Done Full", "done", "feature/x", tier="full",
                      spec="2026-05-21-done-full-design.md")

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_git_add") as git_add,
    ):
        board._cmd_set_pr(pr=42, branch="feature/x")

    assert "  pr: 42" in plan.read_text()
    assert "  prs: [42]" in spec_path.read_text()
    staged = git_add.call_args.args[0]
    assert plan in staged
    assert spec_path in staged
    assert index in staged


def test_set_pr_appends_to_existing_spec_prs_list(tmp_path):
    """Spec already has prs: [42]; set-pr 51 makes [42, 51]."""
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    specs.mkdir(parents=True)
    spec_path = specs / "2026-05-21-spec-design.md"
    spec_path.write_text(
        "---\nstatus: done\ntype: spec\ndate: 2026-05-21\nsummary: T\n"
        "related:\n  prs: [42]\n---\n"
    )
    plan = _make_plan(plans, "Second", "done", "feature/x", tier="full",
                      spec="2026-05-21-spec-design.md")

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_git_add"),
    ):
        board._cmd_set_pr(pr=51, branch="feature/x")

    assert "  prs: [42, 51]" in spec_path.read_text()


def test_set_pr_dedupes_spec_prs(tmp_path):
    """Spec has prs: [42]; set-pr 42 again keeps [42]."""
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    specs.mkdir(parents=True)
    spec_path = specs / "2026-05-21-spec-design.md"
    spec_path.write_text(
        "---\nstatus: done\ntype: spec\ndate: 2026-05-21\nsummary: T\n"
        "related:\n  prs: [42]\n---\n"
    )
    _make_plan(plans, "Plan", "done", "feature/x", tier="full",
               spec="2026-05-21-spec-design.md")

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_git_add"),
    ):
        board._cmd_set_pr(pr=42, branch="feature/x")

    text = spec_path.read_text()
    assert "  prs: [42]" in text
    assert "[42, 42]" not in text


def test_set_pr_on_shared_active_spec_appends_anyway(tmp_path):
    """Spec is status: active (still referenced by another active plan). PR still appended."""
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    specs.mkdir(parents=True)
    spec_path = specs / "2026-05-21-shared-design.md"
    spec_path.write_text(
        "---\nstatus: active\ntype: spec\ndate: 2026-05-21\nsummary: Shared\n---\n"
    )
    # The done plan we're set-pring
    done_plan = _make_plan(plans, "Done Plan", "done", "feature/x", tier="full",
                           spec="2026-05-21-shared-design.md")
    # A second active plan still referencing the same spec (different branch)
    _make_plan(plans, "Other Active", "active", "feature/y", tier="full",
               spec="2026-05-21-shared-design.md")

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_git_add"),
    ):
        board._cmd_set_pr(pr=42, branch="feature/x")

    spec_text = spec_path.read_text()
    assert "  prs: [42]" in spec_text
    # Spec status was not touched by set-pr
    assert "status: active" in spec_text
    assert "  pr: 42" in done_plan.read_text()


def test_set_pr_rejects_zero_or_negative_pr(tmp_path):
    """set-pr with pr <= 0 errors and exits 1, plan untouched."""
    import pytest
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    specs.mkdir(parents=True)
    plan = _make_plan(plans, "Done", "done", "feature/x", tier="lite")
    original = plan.read_text()

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_git_add"),
    ):
        for bad in (0, -1):
            with pytest.raises(SystemExit) as exc_info:
                board._cmd_set_pr(pr=bad, branch="feature/x")
            assert exc_info.value.code == 1
            assert plan.read_text() == original


def test_set_pr_errors_when_no_done_plan_for_branch(tmp_path):
    """No done plan on branch — set-pr exits 1."""
    import pytest
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    plans.mkdir(parents=True)
    specs.mkdir(parents=True)

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_git_add"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            board._cmd_set_pr(pr=42, branch="feature/none")
        assert exc_info.value.code == 1


def test_set_pr_errors_when_only_an_active_plan_exists_for_branch(tmp_path):
    """Plan exists but is active, not done — set-pr exits 1."""
    import pytest
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    specs.mkdir(parents=True)
    _make_plan(plans, "Active", "active", "feature/x", tier="lite")

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_git_add"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            board._cmd_set_pr(pr=42, branch="feature/x")
        assert exc_info.value.code == 1


def test_set_pr_idempotent_when_plan_already_has_same_pr(tmp_path):
    """Plan has pr: 42; set-pr --pr 42 again leaves the file identical."""
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    specs.mkdir(parents=True)
    plans.mkdir(parents=True)
    plan = plans / "2026-05-21-idempotent.md"
    plan.write_text(
        "---\nstatus: done\ntype: plan\ndate: 2026-05-21\nsummary: Idem\n"
        "branch: feature/x\ntier: lite\nrelated:\n  pr: 42\n---\n"
    )

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_git_add"),
    ):
        before = plan.read_text()
        board._cmd_set_pr(pr=42, branch="feature/x")
        after = plan.read_text()

    assert before == after


def test_set_pr_skips_missing_spec_file(tmp_path):
    """Plan references a spec that doesn't exist on disk — plan still gets pr, spec not staged."""
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    specs.mkdir(parents=True)
    plan = _make_plan(plans, "Done", "done", "feature/x", tier="full",
                      spec="missing-design.md")

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_git_add") as git_add,
    ):
        board._cmd_set_pr(pr=42, branch="feature/x")

    assert "  pr: 42" in plan.read_text()
    staged = git_add.call_args.args[0]
    missing_spec = specs / "missing-design.md"
    assert missing_spec not in staged


def test_set_pr_errors_on_multiple_done_plans_for_branch(tmp_path):
    """Two done plans on same branch — set-pr refuses to guess and exits 1."""
    import pytest
    docs = tmp_path / "docs" / "superpowers"
    plans = docs / "plans"
    specs = docs / "specs"
    index = docs / "INDEX.md"
    specs.mkdir(parents=True)
    _make_plan(plans, "First", "done", "feature/x", tier="lite")
    _make_plan(plans, "Second", "done", "feature/x", tier="lite")

    with (
        mock.patch.object(board, "DOCS_ROOT", docs),
        mock.patch.object(board, "PLANS_ROOT", plans),
        mock.patch.object(board, "SPECS_ROOT", specs),
        mock.patch.object(board, "INDEX_PATH", index),
        mock.patch.object(board, "_git_add"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            board._cmd_set_pr(pr=42, branch="feature/x")
        assert exc_info.value.code == 1
