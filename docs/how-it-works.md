# How it works

powered-dev adds a lightweight task board and enforcement layer to your Claude Code workflow. Everything lives in your repo — no external services, no plugins required.

## The board

Two files track work:

- **`docs/board/backlog.md`** — you maintain this. Each `## Title` heading is a task. Add notes, links, acceptance criteria under each heading.
- **`docs/board/in-flight.md`** — auto-generated. Derived from plan files that have `status: active` in their YAML frontmatter.

## Task lifecycle

```
backlog.md          /task-start           work + commits           /task-finish
┌──────────┐    ┌──────────────────┐    ┌──────────────┐    ┌──────────────────┐
│ ## Title  │───▶│ scaffold plan/   │───▶│ normal dev   │───▶│ flip plan to     │
│           │    │ spec stubs       │    │ loop         │    │ done             │
└──────────┘    └──────────────────┘    └──────────────┘    └──────────────────┘
                                                                     │
                                                              /task-ship
                                                            ┌──────────────────┐
                                                            │ commit, push,    │
                                                            │ open PR, watch   │
                                                            │ CI, merge        │
                                                            └──────────────────┘
```

### `/task-start`

Picks a backlog item and runs `board.py start`, which:

1. Removes the entry from `backlog.md`.
2. Creates a plan stub in `docs/superpowers/plans/` with `status: active` and `branch: <current-branch>`.
3. For **full** tier tasks, also creates a spec stub in `docs/superpowers/specs/`.
4. Regenerates `in-flight.md`.

If the superpowers plugin is installed, it then chains into brainstorming (full tier) or plan writing (lite tier).

### `/task-finish`

Runs `board.py finish`, which flips the active plan's status to `done` (and linked spec if applicable). The merge gate now allows push/merge/PR creation for this branch.

### `/task-ship`

Handles the full ship cycle: commit with a drafted message, push, open or reuse a PR, watch CI in the background, then prompt to merge (green) or debug (red).

## Three-ring enforcement

The board system enforces task completion through three independent mechanisms:

### Ring 1: Claude Code PreToolUse hooks

Defined in `.claude/settings.json`. These fire before Claude executes certain shell commands:

- **Pre-commit gate**: runs your gate command (lint + typecheck + test) before `git commit`.
- **Pre-merge/push/PR gate**: calls `board.py check-merge` before `git merge`, `git push`, or `gh pr create`. Blocks if the branch has an active (unfinished) plan.

### Ring 2: Git pre-commit hook

A shell script at `scripts/githooks/pre-commit` that runs on every `git commit`:

- Regenerates `in-flight.md` and `INDEX.md`, catching drift.
- Lints backlog for duplicate titles.
- Lints YAML frontmatter on staged doc files.
- Enforces `CLAUDE.md` line budget.

### Ring 3: GitHub Actions

`.github/workflows/board-gate.yml` runs `board.py check-pr` on pull requests. Fails the check if the PR's branch still has an active plan — preventing merge via GitHub branch protection.

## Document indexing

`docs_index.py` maintains `docs/superpowers/INDEX.md` — an auto-generated catalog of all specs, plans, reports, and handoffs. Each document must have YAML frontmatter with required fields (`status`, `type`, `date`, `summary`). The pre-commit hook validates this.

## File overview

```
scripts/
  board.py           Board lifecycle automation (start, finish, check-merge, etc.)
  docs_index.py      Frontmatter indexer (regenerate INDEX.md, lint)
  frontmatter.py     Zero-dep YAML frontmatter parser
  githooks/
    pre-commit       Git hook — board checks, index drift, frontmatter lint
  claude_hooks/
    pre_merge_gate.sh  Claude Code hook — blocks merge/push/PR if plan active

.claude/
  commands/
    task-start.md      Pick up a backlog item
    task-finish.md     Mark current task done
    task-backlog.md    View and triage backlog
    task-ship.md       Commit, push, PR, CI, merge
    request-codex-review.md  (optional) Codex-powered PR/local review
  codex/
    review-prompt.md           Codex review instructions
    review-findings.schema.json  Output schema for findings
  settings.json      PreToolUse hook definitions

.github/workflows/
  board-gate.yml     CI check for plan status

docs/
  board/
    backlog.md       Your task backlog (human-managed)
    in-flight.md     Active tasks (auto-generated)
  superpowers/
    INDEX.md         Document catalog (auto-generated)
    specs/           Design specs
    plans/           Implementation plans
    reports/         Post-mortems, investigations
    handoffs/        Context handoff documents
```
