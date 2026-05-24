---
description: Request a Codex review for a PR or local-only changes. PR reviews post inline GitHub review comments; local reviews write a repo-local markdown report.
---

Run Codex as a second reviewer on a pull request or on local-only changes.

Arguments (may be empty): `$ARGUMENTS`

## Pre-flight

1. Verify `codex` is installed: `/Applications/Codex.app/Contents/Resources/codex --version` must exit 0. If not, stop with: "Codex CLI not found at expected path. Install/launch Codex.app from https://codex.openai.com/."
2. If `$ARGUMENTS` resolves to PR mode (numeric, `owner/repo#N`, GitHub URL, or empty on a non-main branch), verify `gh auth status` exits 0. If not, stop with: "Run `gh auth login` first." Local-change mode does not require GitHub auth.

## Stage 1 — Prepare

Run the helper. On success it prints the per-review directory; on no-changes/no-PR it exits non-zero with a message:

```bash
REVIEW_DIR=$(python3 scripts/codex_review.py prepare "$ARGUMENTS")
test -n "$REVIEW_DIR" || exit 1
. "$REVIEW_DIR/dispatch.env"   # exports CODEX_REVIEW_DIR, CODEX_REVIEW_SCHEMA, CODEX_REVIEW_ROOT
```

## Stage 2 — Dispatch codex in background

Use the `Bash` tool with `run_in_background: true`:

```bash
( /Applications/Codex.app/Contents/Resources/codex exec \
    --json \
    --output-schema "$CODEX_REVIEW_SCHEMA" \
    --output-last-message "$CODEX_REVIEW_DIR/last-message.json" \
    --sandbox read-only \
    --cd "$CODEX_REVIEW_ROOT" \
    - < "$CODEX_REVIEW_DIR/prompt.txt" \
    > "$CODEX_REVIEW_DIR/codex.jsonl" 2> "$CODEX_REVIEW_DIR/review-stderr"
  echo "__CODEX_EXIT__=$?" > "$CODEX_REVIEW_DIR/status"
)
```

After dispatching, end the assistant turn. The harness notifies when the background process exits.

## Stage 3 — On wake: finalize

```bash
python3 scripts/codex_review.py finish
```

The helper:
- Loads the latest review directory from `/tmp/codex-review.latest`.
- Reads `status` to check codex's exit code; on non-zero prints the last 30 lines of `codex.jsonl` and stops.
- Validates the JSON output. On schema violation: PR mode posts a single degraded comment; local mode writes a degraded report.
- Filters findings against the touched-files diff, computes the event (`REQUEST_CHANGES` if any critical else `COMMENT`), assembles the report/payload.
- PR mode: POSTs the review via `gh api`. On 422 with comments-validation failure, retries body-only.
- Local mode: writes `docs/superpowers/reports/codex-review-<id>.md`, runs `python3 scripts/docs_index.py regenerate`, stages the report + INDEX.
- Cleans up the PR worktree (if any).

## Edge cases

- **Branch protection prevents `REQUEST_CHANGES` from author**: caught by the 422 fallback (retry as `COMMENT` body-only).
- **PR force-pushed mid-review**: `commit_id` pins inline anchors; stale anchors fail validation → degraded body-only path catches it.
- **More findings than GitHub's per-review cap (~250)**: GitHub returns 422; body-only fallback catches it.
- **`$FOCUS` contains shell metacharacters**: passed via heredoc into the prompt file, not into a shell command. No injection risk.
- **Forensic files**: `/tmp/codex-review-<key>/` is left in place until the next invocation for the same key overwrites it.
