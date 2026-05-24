# powered-dev

A repo-local workflow for Claude Code projects. Adds a task board, three rings of merge enforcement, and `/task-start` + `/task-ship` slash commands — so the agent can't accidentally ship half-finished work.

Zero external dependencies. Language-agnostic. Pairs with the [superpowers](https://github.com/anthropics/claude-code-plugins) plugin.

<!-- TODO: asciinema embed once recorded -->

## A task, end to end

Say your `docs/board/backlog.md` has one entry:

```markdown
## Add a /healthz endpoint
```

1. **`/task-start`** picks the entry and asks `full` vs. `lite`. It scaffolds `docs/superpowers/plans/2026-05-24-add-a-healthz-endpoint.md` with `status: active` and `branch: <current-branch>`, removes the entry from the backlog, and regenerates `docs/superpowers/INDEX.md`. The plan file is the source of truth for what's in flight.

2. **The superpowers plugin takes over** (if installed). It chains into brainstorming for `full` (explore approaches, write a spec, then a plan) or straight to plan-writing for `lite`. The stub becomes a real implementation plan with TDD steps.

3. **You implement.** Edit code, run tests. Nothing about powered-dev gets in your way during the work itself.

4. **Claude Code goes to commit.** A PreToolUse hook fires your gate command (lint + typecheck + test) before `git commit` runs; if it fails, the commit doesn't happen and Claude sees the failure. Independently, the git pre-commit hook regenerates `INDEX.md` and lints the YAML frontmatter on every staged doc.

5. **`/task-ship`** is the end-of-task command. It marks the active plan `done`, drafts a commit message from the diff, commits, pushes, and opens (or reuses) a PR. It then watches CI in the background and prompts you to merge when green — or hands off to systematic debugging if red.

6. **If the agent tries to push before the plan is finished**, a second PreToolUse hook blocks `git push` / `git merge` / `gh pr create` until the plan flips to `done`. `/task-ship` knows about this and can finish the plan inline when the work really is complete.

7. **The PR opens.** GitHub Actions runs `board.py check-pr`, which fails the required check if any plan on the PR's branch is still active. Branch protection turns that into a hard merge block.

Three independent checks. The agent can bypass one in a moment of cleverness; it can't bypass all three.

## The three rings

| Ring | Where | What it blocks |
|---|---|---|
| **1 — Claude Code hooks** | `.claude/settings.json` PreToolUse | gate command before commit; active-plan check before push/merge/PR |
| **2 — Git pre-commit hook** | `scripts/githooks/pre-commit` | INDEX drift, duplicate backlog titles, malformed frontmatter |
| **3 — GitHub Action** | `.github/workflows/board-gate.yml` | PR check: active plan still on the branch |

## Install

One-time, from any git repo:

```bash
mkdir -p .claude/commands
curl -sL https://raw.githubusercontent.com/8enji/powered-dev/main/init-workflow.md \
  -o .claude/commands/init-workflow.md
```

Then, in Claude Code:

```
/init-workflow
```

`/init-workflow` asks for a project description and a gate command (e.g., `make all`, `npm run lint && npm test`, `ruff check . && pytest`), wires up the hooks, installs the scaffold, and removes itself.

## Requirements

`python3` (3.9+, no pip packages), `bash`, `git`, `gh` CLI for `/task-ship`, `jq` for the optional `/request-codex-review` command.

## Pairs with superpowers

Without [superpowers](https://github.com/anthropics/claude-code-plugins), powered-dev creates spec/plan stubs and you fill them. With it, `/task-start` chains into brainstorming → spec → plan → TDD → verify. The `/init-workflow` flow offers to install it for you.

## More

- [How it works](docs/how-it-works.md) — lifecycle, file layout, recovery
- [Customization](docs/customization.md) — gate command, tiers, hooks, frontmatter schema

## License

MIT.
