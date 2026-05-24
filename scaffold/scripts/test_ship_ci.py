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
