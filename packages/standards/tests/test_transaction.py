"""Failure recovery preserves user state without hiding partial rollback."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import transaction as transaction_module
from sarj_standards.libs.adoption.transaction import FileTransaction, assert_expected, validate_targets


if TYPE_CHECKING:
    from pathlib import Path


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

    def denied(_root: Path, _path: Path, _contents: bytes) -> None:
        message = "read-only filesystem"
        raise PermissionError(message)

    monkeypatch.setattr(transaction_module, "atomic_write_bytes", denied)

    report = transaction.rollback()

    assert not report.ok
    assert "read-only filesystem" in (report.render() or "")


def test_transaction_rejects_hard_linked_mutation_target(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text('{"private": true}\n', encoding="utf-8")
    target = tmp_path / "package.json"
    target.hardlink_to(outside)

    with pytest.raises(OSError, match="hard-linked"):
        validate_targets(tmp_path, (target,))

    assert outside.read_text(encoding="utf-8") == '{"private": true}\n'


def test_planned_write_refuses_a_late_concurrent_edit(tmp_path: Path) -> None:
    target = tmp_path / "package.json"
    target.write_text('{"before": true}\n', encoding="utf-8")
    expected = target.read_bytes()
    target.write_text('{"concurrent": true}\n', encoding="utf-8")

    with pytest.raises(OSError, match="changed concurrently"):
        assert_expected(tmp_path, target, expected)

    assert target.read_text(encoding="utf-8") == '{"concurrent": true}\n'
