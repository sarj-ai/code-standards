from __future__ import annotations

from importlib.resources import files
from importlib.util import find_spec
from pathlib import Path
import sys
from typing import TYPE_CHECKING

import pytest
from sarj_python_lint.rule_base import Rule as PythonRule
from sarj_python_lint.rule_metadata import authored_descriptors, load_descriptors
from sarj_python_lint.rules import REGISTRY as PYTHON_RULES
from sarj_python_lint.rules.no_dunder_all import NoDunderAll

from sarj_standards.libs.linting.analysis import native_metadata
from sarj_standards.libs.linting.external import ProcessOutput, run_process
from sarj_standards.libs.repository import (
    python_rule_descriptors,
    rule_authoring,
    rule_inventory_artifact,
    rule_lifecycle,
    rule_maintenance,
)
from sarj_standards.libs.rules import RuleSelector


if TYPE_CHECKING:
    from collections.abc import Sequence


_ROOT = Path(__file__).resolve().parents[4]
_REGISTRY = Path("packages/python/src/sarj_python_lint/rules/_registry.py")
_INVENTORY = Path("packages/standards/src/sarj_standards/configs/rule-inventory.v1.json")
_REGISTRY_SOURCE = "from types import MappingProxyType\n\n_AUTHORING_REGISTRY = MappingProxyType({\n})\n"
_EMPTY_DESCRIPTORS = "SCHEMA_VERSION = 1\nDESCRIPTORS: tuple = ()\n"


def _projection(code: str, *, rule_id: str = 'RuleId("new-clock-rule")') -> str:
    return (
        "SCHEMA_VERSION = 1\nDESCRIPTORS: tuple = (RuleDescriptor(\n"
        f"rule_id={rule_id}, module='sarj_python_lint.rules.new_clock_rule', class_name='NewClockRule',\n"
        f"code={code!r}, description='Use an explicit clock.', aliases=(), enabled_by_default=True),)\n"
    )


def _format(root: Path, *, descriptors: str | None = "old descriptors\n") -> Path:
    registry = root / _REGISTRY
    registry.parent.mkdir(parents=True)
    registry.write_text(_REGISTRY_SOURCE, encoding="utf-8")
    destination = root / python_rule_descriptors.DESCRIPTOR_PATH
    if descriptors is not None:
        destination.write_text(descriptors, encoding="utf-8")
    return destination


def test_independent_fresh_renderer_matches_installed_source_owner() -> None:
    from sarj_python_lint.rule_metadata import render_authored_descriptors  # ruff: ignore[import-outside-top-level] -- this test explicitly selects independent native metadata generation.

    assert load_descriptors() == authored_descriptors()
    script = (
        "import sys; from sarj_python_lint.rule_metadata import render_authored_descriptors; "
        "sys.stdout.write(render_authored_descriptors())"
    )
    completed = run_process((sys.executable, "-I", "-c", script), cwd=_ROOT, timeout_seconds=120)
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr
    assert completed.stdout == render_authored_descriptors()
    assert completed.stdout == files("sarj_python_lint").joinpath("_rule_descriptors.py").read_text(encoding="utf-8")
    if _uses_selected_python_sources(_ROOT):
        assert python_rule_descriptors.render(_ROOT) == completed.stdout
    else:
        with pytest.raises(RuntimeError, match="selected checkout's source packages"):
            python_rule_descriptors.render(_ROOT)
        with pytest.raises(RuntimeError, match="selected checkout's source packages"):
            python_rule_descriptors.emit(_ROOT)


def _uses_selected_python_sources(root: Path) -> bool:
    packages = (("standards", "sarj_standards"), ("contracts", "sarj_rule_contracts"), ("python", "sarj_python_lint"))
    for package, module in packages:
        spec = find_spec(module)
        expected = root / f"packages/{package}/src/{module}/__init__.py"
        if spec is None or spec.origin is None or Path(spec.origin).resolve() != expected.resolve():
            return False
    return True


@pytest.mark.parametrize(
    ("arguments", "status"),
    [(("--check",), 0), (("--sync",), 0), ((), 2), (("--emit", "--check"), 2), (("--check", "--sync"), 2)],
    ids=("check", "sync", "missing-mode", "emit-check-conflict", "check-sync-conflict"),
)
def test_installed_descriptor_worker_preserves_mode_and_exit_contract(
    tmp_path: Path, arguments: tuple[str, ...], status: int
) -> None:
    completed = run_process(
        (
            sys.executable,
            "-I",
            "-m",
            "sarj_standards.libs.repository.python_rule_descriptors",
            "--root",
            str(tmp_path),
            *arguments,
        ),
        cwd=tmp_path,
        timeout_seconds=30,
    )
    assert completed.returncode == status
    if status == 0:
        assert completed.stdout == "ok: Python registry does not use generated descriptors\n"
        assert not completed.stderr
    else:
        assert not completed.stdout
        assert "choose exactly one of --emit, --check or --sync" in completed.stderr


