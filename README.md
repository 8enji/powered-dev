# powered-dev

Structured workflow for Claude Code projects. Board system, merge gates,
slash commands, and CI — language-agnostic, zero external dependencies.

## Quick start

```bash
mkdir -p .claude/commands
curl -sL https://raw.githubusercontent.com/8enji/powered-dev/main/init-workflow.md \
  -o .claude/commands/init-workflow.md
```

Then in Claude Code:

```
/init-workflow
```

## What you get

- **Board system** — `docs/board/backlog.md` -> `/task-start` -> spec/plan stubs -> `/task-finish` -> merge unlocked
- **Merge gates** — three rings: Claude Code PreToolUse hook, git pre-commit hook, GitHub Action
- **Slash commands** — `/task-backlog`, `/task-start`, `/task-finish`, `/task-ship`, `/request-codex-review` (optional)
- **Doc indexing** — auto-generated `INDEX.md` from YAML frontmatter, drift-checked on commit

## Requirements

- `python3` (3.9+, no pip packages)
- `bash`
- `git`
- `gh` CLI (for `/task-ship`)
- `jq` (for `/request-codex-review`)

## Recommended

Install the [superpowers](https://github.com/anthropics/claude-code-plugins) Claude Code plugin
for the full skill chain: brainstorm -> spec -> plan -> TDD -> verify.

During `/init-workflow`, powered-dev checks for superpowers and can install it with:

```
/plugin install superpowers@claude-plugins-official
```

## Happy path

After `/init-workflow` installs the scaffold:

1. Add work to `docs/board/backlog.md` as a `## Task title` heading with notes beneath it.
2. Run `/task-start`, pick the backlog title, and choose `full` for design-heavy work or `lite` for small changes.
3. Work normally. The active plan appears in `docs/board/in-flight.md`, and supporting docs are indexed in `docs/superpowers/INDEX.md`.
4. Run `/task-finish` when the implementation, plan checkboxes, and project gate command are complete.
5. Run `/task-ship` to commit, push, open or reuse a PR, watch CI, optionally request `/request-codex-review`, and merge when ready.

## Failure recovery

- **Active plan blocks push or PR creation** — run `/task-finish` if the work is complete, or `python3 scripts/board.py abandon` if the task should be closed without shipping.
- **Commit fails after docs regenerate** — review the regenerated `docs/board/in-flight.md` or `docs/superpowers/INDEX.md`, stage the generated file, and commit again.
- **Codex review wakes up later** — continue from the same conversation. The review command stores state under `/tmp/codex-review-*.state.json` or `/tmp/codex-local-review-*.state.json` so the agent can resume posting the review or writing the local report.
- **CI watch fails or has no required checks** — `/task-ship` will ask whether to watch non-required checks, merge now, stop, open the run, print logs, or invoke systematic debugging.

## How it works

See [docs/how-it-works.md](docs/how-it-works.md).

## Customization

See [docs/customization.md](docs/customization.md).

## License

MIT
