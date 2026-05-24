---
description: Request a Codex review for a PR or local-only changes. PR reviews post inline GitHub review comments; local reviews write a repo-local markdown report.
---

Run Codex as a second reviewer on a pull request or on local-only changes.

Arguments (may be empty): `$ARGUMENTS`

## Pre-flight

1. Run `git rev-parse --abbrev-ref HEAD`. If the result is `main`, `master`, or literal `HEAD` and `$ARGUMENTS` is empty, use local-change mode.
2. Verify `codex` is installed: check that `/Applications/Codex.app/Contents/Resources/codex --version` exits 0. If not, stop with: "Codex CLI not found at expected path. Install/launch Codex.app from https://codex.openai.com/."
3. Parse `$ARGUMENTS`. Use the first whitespace-separated token as the review identifier (if any). Everything after the first whitespace is the optional **focus prompt** (stored as `$FOCUS`; may be empty). Identifier forms:
   - Empty on `main`, `master`, or detached `HEAD` -> local-change mode.
   - Empty on any other branch -> run `gh pr view --json number,url,headRefOid,baseRefName,headRefName,isCrossRepository,title,headRepositoryOwner` and inspect the result:
     - Success with valid JSON -> current-branch PR mode.
     - Known no-PR case (`gh` reports no pull request for this branch) -> local-change mode.
     - Auth, network, rate limit, missing `gh`, or malformed output -> stop and surface the error. Do not fall back to local-change mode.
   - `local` or `--local` -> local-change mode.
   - Numeric (e.g. `1234`) -> PR mode; require `gh auth status` and a successful `gh pr view`.
   - `owner/repo#N` -> PR mode; require `gh auth status` and a successful `gh pr view`.
   - `https://github.com/<owner>/<repo>/pull/<N>...` -> PR mode; require `gh auth status` and a successful `gh pr view`.
   - Anything else with no PR shape -> local-change mode with the entire `$ARGUMENTS` as `$FOCUS`.
4. For PR mode only, verify `gh auth status` exits 0. If not, stop with: "Run `gh auth login` first." Local-change mode does not require GitHub auth.

## Stage 1 — Select Review Mode

1. If local-change mode was selected, go to **Local-change mode**.
2. Otherwise continue to **PR mode**.

## Local-change Mode

Local-change mode reviews changes that have not been opened as a PR yet. It supports staged files, unstaged files, untracked files, and local branch commits that differ from a detected base branch. It writes a markdown report in the repository instead of posting to GitHub.

### Stage L1 — Resolve Local Diff

1. Capture:
   ```bash
   REVIEW_ROOT="$(pwd)"
   REVIEW_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
   STATE="/tmp/codex-local-review-$REVIEW_ID.state.json"
   REPORT_DIR="docs/superpowers/reports"
   REPORT="docs/superpowers/reports/codex-review-$REVIEW_ID.md"
   REPORT_TMP="/tmp/codex-local-review-$REVIEW_ID.report.md"
   PROMPT_PATH="/tmp/codex-local-review-$REVIEW_ID.prompt"
   STATUS_PATH="/tmp/codex-local-review-$REVIEW_ID.status"
   JSONL_PATH="/tmp/codex-local-review-$REVIEW_ID.jsonl"
   LAST_MESSAGE_PATH="/tmp/codex-local-review-$REVIEW_ID.last-message"
   TOUCHED_FILES_PATH="/tmp/codex-local-review-$REVIEW_ID.touched-files"
   EVENT_PATH="/tmp/codex-local-review-$REVIEW_ID.event"
   PROMPT_SOURCE="$(pwd)/.claude/codex/review-prompt.md"
   SCHEMA_PATH="$(pwd)/.claude/codex/review-findings.schema.json"
   mkdir -p "$REPORT_DIR"
   ```
