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


def test_parse_flow_list_at_top_level(tmp_path):
    """Flow-style list at the top level parses to a Python list of strings."""
    p = _write(tmp_path, "---\nstatus: done\ntags: [a, b, c]\n---\n")
    fm = parse_frontmatter(p)
    assert fm is not None
    assert fm["tags"] == ["a", "b", "c"]


def test_parse_flow_list_inside_nested_mapping(tmp_path):
    """Flow-style list inside `related:` parses to a Python list."""
    content = "---\nstatus: done\ntype: spec\ndate: 2026-05-24\nsummary: Test\nrelated:\n  prs: [42, 51]\n---\n"
    p = _write(tmp_path, content)
    fm = parse_frontmatter(p)
    assert fm is not None
    assert fm["related"] == {"prs": ["42", "51"]}


def test_parse_empty_flow_list(tmp_path):
    """An empty flow list parses to an empty Python list."""
    p = _write(tmp_path, "---\nstatus: done\ntags: []\n---\n")
    fm = parse_frontmatter(p)
    assert fm is not None
    assert fm["tags"] == []


def test_parse_flow_list_with_quoted_strings(tmp_path):
    """Quoted items in a flow list have their quotes stripped."""
    p = _write(tmp_path, '---\nstatus: done\ntags: ["a", "b"]\n---\n')
    fm = parse_frontmatter(p)
    assert fm is not None
    assert fm["tags"] == ["a", "b"]


def test_block_style_list_still_unsupported(tmp_path):
    """Block-style `- item` lists are not supported. Nested branch returns empty dict-or-string."""
    # The block form: `key:\n  - a\n  - b\n`. The nested-mapping branch looks for
    # `  child:` lines; finding none, it returns the empty-dict-becomes-empty-string
    # fallback. This test pins the current behavior so a future parser rewrite that
    # silently changes it gets caught.
    p = _write(tmp_path, "---\nstatus: done\nkey:\n  - a\n  - b\n---\n")
    fm = parse_frontmatter(p)
    assert fm is not None
    assert fm["key"] == ""
