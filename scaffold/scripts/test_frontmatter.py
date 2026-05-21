"""Tests for the zero-dep YAML frontmatter parser."""

from pathlib import Path
from frontmatter import parse_frontmatter


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.md"
    p.write_text(content, encoding="utf-8")
    return p


def test_simple_frontmatter(tmp_path):
    p = _write(tmp_path, "---\nstatus: active\ntype: plan\ndate: 2026-05-21\nsummary: Test\n---\n\n# Body\n")
    fm = parse_frontmatter(p)
    assert fm is not None
    assert fm["status"] == "active"
    assert fm["type"] == "plan"
    assert fm["date"] == "2026-05-21"
    assert fm["summary"] == "Test"


def test_nested_related(tmp_path):
    content = "---\nstatus: active\ntype: plan\ndate: 2026-05-21\nsummary: Test\nrelated:\n  spec: foo-design.md\n  pr: 42\n---\n\n# Body\n"
    p = _write(tmp_path, content)
    fm = parse_frontmatter(p)
    assert fm is not None
    assert fm["related"] == {"spec": "foo-design.md", "pr": "42"}


def test_no_frontmatter(tmp_path):
    p = _write(tmp_path, "# Just a heading\n\nSome text.\n")
    assert parse_frontmatter(p) is None


def test_unterminated_frontmatter(tmp_path):
    p = _write(tmp_path, "---\nstatus: active\n# No closing delimiters\n")
    assert parse_frontmatter(p) is None


def test_quoted_values(tmp_path):
    p = _write(tmp_path, '---\nstatus: active\nsummary: "A quoted: value"\n---\n')
    fm = parse_frontmatter(p)
    assert fm is not None
    assert fm["summary"] == "A quoted: value"


def test_empty_value(tmp_path):
    p = _write(tmp_path, "---\nstatus: active\nbranch:\n---\n")
    fm = parse_frontmatter(p)
    assert fm is not None
    assert fm["branch"] == ""


def test_multiline_nested(tmp_path):
    content = "---\nstatus: done\ntype: plan\ndate: 2026-05-21\nsummary: Test\ntier: full\nrelated:\n  spec: design.md\n  pr: 99\n---\n"
    p = _write(tmp_path, content)
    fm = parse_frontmatter(p)
    assert fm["tier"] == "full"
    assert fm["related"]["spec"] == "design.md"
    assert fm["related"]["pr"] == "99"
