"""Failure recovery preserves user state without hiding partial rollback."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

from sarj_lint_configs.libs.adoption.transaction import FileTransaction


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_rollback_restores_file_permission_bits(tmp_path: Path) -> None:
    owned = tmp_path / "owned.txt"
    owned.write_text("before\n", encoding="utf-8")
    owned.chmod(0o640)
    transaction = FileTransaction.capture(tmp_path, (owned,))
    owned.write_text("after\n", encoding="utf-8")
    owned.chmod(0o777)

    report = transaction.rollback()

    assert report.ok
    assert owned.read_text(encoding="utf-8") == "before\n"
    assert stat.S_IMODE(owned.stat().st_mode) == 0o640


def test_rollback_does_not_overwrite_detectable_concurrent_content(tmp_path: Path) -> None:
    owned = tmp_path / "owned.txt"
    owned.write_text("before\n", encoding="utf-8")
    transaction = FileTransaction.capture(tmp_path, (owned,))
    owned.write_text("standards write\n", encoding="utf-8")
    transaction.mark_written(owned)
    owned.write_text("concurrent edit\n", encoding="utf-8")

    report = transaction.rollback()

    assert not report.ok
    assert "changed concurrently" in (report.render() or "")
    assert owned.read_text(encoding="utf-8") == "concurrent edit\n"


def test_rollback_removes_only_new_empty_parent_directories(tmp_path: Path) -> None:
    generated = tmp_path / "new" / "deep" / "generated.txt"
    transaction = FileTransaction.capture(tmp_path, (generated,))
    generated.parent.mkdir(parents=True)
    generated.write_text("partial\n", encoding="utf-8")

    report = transaction.rollback()

    assert report.ok
    assert not (tmp_path / "new").exists()


def test_rollback_reports_permission_failure_without_raising(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    owned = tmp_path / "owned.txt"
    owned.write_text("before\n", encoding="utf-8")
    transaction = FileTransaction.capture(tmp_path, (owned,))
    owned.write_text("after\n", encoding="utf-8")

    def denied(_path: Path, _contents: bytes) -> int:
        message = "read-only filesystem"
        raise PermissionError(message)

    monkeypatch.setattr(type(owned), "write_bytes", denied)

    report = transaction.rollback()

    assert not report.ok
    assert "read-only filesystem" in (report.render() or "")
