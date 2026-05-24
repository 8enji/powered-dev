---
status: active
type: spec
date: 2026-05-24
summary: Persist PR numbers in plan and spec frontmatter so finished docs link back to the PR that implemented them
---

# Related-PR traceability

## Problem

`scaffold/scripts/docs_index.py` lint emits a non-fatal warning whenever a doc has `status: done` without a `related.pr` field (lines 220–225). Today nothing in the pipeline ever writes that field, so every finished plan will trigger the warning. The PR number is known at exactly one moment — inside `/task-ship` right after it opens or reuses a PR — but never persisted onto the frontmatter, so spec/plan documents lose their forward link to the implementation that shipped them.

## Goal

Persist the PR number from `/task-ship` onto the plan that ships and (when applicable) onto the spec it implements, so the docs index gives a complete spec → plan → PR trail and the soft warning resolves on every shipped doc.

## Non-goals

- Backfilling PR numbers onto pre-existing finished docs. (There are none today; the change is forward-looking.)
- Changing `/task-finish` (the manual finish path). It continues to flip status without a PR; the warning remains as the signal that traceability is incomplete.
- Auto-detecting PRs inside `board.py` via `gh`. `board.py` stays free of `gh`/`git` PR coupling — `/task-ship` supplies the number.
- Tracking merge SHAs, commit lists, or any field beyond the PR number.
- Adding `--pr` to `board.py finish` / `board.py abandon`. The PR write is a separate command (`set-pr`) because `/task-ship`'s pre-flight finishes the plan *before* the PR is opened. A `finish --pr` flag would be dead code.
- Promoting the warning to an error, on plans or specs.

## Data shape

Two distinct shapes by file type:

| File type | Field | Shape | Cardinality |
|---|---|---|---|
| Plan | `related.pr` | scalar integer | One per plan (a plan ships in exactly one PR) |
| Spec | `related.prs` | flow-style YAML list of integers | Many per spec (a spec can be implemented over multiple PRs) |

Example plan frontmatter after `/task-ship`:

```yaml
---
status: done
type: plan
date: 2026-05-24
summary: Persist PR numbers ...
branch: claude/some-branch
tier: full
related:
  spec: 2026-05-24-related-pr-traceability-design.md
  pr: 42
---
```

Example spec frontmatter after one finish, then a second finish on a follow-up plan:

```yaml
---
status: done
type: spec
date: 2026-05-24
summary: Persist PR numbers ...
related:
  prs: [42, 51]
---
```

Block-style lists (`- 42` / `- 51`) are intentionally not supported. Flow style only.

## Component changes

### `scaffold/scripts/frontmatter.py` — parser extension

`_parse_yaml_block` currently treats every value as a string. Extend it so values that look like a flow-style list — `[v1, v2, ...]` — are parsed into a Python `list[str]`. Empty list `[]` is `[]`. Whitespace around items is trimmed. Quoted items have quotes stripped. This applies at both the top level and inside the one-level nested mapping (so `related: { prs: [42, 51] }` written in block form also works).

All other values continue to parse as strings. Block-style lists (`- item`) remain unsupported and are silently ignored as today — this is a known limitation, not a regression.

### `scaffold/scripts/board.py` — write side

1. **`_cmd_finish` and `_cmd_abandon` are unchanged.** They still only flip status. PR writes are the new `set-pr` command's responsibility (see item 3).

2. **Two new helpers**, both targeted text edits that read existing frontmatter, then rewrite the file:
   - `_set_related_scalar(path: Path, key: str, value: int | str) -> None` — set or replace one nested key under `related:`. Creates the `related:` block if absent.
   - `_append_related_list(path: Path, key: str, value: int) -> None` — append `value` to the list at `related.<key>`, deduplicated. Creates `related:` and/or `<key>: [value]` if absent. Idempotent on the same value.

   Both helpers use the existing `parse_frontmatter` to know prior state, then perform a minimal text rewrite of the frontmatter block (not regex over the whole file). They preserve unrelated lines, blank lines, and key ordering elsewhere in the frontmatter. They are the *only* writers of nested `related.*` keys outside of stub creation.

3. **New subcommand `board.py set-pr --pr <int> --branch <branch>`** wired to `_cmd_set_pr`:
   - Validates `pr > 0` (argparse `type=int` + an inline check); errors and exits 1 otherwise.
   - Finds the plan whose `branch:` matches and whose `status:` is `done`. If none found, error and exit 1.
   - Calls `_set_related_scalar(plan_path, "pr", pr)` on the plan.
   - If the plan is `tier: full` AND the linked spec exists on disk, calls `_append_related_list(spec_path, "prs", pr)` — **regardless of the spec's current status** (so shared specs whose status stays `active` because another plan still references them still gain PR history).
   - Regenerates `INDEX.md`, then `git add`s the touched files (plan, optional spec, index).

   Note: `set-pr` operates on a plan that's already `status: done`. It is intentionally **not** valid to call `set-pr` on an active plan. This pairs `set-pr` strictly with the post-finish backfill use case and rules out using it as a sneaky in-flight write.

