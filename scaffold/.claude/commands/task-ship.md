---
description: One-shot — commit, push, open PR, watch CI, then prompt to merge (green) or invoke /systematic-debugging with logs (red).
---

Ship the current branch.

## Pre-flight

1. Run `BRANCH=$(git rev-parse --abbrev-ref HEAD)`. If the result is `main` or `master`, stop and tell the user to create a branch first. If the result is the literal string `HEAD` (detached state — mid-rebase, checked out a commit directly, etc.), stop and tell the user to check out a feature branch first; do **not** attempt to push from detached HEAD.
2. Run `python3 scripts/board.py check-merge "$BRANCH"` before committing or pushing.
   - If it passes, continue.
   - If it blocks because the branch still has an active plan, ask: "This branch still has an active plan. Finish it and continue shipping?" Options: **Finish and continue** / **Stop**.
   - On **Finish and continue**:
     1. **Verify the plan is complete.** Find the active plan file under `docs/superpowers/plans/` whose frontmatter has `status: active` and `branch: $BRANCH`. Read its body; every top-level checkbox (`- [ ]` at column 0) must be `- [x]`. If any are unticked, list them and stop.
     2. **Verify the gate passes.** Find the gate command in `CLAUDE.md` (the `Before claiming done → run <command>` line) and run it. If it exits non-zero, surface the output and stop.
     3. Only after both pass: run `python3 scripts/board.py finish`, then rerun `python3 scripts/board.py check-merge "$BRANCH"`. If it still blocks, surface the message and stop.
   - On **Stop**, exit. The user can resume later — either run `/task-ship` again when the work is ready, or run `python3 scripts/board.py finish` directly to flip status without shipping.
   - For any other failure, surface the command output and stop.
3. The `PreToolUse` Bash hooks (`pre_merge_gate.sh` on `git push` / `gh *`) will also fire during the steps below. If any of them blocks, surface the hook's message and stop.

## 1. Commit + push

1. Run `git status --porcelain`. If the output is empty AND `git rev-list @{u}..HEAD --count` returns `0`, skip to section 2 (nothing to commit or push). If the `rev-list` command fails because there is no upstream configured (`fatal: no upstream configured`), treat the skip condition as false — i.e., proceed normally; the push step will create the upstream.
2. If the working tree is dirty (porcelain not empty):
   1. Run `git diff --staged` and `git diff` to see all changes.
   2. Read recent commit messages with `git log -5 --oneline` to match scope/style.
   3. Draft a commit message in the form `<type>(<scope>): <subject>` (one-line subject; multi-line body optional but encouraged for non-trivial changes).
   4. Use `AskUserQuestion` to confirm. Question: "Commit message?" Options: **Use draft** / **Let me edit** / **Abort**. On **Let me edit**, ask the user for the replacement message in a follow-up turn, then continue with step 5. On **Abort**, stop — do not commit or push.
   5. On confirmation, stage with an **explicit file list** (never `git add -A` / `git add .`): `git add <file1> <file2> ...`.
   6. Commit using a heredoc. **Important:** when you actually execute the command, the closing `EOF` must be at column 0; the leading whitespace shown below is markdown list indentation only and is not part of the bash you run.
      ```bash
      git commit -m "$(cat <<'EOF'
      <type>(<scope>): <subject>

      <optional body>

      Co-Authored-By: Claude <noreply@anthropic.com>
      EOF
      )"
      ```
   7. If the pre-commit hook fails, do NOT amend. Fix the issue, re-stage, create a new commit.
3. Push:
   1. If `git rev-parse --abbrev-ref --symbolic-full-name @{u}` exits non-zero (no upstream), run `git push -u origin "$(git rev-parse --abbrev-ref HEAD)"`.
   2. Else run `git push`.

## 2. Open or reuse PR

1. Get current state: `gh pr view --json number,url,state,baseRefName` (operates on the current branch by default).
2. Branch on the result:
   - `state: "OPEN"` → reuse. Capture `number` as `$PR`, `url` as `$PR_URL`, and `baseRefName` as `$BASE`. Print "Reusing open PR #<n>: <url>". Continue to section 3.
   - `state: "MERGED"` → print "PR #<n> already merged: <url>". Stop.
   - `state: "CLOSED"` → print "PR #<n> closed (not merged): <url>. Reopen manually if you want to ship this branch." Stop.
   - Command exits non-zero with no JSON on stdout → no PR exists; continue to step 3.
3. Draft a PR title and body for a new PR:
   1. Resolve the default base branch: `BASE=$(gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name')`.
   2. Fetch the base ref if needed: `git fetch origin "$BASE:refs/remotes/origin/$BASE"`.
   3. Get commits since the base branch: `git log "origin/$BASE..HEAD" --oneline`.
   4. Title: under 70 chars. If there is exactly one commit, use its subject verbatim. Otherwise compose a title from the subjects.
   5. Body: `## Summary` (1-3 bullets) + `## Test plan` (markdown checklist) + trailing `Generated with [Claude Code](https://claude.com/claude-code)` line.
4. Open the PR via heredoc.
   ```bash
   gh pr create --base "$BASE" --title "<title>" --body "$(cat <<'EOF'
   ## Summary
   - ...

   ## Test plan
   - [ ] ...

   Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )"
   ```
   Run `gh pr view --json number,url` immediately after to capture `$PR` and `$PR_URL`.
