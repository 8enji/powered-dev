---
description: Mark current branch's active plan done, flip its spec, regen the board.
---

Finish the task on the current branch.

1. Confirm the plan is genuinely complete: all top-level checkboxes ticked, gate command passes.
2. Run: `python3 scripts/board.py finish`
3. Review the staged diff and commit. Commit message format: `chore(board): finish task — <plan summary>`.
4. The merge gate will now permit `git merge` / `gh pr create` for this branch.