@pytest.mark.parametrize("help_option", ["-h", "--help"])
def test_installed_descriptor_worker_help_does_not_execute_pending_modes(tmp_path: Path, help_option: str) -> None:
    destination = _format(tmp_path)
    paths = (tmp_path / _REGISTRY, destination)
    before = tuple(path.read_bytes() for path in paths)
    completed = run_process(
        (
            sys.executable,
            "-I",
            "-m",
            "sarj_standards.libs.repository.python_rule_descriptors",
            "--root",
            str(tmp_path),
            "--emit",
            "--check",
            help_option,
        ),
        cwd=tmp_path,
        timeout_seconds=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr
    assert "Usage:" in completed.stdout
    assert "--emit" in completed.stdout
    assert "--check" in completed.stdout
    assert "--sync" in completed.stdout
    assert tuple(path.read_bytes() for path in paths) == before


def test_full_native_metadata_retains_live_instance_completeness() -> None:
    actual = native_metadata(PYTHON_RULES)
    expected = {entry.code: (entry.rule_id, entry.description) for entry in authored_descriptors()}
    assert {code: (entry.rule_id, entry.description) for code, entry in actual.items()} == expected


def test_emit_rejects_a_different_source_checkout(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="selected checkout"):
        python_rule_descriptors.emit(tmp_path)


@pytest.mark.parametrize(
    "projection",
    ["", "SCHEMA_VERSION = True\nDESCRIPTORS: tuple = ()\n", "SCHEMA_VERSION = 1\n"],
    ids=("empty", "invalid-schema", "missing-table"),
)
def test_fresh_renderer_rejects_incomplete_worker_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, projection: str
) -> None:
    def worker(_argv: Sequence[str], *, cwd: Path, timeout_seconds: float) -> ProcessOutput:
        assert cwd == tmp_path
        assert timeout_seconds == 120
        return ProcessOutput(0, projection, "")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- malformed worker output must fail before any artifact writer.
        python_rule_descriptors, "run_process", worker
    )
    with pytest.raises(ValueError, match="incompatible module exports"):
        python_rule_descriptors.render(tmp_path)


def test_fresh_renderer_preserves_oracle_process_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def worker(_argv: Sequence[str], *, cwd: Path, timeout_seconds: float) -> ProcessOutput:
        assert cwd == tmp_path
        assert timeout_seconds == 120
        return ProcessOutput(9, "", "metadata validation failed")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- a failed authoritative worker must not become a successful empty projection.
        python_rule_descriptors, "run_process", worker
    )
    with pytest.raises(RuntimeError, match="exit code 9: metadata validation failed"):
        python_rule_descriptors.render(tmp_path)


def test_legacy_native_format_does_not_regenerate_descriptors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = tmp_path / _REGISTRY
    registry.parent.mkdir(parents=True)
    registry.write_text("from types import MappingProxyType\nREGISTRY = MappingProxyType({})\n", encoding="utf-8")

    def forbidden_render(_root: Path) -> str:
        msg = "legacy registry must not request descriptors"
        raise AssertionError(msg)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- legacy-format bypass of descriptor generation is the contract under test.
        python_rule_descriptors, "render", forbidden_render
    )
    assert python_rule_descriptors.sync(tmp_path, check=False).status == 0
    assert not (tmp_path / python_rule_descriptors.DESCRIPTOR_PATH).exists()


def test_runtime_registry_requires_the_real_independent_authoring_table(tmp_path: Path) -> None:
    runtime = tmp_path / "packages/python/src/sarj_python_lint/rules/_runtime_registry.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="literal independent authoring table"):
        python_rule_descriptors.enabled(tmp_path)


