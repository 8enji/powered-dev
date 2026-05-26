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

## 1. Commit

1. Run `git status --porcelain`. If the output is empty, there is nothing new to commit — skip sections 1 and 2 entirely (no implementation commit means no followups to log against it) and proceed to section 3 (push), which will independently decide whether there is anything to push.
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

## 2. Log followups to backlog

Reflect on what just shipped. Surface followups so they aren't lost.

**Skip this section entirely if section 1 was skipped** (no new implementation commit means `HEAD` belongs to a previous run; logging followups against it would attach stale references).

1. Build a candidate list from two sources:
   - **Reflection.** Review the diff just committed (`git show --stat HEAD` for the file list; `git diff HEAD~1..HEAD` for content) and propose items that were noticed but deferred: related bugs, refactor opportunities, tests you skipped, polish you punted on.
   - **Diff scan for new TODO/FIXME.** Run:
     ```bash
     git diff HEAD~1..HEAD --unified=0 | grep -nE '^\+[^+].*\b(TODO|FIXME)\b' || true
     ```
     This filters to lines *added* by the commit that contain `TODO` or `FIXME` (the `[^+]` guards against matching the `+++ b/file` diff header). To recover `<file>:<line>` for each match, walk the diff alongside the matches or use `git grep -nE '\b(TODO|FIXME)\b'` on the working tree and intersect with the file list from `git show --name-only HEAD`.
   - Treat each TODO/FIXME match as a candidate item.
2. If the candidate list is **empty**, print `No followups to log.` and continue to section 3 (push). Skip the rest of this section.
3. Draft each candidate as `{title, notes, source}`:
   - `title` — short imperative phrase (under ~80 chars). Mirror the style of existing backlog titles in the repo.
   - `notes` — 1-3 lines: what to do, why it was deferred.
   - `source` — for reflection items, the commit SHA (`git rev-parse --short HEAD`). For TODO/FIXME items, `<file>:<line>` of the comment.
4. Present the full list to the user with `AskUserQuestion`. Question: "Log these followups to the backlog?" Options: **Approve all** / **Edit list** / **Skip**.
   - **Approve all** → continue to step 5.
   - **Edit list** → ask the user in a follow-up turn for the revised list (free-form text). Parse it back into `{title, notes, source}` tuples. Then continue to step 5.
   - **Skip** → print `Skipped logging followups.` and continue to section 3.
5. For each item, run `python3 scripts/board.py add "<title>" --notes "<notes>" --source "<source>"`. If `board.py` exits non-zero (duplicate title or other validation error), surface the message, skip that item, and continue with the rest.
6. After all items are added, run `git status --porcelain`. If it shows staged changes (it should — `board.py add` stages `backlog.md` and `INDEX.md`), commit. **Important:** when you actually execute the command, the closing `EOF` must be at column 0; the leading whitespace shown below is markdown list indentation only and is not part of the bash you run.
   ```bash
   git commit -m "$(cat <<'EOF'
   chore(board): log followups

   Co-Authored-By: Claude <noreply@anthropic.com>
   EOF
   )"
   ```
   If the pre-commit hook fails, do NOT amend. Fix the issue, re-stage, create a new commit.
7. Continue to section 3 (push). Both commits push together.

## 3. Push

1. If `git rev-parse --abbrev-ref --symbolic-full-name @{u}` exits non-zero (no upstream), run `git push -u origin "$(git rev-parse --abbrev-ref HEAD)"`.
2. Else run `git push`.

## 4. Open or reuse PR

1. Get current state: `gh pr view --json number,url,state,baseRefName` (operates on the current branch by default).
2. Branch on the result:
   - `state: "OPEN"` → reuse. Capture `number` as `$PR`, `url` as `$PR_URL`, and `baseRefName` as `$BASE`. Print "Reusing open PR #<n>: <url>". Continue to section 5.
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

## 5. Watch CI in the background

