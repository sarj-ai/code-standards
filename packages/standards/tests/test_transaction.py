from __future__ import annotations

from functools import partial
import os
from pathlib import Path
import stat
from typing import Literal, override

import pytest
from sarj_rule_contracts import SourceChangedError

from sarj_standards.libs.adoption import transaction as transaction_module
from sarj_standards.libs.adoption.transaction import FileTransaction, assert_expected, validate_targets


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

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- write failure injection verifies transaction rollback.
        transaction_module, "atomic_write_bytes", denied
    )

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


@pytest.mark.parametrize("operation", ["write", "delete"])
def test_rollback_restores_real_mutation_interrupted_before_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: Literal["write", "delete"]
) -> None:
    owned = tmp_path / "owned.txt"
    original = b"before\n"
    replacement = b"after\n"
    owned.write_bytes(original)
    owned.chmod(0o640)
    captured = FileTransaction.capture(tmp_path, (owned,), explicit_only=True)
    real_write = transaction_module.atomic_write_bytes
    real_remove = transaction_module.remove_file
    effects: list[str] = []

    def write_then_interrupt(root: Path, path: Path, contents: bytes, *, mode: int | None = None) -> None:
        real_write(root, path, contents, mode=mode)
        if path == owned and contents == replacement:
            effects.append("write")
            raise KeyboardInterrupt

    def remove_then_interrupt(root: Path, path: Path) -> None:
        real_remove(root, path)
        effects.append("delete")
        raise KeyboardInterrupt

    if operation == "write":
        monkeypatch.setattr(  # sarj-noqa: SARJ445 -- interrupt after the real atomic replacement, before transaction receipt publication.
            transaction_module, "atomic_write_bytes", write_then_interrupt
        )
        mutate = partial(captured.write_bytes, owned, replacement)
    else:
        monkeypatch.setattr(  # sarj-noqa: SARJ445 -- interrupt after the real unlink, before transaction receipt publication.
            transaction_module, "remove_file", remove_then_interrupt
        )
        mutate = partial(captured.remove_file, owned)

    with pytest.raises(KeyboardInterrupt):
        mutate()

    assert effects == [operation]
    assert (owned.read_bytes() if owned.is_file() else None) != original
    report = captured.rollback()
    assert report.ok
    assert owned.read_bytes() == original
    assert stat.S_IMODE(owned.stat().st_mode) == 0o640


def test_source_rollback_restores_real_replacement_interrupted_before_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = tmp_path / "owned.py"
    original = b"before\n"
    replacement = b"after\n"
    owned.write_bytes(original)
    owned.chmod(0o640)
    group = owned.stat().st_gid
    captured = FileTransaction.capture(tmp_path, (owned,), explicit_only=True, source_writes=True)
    real_replace = Path.replace
    effects: list[Path] = []

    def replace_then_interrupt(temporary: Path, destination: Path) -> Path:
        result = real_replace(temporary, destination)
        if destination == owned and owned.read_bytes() == replacement:
            effects.append(destination)
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- interrupt after the native source replacement, before its transaction receipt is published.
        Path, "replace", replace_then_interrupt
    )

    with pytest.raises(KeyboardInterrupt):
        captured.write_bytes(owned, replacement)

    assert effects == [owned]
    assert owned.read_bytes() == replacement
    assert captured.written == {}
    report = captured.rollback()
    assert report.ok
    assert owned.read_bytes() == original
    assert stat.S_IMODE(owned.stat().st_mode) == 0o640
    assert owned.stat().st_gid == group
    assert not list(tmp_path.glob(".sarj-fix-*"))


def test_rejected_later_source_write_retains_receipt_and_preserves_concurrent_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = tmp_path / "owned.py"
    owned.write_bytes(b"before\n")
    first = b"first\n"
    foreign = b"independent edit\n"
    captured = FileTransaction.capture(tmp_path, (owned,), explicit_only=True, source_writes=True)
    captured.write_bytes(owned, first)
    native_fsync = os.fsync

    def concurrent_fsync(descriptor: int) -> None:
        native_fsync(descriptor)
        if owned.read_bytes() == first:
            owned.write_bytes(foreign)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- edit the real source during temporary-file fsync so the final pre-replacement guard rejects a later attempt.
        "sarj_rule_contracts.files.os.fsync", concurrent_fsync
    )

    with pytest.raises(SourceChangedError, match="source changed while fixes were prepared"):
        captured.write_bytes(owned, b"second\n")

    assert captured.written == {owned: first}
    assert owned.read_bytes() == foreign
    report = captured.rollback()
    assert not report.ok
    assert "changed concurrently" in (report.render() or "")
    assert owned.read_bytes() == foreign
    assert not list(tmp_path.glob(".sarj-fix-*"))


