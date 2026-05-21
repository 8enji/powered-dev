---
description: Run Codex against a PR (current branch's open PR, or explicit PR# / URL) and post an inline-annotated GitHub PR Review. Escalates to REQUEST_CHANGES on any critical finding.
---

Run Codex as a second reviewer on a pull request and post inline comments.

Arguments (may be empty): `$ARGUMENTS`

## Pre-flight

1. Run `git rev-parse --abbrev-ref HEAD`. If the result is `main` or `master` and `$ARGUMENTS` is empty, stop with: "Pass a PR# or URL, or switch to a feature branch." If the result is the literal string `HEAD` (detached) and `$ARGUMENTS` is empty, stop with the same message.
2. Verify `codex` is installed: check that `/Applications/Codex.app/Contents/Resources/codex --version` exits 0. If not, stop with: "Codex CLI not found at expected path. Install/launch Codex.app from https://codex.openai.com/."
3. Verify `gh auth status` exits 0. If not, stop with: "Run `gh auth login` first."

## Stage 1 — Resolve PR + review-root

1. Parse `$ARGUMENTS`. Use the first whitespace-separated token as the PR identifier (if any). Everything after the first whitespace is the optional **focus prompt** (stored as `$FOCUS`; may be empty). Identifier forms:
   - Empty → current-branch mode.
   - Numeric (e.g. `1234`) → `$PR = 1234`, `$OWNER/$REPO` resolved via `gh repo view --json owner,name --jq '.owner.login + "/" + .name'`.
   - `owner/repo#N` → split on `#` for owner/repo and PR number.
   - `https://github.com/<owner>/<repo>/pull/<N>...` → regex out owner/repo/N.
   - Anything else → stop with: "Unrecognized PR identifier: `<arg>`. Use a PR number, `owner/repo#N`, or a GitHub PR URL."
2. **Current-branch mode**: run `gh pr view --json number,url,headRefOid,baseRefName,headRefName,isCrossRepository,title,headRepositoryOwner`. If the command exits non-zero (no open PR), stop with: "No open PR for `<branch>`; pass PR# or URL." On success, capture: `PR`, `PR_URL`, `HEAD_SHA` (`.headRefOid`), `BASE`, `TITLE`, `OWNER` (from `gh repo view`), `REPO` (from `gh repo view`).
3. **Explicit-PR mode**: run `gh pr view "$PR" -R "$OWNER/$REPO" --json number,url,headRefOid,baseRefName,headRefName,isCrossRepository,title`. Same exit-code handling. Capture the same fields.
4. Sanity-check the diff. In current-branch mode: `git diff "origin/$BASE...HEAD" --name-only`. In explicit-PR mode: defer this check to step 5 below (after the worktree exists). If empty, stop with: "PR #$PR has no file changes; nothing to review."
5. Determine `REVIEW_ROOT`:
   - Current-branch mode: `REVIEW_ROOT="$(pwd)"`.
   - Explicit-PR mode:
     ```bash
     WT="/tmp/codex-review-pr-$PR"
     if git worktree list --porcelain | grep -q "^worktree $WT$"; then
       git worktree remove --force "$WT" 2>/dev/null || true
     fi
     rm -rf "$WT" 2>/dev/null || true
     git fetch origin "pull/$PR/head:refs/remotes/origin/pr-$PR-head"
     git worktree add "$WT" "refs/remotes/origin/pr-$PR-head"
     REVIEW_ROOT="$WT"
     test -n "$(git -C "$REVIEW_ROOT" diff "origin/$BASE...HEAD" --name-only)" \
       || { echo "PR #$PR has no file changes; nothing to review."; exit 0; }
     ```
6. Concurrency check. An empty `/tmp/codex-review-$PR.status` file is the still-running marker.
   ```bash
   STATUS="/tmp/codex-review-$PR.status"
   test -f "$STATUS" && ! test -s "$STATUS" && echo "STILL_RUNNING"
   ```
   If the snippet prints `STILL_RUNNING`, use `AskUserQuestion`. Question: "A prior Codex review for PR #$PR may still be running. Continue?" Options: **Start new (overwrite)** / **Stop**. On **Stop**, exit. On **Start new (overwrite)**, fall through.
7. Clear leftover `/tmp` state from any prior run:
   ```bash
   rm -f "/tmp/codex-review-$PR".{status,jsonl,last-message,prompt,touched-files,touched-files.json,review-payload.json,review-payload.body-only.json,review-response.json,review-stderr}
   ```

## Stage 2 — Dispatch Codex in background

1. Build the rendered prompt by prepending PR metadata to the static prompt file:
   ```bash
   ( cat <<EOF
   ## PR metadata
   - Title: $TITLE
   - Base: origin/$BASE
   - Head SHA: $HEAD_SHA
   - Focus (from invoker, may be empty): $FOCUS

   EOF
     cat "$(pwd)/.claude/codex/review-prompt.md"
   ) > "/tmp/codex-review-$PR.prompt"
   ```
   **Important:** the closing `EOF` must be at column 0 when executed; indentation above is markdown rendering only.

   Note: `cat .claude/codex/review-prompt.md` is rooted at the **invoking** repo's working tree (where the slash command lives), not `$REVIEW_ROOT` (which may be a temp worktree). Use `$(pwd)/.claude/codex/review-prompt.md` from the invoking tree, captured before any `cd` into `$REVIEW_ROOT`.
2. Dispatch the Codex run in the background. Use the `Bash` tool with `run_in_background: true`:
   ```bash
   ( /Applications/Codex.app/Contents/Resources/codex exec \
       --json \
       --output-schema "$(pwd)/.claude/codex/review-findings.schema.json" \
       --output-last-message "/tmp/codex-review-$PR.last-message" \
       --sandbox read-only \
       --cd "$REVIEW_ROOT" \
       - < "/tmp/codex-review-$PR.prompt" \
       > "/tmp/codex-review-$PR.jsonl" 2>&1
     echo "__CODEX_EXIT__=$?" > "/tmp/codex-review-$PR.status"
   )
   ```
   (Same caveat: `--output-schema` path must be rooted at the invoking tree.)
3. After dispatching, end the assistant turn. The harness notifies when the background process exits.

## Stage 3 — On wake: parse findings

1. Read `/tmp/codex-review-$PR.status`. Parse `<n>` from `__CODEX_EXIT__=<n>`. If the file is missing or malformed, treat `<n>` as non-zero.
2. If `<n> != 0`:
   - Print the exit code and the last 30 lines of `/tmp/codex-review-$PR.jsonl` (use `tail -n 30`).
   - Run cleanup (Stage 5) and stop. Do not retry.
3. If `<n> == 0`:
   1. Validate `/tmp/codex-review-$PR.last-message` parses as JSON with the expected shape. On schema violation, post raw output as a single conversation comment, run cleanup (Stage 5), and stop.
      ```bash
      if ! jq -e '(.summary | type) == "string" and (.findings | type) == "array"' \
            "/tmp/codex-review-$PR.last-message" > /dev/null 2>&1; then
        BANNER="## Codex review (degraded)

      _Codex did not produce schema-conforming JSON; posting raw output as a single comment._
      "
        ( printf '%s\n' "$BANNER"
          cat "/tmp/codex-review-$PR.last-message"
        ) | gh -R "$OWNER/$REPO" pr comment "$PR" --body-file -
        if [ -n "$WT" ] && [ -d "$WT" ]; then
          git worktree remove --force "$WT" 2>/dev/null || true
          rm -rf "$WT" 2>/dev/null || true
        fi
        exit 0
      fi
      ```
      Surface the posted comment URL before exiting.
   2. Build the touched-files list from the diff:
      ```bash
      git -C "$REVIEW_ROOT" diff "origin/$BASE...HEAD" --name-only \
        > "/tmp/codex-review-$PR.touched-files"
      ```
   3. Filter findings against the touched files; track drop count:
      ```bash
      jq -R -s 'split("\n") | map(select(length > 0))' \
        "/tmp/codex-review-$PR.touched-files" \
        > "/tmp/codex-review-$PR.touched-files.json"
      DROPPED=$(jq --slurpfile touched "/tmp/codex-review-$PR.touched-files.json" \
        '[.findings[] | select((.path as $p | $touched[0] | index($p)) | not)] | length' \
        "/tmp/codex-review-$PR.last-message")
      jq --slurpfile touched "/tmp/codex-review-$PR.touched-files.json" \
        '.findings |= map(select((.path as $p | $touched[0] | index($p))))' \
        "/tmp/codex-review-$PR.last-message" > "/tmp/codex-review-$PR.last-message.filtered"
      mv "/tmp/codex-review-$PR.last-message.filtered" "/tmp/codex-review-$PR.last-message"
      ```
   4. Decide the event:
      ```bash
      if jq -e '.findings[] | select(.severity == "critical")' \
            "/tmp/codex-review-$PR.last-message" > /dev/null 2>&1; then
        EVENT="REQUEST_CHANGES"
      else
        EVENT="COMMENT"
      fi
      ```
   5. Compute the severity histogram:
      ```bash
      HISTO=$(jq -r '
        .findings
        | group_by(.severity)
        | map({(.[0].severity): length})
        | add // {}
        | "\(.critical // 0) critical · \(.major // 0) major · \(.minor // 0) minor · \(.nit // 0) nit"
      ' "/tmp/codex-review-$PR.last-message")
      ```
   6. Build the review body:
      ```bash
      SUMMARY=$(jq -r '.summary' "/tmp/codex-review-$PR.last-message")
      MODEL=$(grep -E '^model[[:space:]]*=' ~/.codex/config.toml | head -1 | sed -E 's/^model[[:space:]]*=[[:space:]]*"?([^"]+)"?[[:space:]]*$/\1/')
      REASONING=$(grep -E '^model_reasoning_effort[[:space:]]*=' ~/.codex/config.toml | head -1 | sed -E 's/^model_reasoning_effort[[:space:]]*=[[:space:]]*"?([^"]+)"?[[:space:]]*$/\1/')
      [ -z "$MODEL" ] && MODEL="default"
      [ -z "$REASONING" ] && REASONING="default"
      BODY="## Codex review

      _Generated by Codex via \`/task-codex-review\`. Model: $MODEL, Reasoning: $REASONING._

      $SUMMARY

      **Findings:** $HISTO"
      if [ "$DROPPED" -gt 0 ]; then
        BODY="$BODY

      _Note: $DROPPED finding(s) referenced files outside the diff and were dropped._"
      fi
      ```
   7. Build the `comments[]` array:
      ```bash
      COMMENTS=$(jq -c '[.findings[] | {path, line, side, body: ("**[" + .severity + "]** " + .body)}]' \
        "/tmp/codex-review-$PR.last-message")
      ```

## Stage 4 — Submit review

1. Assemble and submit the payload:
   ```bash
   jq -n \
     --arg event "$EVENT" \
     --arg body  "$BODY" \
     --arg sha   "$HEAD_SHA" \
     --argjson comments "$COMMENTS" \
     '{event:$event, body:$body, commit_id:$sha, comments:$comments}' \
     > "/tmp/codex-review-$PR.review-payload.json"

   gh api -X POST "/repos/$OWNER/$REPO/pulls/$PR/reviews" \
          --input "/tmp/codex-review-$PR.review-payload.json" \
          > "/tmp/codex-review-$PR.review-response.json" 2> "/tmp/codex-review-$PR.review-stderr"
   API_EXIT=$?
   ```
2. Branch on the result:
   - `API_EXIT == 0` → success. Print the review URL:
     ```bash
     URL=$(jq -r '.html_url' "/tmp/codex-review-$PR.review-response.json")
     echo "Posted Codex review ($EVENT) on PR #$PR: $URL"
     ```
   - `API_EXIT != 0` and stderr contains `Unprocessable Entity` or `comments` validation error → retry once with `comments: []` (body-only review):
     ```bash
     jq '.comments = []' "/tmp/codex-review-$PR.review-payload.json" \
       > "/tmp/codex-review-$PR.review-payload.body-only.json"
     gh api -X POST "/repos/$OWNER/$REPO/pulls/$PR/reviews" \
            --input "/tmp/codex-review-$PR.review-payload.body-only.json" \
            > "/tmp/codex-review-$PR.review-response.json" 2>&1
     API_EXIT=$?
     ```
     - On success: `Posted Codex review ($EVENT, body-only after inline validation failure) on PR #$PR: <url>`.
     - On second failure: print stderr from both attempts and stop.
   - Any other non-zero exit (auth, network) → print stderr and stop.

## Stage 5 — Cleanup

Runs unconditionally before returning:

```bash
if [ -n "$WT" ] && [ -d "$WT" ]; then
  git worktree remove --force "$WT" 2>/dev/null || true
  rm -rf "$WT" 2>/dev/null || true
fi
```

Leave `/tmp/codex-review-$PR.*` on disk for forensic value — they get wiped at the start of the next `/task-codex-review` run for the same PR (Stage 1 step 7).

## Edge cases

- **Branch protection prevents `REQUEST_CHANGES` from author**: GitHub may reject `event: REQUEST_CHANGES` if the user is the PR author. Falls through to the 422 handling — retry as body-only with `event: COMMENT`.
- **PR force-pushed mid-review**: `commit_id: $HEAD_SHA` pins inline anchors. Comments anchored to stale lines fail validation → degraded body-only path catches it.
- **Codex emits more findings than GitHub's per-review comment cap (~250)**: GitHub returns 422. Body-only fallback catches it.
- **`$FOCUS` contains shell metacharacters**: passed via heredoc into the prompt file, not into a shell command. No injection risk.
- **`gh` and `codex` disagree about repo identity** (fork checkout where `origin` != upstream): rely on `gh repo view`'s answer.
