---
status: active
type: spec
date: 2026-05-23
summary: Let /task-start create ad hoc tasks directly when the backlog is empty or the user supplies a title
---

# /task-start ad hoc tasks

## Problem

`/task-start` today requires the task title to exist as a `## heading` in `docs/board/backlog.md`. `board.py start` errors with "Backlog entry not found" otherwise, and a missing backlog file is also fatal. This forces a two-step ritual for any work the user wants to start "right now": first edit the backlog, then run the command. For one-off fixes, exploratory work, or projects that don't maintain a backlog at all, the friction outweighs the benefit.

## Goal

Allow `/task-start` to scaffold spec/plan stubs without a corresponding backlog entry, triggered either by an empty backlog or by an explicit title supplied to the command.

## Non-goals

- Changing the tier model (`full` vs. `lite`).
- Changing the active-plan-per-branch invariant — only one active plan per branch, still enforced.
- Changing `/task-ship`, `/task-finish`, the merge gate, the GitHub Action, or any hook.
- Adding a way to start ad hoc tasks at the CLI without also going through the slash command's branch check.

## User-facing behavior

The slash command grows three branches:

| Invocation | Backlog state | Behavior |
|---|---|---|
| `/task-start "My title"` | any | Use the arg as the title. If it matches a `## heading` in the backlog, that entry is consumed (removed) as today; otherwise the task is ad hoc and the backlog is untouched. |
| `/task-start` (no arg) | has `## heading` entries | Today's flow — list titles, user picks. |
| `/task-start` (no arg) | empty (no `## heading` entries, or file missing) | Prompt: "Backlog is empty. Title for the new task?" |

After the title is resolved, the tier prompt (`full`/`lite`) and the branch check (not `main`/`master`) are unchanged.

The chain into the next skill is unchanged: `full` invokes `superpowers:brainstorming`, `lite` invokes `superpowers:writing-plans`.

## `board.py` changes

Two relaxations inside `_cmd_start`:

1. **Missing backlog file is not fatal.** If `BACKLOG_PATH` does not exist, skip the backlog-removal step and continue. Today this exits with "Backlog not found at ...".
2. **Title not in backlog is not fatal.** When `_find_backlog_entry(...) is None`, print an informational line ("No matching backlog entry for '<title>' — creating ad hoc task.") and skip both `_remove_backlog_entry(...)` and adding `BACKLOG_PATH` to the staged-paths list. Today this exits with "Backlog entry not found".

Everything else in `_cmd_start` stays put:

- Active-plan-on-branch check still errors and exits 1.
- `--tier` still defaults to `lite` and validates `full`/`lite`.
- Spec stub (full tier) and plan stub render from the same templates with the same fields.
- `INDEX.md` is regenerated.
- `git add` stages the same touched files (just minus `BACKLOG_PATH` in the ad hoc case).

No new subcommand. No new flags.

## Slash command changes

Edit `scaffold/.claude/commands/task-start.md`:

- Step 1 becomes: "If a positional argument is provided, use it as the title. Otherwise, read `docs/board/backlog.md` and list each `## title`."
- Step 2 becomes: "If a title was provided as an argument, skip to step 3. Otherwise: if the backlog has at least one `## title`, ask the user which to start. If the backlog has no `## title` entries (or the file is missing), ask the user for an ad hoc title."
- Step 3 (branch check) and step 4 (run `board.py start ...`) are unchanged.
- Step 5 (review staged diff) and step 6 (chain into next skill) are unchanged.

The CLI call in step 4 stays `python3 scripts/board.py start "<exact title>" --tier <full|lite>`.

## Docs changes

- `docs/how-it-works.md`, under `### /task-start`: add a sentence noting that an arg or empty backlog creates an ad hoc task without requiring a backlog entry.
- `docs/customization.md`, under "Backlog format": add a note that `/task-start "Title"` works without a corresponding backlog entry.

## Testing

New tests in `scaffold/scripts/test_board.py`:

1. `test_start_creates_ad_hoc_when_title_absent_from_backlog` — backlog file exists with some other entry, call `_cmd_start("New Title", "lite")`, assert: plan file created, INDEX regenerated, backlog file NOT staged, backlog content unchanged on disk, exit success.
2. `test_start_creates_ad_hoc_when_backlog_file_missing` — no backlog file at all, call `_cmd_start("New Title", "lite")`, assert: plan file created, INDEX regenerated, exit success.
3. `test_start_full_tier_ad_hoc_creates_spec_and_plan` — same as (1) but tier `full`, assert spec stub also created.

Existing tests stay green unchanged:

- `test_start_rejects_duplicate_active_plan` — active-plan-on-branch still errors.
- `test_start_stages_backlog_plan_and_index_without_in_flight` — backlog-match path unchanged.

The covenant test `test_board_module_has_no_in_flight_symbols` is unrelated and stays.

## Edge cases

- **Title arg exactly matches a backlog `##` heading** — treated as a backlog match, entry is removed (no behavior change vs. today's interactive picker).
- **Backlog file contains only HTML comments / no `## heading`** — slash command treats as empty and prompts for a title. `board.py` would find no entry to remove and continue silently (the slash command never asks `board.py` about a backlog title in this case).
- **Active plan already exists on the branch** — still errors; user must `/task-finish` or `board.py abandon` first.
- **Branch is `main`/`master`** — slash command stops before invoking `board.py` (unchanged).
- **CLI user runs `board.py start "typo-of-real-title"`** — silently produces an ad hoc task instead of erroring. The "No matching backlog entry" line is the only signal. This is an accepted trade-off for keeping a single CLI surface; the slash command's picker is the primary UX for backlog-driven starts.

## Out of scope follow-ups (not in this change)

- A `--from-backlog` strict flag on `board.py start` for CI-style "must match" semantics.
- Accepting `--tier` as a slash command arg alongside the title.
- A separate `board.py adhoc` subcommand.