### `scaffold/scripts/docs_index.py` — read side

1. **Lint update** (replaces lines 220–225):
   - If `status == "done"` and `type == "plan"`: warn if `related.pr` is absent.
   - If `status == "done"` and `type == "spec"`: warn if `related.prs` is absent or empty.
   - No warning on other types (`report`, `handoff`) — out of scope.

2. **`_fmt_entry` rendering** (current lines 68–77): when iterating `related.items()`, render lists as comma-joined inside brackets: `prs: [42, 51]`. Scalars unchanged. Keeps INDEX.md readable without HTML linkification (the PR isn't a URL today, just a number).

### `scaffold/.claude/commands/task-ship.md` — caller

`/task-ship`'s pre-flight `check-merge` runs *before* section 2 ("Open or reuse PR"), so when the user picks "Finish and continue" in pre-flight, `$PR` does not yet exist. The PR is only captured later. Similarly, when the user ran `/task-finish` manually before `/task-ship`, the plan is already `done` before the PR exists. In **both** cases we need the same backfill step after `$PR` is captured.

Changes to `task-ship.md`:

- **Pre-flight "Finish and continue" branch.** Unchanged. Still calls `python3 scripts/board.py finish` (no PR yet).

- **End of section 2 (after `$PR` is captured), append new step 6 "Backfill PR onto plan/spec":**
  1. Attempt the backfill: `python3 scripts/board.py set-pr --pr "$PR" --branch "$BRANCH"`. If it exits non-zero (no done plan on this branch — the user is shipping work that's not board-managed, or already-set), skip the rest of step 6.
  2. If `set-pr` succeeded, `git status --porcelain` will show the staged plan / spec / INDEX.md. Commit them with a fixed message and push:
     ```bash
     git commit -m "chore(board): backfill PR #$PR onto plan/spec

     Co-Authored-By: Claude <noreply@anthropic.com>"
     git push
     ```
     This adds one small follow-up commit to the same PR; CI re-runs naturally on the push.

  This step runs unconditionally; the `set-pr` no-op-on-error semantics cover the three real-world entry points:
  1. Plan was finished by pre-flight in this `/task-ship` session.
  2. Plan was finished by a prior `/task-finish` call.
  3. There is no done plan on this branch (set-pr exits non-zero, skip the commit step).

  Subsequent re-invocations of `/task-ship` on the same branch are idempotent: `set-pr` re-runs, computes the same frontmatter (PR already written, dedup keeps the list stable), `git status --porcelain` is empty, no extra commit.

### `scaffold/.claude/commands/task-finish.md` — unchanged

`/task-finish` is the manual escape hatch; it continues to flip status without a PR. The lint warning is the visible signal that a finished doc has no PR — the user can either ignore it or run `board.py set-pr` manually later.

## Testing

New tests, all in `scaffold/scripts/`:

**`test_frontmatter.py`** — new cases:
1. `test_parse_flow_list_at_top_level` — `key: [1, 2, 3]` parses to `["1", "2", "3"]`.
2. `test_parse_flow_list_inside_nested_mapping` — `related:\n  prs: [42, 51]` parses to `{"related": {"prs": ["42", "51"]}}`.
3. `test_parse_empty_flow_list` — `key: []` parses to `[]`.
4. `test_parse_flow_list_with_quoted_strings` — `key: ["a", "b"]` parses to `["a", "b"]`.
5. `test_block_style_list_still_unsupported` — `key:\n  - a\n  - b` parses to `{"key": ""}` as today (the nested-mapping branch sees no `  child:` lines and returns empty); documents the deliberate limitation.

**`test_board.py`** — new cases:
1. `test_set_pr_writes_plan_related_pr` — lite-tier plan with `status: done` and `branch: claude/foo` on disk, call `_cmd_set_pr(pr=42, branch="claude/foo")`, assert plan frontmatter now has `related.pr: 42`.
2. `test_set_pr_appends_to_spec_prs_for_full_tier` — full-tier done plan + linked spec, `_cmd_set_pr(pr=42, branch="claude/foo")`, assert plan has `related.pr: 42` AND spec has `related.prs: [42]`. Both files (plus INDEX.md) in `git_add` call.
3. `test_set_pr_appends_to_existing_spec_prs_list` — spec already has `related.prs: [42]` from a prior plan; finishing and set-pring a sibling plan with `--pr 51` makes the spec `[42, 51]`.
4. `test_set_pr_dedupes_spec_prs` — spec has `[42]`, run `set-pr --pr 42` again, spec stays `[42]` (not `[42, 42]`).
5. `test_set_pr_on_shared_active_spec_appends_anyway` — spec is `status: active` (referenced by another active plan), set-pr on the done plan still appends to the spec's `related.prs`. Spec status unchanged.
6. `test_set_pr_rejects_zero_or_negative_pr` — `set-pr --pr 0` and `--pr -1` both exit 1, files untouched.
7. `test_set_pr_errors_when_no_done_plan_for_branch` — no matching done plan on branch, exit 1.
8. `test_set_pr_errors_when_only_an_active_plan_exists_for_branch` — plan exists but `status: active`, set-pr exits 1 (set-pr operates on done plans only).
9. `test_set_pr_idempotent_when_plan_already_has_same_pr` — plan has `related.pr: 42`, run `set-pr --pr 42` again, frontmatter unchanged byte-for-byte, no new git diff.
10. `test_set_pr_skips_missing_spec_file` — done plan references a spec that doesn't exist on disk; plan still gets `related.pr`, no exception, no spec staged.
11. `test_set_pr_errors_on_multiple_done_plans_for_branch` — two done plans both have `branch: claude/foo`; set-pr refuses to guess and exits 1.

**`test_docs_index.py`** — new cases:
1. `test_lint_warns_on_done_plan_without_related_pr` — plan with `status: done`, no `related.pr`, lint emits the warning.
2. `test_lint_silent_on_done_plan_with_related_pr` — plan with `status: done` and `related.pr: 42`, no warning.
3. `test_lint_warns_on_done_spec_without_related_prs` — spec with `status: done`, no `related.prs`, warning emitted.
4. `test_lint_silent_on_done_spec_with_related_prs` — spec with `status: done` and `related.prs: [42]`, no warning.
5. `test_lint_warns_on_done_spec_with_empty_related_prs` — `related.prs: []` is treated as missing.
6. `test_fmt_entry_renders_list_as_bracketed_comma_join` — INDEX line for a spec with `related.prs: [42, 51]` contains `prs: [42, 51]`.

Existing tests stay green.

## Edge cases

- **Plan finished via `/task-finish`, never shipped.** Flips to done with no PR; warning fires on next lint. Acceptable — the warning is the signal. The user can run `/task-ship` later and step 6 will backfill, or invoke `board.py set-pr` manually.
- **Plan finished via `/task-ship` pre-flight, then PR opened.** Finish happens *before* `$PR` is captured. Step 6 backfills via `set-pr` and creates a small follow-up commit.
- **`/task-ship` reused an existing open PR.** `$PR` is still captured the same way; backfill is idempotent on the same PR number (dedup on the spec, no-op on the plan), so reruns don't churn the diff.
- **Plan's linked spec doesn't exist on disk** (manual deletion or rename). `set-pr` writes the plan's `related.pr` and skips the spec append with a printed notice. Doesn't error.
- **Spec shared by another active plan.** Spec status stays `active`; `related.prs` still gets the new PR appended.
- **PR number 0 or negative.** `_cmd_set_pr` validates `> 0` and exits 1. No silent garbage in frontmatter.
- **`set-pr` called on an active plan.** Errors and exits 1. `set-pr` only operates on `status: done` plans. This rules out using it to attach a PR mid-implementation, which would be premature.
- **`set-pr` run twice with the same PR.** Idempotent: plan's `related.pr` already equals the new value (no write needed), spec's `related.prs` dedups. `git status --porcelain` empty, no follow-up commit.
- **`set-pr` run with a different PR than already written.** Plan's `related.pr` is overwritten (last-wins, scalar). Spec's `related.prs` appends the new one. The plan-level mismatch is a user error (a plan ships in exactly one PR); acceptable. The spec-level append is correct.
- **Branch has multiple done plans.** Shouldn't happen under normal use (one active plan per branch invariant), but if it does, `set-pr` errors out clearly: "Multiple done plans on branch X — refusing to ambiguously assign PR." Forces the user to disambiguate manually.
- **Frontmatter parser sees `key: [foo` (malformed).** Falls back to treating the value as a string `"[foo"`, same as any other unrecognized shape. No exception.

## Out of scope follow-ups

- Documenting `board.py set-pr` as a user-facing manual backfill workflow in `docs/customization.md`. (The command exists; just no docs yet.)
- Block-style YAML list support in the parser.
- Rendering PR numbers in INDEX.md as clickable GitHub links (would require knowing the repo slug).
- Tracking merge SHAs or commit lists alongside PR numbers.
- Promoting the warning to an error gated by a config flag.
- Backfill tooling to populate PR numbers on historical done docs via git history.
