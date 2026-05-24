---
status: active
type: plan
date: 2026-05-23
summary: Let /task-start create ad hoc tasks directly when the backlog is empty or the user supplies a title
branch: claude/heuristic-beaver-f9c532
tier: full
related:
  spec: 2026-05-23-task-start-ad-hoc-tasks-design.md
---

# /task-start ad hoc tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `/task-start` scaffold spec/plan stubs without a corresponding backlog entry, triggered either by passing a title as an argument or by an empty backlog.

**Architecture:** Relax `_cmd_start` in `board.py` so a missing backlog file or a title not present in the backlog are both treated as "ad hoc": skip the backlog-removal step, scaffold stubs as usual. The slash command grows three input branches (arg, picker, ad hoc prompt) and chooses among them before invoking the existing CLI surface.

**Tech Stack:** Python 3 (stdlib only), pytest, Markdown slash command files.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scaffold/scripts/board.py` | Modify | `_cmd_start` no longer errors on missing backlog file or missing entry; both become "ad hoc" paths. |
| `scaffold/scripts/test_board.py` | Modify | Add three tests covering the ad hoc branches (lite no-match, missing-file, full-tier ad hoc). |
| `scaffold/.claude/commands/task-start.md` | Modify | Rewrite step 1+2 so the agent uses an arg if supplied, picks from backlog if non-empty, or prompts for an ad hoc title otherwise. |
| `docs/how-it-works.md` | Modify | Note the ad hoc path in the `/task-start` section. |
| `docs/customization.md` | Modify | Note the ad hoc path under "Backlog format". |

No new files. No new CLI flags.

---

## Task 1: Test the lite-tier ad hoc path (title not in backlog)

**Files:**
- Modify: `scaffold/scripts/test_board.py` — append after the last existing test.

- [ ] **Step 1: Write the failing test**

Append to [scaffold/scripts/test_board.py](scaffold/scripts/test_board.py):

```python
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
    # Backlog content unchanged on disk
    assert backlog.read_text() == "## Other Task\n\nSome notes.\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scaffold/scripts/test_board.py::test_start_creates_ad_hoc_when_title_absent_from_backlog -v`

