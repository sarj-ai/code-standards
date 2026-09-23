from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import transaction
from sarj_standards.libs.repository import (
    config_generation,
    rule_catalog_artifact,
    rule_inventory_artifact,
    rule_level_source,
    rule_lifecycle,
    rule_maintenance,
)
from sarj_standards.libs.rules import DefaultLevel, RuleEngine, RuleId, RuleSelector


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


_SELECTOR = RuleSelector(RuleEngine.PYTHON, RuleId("new-rule"))
_SOURCE = "packages/python/src/sarj_python_lint/rules/new_rule.py"


def _files(root: Path) -> tuple[Path, ...]:
    relative = (
        _SOURCE,
        "packages/standards/src/sarj_standards/configs/rule-inventory.v1.json",
        "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json",
        "packages/standards/src/sarj_standards/configs/rule-ledger.json",
        "packages/typescript/src/index.ts",
        "packages/standards/src/sarj_standards/configs/eslint.strict.mjs",
        "packages/standards/src/sarj_standards/configs/eslint.application.mjs",
    )
    paths = tuple(root / item for item in relative)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(
                "from sarj_python_lint.rule_base import (\n    RuleDocumentation,\n)\n"
                "documentation = RuleDocumentation(\n    summary='example',\n)\n"
                if path == paths[0]
                else '{"schemaVersion":1,"rules":[]}\n',
                encoding="utf-8",
            )
    return paths


def _mock_builders(monkeypatch: pytest.MonkeyPatch, *, fail_catalog_sync: bool = False) -> None:
    def build_inventory(_root: Path) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "rules": [{"family": "python", "id": "new-rule", "code": "SARJ999", "source": _SOURCE, "test": "y"}],
        }

    def build_catalog(_root: Path) -> object:
        return object()

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- lifecycle orchestration interception is the behavior under test.
        rule_inventory_artifact,
        "build",
        build_inventory,
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- lifecycle orchestration interception is the behavior under test.
        rule_catalog_artifact, "build", build_catalog
    )

    def sync_warning_levels(_root: Path, *, check: bool) -> bool:
        _ = check
        return True

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- lifecycle orchestration interception is the behavior under test.
        config_generation,
        "sync_warning_levels",
        sync_warning_levels,
    )

    def sync_to(relative: str, *, fail: bool = False) -> Callable[..., object]:
        def sync(root: Path, *, check: bool) -> object:
            if check:
                status = 0 if (root / relative).read_text(encoding="utf-8") == '{"updated":true}\n' else 1
                return type("Result", (), {"status": status})()
            if fail:
                msg = "catalog generation failed"
                raise RuntimeError(msg)
            transaction.atomic_write_text(root, root / relative, '{"updated":true}\n')
            return type("Result", (), {"status": 0})()

        return sync

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- lifecycle orchestration interception is the behavior under test.
        rule_inventory_artifact,
        "sync",
        sync_to("packages/standards/src/sarj_standards/configs/rule-inventory.v1.json"),
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- lifecycle orchestration interception is the behavior under test.
        rule_maintenance,
        "sync_ledger",
        sync_to("packages/standards/src/sarj_standards/configs/rule-ledger.json"),
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- lifecycle orchestration interception is the behavior under test.
        rule_catalog_artifact,
        "sync",
        sync_to(
            "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json",
            fail=fail_catalog_sync,
        ),
    )


def test_stage_warning_updates_all_artifacts_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, *_ = _files(tmp_path)
    _mock_builders(monkeypatch)

    first = rule_lifecycle.stage_warning(tmp_path, _SELECTOR)
    after_first = tuple(path.read_bytes() for path in _files(tmp_path))
    second = rule_lifecycle.stage_warning(tmp_path, _SELECTOR)

    assert first.status == 0
    assert first.changed
    assert second.status == 0
    assert not second.changed
    assert tuple(path.read_bytes() for path in _files(tmp_path)) == after_first
    assert "default_level=Severity.WARNING" in source.read_text(encoding="utf-8")


