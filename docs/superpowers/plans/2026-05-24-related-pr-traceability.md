---
status: active
type: plan
date: 2026-05-24
summary: Persist PR numbers in plan and spec frontmatter so finished docs link back to the PR that implemented them
branch: claude/sad-chatterjee-cd1aa7
tier: full
related:
  spec: 2026-05-24-related-pr-traceability-design.md
---

# Related-PR traceability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist PR numbers from `/task-ship` onto the plan that shipped and the spec it implements, resolving the soft `status: done` warning at [scaffold/scripts/docs_index.py:220](scaffold/scripts/docs_index.py:220) and giving the docs index a spec → plan → PR trail.

**Architecture:** Three layers, each one job. (1) `frontmatter.py` gains flow-style list parsing. (2) `board.py` gains two structured-edit helpers and a new `set-pr` subcommand that finds the done plan on a branch and writes `related.pr` on the plan plus appends to `related.prs` on the linked spec. (3) `docs_index.py` lint becomes type-aware (plans want `related.pr`, specs want `related.prs`), and INDEX rendering handles lists. `/task-ship` calls `set-pr` after the PR is captured and creates a small follow-up commit. `/task-finish` is unchanged.

**Tech Stack:** Python 3 (stdlib only), pytest, Markdown slash command files.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scaffold/scripts/frontmatter.py` | Modify | Parse flow-style `[a, b, c]` lists into Python lists at top level and inside nested mappings. |
| `scaffold/scripts/test_frontmatter.py` | Modify | Cover the new list-parsing cases and the deliberate non-support of block-style lists. |
| `scaffold/scripts/board.py` | Modify | Add `_edit_frontmatter_related`, `_set_related_scalar`, `_append_related_list`, `_find_done_plans_for_branch`, `_cmd_set_pr`, and wire `set-pr` into argparse. |
| `scaffold/scripts/test_board.py` | Modify | Cover the new `set-pr` command across all branches: lite, full+spec, dedup, idempotent, errors. |
| `scaffold/scripts/docs_index.py` | Modify | Lint becomes type-aware; `_fmt_entry` renders list-valued `related` items as `key: [v, v]`. |
| `scaffold/scripts/test_docs_index.py` | Modify | Cover the new lint behavior and list rendering. |
| `scaffold/.claude/commands/task-ship.md` | Modify | Append step 6 in section 2 to call `set-pr` and commit the backfill. |

No new files. No new external dependencies.

---

## Task 1: Extend frontmatter parser to support flow-style lists

**Files:**
- Modify: `scaffold/scripts/frontmatter.py`
- Modify: `scaffold/scripts/test_frontmatter.py`

- [ ] **Step 1: Write the failing tests**

Append to [scaffold/scripts/test_frontmatter.py](scaffold/scripts/test_frontmatter.py):

```python
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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest scaffold/scripts/test_frontmatter.py -v -k "flow_list or block_style"`

Expected: all five new tests FAIL. `test_parse_flow_list_at_top_level` and `test_parse_empty_flow_list` will report `fm["tags"]` is a string like `"[a, b, c]"` instead of a list. `test_parse_flow_list_inside_nested_mapping` will report `fm["related"]["prs"]` is the string `"[42, 51]"`. `test_block_style_list_still_unsupported` may PASS already (it pins current behavior) — that's fine.

- [ ] **Step 3: Implement flow-style list parsing**

In [scaffold/scripts/frontmatter.py](scaffold/scripts/frontmatter.py), add a helper above `_parse_yaml_block` (just below `_strip_quotes` at line 29):

```python
def _parse_value(val: str) -> Any:
    """Parse a YAML scalar value. Returns a list if val is a flow-style list, else a string."""
    val = val.strip()
    if len(val) >= 2 and val[0] == "[" and val[-1] == "]":
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(item.strip()) for item in inner.split(",")]
    return _strip_quotes(val)