Expected: FAIL with `SystemExit: 1` (because today's code calls `sys.exit(1)` with "Backlog entry not found").

- [ ] **Step 3: Implement the relaxation in `_cmd_start`**

In [scaffold/scripts/board.py](scaffold/scripts/board.py), replace the block that currently reads:

```python
    # Check entry exists in backlog
    if not BACKLOG_PATH.exists():
        print(f"ERROR: Backlog not found at {BACKLOG_PATH}")
        sys.exit(1)

    offsets = _find_backlog_entry(BACKLOG_PATH, title)
    if offsets is None:
        print(f"ERROR: Backlog entry not found: '{title}'")
        sys.exit(1)
```

…with:

```python
    # Look up the entry in the backlog if it exists. A missing file or
    # missing entry means this is an ad hoc task — fine, just skip the
    # removal step later.
    backlog_match = (
        BACKLOG_PATH.exists()
        and _find_backlog_entry(BACKLOG_PATH, title) is not None
    )
    if not backlog_match:
        print(f"No matching backlog entry for '{title}' — creating ad hoc task.")
```

Then, further down in the same function, replace:

```python
    # Remove from backlog
    _remove_backlog_entry(BACKLOG_PATH, title)
    print(f"Removed '{title}' from backlog.")
    touched.append(BACKLOG_PATH)
```

…with:

```python
    # Remove from backlog only if we matched an entry
    if backlog_match:
        _remove_backlog_entry(BACKLOG_PATH, title)
        print(f"Removed '{title}' from backlog.")
        touched.append(BACKLOG_PATH)
```

Also update the function docstring from:

```python
    """Start a task: scaffold plan stub (+ spec stub for full tier),
    remove from backlog, regenerate index, git add touched files.
    """
```

…to:

```python
    """Start a task: scaffold plan stub (+ spec stub for full tier),
    remove from backlog if the title matches an entry, regenerate index,
    git add touched files.
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scaffold/scripts/test_board.py::test_start_creates_ad_hoc_when_title_absent_from_backlog -v`

Expected: PASS.

- [ ] **Step 5: Run the full board test suite to confirm no regressions**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v`

Expected: all tests pass (10 total now — the original 9 plus the new one). In particular `test_start_stages_backlog_plan_and_index_without_in_flight` (backlog match path) and `test_start_rejects_duplicate_active_plan` must stay green.

- [ ] **Step 6: Commit**

```bash
git add scaffold/scripts/board.py scaffold/scripts/test_board.py
git commit -m "feat(board): allow start without matching backlog entry

When a title is not present in the backlog, _cmd_start prints a notice
and proceeds with scaffolding instead of erroring. This is the first
half of the ad hoc-tasks feature; the slash command still always passes
a title that matches the backlog today.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Test the missing-backlog-file path

**Files:**
- Modify: `scaffold/scripts/test_board.py`

- [ ] **Step 1: Write the test**

Append to [scaffold/scripts/test_board.py](scaffold/scripts/test_board.py):

```python
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
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python3 -m pytest scaffold/scripts/test_board.py::test_start_creates_ad_hoc_when_backlog_file_missing -v`

Expected: PASS. The Task 1 implementation already handles this case because `BACKLOG_PATH.exists()` short-circuits the `_find_backlog_entry` lookup. No production-code changes needed.

- [ ] **Step 3: Run the full board test suite**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v`

Expected: 11 passing tests.

- [ ] **Step 4: Commit**

```bash
git add scaffold/scripts/test_board.py
git commit -m "test(board): cover ad hoc start when backlog file is missing

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Test the full-tier ad hoc path

**Files:**
- Modify: `scaffold/scripts/test_board.py`

- [ ] **Step 1: Write the test**

Append to [scaffold/scripts/test_board.py](scaffold/scripts/test_board.py):

```python
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
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python3 -m pytest scaffold/scripts/test_board.py::test_start_full_tier_ad_hoc_creates_spec_and_plan -v`

Expected: PASS. Full-tier already runs through the same code path; no production-code changes needed.

- [ ] **Step 3: Run the full board test suite**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v`

Expected: 12 passing tests.

- [ ] **Step 4: Commit**

```bash
git add scaffold/scripts/test_board.py
git commit -m "test(board): cover full-tier ad hoc start

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Rewrite the `/task-start` slash command

**Files:**
- Modify: `scaffold/.claude/commands/task-start.md`

- [ ] **Step 1: Replace the file contents**

Overwrite [scaffold/.claude/commands/task-start.md](scaffold/.claude/commands/task-start.md) with:

```markdown
---
description: Start a backlog item or an ad hoc task (scaffold spec+plan stubs, or just plan for lite).
---

Pick a backlog item, or accept a title for an ad hoc task, then start work on it.

1. Resolve the task title:
   - If the user invoked the command with a positional argument (e.g. `/task-start "Fix login bug"`), use that argument as the exact title and skip to step 2.
   - Otherwise, read `docs/board/backlog.md` and collect every `## title` heading (ignoring HTML comment blocks).
     - If there is at least one such heading, ask the user which title to start.
     - If there are no `## title` headings (or the file does not exist), ask the user for a title for a new ad hoc task.
2. Ask the user which tier to use:
   - **full** — feature work, design discussion needed, user-visible behavior change.
   - **lite** — typo fixes, small renames, chore cleanups, doc-only changes.
3. Verify the current branch is not `main`/`master`. If it is, ask the user to create a branch first (do not proceed).
4. Run: `python3 scripts/board.py start "<exact title>" --tier <full|lite>`
   - If the title matches a backlog entry, `board.py` will remove it from the backlog as part of scaffolding.
   - If the title is not in the backlog (ad hoc), `board.py` prints "No matching backlog entry … — creating ad hoc task." and scaffolds the stubs without touching the backlog.
5. Review the staged diff (`git diff --staged`). Leave it staged by default — `/task-ship` will include the scaffold in the implementation commit. To commit the scaffold separately instead, use: `chore(board): start task — <title>`.
6. Next skill:
   - **full** → invoke `superpowers:brainstorming` to fill the spec stub at `docs/superpowers/specs/<date>-<slug>-design.md`.
   - **lite** → invoke `superpowers:writing-plans` to fill the plan stub at `docs/superpowers/plans/<date>-<slug>.md`.

If the superpowers plugin is not installed, skip step 6 and tell the user to fill the spec/plan stubs manually or install the superpowers plugin.
```

- [ ] **Step 2: Verify the markdown is syntactically clean**

Run: `head -1 scaffold/.claude/commands/task-start.md`

Expected: `---` (YAML frontmatter opener).

Run: `grep -c "^##" scaffold/.claude/commands/task-start.md`

Expected: `0` (no `##` headings — the file uses an ordered list, not section headers).

- [ ] **Step 3: Commit**

```bash
git add scaffold/.claude/commands/task-start.md
git commit -m "feat(task-start): accept title arg and prompt for ad hoc when backlog empty

The slash command now (a) uses a positional arg as the task title when
present, (b) falls back to the backlog picker if the backlog has
entries, and (c) prompts for an ad hoc title when the backlog is empty
or missing.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Update `docs/how-it-works.md`

**Files:**
- Modify: `docs/how-it-works.md` — the `### /task-start` subsection.

- [ ] **Step 1: Edit the section**

In [docs/how-it-works.md](docs/how-it-works.md), find this paragraph (currently around line 25):

```markdown
### `/task-start`

Picks a backlog item and runs `board.py start`, which:

1. Removes the entry from `backlog.md`.
2. Creates a plan stub in `docs/superpowers/plans/` with `status: active` and `branch: <current-branch>`.
3. For **full** tier tasks, also creates a spec stub in `docs/superpowers/specs/`.
4. Regenerates `docs/superpowers/INDEX.md`.

If the superpowers plugin is installed, it then chains into brainstorming (full tier) or plan writing (lite tier).
```

Replace it with:

```markdown
### `/task-start`

Picks a backlog item — or accepts an ad hoc title — and runs `board.py start`, which:

1. Removes the entry from `backlog.md` (skipped for ad hoc tasks).
2. Creates a plan stub in `docs/superpowers/plans/` with `status: active` and `branch: <current-branch>`.
3. For **full** tier tasks, also creates a spec stub in `docs/superpowers/specs/`.
4. Regenerates `docs/superpowers/INDEX.md`.

Pass a title (`/task-start "Fix login bug"`) to start an ad hoc task without a backlog entry. With no arg, the command falls back to a backlog picker, or prompts for an ad hoc title when the backlog is empty.

If the superpowers plugin is installed, it then chains into brainstorming (full tier) or plan writing (lite tier).
```

- [ ] **Step 2: Commit**

```bash
git add docs/how-it-works.md
git commit -m "docs(how-it-works): document /task-start ad hoc path

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Update `docs/customization.md`

**Files:**
- Modify: `docs/customization.md` — the "Backlog format" section.

- [ ] **Step 1: Edit the section**

In [docs/customization.md](docs/customization.md), find the "Backlog format" section, which currently ends with:

```markdown
Titles must be unique (enforced by the pre-commit hook).
```

Append a new paragraph immediately after that line:

```markdown
Titles must be unique (enforced by the pre-commit hook).

You don't have to put every task in the backlog. Pass a title directly with `/task-start "Title"` and the command scaffolds the spec/plan stubs without requiring a backlog entry — useful for one-off fixes or projects that don't maintain a backlog.
```

- [ ] **Step 2: Commit**

```bash
git add docs/customization.md
git commit -m "docs(customization): note /task-start ad hoc usage

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run the board test suite one last time**

Run: `python3 -m pytest scaffold/scripts/test_board.py -v`

Expected: 12 passing tests (9 original + 3 new).

- [ ] **Step 2: Run the full scaffold test suite**

Run: `python3 -m pytest scaffold/scripts/ -v`

Expected: all tests across `test_board.py`, `test_docs_index.py`, `test_end_workflow_docs.py`, `test_frontmatter.py` pass. The new behavior should not affect any other test file.

- [ ] **Step 3: Sanity-check the modified `_cmd_start` by simulating an ad hoc start with `--help`**

Run: `python3 scaffold/scripts/board.py start --help`

Expected: argparse usage is unchanged — `start` still takes a positional `title` and an optional `--tier` of `lite` or `full`. No new flags surfaced.

- [ ] **Step 4: Confirm the slash command frontmatter is intact**

Run: `head -3 scaffold/.claude/commands/task-start.md`

Expected:
```
---
description: Start a backlog item or an ad hoc task (scaffold spec+plan stubs, or just plan for lite).
---
```

- [ ] **Step 5: Tick this plan's checkboxes and finish**

Once every checkbox above is `- [x]`, the plan is complete. The `/task-ship` flow will then verify the plan is complete (all top-level checkboxes ticked) and pass the gate command before allowing the merge.
```