def test_malformed_authoring_marker_cannot_bypass_descriptor_check(tmp_path: Path) -> None:
    registry = tmp_path / _REGISTRY
    registry.parent.mkdir(parents=True)
    registry.write_text("_AUTHORING_REGISTRY = {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="literal independent authoring table"):
        python_rule_descriptors.enabled(tmp_path)


def test_check_reports_missing_descriptor_without_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = _format(tmp_path, descriptors=None)

    def projection(_root: Path) -> str:
        return "SCHEMA_VERSION = 1\n"

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the independent renderer is controlled to isolate read-only drift behavior.
        python_rule_descriptors, "render", projection
    )
    result = python_rule_descriptors.sync(tmp_path, check=True)
    assert result.status == 1
    assert "drift" in result.message
    assert not destination.exists()


def test_descriptor_check_stops_inventory_before_live_runtime_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _format(tmp_path)

    def projection(_root: Path) -> str:
        return "SCHEMA_VERSION = 1\n"

    def forbidden_inventory(_root: Path) -> str:
        msg = "stale descriptors must fail before reading runtime registries"
        raise AssertionError(msg)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- ordering independent source validation before live inventory is under test.
        python_rule_descriptors, "render", projection
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- runtime inventory must not mask descriptor drift.
        rule_inventory_artifact, "render", forbidden_inventory
    )
    assert rule_inventory_artifact.sync(tmp_path, check=True).status == 1


def test_inventory_failure_rolls_back_descriptor_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = _format(tmp_path)
    inventory = tmp_path / _INVENTORY
    inventory.parent.mkdir(parents=True)
    inventory.write_text("old inventory\n", encoding="utf-8")

    def projection(_root: Path) -> str:
        return "SCHEMA_VERSION = 1\n"

    def failed_inventory(_root: Path) -> str:
        assert destination.read_text(encoding="utf-8") == "SCHEMA_VERSION = 1\n"
        msg = "inventory projection failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- generate a new descriptor before the real transaction's later failure.
        python_rule_descriptors, "render", projection
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- failure after a descriptor write must trigger the owning transaction rollback.
        rule_inventory_artifact, "render", failed_inventory
    )
    with pytest.raises(RuntimeError, match="inventory projection failed"):
        rule_inventory_artifact.sync(tmp_path, check=False)
    assert destination.read_text(encoding="utf-8") == "old descriptors\n"
    assert inventory.read_text(encoding="utf-8") == "old inventory\n"


def test_new_rule_plan_is_dry_and_records_descriptor_before_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = _format(tmp_path)

    def forbidden_render(_root: Path) -> str:
        msg = "dry plans must not execute the source oracle"
        raise AssertionError(msg)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- planning must remain read-only and cannot execute future authored code.
        python_rule_descriptors, "render", forbidden_render
    )
    plan = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse("python:new-clock-rule"), category="testing", summary="Use an explicit clock."
    )
    assert plan.descriptors == python_rule_descriptors.DescriptorPlan(destination, b"old descriptors\n")
    assert all(not path.exists() for path, _ in plan.files)
    assert destination.read_text(encoding="utf-8") == "old descriptors\n"
    assert str(python_rule_descriptors.DESCRIPTOR_PATH) in plan.render(tmp_path)


@pytest.mark.parametrize("failure", ["oracle", "concurrent-descriptor"])
def test_new_rule_generation_failures_restore_source_registration_and_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    destination = _format(tmp_path)
    registry = tmp_path / _REGISTRY
    before = registry.read_bytes()
    plan = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse("python:new-clock-rule"), category="testing", summary="Use an explicit clock."
    )

    def failed_projection(_root: Path) -> str:
        assert all(path.is_file() for path, _ in plan.files)
        assert "NewClockRule.id: NewClockRule" in registry.read_text(encoding="utf-8")
        if failure == "oracle":
            msg = "source oracle failed"
            raise RuntimeError(msg)
        destination.write_text("concurrent owner\n", encoding="utf-8")
        return "SCHEMA_VERSION = 1\n"

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- inject source-oracle and concurrent-owner failure after real scaffold writes.
        python_rule_descriptors, "render", failed_projection
    )
    with pytest.raises((RuntimeError, OSError), match=r"source oracle failed|changed concurrently"):
        rule_authoring.apply(plan, tmp_path)
    assert registry.read_bytes() == before
    assert all(not path.exists() for path, _ in plan.files)
    assert not plan.edits[1].path.exists()
    expected = "old descriptors\n" if failure == "oracle" else "concurrent owner\n"
    assert destination.read_text(encoding="utf-8") == expected


