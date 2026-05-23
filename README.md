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

- **Board system** — `docs/board/backlog.md` -> `/task-start` -> spec/plan stubs -> `/task-ship`
- **Merge gates** — three rings: Claude Code PreToolUse hook, git pre-commit hook, GitHub Action
- **Slash commands** — `/task-start`, `/task-ship`; `/task-finish` for manual completion; `/request-codex-review` as an optional separate review command
- **Doc indexing** — auto-generated `INDEX.md` from YAML frontmatter, drift-checked on commit

## Requirements

- `python3` (3.9+, no pip packages)
- `bash`
- `git`
- `gh` CLI (for `/task-ship`)
- `jq` (for optional `/request-codex-review`)

## Recommended

Install the [superpowers](https://github.com/anthropics/claude-code-plugins) Claude Code plugin
for the full skill chain: brainstorm -> spec -> plan -> TDD -> verify.

During `/init-workflow`, powered-dev checks for superpowers and can install it with:

```
/plugin install superpowers@claude-plugins-official
```

## Happy path

1. Run `/init-workflow` once to install the scaffold.
2. Add work to `docs/board/backlog.md`, then run `/task-start`, pick the backlog title, and choose `full` for design-heavy work or `lite` for small changes.
3. Work normally, then run `/task-ship`. It can finish the active plan, commit, push, open or reuse a PR, watch CI, and merge when ready.

Optional: run `/request-codex-review` separately when you want a Codex review of a PR or local change set.

## Failure recovery

- **Active plan blocks push or PR creation** — `/task-ship` can finish the active plan inline if the work is complete, or run `python3 scripts/board.py abandon` if the task should be closed without shipping.
- **Commit fails after docs regenerate** — review the regenerated `docs/superpowers/INDEX.md`, stage it, and commit again.
- **Codex review wakes up later** — continue from the same conversation. The review command stores state under `/tmp/codex-review-*.state.json` or `/tmp/codex-local-review-*.state.json` so the agent can resume posting the review or writing the local report.
- **CI watch fails or has no required checks** — `/task-ship` will ask whether to watch non-required checks, merge now, stop, open the run, print logs, or invoke systematic debugging.

## How it works

See [docs/how-it-works.md](docs/how-it-works.md).

## Customization

See [docs/customization.md](docs/customization.md).

## License

MIT
