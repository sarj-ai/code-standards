"""Warning-first authoring is one idempotent transactional operation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import transaction
from sarj_standards.libs.repository import (
    rule_catalog_artifact,
    rule_inventory_artifact,
    rule_lifecycle,
    rule_maintenance,
)


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


_SELECTOR = "python:new-rule"


def _files(root: Path) -> tuple[Path, ...]:
    relative = (
        "packages/standards/src/sarj_standards/configs/rule-warning-levels.v1.json",
        "packages/standards/src/sarj_standards/configs/rule-inventory.v1.json",
        "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json",
        "packages/standards/src/sarj_standards/configs/rule-ledger.json",
    )
    paths = tuple(root / item for item in relative)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text('{"schemaVersion":1,"rules":[]}\n', encoding="utf-8")
    return paths


def _mock_builders(monkeypatch: pytest.MonkeyPatch, *, fail_catalog_sync: bool = False) -> None:
    def build_inventory(_root: Path) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "rules": [{"family": "python", "id": "new-rule", "code": "SARJ999", "source": "x", "test": "y"}],
        }

    def build_catalog(_root: Path) -> object:
        return object()

    monkeypatch.setattr(
        rule_inventory_artifact,
        "build",
        build_inventory,
    )
    monkeypatch.setattr(rule_catalog_artifact, "build", build_catalog)

    def sync_to(relative: str, *, fail: bool = False) -> Callable[..., object]:
        def sync(root: Path, *, check: bool) -> object:
            if check:
                return type("Result", (), {"status": 0})()
            if fail:
                msg = "catalog generation failed"
                raise RuntimeError(msg)
            transaction.atomic_write_text(root, root / relative, '{"updated":true}\n')
            return type("Result", (), {"status": 0})()

        return sync

    monkeypatch.setattr(
        rule_inventory_artifact,
        "sync",
        sync_to("packages/standards/src/sarj_standards/configs/rule-inventory.v1.json"),
    )
    monkeypatch.setattr(
        rule_maintenance,
        "sync_ledger",
        sync_to("packages/standards/src/sarj_standards/configs/rule-ledger.json"),
    )
    monkeypatch.setattr(
        rule_catalog_artifact,
        "sync",
        sync_to(
            "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json",
            fail=fail_catalog_sync,
        ),
    )


def test_stage_warning_updates_all_artifacts_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    warning, *_ = _files(tmp_path)
    _mock_builders(monkeypatch)

    first = rule_lifecycle.stage_warning(tmp_path, _SELECTOR)
    after_first = tuple(path.read_bytes() for path in _files(tmp_path))
    second = rule_lifecycle.stage_warning(tmp_path, _SELECTOR)

    assert first.status == 0
    assert first.changed
    assert second.status == 0
    assert not second.changed
    assert tuple(path.read_bytes() for path in _files(tmp_path)) == after_first
    assert warning.read_text(encoding="utf-8") == '{"rules":["python:new-rule"],"schemaVersion":1}\n'


def test_stage_warning_rolls_back_every_artifact_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _files(tmp_path)
    before = tuple(path.read_bytes() for path in paths)
    _mock_builders(monkeypatch, fail_catalog_sync=True)

    with pytest.raises(RuntimeError, match="catalog generation failed"):
        _ = rule_lifecycle.stage_warning(tmp_path, _SELECTOR)

    assert tuple(path.read_bytes() for path in paths) == before


def test_stage_warning_check_and_unknown_rule_never_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _files(tmp_path)
    before = tuple(path.read_bytes() for path in paths)
    _mock_builders(monkeypatch)

    result = rule_lifecycle.stage_warning(tmp_path, _SELECTOR, check=True)
    assert result.status == 1
    assert not result.changed
    assert tuple(path.read_bytes() for path in paths) == before
    with pytest.raises(ValueError, match="unknown live rule selector"):
        _ = rule_lifecycle.stage_warning(tmp_path, "python:missing")
    assert tuple(path.read_bytes() for path in paths) == before
