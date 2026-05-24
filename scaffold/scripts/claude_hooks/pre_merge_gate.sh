#!/usr/bin/env bash
# Claude Code PreToolUse hook. Wired in .claude/settings.json.
#
# Fires on `git merge`, `git push`, or `gh pr create`. Blocks (exit 2) when
# the target branch has an active plan in docs/superpowers/plans/. Forces the
# agent to finish the active plan before merging.

set -euo pipefail

CMD=$(jq -r '.tool_input.command // empty')
FIRST_LINE=$(head -1 <<<"$CMD")

git_merge='^git( +-[cC] +[^ ]+)* +merge( |$)'
gh_pr='^gh +pr +create( |$)'
git_push='^git +push( |$)'

REPO_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$REPO_ROOT"

if [[ "$FIRST_LINE" =~ $gh_pr ]] || [[ "$FIRST_LINE" =~ $git_push ]]; then
    TARGET=$(git rev-parse --abbrev-ref HEAD)
    python3 "$REPO_ROOT/scripts/board.py" check-merge "$TARGET" 1>&2 || exit 2
elif [[ "$FIRST_LINE" =~ $git_merge ]]; then
    CURRENT=$(git rev-parse --abbrev-ref HEAD)
    if [[ "$CURRENT" != "main" && "$CURRENT" != "master" ]]; then
        exit 0
    fi
    python3 "$REPO_ROOT/scripts/board.py" check-merge-cmd "$FIRST_LINE" 1>&2 || exit 2
fi
exit 0
