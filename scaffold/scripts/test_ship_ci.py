"""Tests for ship_ci.py."""

from pathlib import Path
from unittest import mock

import ship_ci


def test_start_wipes_state_files(tmp_path: Path) -> None:
    status = tmp_path / "ship-123.status"
    retries = tmp_path / "ship-123.retries"
    all_mode = tmp_path / "ship-123.all-status"
    for p in (status, retries, all_mode):
        p.write_text("stale")

    with mock.patch.object(ship_ci, "TMP_DIR", tmp_path):
        ship_ci._cmd_start(pr=123)

    assert not status.exists()
    assert not retries.exists()
    assert not all_mode.exists()


def test_start_is_idempotent_when_no_state(tmp_path: Path) -> None:
    with mock.patch.object(ship_ci, "TMP_DIR", tmp_path):
        ship_ci._cmd_start(pr=123)  # should not raise


def test_read_exit_code_returns_int_when_status_present(tmp_path: Path) -> None:
    (tmp_path / "ship-123.status").write_text("__SHIP_EXIT__=0\n")
    with mock.patch.object(ship_ci, "TMP_DIR", tmp_path):
        assert ship_ci._read_exit_code(pr=123) == 0


def test_read_exit_code_returns_nonzero_when_status_present(tmp_path: Path) -> None:
    (tmp_path / "ship-123.status").write_text("__SHIP_EXIT__=8\n")
    with mock.patch.object(ship_ci, "TMP_DIR", tmp_path):
        assert ship_ci._read_exit_code(pr=123) == 8


def test_read_exit_code_returns_none_when_status_missing(tmp_path: Path) -> None:
    with mock.patch.object(ship_ci, "TMP_DIR", tmp_path):
        assert ship_ci._read_exit_code(pr=123) is None


def test_read_exit_code_returns_none_when_marker_malformed(tmp_path: Path) -> None:
    (tmp_path / "ship-123.status").write_text("totally not the right format\n")
    with mock.patch.object(ship_ci, "TMP_DIR", tmp_path):
        assert ship_ci._read_exit_code(pr=123) is None


def test_is_all_mode_false_when_marker_absent(tmp_path: Path) -> None:
    with mock.patch.object(ship_ci, "TMP_DIR", tmp_path):
        assert ship_ci._is_all_mode(pr=123) is False


def test_is_all_mode_true_when_marker_present(tmp_path: Path) -> None:
    (tmp_path / "ship-123.all-status").write_text("")
    with mock.patch.object(ship_ci, "TMP_DIR", tmp_path):
        assert ship_ci._is_all_mode(pr=123) is True


def test_read_retries_returns_zero_when_absent(tmp_path: Path) -> None:
    with mock.patch.object(ship_ci, "TMP_DIR", tmp_path):
        assert ship_ci._read_retries(pr=123) == 0


def test_read_retries_returns_stored_value(tmp_path: Path) -> None:
    (tmp_path / "ship-123.retries").write_text("3\n")
    with mock.patch.object(ship_ci, "TMP_DIR", tmp_path):
        assert ship_ci._read_retries(pr=123) == 3


def test_bump_retries_increments_and_returns_new(tmp_path: Path) -> None:
    with mock.patch.object(ship_ci, "TMP_DIR", tmp_path):
        assert ship_ci._bump_retries(pr=123) == 1
        assert ship_ci._bump_retries(pr=123) == 2
        assert (tmp_path / "ship-123.retries").read_text().strip() == "2"


def test_classify_checks_empty_list() -> None:
    assert ship_ci._classify_checks([]) == "empty"


def test_classify_checks_all_passing() -> None:
    checks = [
        {"name": "lint", "state": "SUCCESS"},
        {"name": "test", "state": "SUCCESS"},
        {"name": "type", "state": "NEUTRAL"},
    ]
    assert ship_ci._classify_checks(checks) == "passing"


def test_classify_checks_any_failing() -> None:
    checks = [
        {"name": "lint", "state": "SUCCESS"},
        {"name": "test", "state": "FAILURE"},
    ]
    assert ship_ci._classify_checks(checks) == "failing"


def test_classify_checks_any_pending() -> None:
    checks = [
        {"name": "lint", "state": "SUCCESS"},
        {"name": "test", "state": "IN_PROGRESS"},
    ]
    assert ship_ci._classify_checks(checks) == "pending"


def test_classify_checks_failing_beats_pending() -> None:
    checks = [
        {"name": "lint", "state": "FAILURE"},
        {"name": "test", "state": "IN_PROGRESS"},
    ]
    assert ship_ci._classify_checks(checks) == "failing"


def test_classify_checks_treats_skipped_and_stale_as_passing() -> None:
    checks = [
        {"name": "a", "state": "SKIPPED"},
        {"name": "b", "state": "STALE"},
        {"name": "c", "state": "SUCCESS"},
    ]
    assert ship_ci._classify_checks(checks) == "passing"


def test_classify_checks_treats_unknown_state_as_pending() -> None:
    checks = [{"name": "weird", "state": "SOMETHING_NEW"}]
    assert ship_ci._classify_checks(checks) == "pending"


def test_gh_checks_json_required_includes_required_flag() -> None:
    with mock.patch.object(ship_ci.subprocess, "run") as run:
        run.return_value = mock.Mock(returncode=0, stdout='[]', stderr="")
        ship_ci._gh_checks_json(pr=123, required_only=True)
    cmd = run.call_args[0][0]
    assert "--required" in cmd
    assert "--json" in cmd
    assert "name,state" in cmd
    assert "123" in cmd


def test_gh_checks_json_all_omits_required_flag() -> None:
    with mock.patch.object(ship_ci.subprocess, "run") as run:
        run.return_value = mock.Mock(returncode=0, stdout='[]', stderr="")
        ship_ci._gh_checks_json(pr=123, required_only=False)
    cmd = run.call_args[0][0]
    assert "--required" not in cmd


def test_gh_checks_json_parses_array() -> None:
    payload = '[{"name":"lint","state":"SUCCESS"}]'
    with mock.patch.object(ship_ci.subprocess, "run") as run:
        run.return_value = mock.Mock(returncode=0, stdout=payload, stderr="")
        result = ship_ci._gh_checks_json(pr=123, required_only=True)
    assert result == [{"name": "lint", "state": "SUCCESS"}]


def test_gh_checks_json_returns_empty_on_no_checks_exit_code() -> None:
    # gh exits non-zero with empty stdout when no checks exist at all
    with mock.patch.object(ship_ci.subprocess, "run") as run:
        run.return_value = mock.Mock(returncode=1, stdout="", stderr="no checks reported")
        result = ship_ci._gh_checks_json(pr=123, required_only=True)
    assert result == []


def test_gh_checks_json_returns_empty_on_malformed_json() -> None:
    with mock.patch.object(ship_ci.subprocess, "run") as run:
        run.return_value = mock.Mock(returncode=0, stdout="not json", stderr="")
        result = ship_ci._gh_checks_json(pr=123, required_only=True)
    assert result == []


def test_gh_checks_json_returns_empty_on_timeout() -> None:
    with mock.patch.object(ship_ci.subprocess, "run") as run:
        run.side_effect = ship_ci.subprocess.TimeoutExpired(cmd=["gh"], timeout=30)
        result = ship_ci._gh_checks_json(pr=123, required_only=True)
    assert result == []