def test_unperformed_first_write_does_not_claim_concurrent_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = tmp_path / "owned.txt"
    original = b"before\n"
    owned.write_bytes(original)
    owned.chmod(0o640)
    captured = FileTransaction.capture(tmp_path, (owned,), explicit_only=True)

    def interrupt_before_write(_root: Path, path: Path, _contents: bytes) -> None:
        path.chmod(0o600)
        raise KeyboardInterrupt

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- change permissions independently and interrupt before any content mutation.
        transaction_module, "atomic_write_bytes", interrupt_before_write
    )

    with pytest.raises(KeyboardInterrupt):
        captured.write_bytes(owned, b"after\n")

    report = captured.rollback()
    assert report.ok
    assert owned.read_bytes() == original
    assert stat.S_IMODE(owned.stat().st_mode) == 0o600


def test_interrupted_later_write_retains_the_earlier_successful_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = tmp_path / "owned.txt"
    original = b"before\n"
    owned.write_bytes(original)
    captured = FileTransaction.capture(tmp_path, (owned,), explicit_only=True)
    captured.write_bytes(owned, b"first\n")
    real_write = transaction_module.atomic_write_bytes

    def interrupt_second_write(root: Path, path: Path, contents: bytes, *, mode: int | None = None) -> None:
        if contents == b"second\n":
            raise KeyboardInterrupt
        real_write(root, path, contents, mode=mode)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- stop a later attempt before its effect while preserving the first real write and rollback.
        transaction_module, "atomic_write_bytes", interrupt_second_write
    )

    with pytest.raises(KeyboardInterrupt):
        captured.write_bytes(owned, b"second\n")

    assert owned.read_bytes() == b"first\n"
    report = captured.rollback()
    assert report.ok
    assert owned.read_bytes() == original


def test_pending_write_preserves_a_different_concurrent_content_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = tmp_path / "owned.txt"
    owned.write_bytes(b"before\n")
    captured = FileTransaction.capture(tmp_path, (owned,), explicit_only=True)
    real_write = transaction_module.atomic_write_bytes
    foreign = b"independent edit\n"

    def write_then_replace_independently(root: Path, path: Path, contents: bytes) -> None:
        real_write(root, path, contents)
        path.write_bytes(foreign)
        raise KeyboardInterrupt

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- make a real standards write, then an independent edit before receipt publication.
        transaction_module, "atomic_write_bytes", write_then_replace_independently
    )

    with pytest.raises(KeyboardInterrupt):
        captured.write_bytes(owned, b"after\n")

    report = captured.rollback()
    assert not report.ok
    assert "changed concurrently" in (report.render() or "")
    assert owned.read_bytes() == foreign


def test_published_receipt_precedes_stale_pending_state(tmp_path: Path) -> None:
    owned = tmp_path / "owned.txt"
    original = b"before\n"
    replacement = b"after\n"
    owned.write_bytes(original)
    owned.chmod(0o640)
    captured = FileTransaction.capture(tmp_path, (owned,), explicit_only=True)

    class ConcurrentAfterReceipt(dict[Path, bytes | None]):  # ruff: ignore[subclass-builtin] -- observe the real public receipt insertion while preserving its mapping behavior.
        @override
        def __setitem__(self, key: Path, value: bytes | None) -> None:
            super().__setitem__(key, value)
            if key == owned and value == replacement:
                owned.write_bytes(original)
                owned.chmod(0o600)
                raise KeyboardInterrupt

    captured.written = ConcurrentAfterReceipt()

    with pytest.raises(KeyboardInterrupt):
        captured.write_bytes(owned, replacement)

    report = captured.rollback()
    assert not report.ok
    assert "changed concurrently" in (report.render() or "")
    assert owned.read_bytes() == original
    assert stat.S_IMODE(owned.stat().st_mode) == 0o600
