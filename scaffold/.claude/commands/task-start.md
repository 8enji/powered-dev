---
description: Move a backlog item to in-flight (scaffold spec+plan stubs, or just plan for lite).
---

Pick a backlog item and start work on it.

1. Read `docs/board/backlog.md` and list each `## title`.
2. Ask the user which title to start, and which tier:
   - **full** — feature work, design discussion needed, user-visible behavior change.
   - **lite** — typo fixes, small renames, chore cleanups, doc-only changes.
3. Verify the current branch is not `main`/`master`. If it is, ask the user to create a branch first (do not proceed).
4. Run: `python3 scripts/board.py start "<exact title>" --tier <full|lite>`
5. Review the staged diff (`git diff --staged`) and commit if it looks right. Commit message format: `chore(board): start task — <title>`.
6. Next skill:
   - **full** → invoke `superpowers:brainstorming` to fill the spec stub at `docs/superpowers/specs/<date>-<slug>-design.md`.
   - **lite** → invoke `superpowers:writing-plans` to fill the plan stub at `docs/superpowers/plans/<date>-<slug>.md`.

If the superpowers plugin is not installed, skip step 6 and tell the user to fill the spec/plan stubs manually or install the superpowers plugin.
