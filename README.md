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
- **Slash commands** — `/task-backlog`, `/task-start`, `/task-finish`, `/task-ship`, `/task-codex-review` (optional)
- **Doc indexing** — auto-generated `INDEX.md` from YAML frontmatter, drift-checked on commit

## Requirements

- `python3` (3.9+, no pip packages)
- `bash`
- `git`
- `gh` CLI (for `/task-ship`)

## Recommended

Install the [superpowers](https://github.com/anthropics/claude-code-plugins) Claude Code plugin
for the full skill chain: brainstorm -> spec -> plan -> TDD -> verify.

## How it works

See [docs/how-it-works.md](docs/how-it-works.md).

## Customization

See [docs/customization.md](docs/customization.md).

## License

MIT