2. Build local evidence files:
   ```bash
   git diff --cached --name-only > "/tmp/codex-local-review-$REVIEW_ID.staged-files"
   git diff --no-ext-diff --name-only > "/tmp/codex-local-review-$REVIEW_ID.unstaged-files"
   git ls-files --others --exclude-standard > "/tmp/codex-local-review-$REVIEW_ID.untracked-files"
   git diff --cached > "/tmp/codex-local-review-$REVIEW_ID.staged.diff"
   git diff --no-ext-diff > "/tmp/codex-local-review-$REVIEW_ID.unstaged.diff"
   ```
3. If a base ref exists, include committed branch changes:
   ```bash
   BASE_REF=""
   for candidate in origin/main origin/master main master; do
     if git rev-parse --verify "$candidate" >/dev/null 2>&1; then
       BASE_REF="$candidate"
       break
     fi
   done
   if [ -n "$BASE_REF" ]; then
     git diff --name-only "$BASE_REF...HEAD" > "/tmp/codex-local-review-$REVIEW_ID.committed-files"
     git diff "$BASE_REF...HEAD" > "/tmp/codex-local-review-$REVIEW_ID.committed.diff"
   else
     : > "/tmp/codex-local-review-$REVIEW_ID.committed-files"
     : > "/tmp/codex-local-review-$REVIEW_ID.committed.diff"
   fi
   ```
4. Combine touched files. If there are none, stop with: "No local changes found to review."
   ```bash
   sort -u \
     "/tmp/codex-local-review-$REVIEW_ID.staged-files" \
     "/tmp/codex-local-review-$REVIEW_ID.unstaged-files" \
     "/tmp/codex-local-review-$REVIEW_ID.untracked-files" \
     "/tmp/codex-local-review-$REVIEW_ID.committed-files" \
     | sed '/^$/d' > "$TOUCHED_FILES_PATH"
   test -s "$TOUCHED_FILES_PATH" \
     || { echo "No local changes found to review."; exit 0; }
   ```
5. Persist local review state before dispatch. The wake path must reload this file instead of relying on shell variables surviving:
   ```bash
   jq -n \
     --arg mode "local" \
     --arg review_id "$REVIEW_ID" \
     --arg review_root "$REVIEW_ROOT" \
     --arg base_ref "$BASE_REF" \
     --arg report_path "$REPORT" \
     --arg report_tmp_path "$REPORT_TMP" \
     --arg prompt_path "$PROMPT_PATH" \
     --arg prompt_source "$PROMPT_SOURCE" \
     --arg schema_path "$SCHEMA_PATH" \
     --arg status_path "$STATUS_PATH" \
     --arg jsonl_path "$JSONL_PATH" \
     --arg last_message_path "$LAST_MESSAGE_PATH" \
     --arg touched_files_path "$TOUCHED_FILES_PATH" \
     --arg event_path "$EVENT_PATH" \
     '{mode:$mode, review_id:$review_id, review_root:$review_root, base_ref:$base_ref, report_path:$report_path, report_tmp_path:$report_tmp_path, prompt_path:$prompt_path, prompt_source:$prompt_source, schema_path:$schema_path, status_path:$status_path, jsonl_path:$jsonl_path, last_message_path:$last_message_path, touched_files_path:$touched_files_path, event_path:$event_path}' \
     > "$STATE"
   printf '%s\n' "$STATE" > "/tmp/codex-local-review.$PPID.latest-state"
   ```

### Stage L2 — Dispatch Codex Locally

1. Build the rendered prompt:
   ```bash
   ( cat <<EOF
   ## Local review metadata
   - Review ID: $REVIEW_ID
   - Base ref: ${BASE_REF:-none}
   - Head SHA: $(git rev-parse HEAD 2>/dev/null || echo unknown)
   - Focus (from invoker, may be empty): $FOCUS

   ## Touched files
   $(cat "$TOUCHED_FILES_PATH")

   ## Diffs available on disk
   - Staged diff: /tmp/codex-local-review-$REVIEW_ID.staged.diff
   - Unstaged diff: /tmp/codex-local-review-$REVIEW_ID.unstaged.diff
   - Committed diff: /tmp/codex-local-review-$REVIEW_ID.committed.diff

   EOF
     cat "$PROMPT_SOURCE"
   ) > "$PROMPT_PATH"
   ```