5. Append a self-link footer:
   ```bash
   BODY=$(gh pr view $PR --json body --jq '.body')
   if ! grep -qF "Pull-Request: $PR_URL" <<<"$BODY"; then
     gh pr edit $PR --body "$(printf '%s\n\nPull-Request: %s\n' "$BODY" "$PR_URL")"
   fi
   ```
6. **Backfill the PR number onto the branch's done plan, if any.** This step runs after `$PR` is captured. It is a no-op when there is no done plan on the branch (e.g. the user shipped work that is not board-managed).
   1. Attempt the backfill:
      ```bash
      python3 scripts/board.py set-pr --pr "$PR" --branch "$BRANCH" 2>/dev/null
      ```
      Capture the exit code. If non-zero, skip the rest of step 6.
   2. If the backfill succeeded, check `git status --porcelain`. If it shows staged or unstaged changes (the plan / spec / INDEX.md updates), commit and push them as a small follow-up commit. The commit ensures the PR's diff reflects the new frontmatter; CI re-runs naturally on the push. **Important:** when you actually execute the command, the closing `EOF` must be at column 0; the leading whitespace shown below is markdown list indentation only and is not part of the bash you run.
      ```bash
      if [ -n "$(git status --porcelain)" ]; then
        git commit -m "$(cat <<EOF
      chore(board): backfill PR #$PR onto plan/spec

      Co-Authored-By: Claude <noreply@anthropic.com>
      EOF
      )"
        git push
      fi
      ```
   3. If the porcelain output is empty after a successful `set-pr`, the PR was already recorded (idempotent rerun); skip the commit/push.

## 3. Watch CI in the background

1. Initialize state: `python3 scripts/ship_ci.py start --pr "$PR"`.
2. Dispatch the watch via the `Bash` tool with `run_in_background: true`:

   ```bash
   gh pr checks "$PR" --watch --required ; echo "__SHIP_EXIT__=$?" > /tmp/ship-$PR.status
   ```

3. End the turn. The harness notifies when the background process exits.

**On wake:**

Run `ACTION=$(python3 scripts/ship_ci.py next-action --pr "$PR")` and branch on `$ACTION`:

| `$ACTION`                          | Do                                                                                              |
| ---------------------------------- | ----------------------------------------------------------------------------------------------- |
| `done-green`                       | Continue to section 4 (Green path).                                                             |
| `done-red`                         | Continue to section 5 (Red path).                                                               |
| `redispatch-required`              | Re-dispatch `gh pr checks "$PR" --watch --required ; echo "__SHIP_EXIT__=$?" > /tmp/ship-$PR.status` in background. End turn. |
| `redispatch-all`                   | Re-dispatch `gh pr checks "$PR" --watch ; echo "__SHIP_EXIT__=$?" > /tmp/ship-$PR.status` in background. End turn.            |
| `redispatch-required-after-15s`    | `sleep 15`, then re-dispatch the required watch as above. End turn.                             |
| `redispatch-all-after-15s`         | `sleep 15`, then re-dispatch the all watch as above. End turn.                                  |
| `ask-non-required`                 | `AskUserQuestion`: **Watch non-required CI** / **Merge now** / **Stop**. See below for actions. |
| `retries-exhausted`                | Print "CI checks never appeared after 5 retries; PR #$PR may be misconfigured." Stop.           |

For `ask-non-required` follow-up:
- **Watch non-required CI** → `python3 scripts/ship_ci.py switch-mode --pr "$PR" --to all`, then dispatch `gh pr checks "$PR" --watch ; echo "__SHIP_EXIT__=$?" > /tmp/ship-$PR.status` in background. End turn.
- **Merge now** → continue to section 4 (Green path).
- **Stop** → print PR URL and stop.

## 4. Green path

1. Capture branch: `BRANCH=$(git rev-parse --abbrev-ref HEAD)`.
2. Check merge readiness: `STATUS=$(gh pr view $PR --json mergeStateStatus --jq '.mergeStateStatus')`. Handle CLEAN/BEHIND/DIRTY/BLOCKED/UNKNOWN.
3. Ask user: "CI green on PR #<n>. Merge now?" Options (include **Request Codex review** only if `.claude/commands/request-codex-review.md` exists):
   - **Merge (squash)** — `gh pr merge $PR --squash --delete-branch`. Print PR URL, merge SHA, branch deleted.
   - **Request Codex review** — invoke `/request-codex-review $PR`. The review runs asynchronously; rerun `/task-ship` when it finishes to return to this prompt.
   - **Don't merge yet** — print URL, stop.
   - **Open in browser** — `gh pr view $PR --web`, stop.

## 5. Red path

1. Capture branch.
2. Find failed run from `gh pr checks $PR --json name,state,link,startedAt`.
3. Extract run ID, fetch logs: `gh run view $RUN_ID --log-failed > /tmp/ship-$PR-failed.log 2>&1`.
4. Print summary (failed check names, run URL, first 20 lines of log).
5. Ask user: "CI failed on PR #<n>. Next step?" Options:
   - **Run /systematic-debugging** — invoke `superpowers:systematic-debugging` with CI failure context.
   - **Print full log** — emit full log contents.
   - **Open run in browser** — `gh run view $RUN_ID --web`.

## Edge cases

- PR already merged/closed — handled in section 2.
- Background watch never exits — re-run `gh pr checks` foreground on re-engage.
- No required checks configured — section 3 step 3 disambiguates.
- Timing race (no checks yet) — retry with pre-sleep, max 5.
- `gh` errors — bubble stderr, stop.