def test_promote_error_removes_warning_and_updates_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, *_ = _files(tmp_path)
    _mock_builders(monkeypatch)
    rule_lifecycle.stage_warning(tmp_path, _SELECTOR)

    result = rule_lifecycle.promote_error(tmp_path, _SELECTOR)

    assert result.status == 0
    assert result.changed
    assert "default_level=Severity.WARNING" not in source.read_text(encoding="utf-8")


def test_stage_warning_resynchronizes_derived_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, *_ = _files(tmp_path)
    _mock_builders(monkeypatch)
    rule_lifecycle.stage_warning(tmp_path, _SELECTOR)
    (tmp_path / "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json").write_text("stale\n")

    check = rule_lifecycle.stage_warning(tmp_path, _SELECTOR, check=True)
    result = rule_lifecycle.stage_warning(tmp_path, _SELECTOR)
    rerun = rule_lifecycle.stage_warning(tmp_path, _SELECTOR)

    assert check.status == 1
    assert not check.changed
    assert result.status == 0
    assert result.changed
    assert rerun.status == 0
    assert not rerun.changed
    assert "default_level=Severity.WARNING" in source.read_text(encoding="utf-8")


def test_stage_warning_rolls_back_every_artifact_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _files(tmp_path)
    before = tuple(path.read_bytes() for path in paths)
    _mock_builders(monkeypatch, fail_catalog_sync=True)

    with pytest.raises(RuntimeError, match="catalog generation failed"):
        rule_lifecycle.stage_warning(tmp_path, _SELECTOR)

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
        rule_lifecycle.stage_warning(
            tmp_path,
            RuleSelector(RuleEngine.PYTHON, RuleId("missing")),
        )
    assert tuple(path.read_bytes() for path in paths) == before


def test_stage_warning_suggests_the_closest_live_selector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _files(tmp_path)
    _mock_builders(monkeypatch)

    with pytest.raises(ValueError, match=r"did you mean python:new-rule\?"):
        rule_lifecycle.stage_warning(
            tmp_path,
            RuleSelector(RuleEngine.PYTHON, RuleId("new-rul")),
        )


def test_stage_warning_points_to_rule_discovery_when_no_selector_is_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _files(tmp_path)
    _mock_builders(monkeypatch)

    with pytest.raises(ValueError, match=r"maintain rules manifest"):
        rule_lifecycle.stage_warning(
            tmp_path,
            RuleSelector(RuleEngine.ESLINT, RuleId("unrelated-name")),
        )


def test_stage_warning_rejects_source_without_rule_documentation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, *_ = _files(tmp_path)
    _mock_builders(monkeypatch)
    source.write_text("class NewRule: pass\n", encoding="utf-8")

    with pytest.raises(ValueError, match="documentation declaration"):
        rule_lifecycle.stage_warning(tmp_path, _SELECTOR)


@pytest.mark.parametrize(
    ("engine", "source", "field"),
    [
        (RuleEngine.ESLINT, "const SAMPLE_DOCUMENTATION = {\n  summary: 'example',\n};\n", 'defaultLevel: "warning"'),
        (
            RuleEngine.TEXT,
            'REGISTRY = {\n        "sample": RuleMeta(\n            code="SARJ999",\n        ),\n}\n',
            "default_level=DefaultLevel.WARNING",
        ),
    ],
)
def test_source_severity_editor_round_trips_other_engines(
    tmp_path: Path,
    engine: RuleEngine,
    source: str,
    field: str,
) -> None:
    path = tmp_path / "rule.txt"
    path.write_text(source, encoding="utf-8")
    selector = RuleSelector(engine, RuleId("sample"))

    staged = rule_level_source.prepare(tmp_path, selector, "rule.txt", DefaultLevel.WARNING)
    assert staged.current is DefaultLevel.ERROR
    assert field in staged.after
    path.write_text(staged.after, encoding="utf-8")
    promoted = rule_level_source.prepare(tmp_path, selector, "rule.txt", DefaultLevel.ERROR)
    assert promoted.current is DefaultLevel.WARNING
    assert promoted.after == source