2. Dispatch the Codex run in the background:
   ```bash
   ( /Applications/Codex.app/Contents/Resources/codex exec \
       --json \
       --output-schema "$SCHEMA_PATH" \
       --output-last-message "$LAST_MESSAGE_PATH" \
       --sandbox read-only \
       --cd "$REVIEW_ROOT" \
       - < "$PROMPT_PATH" \
       > "$JSONL_PATH" 2>&1
     echo "__CODEX_EXIT__=$?" > "$STATUS_PATH"
   )
   ```
3. After dispatching, end the assistant turn. The harness notifies when the background process exits.

### Stage L3 — On Wake: Write Local Report

1. Load persisted state. If the current assistant turn does not know `REVIEW_ID`, read the state path from `/tmp/codex-local-review.$PPID.latest-state`:
   ```bash
   STATE=${STATE:-$(cat "/tmp/codex-local-review.$PPID.latest-state")}
   MODE=$(jq -r '.mode' "$STATE")
   REVIEW_ID=$(jq -r '.review_id' "$STATE")
   REVIEW_ROOT=$(jq -r '.review_root' "$STATE")
   REPORT=$(jq -r '.report_path' "$STATE")
   REPORT_TMP=$(jq -r '.report_tmp_path' "$STATE")
   STATUS_PATH=$(jq -r '.status_path' "$STATE")
   JSONL_PATH=$(jq -r '.jsonl_path' "$STATE")
   LAST_MESSAGE_PATH=$(jq -r '.last_message_path' "$STATE")
   TOUCHED_FILES_PATH=$(jq -r '.touched_files_path' "$STATE")
   EVENT_PATH=$(jq -r '.event_path' "$STATE")
   test "$MODE" = "local" || { echo "State file is not for a local Codex review: $STATE"; exit 1; }
   cd "$REVIEW_ROOT"
   ```
2. Read `$STATUS_PATH`. Parse `<n>` from `__CODEX_EXIT__=<n>`. If the file is missing or malformed, treat `<n>` as non-zero.
3. If `<n> != 0`, print the exit code and the last 30 lines of `$JSONL_PATH`, then stop.
4. If `<n> == 0`, validate `$LAST_MESSAGE_PATH` parses as JSON with `summary` and `findings`. If it does not, write a degraded report:
   ```bash
   {
     printf '%s\n' '---'
     printf 'status: done\n'
     printf 'type: report\n'
     printf 'date: %s\n' "$(date -u +%Y-%m-%d)"
     printf 'summary: Codex local review for %s\n' "$REVIEW_ID"
     printf '%s\n\n' '---'
     printf '# Codex local review %s\n\n' "$REVIEW_ID"
     printf '_Codex did not produce schema-conforming JSON; raw output follows._\n\n'
     cat "$LAST_MESSAGE_PATH"
   } > "$REPORT_TMP"
   cp "$REPORT_TMP" "$REPORT"
   python3 scripts/docs_index.py regenerate
   git add "$REPORT" docs/superpowers/INDEX.md
   echo "Wrote degraded Codex local review report and staged index update: $REPORT"
   exit 0
   ```
