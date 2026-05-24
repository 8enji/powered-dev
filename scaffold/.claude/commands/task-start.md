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
