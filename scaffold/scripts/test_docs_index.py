"""Tests for docs_index.py."""

import textwrap
from pathlib import Path

from docs_index import build_index, lint


def _setup_docs(tmp_path: Path) -> Path:
    docs = tmp_path / "docs" / "superpowers"
    for sub in ("specs", "plans", "reports", "handoffs"):
        (docs / sub).mkdir(parents=True)

    (docs / "specs" / "2026-05-21-example-design.md").write_text(textwrap.dedent("""\
        ---
        status: active
        type: spec
        date: 2026-05-21
        summary: Example spec
        ---

        # Example
    """))

    (docs / "plans" / "2026-05-21-example.md").write_text(textwrap.dedent("""\
        ---
        status: active
        type: plan
        date: 2026-05-21
        summary: Example plan
        branch: feature/example
        tier: full
        related:
          spec: 2026-05-21-example-design.md
        ---

        # Example plan
    """))

    (docs / "plans" / "legacy-no-frontmatter.md").write_text("# Legacy\n\nNo frontmatter.\n")
    return docs


def test_build_index_sections(tmp_path):
    docs = _setup_docs(tmp_path)
    index = build_index(docs)
    assert "## Active" in index
    assert "## Recently done" in index
    assert "## Legacy (unfrontmattered)" in index
    assert "2026-05-21-example-design.md" in index
    assert "2026-05-21-example.md" in index
    assert "legacy-no-frontmatter.md" in index


def test_build_index_empty(tmp_path):
    docs = tmp_path / "docs" / "superpowers"
    for sub in ("specs", "plans", "reports", "handoffs"):
        (docs / sub).mkdir(parents=True)
    index = build_index(docs)
    assert "_(none)_" in index


def test_lint_valid(tmp_path):
    docs = _setup_docs(tmp_path)
    spec = docs / "specs" / "2026-05-21-example-design.md"
    plan = docs / "plans" / "2026-05-21-example.md"
    errors, warnings = lint([spec, plan])
    assert errors == []


def test_lint_missing_field(tmp_path):
    p = tmp_path / "bad.md"
    p.write_text("---\nstatus: active\n---\n")
    errors, _ = lint([p])
    assert any("missing required field" in e for e in errors)


def test_lint_invalid_status(tmp_path):
    p = tmp_path / "bad.md"
    p.write_text("---\nstatus: bogus\ntype: spec\ndate: 2026-01-01\nsummary: X\n---\n")
    errors, _ = lint([p])
    assert any("invalid status" in e for e in errors)


def test_lint_full_tier_requires_spec(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("---\nstatus: active\ntype: plan\ndate: 2026-01-01\nsummary: X\nbranch: b\ntier: full\n---\n")
    errors, _ = lint([p])
    assert any("requires `related.spec`" in e for e in errors)


def test_lint_lite_tier_forbids_spec(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("---\nstatus: active\ntype: plan\ndate: 2026-01-01\nsummary: X\nbranch: b\ntier: lite\nrelated:\n  spec: foo.md\n---\n")
    errors, _ = lint([p])
    assert any("forbids `related.spec`" in e for e in errors)


def test_lint_plan_missing_branch(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("---\nstatus: active\ntype: plan\ndate: 2026-01-01\nsummary: X\ntier: lite\n---\n")
    errors, _ = lint([p])
    assert any("plan missing required field `branch`" in e for e in errors)


def test_lint_plan_missing_tier(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("---\nstatus: active\ntype: plan\ndate: 2026-01-01\nsummary: X\nbranch: feature/x\n---\n")
    errors, _ = lint([p])
    assert any("plan missing required field `tier`" in e for e in errors)


def test_lint_plan_with_branch_and_tier_passes(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("---\nstatus: active\ntype: plan\ndate: 2026-01-01\nsummary: X\nbranch: feature/x\ntier: lite\n---\n")
    errors, _ = lint([p])
    assert not any("plan missing" in e for e in errors)


def test_lint_warns_on_done_plan_without_related_pr(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text(
        "---\nstatus: done\ntype: plan\ndate: 2026-01-01\nsummary: X\n"
        "branch: b\ntier: lite\n---\n"
    )
    _, warnings = lint([p])
    assert any("related.pr" in w for w in warnings)


def test_lint_silent_on_done_plan_with_related_pr(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text(
        "---\nstatus: done\ntype: plan\ndate: 2026-01-01\nsummary: X\n"
        "branch: b\ntier: lite\nrelated:\n  pr: 42\n---\n"
    )
    _, warnings = lint([p])
    assert warnings == []


def test_lint_warns_on_done_spec_without_related_prs(tmp_path):
    p = tmp_path / "spec.md"
    p.write_text("---\nstatus: done\ntype: spec\ndate: 2026-01-01\nsummary: X\n---\n")
    _, warnings = lint([p])
    assert any("related.prs" in w for w in warnings)


def test_lint_silent_on_done_spec_with_related_prs(tmp_path):
    p = tmp_path / "spec.md"
    p.write_text(
        "---\nstatus: done\ntype: spec\ndate: 2026-01-01\nsummary: X\n"
        "related:\n  prs: [42]\n---\n"
    )
    _, warnings = lint([p])
    assert warnings == []


def test_lint_warns_on_done_spec_with_empty_related_prs(tmp_path):
    p = tmp_path / "spec.md"
    p.write_text(
        "---\nstatus: done\ntype: spec\ndate: 2026-01-01\nsummary: X\n"
        "related:\n  prs: []\n---\n"
    )
    _, warnings = lint([p])
    assert any("related.prs" in w for w in warnings)


def test_fmt_entry_renders_list_as_bracketed_comma_join(tmp_path):
    """INDEX line for a doc with related.prs: [42, 51] contains 'prs: [42, 51]'."""
    docs = tmp_path / "docs" / "superpowers"
    for sub in ("specs", "plans", "reports", "handoffs"):
        (docs / sub).mkdir(parents=True)

    (docs / "specs" / "2026-05-24-listed-design.md").write_text(textwrap.dedent("""\
        ---
        status: done
        type: spec
        date: 2026-05-24
        summary: Listed
        related:
          prs: [42, 51]
        ---

        # Listed
    """))

    index = build_index(docs)
    assert "prs: [42, 51]" in index
