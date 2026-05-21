---
description: Summarize backlog tasks for the human orchestrator.
---

Show the backlog so the user can pick what to work on next.

1. Read `docs/board/backlog.md`. Extract each `## title` and the lines beneath it (until the next `## ` or `---` separator).
2. For each entry, get the date it was added: `git blame -L "/^## <title>$/,+1" docs/board/backlog.md` and take the commit date.
3. Classify each entry as **full** or **lite** based on the notes. Heuristics:
   - lite: typo/rename/chore/doc-only/single-file refactor language.
   - full: behavior change, new module, design discussion, "rethink"/"design"/"system" in the title.
4. Group output:
   - **Quick wins (lite candidates)** — oldest first.
   - **Substantial work (full candidates)** — oldest first.
5. Read `docs/board/in-flight.md`. Close with one line: "Currently N in-flight tasks. Suggest <title> next — <one-clause reason>."
6. One line per item. No commentary unless asked.
