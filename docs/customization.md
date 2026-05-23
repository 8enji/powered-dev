# Customization

powered-dev is designed to be forked and adapted. Everything is plain files — no build step, no config service.

## Gate command

The gate command is the single most important configuration point. It's the command that must pass before a task can be marked done, and it's wired into the Claude Code pre-commit hook.

Set during `/init-workflow` setup, it appears in two places:

- **`CLAUDE.md`** — the "before claiming done" instruction.
- **`.claude/settings.json`** — the PreToolUse hook that fires before `git commit`.

To change it after setup, update both files. Common examples:

```
make all                           # Makefile-based projects
npm run lint && npm test           # Node.js
ruff check . && pytest             # Python
cargo clippy && cargo test         # Rust
go vet ./... && go test ./...      # Go
```

## CLAUDE.md line budget

The pre-commit hook enforces a line budget on `CLAUDE.md` (default: 50 lines). This keeps the file focused — CLAUDE.md should be a concise reference, not a novel.

Override with an environment variable:

```bash
export POWERED_DEV_CLAUDE_MD_MAX_LINES=80
```

Or set it in your shell profile to make it permanent.

## Task tiers

`/task-start` asks for a tier:

- **full** — creates both a spec stub and a plan stub. Use for features, design changes, anything that benefits from upfront thinking.
- **lite** — creates only a plan stub. Use for typo fixes, small renames, doc-only changes, chores.

The tier affects the plan template (full plans have a `related.spec` field) and which superpowers skill is invoked (brainstorming for full, plan-writing for lite).

## Codex review

`/request-codex-review` is optional — installed only if you opt in during `/init-workflow`. It can review either a GitHub PR or local-only changes that have not been opened as a PR yet. It requires:

- [Codex.app](https://codex.openai.com/) installed locally.
- `jq` available on PATH.
- For PR reviews: `gh` CLI authenticated (`gh auth login`).

For PR reviews, the command dispatches Codex in a read-only sandbox against the PR diff, parses structured findings, and posts them as inline GitHub PR review comments. Findings with `severity: critical` trigger `REQUEST_CHANGES`; everything else is `COMMENT`.

For local-change reviews, run `/request-codex-review local` or run `/request-codex-review` from a branch without an open PR. The command reviews staged, unstaged, untracked, and locally committed branch changes, then writes a markdown report under `docs/superpowers/reports/`.

To add it after initial setup, copy these files from the powered-dev scaffold:

```
.claude/commands/request-codex-review.md
.claude/codex/review-prompt.md
.claude/codex/review-findings.schema.json
```

## Frontmatter schema

Documents in `docs/superpowers/` must have YAML frontmatter. Required fields:

| Field | Values | Notes |
|-------|--------|-------|
| `status` | `active`, `done`, `abandoned` | Drives board state |
| `type` | `spec`, `plan`, `report`, `handoff` | Determines index grouping |
| `date` | `YYYY-MM-DD` | Creation date |
| `summary` | Free text | Short description |

Plans additionally require:

| Field | Values | Notes |
|-------|--------|-------|
| `branch` | Git branch name | Links plan to branch for merge gate |
| `tier` | `full`, `lite` | Determines plan template |

Full-tier plans also have:

```yaml
related:
  spec: filename.md
```

## Superpowers plugin

powered-dev works without the superpowers plugin, but pairs well with it. Superpowers provides a structured skill chain:

1. **Brainstorming** — explore approaches before committing to one.
2. **Writing specs** — fill the spec stub created by `/task-start`.
3. **Writing plans** — fill the plan stub with concrete implementation steps.
4. **TDD** — test-driven development workflow.
5. **Verification** — confirm the implementation matches the plan.

When superpowers is installed, `/task-start` automatically chains into the appropriate skill. Without it, you fill the stubs manually.

## Disabling enforcement rings

### Disable Claude Code hooks

Remove or comment out entries in `.claude/settings.json` under `hooks.PreToolUse`.

### Disable git pre-commit hook

```bash
git commit --no-verify
```

Or remove the hook:

```bash
rm .git/hooks/pre-commit
```

### Disable GitHub Actions gate

Delete `.github/workflows/board-gate.yml` or add `if: false` to the job.

## Adding custom hooks

The `.claude/settings.json` PreToolUse array is extensible. Each entry has:

- `matcher` — tool name to intercept (e.g., `Bash`).
- `hooks[].if` — glob pattern for the command (e.g., `Bash(git push*)`).
- `hooks[].command` — shell command to run. Exit 0 to allow, exit 2 to block.
- `hooks[].timeout` — milliseconds.
- `hooks[].statusMessage` — shown in Claude Code UI while running.

## Backlog format

`docs/board/backlog.md` uses `## Title` headings. Content under each heading is free-form — use it for notes, acceptance criteria, links, or leave it empty.

```markdown
## Add user authentication

OAuth2 with GitHub provider. See RFC-1234.

## Fix timezone bug in reports

Reports show UTC instead of user's local timezone.

## Update README screenshots
```

Titles must be unique (enforced by the pre-commit hook).