5. Filter findings against touched files, compute the event, and persist it:
   ```bash
   jq -R -s 'split("\n") | map(select(length > 0))' \
     "$TOUCHED_FILES_PATH" \
     > "/tmp/codex-local-review-$REVIEW_ID.touched-files.json"
   DROPPED=$(jq --slurpfile touched "/tmp/codex-local-review-$REVIEW_ID.touched-files.json" \
     '[.findings[] | select((.path as $p | $touched[0] | index($p)) | not)] | length' \
     "$LAST_MESSAGE_PATH")
   jq --slurpfile touched "/tmp/codex-local-review-$REVIEW_ID.touched-files.json" \
     '.findings |= map(select((.path as $p | $touched[0] | index($p))))' \
     "$LAST_MESSAGE_PATH" > "/tmp/codex-local-review-$REVIEW_ID.last-message.filtered"
   mv "/tmp/codex-local-review-$REVIEW_ID.last-message.filtered" "$LAST_MESSAGE_PATH"
   if jq -e '.findings[] | select(.severity == "critical")' \
        "$LAST_MESSAGE_PATH" > /dev/null 2>&1; then
     EVENT="REQUEST_CHANGES"
   else
     EVENT="COMMENT"
   fi
   echo "$EVENT" > "$EVENT_PATH"
   ```
6. Write the local markdown report:
   ```bash
   SUMMARY=$(jq -r '.summary' "$LAST_MESSAGE_PATH")
   HISTO=$(jq -r '
     .findings
     | group_by(.severity)
     | map({(.[0].severity): length})
     | add // {}
     | "\(.critical // 0) critical · \(.major // 0) major · \(.minor // 0) minor · \(.nit // 0) nit"
   ' "$LAST_MESSAGE_PATH")
   {
     printf '%s\n' '---'
     printf 'status: done\n'
     printf 'type: report\n'
     printf 'date: %s\n' "$(date -u +%Y-%m-%d)"
     printf 'summary: Codex local review for %s\n' "$REVIEW_ID"
     printf '%s\n\n' '---'
     printf '# Codex local review %s\n\n' "$REVIEW_ID"
     printf '**Event:** %s\n\n' "$EVENT"
     printf '**Findings:** %s\n\n' "$HISTO"
     printf '%s\n\n' "$SUMMARY"
     if [ "$DROPPED" -gt 0 ]; then
       printf '_Note: %s finding(s) referenced files outside the local diff and were dropped._\n\n' "$DROPPED"
     fi
     jq -r '.findings[] | "## [\(.severity)] \(.path):\(.line)\n\n\(.body)\n"' \
       "$LAST_MESSAGE_PATH"
   } > "$REPORT_TMP"
   cp "$REPORT_TMP" "$REPORT"
   python3 scripts/docs_index.py regenerate
   git add "$REPORT" docs/superpowers/INDEX.md
   echo "Wrote Codex local review report and staged index update: $REPORT"
   ```

## PR Mode