```

Then replace the two places in `_parse_yaml_block` that currently call `_strip_quotes(val)` and `_strip_quotes(cm.group(2).strip())` with `_parse_value(...)`. The full updated function:

```python
def _parse_yaml_block(block: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    lines = block.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)", line)
        if not m:
            i += 1
            continue
        key = m.group(1)
        val = m.group(2).strip()
        if val:
            result[key] = _parse_value(val)
            i += 1
        else:
            nested: dict[str, Any] = {}
            i += 1
            while i < len(lines):
                child = lines[i]
                cm = re.match(r"^  ([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)", child)
                if cm:
                    nested[cm.group(1)] = _parse_value(cm.group(2).strip())
                    i += 1
                else:
                    break
            result[key] = nested if nested else ""
    return result
```

Note: the inner `nested` dict's value type changes from `dict[str, str]` to `dict[str, Any]` because list values can now appear.

- [ ] **Step 4: Run all frontmatter tests to verify they pass**

Run: `python3 -m pytest scaffold/scripts/test_frontmatter.py -v`

Expected: 12 passing tests (7 original + 5 new). Pay particular attention that `test_nested_related` and `test_multiline_nested` still pass — those tests assert string values for `pr`, which the new parser still returns since `"42"` is not a flow-list shape.

- [ ] **Step 5: Commit**

```bash
git add scaffold/scripts/frontmatter.py scaffold/scripts/test_frontmatter.py
git commit -m "$(cat <<'EOF'
feat(frontmatter): parse flow-style YAML lists

Values matching [a, b, c] now parse into a Python list of strings, both
at the top level and inside one-level nested mappings. Empty lists and
quoted items are handled. Block-style lists remain unsupported by
design; a regression test pins that behavior.

Enables related.prs: [42, 51] on spec frontmatter.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add `_edit_frontmatter_related` and `_set_related_scalar` helpers

**Files:**
- Modify: `scaffold/scripts/board.py`
- Modify: `scaffold/scripts/test_board.py`

- [ ] **Step 1: Write the failing tests**

Append to [scaffold/scripts/test_board.py](scaffold/scripts/test_board.py):

```python
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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v -k "set_related_scalar"`

Expected: all four FAIL with `AttributeError: module 'board' has no attribute '_set_related_scalar'`.

- [ ] **Step 3: Implement the helpers**

In [scaffold/scripts/board.py](scaffold/scripts/board.py), insert these two functions immediately after `_flip_status_in_file` (which ends at line 289):

```python
def _edit_frontmatter_related(path: Path, mutator) -> None:
    """Apply mutator to the file's `related` dict and rewrite the frontmatter block.

    mutator: Callable[[dict[str, Any]], dict[str, Any]] — receives the current
    related dict (empty dict if absent), returns the new related dict.

    Preserves all non-related frontmatter lines and the body verbatim. The
    `related:` block is fully rewritten using `key: value` for scalars and
    `key: [v1, v2]` for lists.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")

    if not lines or lines[0] != "---":
        return  # No frontmatter; nothing to edit
    fm_end = None
    for i in range(1, len(lines)):
        if lines[i] == "---":
            fm_end = i
            break
    if fm_end is None:
        return  # Malformed frontmatter

    related_start = None
    related_end = None
    for i in range(1, fm_end):
        if re.match(r"^related\s*:\s*$", lines[i]):
            related_start = i
            j = i + 1
            while j < fm_end:
                if lines[j].startswith("  ") or lines[j].strip() == "":
                    j += 1
                else:
                    break
            related_end = j
            break

    fm = parse_frontmatter(path) or {}
    current = fm.get("related")
    current_related: dict[str, Any] = current if isinstance(current, dict) else {}

    new_related = mutator(dict(current_related))

    if new_related:
        related_lines = ["related:"]
        for k, v in new_related.items():
            if isinstance(v, list):
                rendered = "[" + ", ".join(str(item) for item in v) + "]"
                related_lines.append(f"  {k}: {rendered}")
            else:
                related_lines.append(f"  {k}: {v}")
    else:
        related_lines = []

    if related_start is not None:
        new_lines = lines[:related_start] + related_lines + lines[related_end:]
    else:
        new_lines = lines[:fm_end] + related_lines + lines[fm_end:]

    path.write_text("\n".join(new_lines), encoding="utf-8")


def _set_related_scalar(path: Path, key: str, value: Any) -> None:
    """Set `related.<key>: <value>` in the file's frontmatter. Idempotent."""
    def mutator(d: dict[str, Any]) -> dict[str, Any]:
        d[key] = value
        return d
    _edit_frontmatter_related(path, mutator)
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v -k "set_related_scalar"`