def test_new_rule_applies_descriptors_after_actual_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = _format(tmp_path, descriptors=None)
    plan = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse("python:new-clock-rule"), category="testing", summary="Use an explicit clock."
    )

    def projection(_root: Path) -> str:
        assert all(path.is_file() for path, _ in plan.files)
        assert "NewClockRule.id: NewClockRule" in (tmp_path / _REGISTRY).read_text(encoding="utf-8")
        return "SCHEMA_VERSION = 1\n"

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- verify generation observes authored files and registration before derived output is written.
        python_rule_descriptors, "render", projection
    )
    rule_authoring.apply(plan, tmp_path)
    assert destination.read_text(encoding="utf-8") == "SCHEMA_VERSION = 1\n"
    assert all(path.is_file() for path, _ in plan.files)


@pytest.mark.parametrize(
    ("rule_id", "error"),
    [('"raw-id"', ValueError), ('OtherId("raw-id")', ValueError), ('RuleId("a" + "b")', TypeError)],
    ids=("plain-string", "other-constructor", "computed-id"),
)
def test_authoring_inventory_requires_the_nominal_literal_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rule_id: str, error: type[TypeError | ValueError]
) -> None:
    def projection(_root: Path) -> str:
        return _projection("SARJ400", rule_id=rule_id)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- nominal worker fields must be validated before deriving inventory rows.
        python_rule_descriptors, "render", projection
    )
    with pytest.raises(error, match=r"literal RuleId|literal rule_id"):
        python_rule_descriptors.authoring_inventory(tmp_path)


def test_registered_source_missing_from_stale_table_remains_preparable_and_syncable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = _format(tmp_path, descriptors=_EMPTY_DESCRIPTORS)
    plan = rule_authoring.plan_new(
        tmp_path, RuleSelector.parse("python:new-clock-rule"), category="testing", summary="Use an explicit clock."
    )
    assert plan.code is not None
    projection_source = _projection(plan.code)

    def projection(_root: Path) -> str:
        assert "NewClockRule.id: NewClockRule" in (tmp_path / _REGISTRY).read_text(encoding="utf-8")
        assert all(path.is_file() for path, _ in plan.files)
        namespace: dict[str, object] = {"__name__": "sarj_python_lint.rules.new_clock_rule"}
        implementation = plan.files[0][0]
        exec(  # ruff: ignore[exec-builtin] -- exercise the actual authored source rather than invent a rule metadata stub.
            compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
                implementation.read_text(encoding="utf-8"), str(implementation), "exec"
            ),
            namespace,
        )
        rule = namespace["NewClockRule"]
        assert isinstance(rule, type)
        assert issubclass(rule, PythonRule)
        instance = rule()
        assert instance.id == "new-clock-rule"
        assert instance.code == plan.code
        return projection_source

    def no_python_runtime(module: str) -> dict[str, type[NoDunderAll]]:
        assert module != "sarj_python_lint.rules", "source inventory must not consult stale Python membership"
        return {}

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- a fresh oracle response represents the actually registered source, independently of stale data.
        python_rule_descriptors, "render", projection
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- reject the exact stale runtime-membership shortcut that previously hid new rules.
        rule_maintenance, "_registry", no_python_runtime
    )
    rule_authoring.apply(plan, tmp_path)
    destination.write_text(_EMPTY_DESCRIPTORS, encoding="utf-8")

    assert python_rule_descriptors.sync(tmp_path, check=True).status == 1
    assert destination.read_text(encoding="utf-8") == _EMPTY_DESCRIPTORS
    prepared = rule_lifecycle.stage_warning(tmp_path, plan.selector, check=True, typescript=())
    assert prepared.status == 1
    assert "synchronize derived artifacts" in prepared.message
    assert destination.read_text(encoding="utf-8") == _EMPTY_DESCRIPTORS

    assert rule_inventory_artifact.sync(tmp_path, check=False).status == 0
    inventory = rule_inventory_artifact.load(tmp_path / _INVENTORY)
    assert [row["id"] for row in inventory["rules"] if row["family"] == "python"] == ["new-clock-rule"]
    assert destination.read_text(encoding="utf-8") == projection_source
    assert rule_inventory_artifact.sync(tmp_path, check=True).status == 0


def test_inventory_without_source_override_keeps_arbitrary_runtime_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def injected_registry(module: str) -> dict[str, type[NoDunderAll]]:
        return {"injected-rule": NoDunderAll} if module == "sarj_python_lint.rules" else {}

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- ordinary inventory consumers retain the existing arbitrary-registry injection boundary.
        rule_maintenance, "_registry", injected_registry
    )
    python = [row for row in rule_maintenance.inventory(tmp_path) if row["family"] == "python"]
    assert [row["id"] for row in python] == ["injected-rule"]