PR mode preserves the original behavior: run Codex against a pull request and post an inline-annotated GitHub PR review. Findings with `severity: critical` escalate the review event to `REQUEST_CHANGES`.

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
   rm -f "/tmp/codex-review-$PR".{status,jsonl,last-message,prompt,touched-files,touched-files.json,review-payload.json,review-payload.body-only.json,review-response.json,review-stderr,event}
   rm -f "/tmp/codex-review-$PR.state.json"
   ```
8. Persist PR review state before dispatch. The wake path must reload this file instead of relying on shell variables surviving:
   ```bash
   STATE="/tmp/codex-review-$PR.state.json"
   PROMPT_PATH="/tmp/codex-review-$PR.prompt"
   STATUS_PATH="/tmp/codex-review-$PR.status"
   JSONL_PATH="/tmp/codex-review-$PR.jsonl"
   LAST_MESSAGE_PATH="/tmp/codex-review-$PR.last-message"
   TOUCHED_FILES_PATH="/tmp/codex-review-$PR.touched-files"
   TOUCHED_FILES_JSON_PATH="/tmp/codex-review-$PR.touched-files.json"
   EVENT_PATH="/tmp/codex-review-$PR.event"
   REVIEW_PAYLOAD_PATH="/tmp/codex-review-$PR.review-payload.json"
   REVIEW_PAYLOAD_BODY_ONLY_PATH="/tmp/codex-review-$PR.review-payload.body-only.json"
   REVIEW_RESPONSE_PATH="/tmp/codex-review-$PR.review-response.json"
   REVIEW_STDERR_PATH="/tmp/codex-review-$PR.review-stderr"
   PROMPT_SOURCE="$(pwd)/.claude/codex/review-prompt.md"
   SCHEMA_PATH="$(pwd)/.claude/codex/review-findings.schema.json"
   jq -n \
     --arg mode "pr" \
     --arg pr "$PR" \
     --arg pr_url "$PR_URL" \
     --arg owner "$OWNER" \
     --arg repo "$REPO" \
     --arg base "$BASE" \
     --arg title "$TITLE" \
     --arg head_sha "$HEAD_SHA" \
     --arg review_root "$REVIEW_ROOT" \
     --arg worktree_path "${WT:-}" \
     --arg prompt_path "$PROMPT_PATH" \
     --arg prompt_source "$PROMPT_SOURCE" \
     --arg schema_path "$SCHEMA_PATH" \
     --arg status_path "$STATUS_PATH" \
     --arg jsonl_path "$JSONL_PATH" \
     --arg last_message_path "$LAST_MESSAGE_PATH" \
     --arg touched_files_path "$TOUCHED_FILES_PATH" \
     --arg touched_files_json_path "$TOUCHED_FILES_JSON_PATH" \
     --arg event_path "$EVENT_PATH" \
     --arg review_payload_path "$REVIEW_PAYLOAD_PATH" \
     --arg review_payload_body_only_path "$REVIEW_PAYLOAD_BODY_ONLY_PATH" \
     --arg review_response_path "$REVIEW_RESPONSE_PATH" \
     --arg review_stderr_path "$REVIEW_STDERR_PATH" \
     '{mode:$mode, pr:$pr, pr_url:$pr_url, owner:$owner, repo:$repo, base:$base, title:$title, head_sha:$head_sha, review_root:$review_root, worktree_path:$worktree_path, prompt_path:$prompt_path, prompt_source:$prompt_source, schema_path:$schema_path, status_path:$status_path, jsonl_path:$jsonl_path, last_message_path:$last_message_path, touched_files_path:$touched_files_path, touched_files_json_path:$touched_files_json_path, event_path:$event_path, review_payload_path:$review_payload_path, review_payload_body_only_path:$review_payload_body_only_path, review_response_path:$review_response_path, review_stderr_path:$review_stderr_path}' \
     > "$STATE"
   printf '%s\n' "$STATE" > "/tmp/codex-review.$PPID.latest-state"
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
    cat "$PROMPT_SOURCE"
   ) > "$PROMPT_PATH"
   ```
   **Important:** the closing `EOF` must be at column 0 when executed; indentation above is markdown rendering only.

   Note: `cat .claude/codex/review-prompt.md` is rooted at the **invoking** repo's working tree (where the slash command lives), not `$REVIEW_ROOT` (which may be a temp worktree). Use `$(pwd)/.claude/codex/review-prompt.md` from the invoking tree, captured before any `cd` into `$REVIEW_ROOT`.
2. Dispatch the Codex run in the background. Use the `Bash` tool with `run_in_background: true`:
   ```bash
   ( /Applications/Codex.app/Contents/Resources/codex exec \
       --json \
      --output-schema "$SCHEMA_PATH" \
      --output-last-message "$LAST_MESSAGE_PATH" \
      --sandbox read-only \
      --cd "$REVIEW_ROOT" \
      - < "$PROMPT_PATH" \
      > "$JSONL_PATH" 2>&1
    echo "__CODEX_EXIT__=$?" > "$STATUS_PATH"
   )
   ```
   (Same caveat: `--output-schema` path must be rooted at the invoking tree.)
3. After dispatching, end the assistant turn. The harness notifies when the background process exits.

## Stage 3 — On wake: parse findings

1. Load persisted state. If the current assistant turn does not know `PR`, read the state path from `/tmp/codex-review.$PPID.latest-state`:
   ```bash
   if [ -z "${STATE:-}" ]; then
     STATE=$(cat "/tmp/codex-review.$PPID.latest-state")
   fi
   MODE=$(jq -r '.mode' "$STATE")
   PR=$(jq -r '.pr' "$STATE")
   PR_URL=$(jq -r '.pr_url' "$STATE")
   OWNER=$(jq -r '.owner' "$STATE")
   REPO=$(jq -r '.repo' "$STATE")
   BASE=$(jq -r '.base' "$STATE")
   HEAD_SHA=$(jq -r '.head_sha' "$STATE")
   REVIEW_ROOT=$(jq -r '.review_root' "$STATE")
   WT=$(jq -r '.worktree_path' "$STATE")
   STATUS_PATH=$(jq -r '.status_path' "$STATE")
   JSONL_PATH=$(jq -r '.jsonl_path' "$STATE")
   LAST_MESSAGE_PATH=$(jq -r '.last_message_path' "$STATE")
   TOUCHED_FILES_PATH=$(jq -r '.touched_files_path' "$STATE")
   TOUCHED_FILES_JSON_PATH=$(jq -r '.touched_files_json_path' "$STATE")
   EVENT_PATH=$(jq -r '.event_path' "$STATE")
   REVIEW_PAYLOAD_PATH=$(jq -r '.review_payload_path' "$STATE")
   REVIEW_PAYLOAD_BODY_ONLY_PATH=$(jq -r '.review_payload_body_only_path' "$STATE")
   REVIEW_RESPONSE_PATH=$(jq -r '.review_response_path' "$STATE")
   REVIEW_STDERR_PATH=$(jq -r '.review_stderr_path' "$STATE")
   test "$MODE" = "pr" || { echo "State file is not for a PR Codex review: $STATE"; exit 1; }
   cd "$REVIEW_ROOT"
   ```
2. Read `$STATUS_PATH`. Parse `<n>` from `__CODEX_EXIT__=<n>`. If the file is missing or malformed, treat `<n>` as non-zero.
3. If `<n> != 0`:
   - Print the exit code and the last 30 lines of `$JSONL_PATH` (use `tail -n 30`).
   - Run cleanup (Stage 5) and stop. Do not retry.
4. If `<n> == 0`:
   1. Validate `$LAST_MESSAGE_PATH` parses as JSON with the expected shape. On schema violation, post raw output as a single conversation comment, run cleanup (Stage 5), and stop.
      ```bash
      if ! jq -e '(.summary | type) == "string" and (.findings | type) == "array"' \
            "$LAST_MESSAGE_PATH" > /dev/null 2>&1; then
        BANNER="## Codex review (degraded)

      _Codex did not produce schema-conforming JSON; posting raw output as a single comment._
      "
        ( printf '%s\n' "$BANNER"
          cat "$LAST_MESSAGE_PATH"
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
        > "$TOUCHED_FILES_PATH"
      ```
   3. Filter findings against the touched files; track drop count:
      ```bash
      jq -R -s 'split("\n") | map(select(length > 0))' \
        "$TOUCHED_FILES_PATH" \
        > "$TOUCHED_FILES_JSON_PATH"
      DROPPED=$(jq --slurpfile touched "$TOUCHED_FILES_JSON_PATH" \
        '[.findings[] | select((.path as $p | $touched[0] | index($p)) | not)] | length' \
        "$LAST_MESSAGE_PATH")
      jq --slurpfile touched "$TOUCHED_FILES_JSON_PATH" \
        '.findings |= map(select((.path as $p | $touched[0] | index($p))))' \
        "$LAST_MESSAGE_PATH" > "/tmp/codex-review-$PR.last-message.filtered"
      mv "/tmp/codex-review-$PR.last-message.filtered" "$LAST_MESSAGE_PATH"
      ```
   4. Decide the event:
      ```bash
      if jq -e '.findings[] | select(.severity == "critical")' \
            "$LAST_MESSAGE_PATH" > /dev/null 2>&1; then
        EVENT="REQUEST_CHANGES"
      else
        EVENT="COMMENT"
      fi
      echo "$EVENT" > "$EVENT_PATH"
      ```
   5. Compute the severity histogram:
      ```bash
      HISTO=$(jq -r '
        .findings
        | group_by(.severity)
        | map({(.[0].severity): length})
        | add // {}
        | "\(.critical // 0) critical · \(.major // 0) major · \(.minor // 0) minor · \(.nit // 0) nit"
      ' "$LAST_MESSAGE_PATH")
      ```
   6. Build the review body:
      ```bash
      SUMMARY=$(jq -r '.summary' "$LAST_MESSAGE_PATH")
      MODEL=$(grep -E '^model[[:space:]]*=' ~/.codex/config.toml | head -1 | sed -E 's/^model[[:space:]]*=[[:space:]]*"?([^"]+)"?[[:space:]]*$/\1/')
      REASONING=$(grep -E '^model_reasoning_effort[[:space:]]*=' ~/.codex/config.toml | head -1 | sed -E 's/^model_reasoning_effort[[:space:]]*=[[:space:]]*"?([^"]+)"?[[:space:]]*$/\1/')
      [ -z "$MODEL" ] && MODEL="default"
      [ -z "$REASONING" ] && REASONING="default"
      BODY="## Codex review

      _Generated by Codex via \`/request-codex-review\`. Model: $MODEL, Reasoning: $REASONING._

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
        "$LAST_MESSAGE_PATH")
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
     > "$REVIEW_PAYLOAD_PATH"

   gh api -X POST "/repos/$OWNER/$REPO/pulls/$PR/reviews" \
          --input "$REVIEW_PAYLOAD_PATH" \
          > "$REVIEW_RESPONSE_PATH" 2> "$REVIEW_STDERR_PATH"
   API_EXIT=$?
   ```
2. Branch on the result:
   - `API_EXIT == 0` → success. Print the review URL:
     ```bash
    URL=$(jq -r '.html_url' "$REVIEW_RESPONSE_PATH")
     echo "Posted Codex review ($EVENT) on PR #$PR: $URL"
     ```
   - `API_EXIT != 0` and stderr contains `Unprocessable Entity` or `comments` validation error → retry once with `comments: []` (body-only review):
     ```bash
    jq '.comments = [] | .event = "COMMENT"' "$REVIEW_PAYLOAD_PATH" \
      > "$REVIEW_PAYLOAD_BODY_ONLY_PATH"
    gh api -X POST "/repos/$OWNER/$REPO/pulls/$PR/reviews" \
           --input "$REVIEW_PAYLOAD_BODY_ONLY_PATH" \
           > "$REVIEW_RESPONSE_PATH" 2>&1
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

Leave `/tmp/codex-review-$PR.*` on disk for forensic value — they get wiped at the start of the next `/request-codex-review` run for the same PR (Stage 1 step 7).

## Edge cases

- **Branch protection prevents `REQUEST_CHANGES` from author**: GitHub may reject `event: REQUEST_CHANGES` if the user is the PR author. Falls through to the 422 handling — retry as body-only with `event: COMMENT`.
- **PR force-pushed mid-review**: `commit_id: $HEAD_SHA` pins inline anchors. Comments anchored to stale lines fail validation → degraded body-only path catches it.
- **Codex emits more findings than GitHub's per-review comment cap (~250)**: GitHub returns 422. Body-only fallback catches it.
- **`$FOCUS` contains shell metacharacters**: passed via heredoc into the prompt file, not into a shell command. No injection risk.
- **`gh` and `codex` disagree about repo identity** (fork checkout where `origin` != upstream): rely on `gh repo view`'s answer.
