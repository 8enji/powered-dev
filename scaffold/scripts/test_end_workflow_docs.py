"""Regression checks for end-of-task workflow command docs."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_legacy_task_codex_review_command_is_not_installed():
    assert not (ROOT / ".claude/commands/task-codex-review.md").exists()


def test_task_finish_command_is_not_installed():
    assert not (ROOT / ".claude/commands/task-finish.md").exists()


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


def test_start_defers_commit_to_ship():
    start = _read(".claude/commands/task-start.md")

    assert "/task-ship" in start
    assert "implementation commit" in start
    assert "Leave it staged by default" in start


def test_ship_delegates_codex_review_to_separate_command():
    """Ship may offer Codex review as a Green-path option, but it must delegate
    all the work to /request-codex-review rather than embedding review machinery."""
    ship = _read(".claude/commands/task-ship.md")

    # No leftover temp-file machinery or bespoke review mode in ship itself.
    assert "/tmp/ship-codex-review-pr" not in ship
    assert "Codex-review mode" not in ship
    # The actual review must dispatch via the separate slash command.
    assert "/request-codex-review $PR" in ship
    # The option must be conditional — only offered when the command file exists.
    # A future edit removing "only if" would unconditionally offer Codex review
    # to users who don't have it installed.
    assert 'only if `.claude/commands/request-codex-review.md` exists' in ship


def test_ship_uses_default_branch_for_new_pr_summary():
    ship = _read(".claude/commands/task-ship.md")

    assert "origin/main..HEAD" not in ship
    assert "defaultBranchRef" in ship
    assert 'git log "origin/$BASE..HEAD" --oneline' in ship
    assert 'gh pr create --base "$BASE"' in ship


def test_codex_review_dispatches_to_python_helper():
    """The slash command must delegate to the codex_review.py helper for both stages."""
    review = _read(".claude/commands/request-codex-review.md")

    assert "python3 scripts/codex_review.py prepare" in review
    assert "python3 scripts/codex_review.py finish" in review


def test_codex_review_passes_session_to_helper():
    """The slash command must pass $PPID as the session id to both stages so
    concurrent Claude sessions don't clobber each other's latest-pointer file."""
    review = _read(".claude/commands/request-codex-review.md")

    assert '--session "$PPID"' in review
    # Both prepare and finish must include the session.
    prepare_line = next(
        l for l in review.splitlines() if "codex_review.py prepare" in l
    )
    finish_line = next(
        l for l in review.splitlines() if "codex_review.py finish" in l
    )
    assert '--session "$PPID"' in prepare_line
    assert '--session "$PPID"' in finish_line


def test_codex_review_dispatch_sources_env_from_helper():
    """The slash command must source the helper-written env file so the background
    Bash call can reference CODEX_REVIEW_DIR, CODEX_REVIEW_SCHEMA, CODEX_REVIEW_ROOT."""
    review = _read(".claude/commands/request-codex-review.md")

    assert "dispatch.env" in review
    assert "CODEX_REVIEW_DIR" in review
    assert "CODEX_REVIEW_SCHEMA" in review
    assert "CODEX_REVIEW_ROOT" in review


def test_codex_review_keeps_background_codex_dispatch_in_slash_command():
    """The codex exec call must remain inline in the slash command (must run as a
    Bash tool call from the assistant turn so the harness wakes on completion)."""
    review = _read(".claude/commands/request-codex-review.md")

    assert "/Applications/Codex.app/Contents/Resources/codex exec" in review
    assert "--output-schema" in review
    assert "--output-last-message" in review
    assert "--sandbox read-only" in review
    assert "run_in_background" in review
    assert "__CODEX_EXIT__" in review


def test_codex_review_documents_edge_cases():
    """The edge-cases section must stay documented in the slash command even after
    the bash logic moves into the Python helper."""
    review = _read(".claude/commands/request-codex-review.md")

    assert "Branch protection" in review
    assert "force-pushed" in review
    assert "FOCUS" in review
    assert "shell metacharacters" in review


def test_request_codex_review_supports_local_changes():
    """Local-change mode behavior is now implemented in codex_review.py; the slash
    command must document that local mode is supported and the prompt source must
    still describe both review modes."""
    review = _read(".claude/commands/request-codex-review.md")
    prompt = _read(".claude/codex/review-prompt.md")
    helper = _read("scripts/codex_review.py")

    assert "local" in review.lower()
    assert "docs/superpowers/reports/codex-review-" in review
    assert "python3 scripts/docs_index.py regenerate" in review

    # Behavioral coverage lives in the helper now. The helper invokes git via
    # argv-style lists (subprocess), not shell strings.
    assert '"diff", "--cached"' in helper
    assert '"ls-files", "--others", "--exclude-standard"' in helper

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


def test_installer_and_docs_do_not_reference_task_finish():
    init = _read("../init-workflow.md")
    readme = _read("../README.md")
    how_it_works = _read("../docs/how-it-works.md")
    ship = _read(".claude/commands/task-ship.md")

    for content in (init, readme, how_it_works, ship):
        assert "task-finish" not in content
        assert "/task-finish" not in content


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


def test_readme_documents_core_commands():
    """README narrative must mention the core slash commands and not reference
    removed commands (task-finish, task-backlog)."""
    readme = _read("../README.md")

    for command in ("/init-workflow", "/task-start", "/task-ship", "/request-codex-review"):
        assert command in readme
    assert "/task-finish" not in readme
    assert "/task-backlog" not in readme


def test_superpowers_install_command_is_documented():
    """The superpowers install command must appear in the install flow (init) and
    in customization docs. The README's narrative install path delegates to
    init-workflow.md, so it does not need the literal install command itself."""
    init = _read("../init-workflow.md")
    customization = _read("../docs/customization.md")

    install_command = "/plugin install superpowers@claude-plugins-official"
    assert install_command in init
    assert install_command in customization
    assert "Install now" in init