Expected: all four PASS.

- [ ] **Step 5: Run the full board test suite to check for regressions**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v`

Expected: all existing tests still pass (the new helpers don't change any current call sites).

- [ ] **Step 6: Commit**

```bash
git add scaffold/scripts/board.py scaffold/scripts/test_board.py
git commit -m "$(cat <<'EOF'
feat(board): add structured frontmatter helpers for related.* keys

_edit_frontmatter_related rewrites only the related: block of a doc's
frontmatter, preserving everything else verbatim. _set_related_scalar
uses it to set or replace one nested key (e.g. related.pr).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add `_append_related_list` helper

**Files:**
- Modify: `scaffold/scripts/board.py`
- Modify: `scaffold/scripts/test_board.py`

- [ ] **Step 1: Write the failing tests**

Append to [scaffold/scripts/test_board.py](scaffold/scripts/test_board.py):

```python
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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v -k "append_related_list"`

Expected: all four FAIL with `AttributeError: module 'board' has no attribute '_append_related_list'`.

- [ ] **Step 3: Implement the helper**

In [scaffold/scripts/board.py](scaffold/scripts/board.py), insert this function immediately after `_set_related_scalar` (just added in Task 2):

```python
def _append_related_list(path: Path, key: str, value: int) -> None:
    """Append `value` to the list at `related.<key>`, deduplicated. Idempotent.

    Compares as strings since parsed values come back as strings.
    """
    def mutator(d: dict[str, Any]) -> dict[str, Any]:
        existing = d.get(key, [])
        if not isinstance(existing, list):
            existing = [existing] if existing else []
        if str(value) not in [str(x) for x in existing]:
            existing.append(value)
        d[key] = existing
        return d
    _edit_frontmatter_related(path, mutator)
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v -k "append_related_list"`

Expected: all four PASS.

- [ ] **Step 5: Run the full board test suite to check for regressions**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v`

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add scaffold/scripts/board.py scaffold/scripts/test_board.py
git commit -m "$(cat <<'EOF'
feat(board): add _append_related_list helper

Appends an int to related.<key>, formatted as a flow-style YAML list,
deduplicated against existing entries. Idempotent on the same value.

Used to track multiple PRs on a spec (related.prs).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add `_find_done_plans_for_branch` helper

**Files:**
- Modify: `scaffold/scripts/board.py`
- Modify: `scaffold/scripts/test_board.py`

- [ ] **Step 1: Write the failing tests**

Append to [scaffold/scripts/test_board.py](scaffold/scripts/test_board.py):

```python
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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v -k "find_done_plans"`

Expected: all four FAIL with `AttributeError: module 'board' has no attribute '_find_done_plans_for_branch'`.

- [ ] **Step 3: Implement the helper**

In [scaffold/scripts/board.py](scaffold/scripts/board.py), add this function immediately after `_find_active_plan_for_branch` (currently ends at line 298):

```python
def _find_done_plans_for_branch(branch: str) -> list[tuple[Path, dict[str, Any]]]:
    """Return all plans whose branch matches and whose status is `done`."""
    all_plans = _collect_plans(PLANS_ROOT)
    return [
        (path, fm)
        for path, fm in all_plans
        if fm.get("branch") == branch and fm.get("status") == "done"
    ]
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v -k "find_done_plans"`

Expected: all four PASS.

- [ ] **Step 5: Commit**

```bash
git add scaffold/scripts/board.py scaffold/scripts/test_board.py
git commit -m "$(cat <<'EOF'
feat(board): add _find_done_plans_for_branch helper

