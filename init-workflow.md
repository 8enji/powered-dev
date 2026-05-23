---
description: "One-time bootstrap — install the powered-dev workflow into this project. Removes itself when done."
---

Bootstrap the powered-dev workflow into this project.

**This is a one-time setup command.** It fetches scaffold files from the powered-dev repo, configures them for this project, and removes itself when done.

## Pre-flight

1. Confirm this is a git repo: `git rev-parse --is-inside-work-tree`. If not, stop with: "This must be a git repository. Run `git init` first."
2. Capture `REPO_ROOT=$(git rev-parse --show-toplevel)`.
3. Check branch: `BRANCH=$(git rev-parse --abbrev-ref HEAD)`. If `main` or `master`, warn the user: "You're on $BRANCH. Consider creating a feature branch first (e.g., `git checkout -b setup-powered-dev`). Continue anyway?" Options: **Continue on $BRANCH** / **Stop (I'll create a branch)**. On Stop, exit.
4. Check for superpowers plugin. Run:
   ```bash
   PLUGIN_DIRS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins"
   if [ -d "$PLUGIN_DIRS" ] && ls "$PLUGIN_DIRS"/*/superpowers 2>/dev/null | head -1 | grep -q .; then
     echo "INSTALLED"
   elif [ -d "$HOME/.claude/plugins" ] && find "$HOME/.claude/plugins" -name "superpowers" -type d 2>/dev/null | head -1 | grep -q .; then
     echo "INSTALLED"
   else
     echo "NOT_INSTALLED"
   fi
   ```
   If `NOT_INSTALLED`, explain: "The **superpowers** plugin provides a structured skill chain (brainstorm → spec → plan → TDD → verify) that pairs well with powered-dev's board system. powered-dev works without it, but `/task-start` can guide implementation work more effectively when it is installed." Then ask: "Install superpowers plugin?" Options: **Install now** / **Skip for now**.
   - On **Install now**, run `/plugin install superpowers@claude-plugins-official`. If the install succeeds, continue. If it fails, surface the error and ask whether to continue without superpowers.
   - On **Skip for now**, continue and explain that `/task-start` will still create spec/plan stubs, but the user or agent will fill them manually.

## Step 1 — Gather configuration

Use `AskUserQuestion` for each. Collect all answers before proceeding.

1. **Project description** (1-2 sentences for CLAUDE.md `## What this is` section).
   - Question: "Short project description (1-2 sentences)?"
   - No default. Required.

2. **Gate command** — the command that must pass before claiming a task is done. This is also wired into the pre-commit Claude hook.
   - Question: "What command should pass before a task can be marked done? This typically chains lint + typecheck + test."
   - Options: **`make all`** / **`npm run lint && npm test`** / **`ruff check . && pytest`** / Custom
   - Required.

3. **Codex review** — whether to install the `/request-codex-review` slash command.
   - Question: "Install Codex automated review (`/request-codex-review`)? Supports PR and local-change reviews. Requires Codex.app."
   - Options: **Yes** / **No**
   - Default: No.

Store answers as `$PROJECT_DESCRIPTION`, `$GATE_CMD`, `$INSTALL_CODEX`.

## Step 2 — Fetch scaffold

Fetch the scaffold tarball from the powered-dev repo. Use a temp directory to stage files before copying.

```bash
STAGING=$(mktemp -d)
REPO_URL="https://github.com/8enji/powered-dev"
BRANCH_REF="main"

# Download the scaffold directory via GitHub's tarball API
curl -sL "$REPO_URL/archive/refs/heads/$BRANCH_REF.tar.gz" \
  | tar -xz -C "$STAGING" --strip-components=2 "powered-dev-$BRANCH_REF/scaffold"

# Verify key files exist
test -f "$STAGING/scripts/board.py" || { echo "error: scaffold fetch failed — board.py not found"; exit 1; }
```

## Step 3 — Copy files into the project

For each file below, check if it already exists in the target project. If it does, ask the user: "File `<path>` already exists. Overwrite?" Options: **Overwrite** / **Skip**. Apply the user's choice.

### Always installed

| Source (in staging) | Destination (in repo) |
|---|---|
| `scripts/board.py` | `scripts/board.py` |
| `scripts/docs_index.py` | `scripts/docs_index.py` |
| `scripts/frontmatter.py` | `scripts/frontmatter.py` |
| `scripts/githooks/pre-commit` | `scripts/githooks/pre-commit` |
| `scripts/claude_hooks/pre_merge_gate.sh` | `scripts/claude_hooks/pre_merge_gate.sh` |
| `.claude/commands/task-start.md` | `.claude/commands/task-start.md` |
| `.claude/commands/task-finish.md` | `.claude/commands/task-finish.md` |
| `.claude/commands/task-ship.md` | `.claude/commands/task-ship.md` |
| `.github/workflows/board-gate.yml` | `.github/workflows/board-gate.yml` |
| `docs/board/backlog.md` | `docs/board/backlog.md` |
| `docs/superpowers/INDEX.md` | `docs/superpowers/INDEX.md` |
| `docs/superpowers/specs/.gitkeep` | `docs/superpowers/specs/.gitkeep` |
| `docs/superpowers/plans/.gitkeep` | `docs/superpowers/plans/.gitkeep` |
| `docs/superpowers/reports/.gitkeep` | `docs/superpowers/reports/.gitkeep` |
| `docs/superpowers/handoffs/.gitkeep` | `docs/superpowers/handoffs/.gitkeep` |

### Conditionally installed (if `$INSTALL_CODEX` is Yes)

| Source (in staging) | Destination (in repo) |
|---|---|
| `.claude/commands/request-codex-review.md` | `.claude/commands/request-codex-review.md` |
| `.claude/codex/review-prompt.md` | `.claude/codex/review-prompt.md` |
| `.claude/codex/review-findings.schema.json` | `.claude/codex/review-findings.schema.json` |

Create all necessary parent directories with `mkdir -p` before copying. Use `cp` for each file.

## Step 4 — Configure templates

### 4a. Render CLAUDE.md

Read `CLAUDE.md.template` from the staging directory. Replace:
- `__PROJECT_DESCRIPTION__` → `$PROJECT_DESCRIPTION`
- `__GATE_CMD__` → `$GATE_CMD`

Save the rendered result. Then:
- If `CLAUDE.md` does not exist → write the rendered template as `CLAUDE.md`.
- If `CLAUDE.md` already exists → append the rendered template's content under a `## powered-dev workflow` header. Ask first: "CLAUDE.md already exists. Append workflow rules?" Options: **Append** / **Skip**.

### 4b. Render settings.json hooks

Read `.claude/settings.json` from the staging directory. Replace:
- `__GATE_CMD__` → `$GATE_CMD`, but first JSON-escape the value (backslashes and double quotes must be escaped so the resulting `.claude/settings.json` remains valid JSON). Use: `ESCAPED_GATE=$(printf '%s' "$GATE_CMD" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')` and substitute `$ESCAPED_GATE` in place of `__GATE_CMD__`.

Then merge into the project's `.claude/settings.json`:
- If `.claude/settings.json` does not exist → write the rendered file directly.
- If `.claude/settings.json` exists:
  1. Read the existing file as JSON.
  2. Read the scaffold file as JSON.
  3. Merge `hooks.PreToolUse`: concatenate the scaffold's `PreToolUse` array entries to the existing array (avoid duplicates by checking `statusMessage` fields).
  4. Write the merged result.

Use `python3 -c` for the merge:
```bash
python3 -c "
import json, sys
existing = json.load(open(sys.argv[1]))
scaffold = json.load(open(sys.argv[2]))
existing.setdefault('hooks', {}).setdefault('PreToolUse', [])
existing_msgs = {h.get('statusMessage','') for entry in existing['hooks']['PreToolUse'] for h in entry.get('hooks',[])}
for entry in scaffold.get('hooks',{}).get('PreToolUse',[]):
    dominated = all(h.get('statusMessage','') in existing_msgs for h in entry.get('hooks',[]))
    if not dominated:
        existing['hooks']['PreToolUse'].append(entry)
json.dump(existing, open(sys.argv[1], 'w'), indent=2)
print('Merged hooks into .claude/settings.json')
" "$REPO_ROOT/.claude/settings.json" "$STAGING/.claude/settings.json"
```

## Step 5 — Install git hooks

```bash
HOOKS_DIR=$(git -C "$REPO_ROOT" config core.hooksPath 2>/dev/null || echo "$REPO_ROOT/.git/hooks")
mkdir -p "$HOOKS_DIR"
DEST="$HOOKS_DIR/pre-commit"
if [ -f "$DEST" ]; then
    echo "A pre-commit hook already exists at $DEST."
fi
```

If a pre-commit hook already exists, ask: "A git pre-commit hook already exists. How should we handle it?" Options:
- **Append** — add a call to `scripts/githooks/pre-commit` at the end of the existing hook.
- **Replace** — overwrite with the powered-dev hook.
- **Skip** — leave the existing hook alone.

On **Append**:
```bash
echo "" >> "$DEST"
echo "# powered-dev board checks" >> "$DEST"
echo "bash \"\$(git rev-parse --show-toplevel)/scripts/githooks/pre-commit\"" >> "$DEST"
```

On **Replace**:
```bash
cp "$REPO_ROOT/scripts/githooks/pre-commit" "$DEST"
chmod +x "$DEST"
```

If no hook exists:
```bash
cp "$REPO_ROOT/scripts/githooks/pre-commit" "$DEST"
chmod +x "$DEST"
```

Ensure the hook is executable: `chmod +x "$DEST"`.

## Step 6 — Cleanup

```bash
rm -rf "$STAGING"
rm -f "$REPO_ROOT/.claude/commands/init-workflow.md"
```

The init command removes itself — it's a one-time bootstrap.

## Step 7 — Summary

Print a summary of what was installed:

```
powered-dev installed successfully!

Installed:
  scripts/board.py, docs_index.py, frontmatter.py
  scripts/githooks/pre-commit
  scripts/claude_hooks/pre_merge_gate.sh
  .claude/commands/task-{start,finish,ship}.md
  [if codex] .claude/commands/request-codex-review.md + codex support files
  .claude/settings.json (hooks merged)
  .github/workflows/board-gate.yml
  docs/board/backlog.md
  docs/superpowers/ directory tree
  CLAUDE.md [created|updated]
  Git pre-commit hook [installed|appended|skipped]

Next steps:
  1. Review the changes: git diff
  2. Add tasks to docs/board/backlog.md
  3. Run /task-start to begin your first task
  4. Run /task-ship when the task is ready to finish and ship
```

## Edge cases

- **Not a git repo**: caught in pre-flight.
- **No network / curl fails**: the tarball download step will fail; surface the error.
- **Existing files**: handled per-file with skip/overwrite prompt.
- **Existing `.claude/settings.json`**: non-destructive merge of hook arrays.
- **Existing CLAUDE.md**: append mode preserves user content.
- **Existing git hooks**: append/replace/skip choice.
- **`core.hooksPath` configured**: respected via `git config core.hooksPath`.
- **No python3**: board.py will fail later; pre-flight could check but keeping it simple — Python 3 is ubiquitous.
