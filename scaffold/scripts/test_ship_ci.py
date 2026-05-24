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