Returns all done plans on a given branch. Caller (set-pr) decides what
to do with 0, 1, or multiple matches.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add `_cmd_set_pr` and wire it into the CLI

**Files:**
- Modify: `scaffold/scripts/board.py`
- Modify: `scaffold/scripts/test_board.py`

- [ ] **Step 1: Write the failing tests**

Append to [scaffold/scripts/test_board.py](scaffold/scripts/test_board.py):

```python
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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v -k "set_pr"`

Expected: all eleven FAIL with `AttributeError: module 'board' has no attribute '_cmd_set_pr'`.

- [ ] **Step 3: Implement `_cmd_set_pr`**

In [scaffold/scripts/board.py](scaffold/scripts/board.py), insert this function immediately after `_cmd_abandon` (currently ends at line 359):

```python
def _cmd_set_pr(pr: int, branch: str) -> None:
    """Backfill a PR number onto the done plan for `branch` and its linked spec.

    - Requires pr > 0.
    - Requires exactly one done plan on the branch.
    - Writes related.pr on the plan.
    - For full tier, appends to related.prs on the linked spec (if it exists on disk).
    - Regenerates INDEX.md and stages the touched files.
    """
    if pr <= 0:
        print(f"ERROR: --pr must be a positive integer, got {pr}.")
        sys.exit(1)

    matches = _find_done_plans_for_branch(branch)
    if not matches:
        print(f"ERROR: No done plan found for branch '{branch}'.")
        sys.exit(1)
    if len(matches) > 1:
        print(f"ERROR: Multiple done plans on branch '{branch}' — refusing to ambiguously assign PR.")
        for path, _ in matches:
            print(f"  - {path.name}")
        sys.exit(1)

    plan_path, fm = matches[0]
    touched: list[Path] = []

    _set_related_scalar(plan_path, "pr", pr)
    print(f"Updated {plan_path.name}: related.pr -> {pr}")
    touched.append(plan_path)

    tier = fm.get("tier", "lite")
    if tier == "full":
        related = fm.get("related")
        if isinstance(related, dict) and "spec" in related:
            spec_name = related["spec"]
            spec_path = SPECS_ROOT / spec_name
            if spec_path.exists():
                _append_related_list(spec_path, "prs", pr)
                print(f"Updated {spec_path.name}: appended {pr} to related.prs")
                touched.append(spec_path)
            else:
                print(f"Skipping spec {spec_name} — file does not exist.")

    _regen_index()
    touched.append(INDEX_PATH)

    _git_add(touched)
    print(f"Done. Run `git commit` to finalize.")
```

- [ ] **Step 4: Wire `set-pr` into the CLI**

In [scaffold/scripts/board.py](scaffold/scripts/board.py), in the `main(...)` function, add a new subparser between the existing `abandon` and `check-merge` parsers (currently around lines 471-475):

Find:

```python
    sub.add_parser("finish", help="Mark active plan as done")
    sub.add_parser("abandon", help="Mark active plan as abandoned")

    check_merge_p = sub.add_parser("check-merge", help="Gate for git merge")
```

Replace with:

```python
    sub.add_parser("finish", help="Mark active plan as done")
    sub.add_parser("abandon", help="Mark active plan as abandoned")

    set_pr_p = sub.add_parser(
        "set-pr",
        help="Backfill a PR number onto the done plan for a branch (and its spec)",
    )
    set_pr_p.add_argument("--pr", type=int, required=True, help="GitHub PR number (positive int)")
    set_pr_p.add_argument("--branch", required=True, help="Branch name whose done plan to update")

    check_merge_p = sub.add_parser("check-merge", help="Gate for git merge")
```