1. Pre-flight: confirm the PR isn't in a state that prevents CI from running. `MERGE_STATE=$(gh pr view "$PR" --json mergeStateStatus --jq '.mergeStateStatus')`. If `$MERGE_STATE` is `DIRTY`, stop and tell the user: "PR #$PR has merge conflicts (mergeStateStatus=DIRTY); CI workflows that depend on the merge ref won't run and the PR can't be merged. Resolve conflicts on the branch, then rerun /task-ship." Do not initialize the watcher.
2. Initialize state: `python3 scripts/ship_ci.py start --pr "$PR"`.
3. Dispatch the watch via the `Bash` tool with `run_in_background: true`:

   ```bash
   gh pr checks "$PR" --watch --required ; echo "__SHIP_EXIT__=$?" > /tmp/ship-$PR.status
   ```

4. End the turn. The harness notifies when the background process exits.

**On wake:**

Run `ACTION=$(python3 scripts/ship_ci.py next-action --pr "$PR")` and branch on `$ACTION`:

| `$ACTION`                          | Do                                                                                              |
| ---------------------------------- | ----------------------------------------------------------------------------------------------- |
| `done-green`                       | Continue to section 6 (Green path).                                                             |
| `done-red`                         | Continue to section 7 (Red path).                                                               |
| `redispatch-required`              | Re-dispatch `gh pr checks "$PR" --watch --required ; echo "__SHIP_EXIT__=$?" > /tmp/ship-$PR.status` in background. End turn. |
| `redispatch-all`                   | Re-dispatch `gh pr checks "$PR" --watch ; echo "__SHIP_EXIT__=$?" > /tmp/ship-$PR.status` in background. End turn.            |
| `redispatch-required-after-15s`    | `sleep 15`, then re-dispatch the required watch as above. End turn.                             |
| `redispatch-all-after-15s`         | `sleep 15`, then re-dispatch the all watch as above. End turn.                                  |
| `ask-non-required`                 | `AskUserQuestion`: **Watch non-required CI** / **Merge now** / **Stop**. See below for actions. |
| `retries-exhausted`                | Print "CI checks never appeared after 5 retries; PR #$PR may be misconfigured." Stop.           |

For `ask-non-required` follow-up:
- **Watch non-required CI** → `python3 scripts/ship_ci.py switch-mode --pr "$PR" --to all`, then dispatch `gh pr checks "$PR" --watch ; echo "__SHIP_EXIT__=$?" > /tmp/ship-$PR.status` in background. End turn.
- **Merge now** → continue to section 6 (Green path).
- **Stop** → print PR URL and stop.

## 6. Green path

1. Capture branch: `BRANCH=$(git rev-parse --abbrev-ref HEAD)`.
2. Check merge readiness: `STATUS=$(gh pr view $PR --json mergeStateStatus --jq '.mergeStateStatus')`. Handle CLEAN/BEHIND/DIRTY/BLOCKED/UNKNOWN.
3. Ask user: "CI green on PR #<n>. Merge now?" Options (include **Request Codex review** only if `.claude/commands/request-codex-review.md` exists):
   - **Merge (squash)** — `gh pr merge $PR --squash --delete-branch`. Print PR URL, merge SHA, branch deleted.
   - **Request Codex review** — invoke `/request-codex-review $PR`. The review runs asynchronously; rerun `/task-ship` when it finishes to return to this prompt.
   - **Don't merge yet** — print URL, stop.
   - **Open in browser** — `gh pr view $PR --web`, stop.

## 7. Red path

1. Capture branch.
2. Find failed run from `gh pr checks $PR --json name,state,link,startedAt`.
3. Extract run ID, fetch logs: `gh run view $RUN_ID --log-failed > /tmp/ship-$PR-failed.log 2>&1`.
4. Print summary (failed check names, run URL, first 20 lines of log).
5. Ask user: "CI failed on PR #<n>. Next step?" Options:
   - **Run /systematic-debugging** — invoke `superpowers:systematic-debugging` with CI failure context.
   - **Print full log** — emit full log contents.
   - **Open run in browser** — `gh run view $RUN_ID --web`.

## Edge cases

- PR already merged/closed — handled in section 4.
- PR has merge conflicts (`mergeStateStatus=DIRTY`) — short-circuited in section 5 step 1 before the watcher starts.
- Background watch never exits — re-run `gh pr checks` foreground on re-engage.
- No required checks configured — section 5 step 3 disambiguates.
- Timing race (no checks yet) — retry with pre-sleep, max 5.
- `gh` errors — bubble stderr, stop.
