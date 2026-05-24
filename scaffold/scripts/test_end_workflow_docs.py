"""Regression checks for end-of-task workflow command docs."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_legacy_task_codex_review_command_is_not_installed():
    assert not (ROOT / ".claude/commands/task-codex-review.md").exists()


def test_task_backlog_command_is_not_installed():
    assert not (ROOT / ".claude/commands/task-backlog.md").exists()


def test_in_flight_artifact_is_not_installed_or_documented():
    assert not (ROOT / "docs/board/in-flight.md").exists()

    checked_paths = [
        "../README.md",
        "../init-workflow.md",
        "../docs/customization.md",
        "../docs/how-it-works.md",
        "CLAUDE.md.template",
        ".claude/commands/task-start.md",
        ".claude/commands/task-finish.md",
        ".claude/commands/task-ship.md",
        "scripts/board.py",
        "scripts/githooks/pre-commit",
    ]
    for path in checked_paths:
        assert "in-flight" not in _read(path)


def test_ship_checks_finished_task_before_commit():
    ship = _read(".claude/commands/task-ship.md")

    assert 'python3 scripts/board.py check-merge "$BRANCH"' in ship
    assert "python3 scripts/board.py finish" in ship


def test_finish_hands_off_cleanly_to_ship():
    finish = _read(".claude/commands/task-finish.md")

    assert "gate command documented in `CLAUDE.md`" in finish
    assert "continue to `/task-ship`" in finish


def test_start_defers_commit_to_ship():
    start = _read(".claude/commands/task-start.md")

    assert "/task-ship" in start
    assert "implementation commit" in start
    assert "Leave it staged by default" in start


def test_ship_keeps_codex_review_as_separate_optional_command():
    ship = _read(".claude/commands/task-ship.md")

    assert "/tmp/ship-codex-review-pr" not in ship
    assert "Codex-review mode" not in ship
    assert "Request Codex review" not in ship
    assert "Optional follow-up" in ship
    assert "/request-codex-review $PR" in ship


def test_ship_uses_default_branch_for_new_pr_summary():
    ship = _read(".claude/commands/task-ship.md")

    assert "origin/main..HEAD" not in ship
    assert "defaultBranchRef" in ship
    assert 'git log "origin/$BASE..HEAD" --oneline' in ship
    assert 'gh pr create --base "$BASE"' in ship


def test_codex_review_persists_event_for_callers():
    review = _read(".claude/commands/request-codex-review.md")

    assert '"/tmp/codex-review-$PR".{status,jsonl,last-message,prompt,touched-files,touched-files.json,review-payload.json,review-payload.body-only.json,review-response.json,review-stderr,event}' in review
    assert 'EVENT_PATH="/tmp/codex-review-$PR.event"' in review
    assert 'echo "$EVENT" > "$EVENT_PATH"' in review


def test_codex_review_persists_wake_state():
    review = _read(".claude/commands/request-codex-review.md")

    assert "/tmp/codex-review-$PR.state.json" in review
    assert "/tmp/codex-local-review-$REVIEW_ID.state.json" in review
    assert 'MODE=$(jq -r \'.mode\'' in review
    assert 'REVIEW_ROOT=$(jq -r \'.review_root\'' in review
    assert 'OWNER=$(jq -r \'.owner\'' in review
    assert 'REPORT=$(jq -r \'.report_path\'' in review


def test_codex_review_empty_args_do_not_hide_gh_failures():
    review = _read(".claude/commands/request-codex-review.md")

    assert "Known no-PR case" in review
    assert "Do not fall back to local-change mode" in review
    assert "Auth, network, rate limit, missing `gh`, or malformed output" in review


def test_request_codex_review_supports_local_changes():
    review = _read(".claude/commands/request-codex-review.md")
    prompt = _read(".claude/codex/review-prompt.md")

    assert "Local-change mode" in review
    assert "git diff --cached" in review
    assert "git diff --no-ext-diff" in review
    assert "git ls-files --others --exclude-standard" in review
    assert "/tmp/codex-local-review-$REVIEW_ID.report.md" in review
    assert "docs/superpowers/reports/codex-review-$REVIEW_ID.md" in review
    assert "python3 scripts/docs_index.py regenerate" in review
    assert 'git add "$REPORT" docs/superpowers/INDEX.md' in review
    assert "pull request or local change set" in prompt
    assert "Use the metadata above to identify the review type" in prompt


def test_installer_uses_request_codex_review_name():
    init = _read("../init-workflow.md")
    customization = _read("../docs/customization.md")
    how_it_works = _read("../docs/how-it-works.md")
    readme = _read("../README.md")

    assert ".claude/commands/request-codex-review.md" in init
    assert "task-codex-review" not in init
    assert "`/request-codex-review`" in customization
    assert "task-codex-review" not in customization
    assert "request-codex-review.md" in how_it_works
    assert "task-codex-review" not in how_it_works
    assert "/request-codex-review" in readme
    assert "task-codex-review" not in readme


def test_installer_does_not_copy_removed_command_or_in_flight_artifact():
    init = _read("../init-workflow.md")

    assert ".claude/commands/task-backlog.md" not in init
    assert "docs/board/in-flight.md" not in init
    assert "{backlog,in-flight}" not in init


def test_codex_review_jq_requirement_is_documented():
    readme = _read("../README.md")
    customization = _read("../docs/customization.md")

    assert "`jq`" in readme
    assert "`jq`" in customization


def test_readme_documents_happy_path_and_failure_recovery():
    readme = _read("../README.md")

    assert "## Happy path" in readme
    for command in ("/init-workflow", "/task-start", "/task-ship"):
        assert command in readme
    happy_path = readme.split("## Happy path", 1)[1].split("## Failure recovery", 1)[0]
    assert "/task-finish" not in happy_path
    assert "/task-backlog" not in readme

    assert "## Failure recovery" in readme
    assert "Active plan blocks push or PR creation" in readme
    assert "Commit fails after docs regenerate" in readme
    assert "Codex review wakes up later" in readme
    assert "CI watch fails or has no required checks" in readme


def test_superpowers_install_command_is_documented():
    init = _read("../init-workflow.md")
    readme = _read("../README.md")
    customization = _read("../docs/customization.md")

    install_command = "/plugin install superpowers@claude-plugins-official"
    assert install_command in init
    assert install_command in readme
    assert install_command in customization
    assert "Install now" in init