Then in the dispatch block at the bottom of `main`, find:

```python
    elif args.command == "abandon":
        _cmd_abandon()
    elif args.command == "check-merge":
```

Replace with:

```python
    elif args.command == "abandon":
        _cmd_abandon()
    elif args.command == "set-pr":
        _cmd_set_pr(args.pr, args.branch)
    elif args.command == "check-merge":
```

- [ ] **Step 5: Run all set-pr tests to verify they pass**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v -k "set_pr"`

Expected: all eleven PASS.

- [ ] **Step 6: Sanity-check the CLI surface**

Run: `python3 scaffold/scripts/board.py set-pr --help`

Expected: argparse usage shows `--pr` and `--branch` as required arguments.

Run: `python3 scaffold/scripts/board.py --help`

Expected: `set-pr` appears in the subcommand list.

- [ ] **Step 7: Run the full board test suite**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v`

Expected: all tests pass. Existing tests should not have regressed (set-pr is purely additive).

- [ ] **Step 8: Commit**

```bash
git add scaffold/scripts/board.py scaffold/scripts/test_board.py
git commit -m "$(cat <<'EOF'
feat(board): add set-pr subcommand for PR backfill

board.py set-pr --pr <int> --branch <branch> finds the done plan on the
named branch, writes related.pr on it, and appends to the linked spec's
related.prs (full tier only). Validates pr > 0, refuses to operate on
active plans, and refuses to guess when multiple done plans exist on
the same branch.

Designed to be called by /task-ship after the PR is captured.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Update `docs_index.py` lint to be type-aware

**Files:**
- Modify: `scaffold/scripts/docs_index.py`
- Modify: `scaffold/scripts/test_docs_index.py`

- [ ] **Step 1: Write the failing tests**

Append to [scaffold/scripts/test_docs_index.py](scaffold/scripts/test_docs_index.py):

```python
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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest scaffold/scripts/test_docs_index.py -v -k "done_plan or done_spec"`

Expected: the plan tests behave per the OLD lint (the "without related.pr" test should already PASS since the current warning checks for `related.pr` on any done doc). The spec tests should FAIL: `test_lint_warns_on_done_spec_without_related_prs` will receive a warning mentioning `related.pr` not `related.prs`; `test_lint_silent_on_done_spec_with_related_prs` will FAIL because the current code requires `related.pr` even on specs; and `test_lint_warns_on_done_spec_with_empty_related_prs` will FAIL similarly.

- [ ] **Step 3: Update the lint logic**

In [scaffold/scripts/docs_index.py](scaffold/scripts/docs_index.py), find the block at lines 220-225:

```python
        # Warn if done without related.pr
        if status == "done":
            related = fm.get("related")
            has_pr = isinstance(related, dict) and "pr" in related
            if not has_pr:
                warnings.append(f"{name}: status `done` without `related.pr`")
```

Replace with:

```python
        # Warn if done without the type-appropriate PR reference
        if status == "done":
            related = fm.get("related")
            related_dict = related if isinstance(related, dict) else {}
            if doc_type == "plan":
                if "pr" not in related_dict:
                    warnings.append(f"{name}: status `done` without `related.pr`")
            elif doc_type == "spec":
                prs = related_dict.get("prs")
                if not isinstance(prs, list) or len(prs) == 0:
                    warnings.append(f"{name}: status `done` without `related.prs`")
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python3 -m pytest scaffold/scripts/test_docs_index.py -v -k "done_plan or done_spec"`

Expected: all five PASS.

- [ ] **Step 5: Run the full docs_index test suite to check for regressions**

Run: `python3 -m pytest scaffold/scripts/test_docs_index.py -v`

Expected: all existing tests still pass. In particular `test_lint_valid` (uses `status: active` docs) is unaffected by the new branches.

- [ ] **Step 6: Commit**

```bash
git add scaffold/scripts/docs_index.py scaffold/scripts/test_docs_index.py
git commit -m "$(cat <<'EOF'
feat(docs_index): make the done-without-PR warning type-aware

