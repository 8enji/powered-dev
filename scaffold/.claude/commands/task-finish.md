---
description: Mark current branch's active plan done, flip its spec, regen the board.
---

Finish the task on the current branch.

1. Confirm the plan is genuinely complete: all top-level checkboxes ticked, and the gate command documented in `CLAUDE.md` passes.
2. Run: `python3 scripts/board.py finish`
3. Review the staged diff. `board.py finish` stages the plan/spec/in-flight/index updates.
4. Either continue to `/task-ship`, which will include these staged files in its commit flow, or commit immediately. If committing now, use: `chore(board): finish task — <plan summary>`.
5. The merge gate will now permit `git merge` / `gh pr create` for this branch.