Plans (type: plan) warn if related.pr is missing. Specs (type: spec)
warn if related.prs is missing or empty. Other types (report, handoff)
are not checked. Mirrors the two-shape PR field design.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Update `docs_index.py` `_fmt_entry` to render lists

**Files:**
- Modify: `scaffold/scripts/docs_index.py`
- Modify: `scaffold/scripts/test_docs_index.py`

- [ ] **Step 1: Write the failing test**

Append to [scaffold/scripts/test_docs_index.py](scaffold/scripts/test_docs_index.py):

```python
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
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `python3 -m pytest scaffold/scripts/test_docs_index.py -v -k "fmt_entry_renders_list"`

Expected: FAIL. Today's `_fmt_entry` iterates `related.items()` and emits `f"{k}: {v}"`, so a list `["42", "51"]` would render as `prs: ['42', '51']` — not the desired `[42, 51]`.

- [ ] **Step 3: Update `_fmt_entry`**

In [scaffold/scripts/docs_index.py](scaffold/scripts/docs_index.py), find the block at lines 68-72:

```python
    # Build related extras string
    extras: list[str] = []
    related = fm.get("related")
    if isinstance(related, dict):
        for k, v in related.items():
            extras.append(f"{k}: {v}")
```

Replace with:

```python
    # Build related extras string. Render list values as [v1, v2] (no quotes).
    extras: list[str] = []
    related = fm.get("related")
    if isinstance(related, dict):
        for k, v in related.items():
            if isinstance(v, list):
                rendered = "[" + ", ".join(str(item) for item in v) + "]"
                extras.append(f"{k}: {rendered}")
            else:
                extras.append(f"{k}: {v}")
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python3 -m pytest scaffold/scripts/test_docs_index.py -v -k "fmt_entry_renders_list"`

Expected: PASS.

- [ ] **Step 5: Run the full docs_index test suite**

Run: `python3 -m pytest scaffold/scripts/test_docs_index.py -v`

Expected: all tests pass. Existing tests that exercise `_fmt_entry` (e.g. `test_build_index_sections`) work with string/dict values, not lists, so they're unaffected.

- [ ] **Step 6: Commit**

```bash
git add scaffold/scripts/docs_index.py scaffold/scripts/test_docs_index.py
git commit -m "$(cat <<'EOF'
feat(docs_index): render list-valued related items as [v1, v2]

When INDEX.md surfaces a related.* key whose value is a list (e.g.
related.prs on a spec), render it as a comma-joined flow form rather
than Python's repr of the list.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Update `/task-ship` to backfill PR after capturing it

**Files:**
- Modify: `scaffold/.claude/commands/task-ship.md`

- [ ] **Step 1: Edit the slash command**

In [scaffold/.claude/commands/task-ship.md](scaffold/.claude/commands/task-ship.md), find the end of section 2 (current step 5 ends with the self-link footer at lines 74-80). Append a new step 6 immediately after step 5 and before the `## 3. Watch CI in the background` heading. Insert this exact block:

````markdown
6. **Backfill the PR number onto the branch's done plan, if any.** This step runs after `$PR` is captured. It is a no-op when there is no done plan on the branch (e.g. the user shipped work that is not board-managed).
   1. Attempt the backfill:
      ```bash
      python3 scripts/board.py set-pr --pr "$PR" --branch "$BRANCH" 2>/dev/null
      ```
      Capture the exit code. If non-zero, skip the rest of step 6.
   2. If the backfill succeeded, check `git status --porcelain`. If it shows staged or unstaged changes (the plan / spec / INDEX.md updates), commit and push them as a small follow-up commit. The commit ensures the PR's diff reflects the new frontmatter; CI re-runs naturally on the push.
      ```bash
      if [ -n "$(git status --porcelain)" ]; then
        git commit -m "$(cat <<EOF
      chore(board): backfill PR #$PR onto plan/spec

      Co-Authored-By: Claude <noreply@anthropic.com>
      EOF
      )"
        git push
      fi
      ```
   3. If the porcelain output is empty after a successful `set-pr`, the PR was already recorded (idempotent rerun); skip the commit/push.
````

- [ ] **Step 2: Verify the file is syntactically clean**

Run: `head -3 scaffold/.claude/commands/task-ship.md`

Expected:
```
---
description: One-shot — commit, push, open PR, watch CI, then prompt to merge (green) or invoke /systematic-debugging with logs (red).
---
```

Run: `grep -c "^## " scaffold/.claude/commands/task-ship.md`

Expected: `7` (today's 6 sections — Pre-flight, 1, 2, 3, 4, 5, Edge cases — unchanged in count; step 6 is a numbered list item *inside* section 2, not a new `## ` heading).

Run: `grep -n "set-pr" scaffold/.claude/commands/task-ship.md`

Expected: at least one line — the new step's command invocation.

- [ ] **Step 3: Commit**

```bash
git add scaffold/.claude/commands/task-ship.md
git commit -m "$(cat <<'EOF'
feat(task-ship): backfill PR number onto done plan/spec after PR is opened

Append step 6 to section 2: after \$PR is captured, run board.py
set-pr to write related.pr on the plan and append to the spec's
related.prs. If set-pr produced changes, commit and push them as a
small follow-up commit so the PR diff reflects the new frontmatter.
No-op when there is no done plan on the branch (set-pr exits non-zero,
swallowed).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Final verification

- [ ] **Step 1: Run the full scaffold test suite**

Run: `python3 -m pytest scaffold/scripts/ -v`

Expected: every test passes — including the originals, the 5 new frontmatter tests, the ~25 new board tests across Tasks 2-5, and the 6 new docs_index tests across Tasks 6-7.

- [ ] **Step 2: Sanity-check the new CLI surface end-to-end**

Run: `python3 scaffold/scripts/board.py set-pr --pr 0 --branch nonexistent`

Expected: exits 1 with `ERROR: --pr must be a positive integer, got 0.` (No plan files modified.)

Run: `python3 scaffold/scripts/board.py set-pr --pr 42 --branch nonexistent`

Expected: exits 1 with `ERROR: No done plan found for branch 'nonexistent'.`

- [ ] **Step 3: Manually confirm a lint round-trip on a synthetic done plan**

Create a temporary test file to confirm the lint behavior end-to-end:

```bash
cat > /tmp/done-plan.md <<'EOF'
---
status: done
type: plan
date: 2026-05-24
summary: Sample
branch: foo
tier: lite
---
EOF
python3 scaffold/scripts/docs_index.py lint /tmp/done-plan.md
```

Expected: stdout contains `WARNING: done-plan.md: status \`done\` without \`related.pr\`` and `OK — 1 file(s) checked, 1 warning(s)` (exit 0; lint is non-fatal on warnings).

Add `related.pr` and re-lint:

```bash
cat > /tmp/done-plan.md <<'EOF'
---
status: done
type: plan
date: 2026-05-24
summary: Sample
branch: foo
tier: lite
related:
  pr: 42
---
EOF
python3 scaffold/scripts/docs_index.py lint /tmp/done-plan.md
rm /tmp/done-plan.md
```

Expected: no `WARNING:` lines, `OK — 1 file(s) checked, 0 warning(s)`.

- [ ] **Step 4: Tick this plan's checkboxes**

Once every checkbox above is `- [x]`, the plan is complete. `/task-ship`'s pre-flight will then verify the plan and pass the gate command.
