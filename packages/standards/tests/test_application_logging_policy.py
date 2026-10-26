from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Unpack

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import MANIFEST_NAME, Manifest
from sarj_standards.libs.linting import library_policy, runner


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sarj_standards.libs.linting.policy import Policy
    from sarj_standards.libs.linting.runner import GroupedPaths
    from tests.call_contracts import CheckOptions


_EVENT = 'import logging\nlogging.warning("application event")\n'


def _source(root: Path, relative: str, body: str = _EVENT) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_manifest_scanners_do_not_start_crawling_python_sources(tmp_path: Path) -> None:
    source = _source(tmp_path, "app.py")

    assert library_policy.scan(tmp_path) == ()
    assert library_policy.scan_paths(tmp_path, [source]) == ()
    assert not library_policy.accepts_path(source, tmp_path)
    assert [item.id for item in library_policy.scan(tmp_path, python_paths=[source])] == ["LIB023"]


def test_selected_policy_keeps_manifest_package_and_allowed_id_semantics(tmp_path: Path) -> None:
    source = _source(tmp_path, "app.py")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("logging\nrequests\n", encoding="utf-8")

    findings = library_policy.scan_paths(
        tmp_path, [requirements], python_paths=[source], allowed_ids=(item for item in ["LIB023"])
    )

    assert [item.id for item in findings] == ["LIB004"]
    assert next(item for item in library_policy.catalog() if item.id == "LIB023").packages == ("logging",)


def test_selected_flat_source_list_does_not_widen_to_neighbor_sources(tmp_path: Path) -> None:
    selected = _source(tmp_path, "selected.py", "import logging\n")
    _source(tmp_path, "other.py")

    assert library_policy.scan_paths(tmp_path, [], python_paths=[selected]) == ()
    with pytest.raises(library_policy.ManifestPolicyError, match="not a directory"):
        library_policy.scan_paths(tmp_path, [], python_paths=[tmp_path])


def test_selected_source_policy_rejects_symlinks_and_root_escapes(tmp_path: Path) -> None:
    outside = _source(tmp_path, "outside.py")
    root = tmp_path / "project"
    root.mkdir()
    linked = root / "linked.py"
    linked.symlink_to(outside)

    with pytest.raises(library_policy.ManifestPolicyError, match="symlink"):
        library_policy.scan_paths(root, [], python_paths=[linked])
    with pytest.raises(library_policy.ManifestPolicyError, match="escapes repository root"):
        library_policy.scan_paths(root, [], python_paths=[outside])


def test_check_paths_and_canonical_analyze_keep_the_existing_report_owner(tmp_path: Path) -> None:
    source = _source(tmp_path, "service.py")

    checked = api.Standards(tmp_path).check([str(source)])
    analyzed = api.Standards(tmp_path).analyze([str(tmp_path)], mode=api.AnalysisMode.RAW)

    assert checked.exit_code != 0
    assert [item.id for item in checked.findings] == ["LIB023"]
    findings = [item for item in analyzed.diagnostics if item.source == "sarj-library-policy"]
    assert [(item.code, item.rule_id, item.location.path) for item in findings] == [("LIB023", "LIB023", "service.py")]
    assert analyzed.exit_code != 0


def test_selected_file_analysis_never_scans_unselected_application_source(tmp_path: Path) -> None:
    selected = _source(tmp_path, "selected.py", "import logging\n")
    _source(tmp_path, "not_selected.py")

    report = api.Standards(tmp_path).analyze([str(selected)], mode=api.AnalysisMode.RAW)

    assert not any(item.source == "sarj-library-policy" for item in report.diagnostics)


def test_canonical_python_group_can_include_type_stubs(tmp_path: Path) -> None:
    selected = _source(tmp_path, "service.pyi", "import logging\n")

    report = api.Standards(tmp_path).analyze([str(selected)], mode=api.AnalysisMode.RAW)

    assert report.issues == ()
    assert not any(item.source == "sarj-library-policy" for item in report.diagnostics)


def test_existing_manifest_path_policy_excludes_python_before_classification(tmp_path: Path) -> None:
    _source(tmp_path, "excluded/service.py")
    manifest = Manifest(
        version=api.__version__,
        configs=(),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
        excluded_paths=("excluded/**",),
    )
    (tmp_path / MANIFEST_NAME).write_text(manifest.render(), encoding="utf-8")

    checked = api.Standards(tmp_path).check([str(tmp_path)])
    analyzed = api.Standards(tmp_path).analyze([str(tmp_path)], mode=api.AnalysisMode.CORPUS)

    assert not any(item.id == "LIB023" for item in checked.findings)
    assert not any(item.source == "sarj-library-policy" for item in analyzed.diagnostics)


def test_custom_rule_selection_still_omits_the_separate_library_policy_owner(tmp_path: Path) -> None:
    source = _source(tmp_path, "service.py")

    report = api.Standards(tmp_path).analyze(
        [str(source)], mode=api.AnalysisMode.RAW, rules=["python:no-loguru-exc-info"]
    )

    assert not any(item.source == "sarj-library-policy" for item in report.diagnostics)


def test_test_preference_exclusion_does_not_disable_logging_correctness(tmp_path: Path) -> None:
    source = _source(
        tmp_path, "tests/test_bridge.py", 'from loguru import logger\nlogger.error("event", exc_info=True)\n'
    )

    report = api.Standards(tmp_path).analyze(
        [str(source)], mode=api.AnalysisMode.RAW, rules=["python:no-loguru-exc-info"]
    )

    assert any(item.code == "SARJ508" for item in report.diagnostics)


@dataclass(frozen=True, slots=True)
class _SyncSucceeded:
    status: int = 0


def test_full_verify_uses_one_native_group_and_fails_on_actual_library_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _source(tmp_path, "service.py")
    groups: list[GroupedPaths] = []

    def native(_paths: Sequence[str], **kwargs: Unpack[CheckOptions]) -> int:
        group = kwargs.get("grouped")
        assert group is not None
        groups.append(group)
        assert group.python == [str(source)]
        return 0

    def no_diagnostics(_root: Path) -> tuple[()]:
        return ()

    def no_sync_plan(_root: Path) -> None:
        return None

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- isolate the public full-check dispatcher from unrelated adoption diagnostics.
        api, "diagnose", no_diagnostics
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- the fixture checks selected-source routing rather than generated-config planning.
        api, "plan_sync", no_sync_plan
    )

    def successful_sync(_plan: object, *, check: bool) -> _SyncSucceeded:
        assert check is True
        return _SyncSucceeded()

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- no generated artifacts are installed by this orchestration unit fixture.
        api, "apply_sync", successful_sync
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- capture the exact native group while the real public LIB023 classifier and policy owner run.
        api, "check", native
    )

    result = api.Standards(tmp_path).check()

    assert result.exit_code == 1
    assert len(groups) == 1
    assert library_policy.scan(tmp_path, python_paths=groups[0].python)[0].id == "LIB023"


def test_analyze_routes_directories_once_and_passes_only_the_canonical_python_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _source(tmp_path, "service.py")
    routed: list[GroupedPaths] = []
    original = runner.group_paths

    def group(paths: Sequence[str], *, policy: Policy | None = None) -> GroupedPaths:
        selected = original(paths, policy=policy)
        routed.append(selected)
        return selected

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe the existing canonical group, without replacing the policy classifier.
        api, "group_paths", group
    )
    report = api.Standards(tmp_path).analyze([str(tmp_path)], mode=api.AnalysisMode.RAW)

    assert len(routed) == 1
    assert routed[0].python == [str(source)]
    assert any(item.code == "LIB023" and item.source == "sarj-library-policy" for item in report.diagnostics)


def test_runner_reuses_a_supplied_native_group_without_another_walk(monkeypatch: pytest.MonkeyPatch) -> None:
    grouped = runner.GroupedPaths()

    def unexpected_walk(_paths: Sequence[str], *, policy: Policy | None = None) -> GroupedPaths:
        pytest.fail(f"the canonical native group must not be selected a second time (policy={policy!r})")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- detect an extra directory walk after the caller selected the canonical group.
        runner, "group_paths", unexpected_walk
    )

    assert runner.run([], grouped=grouped) == 0


def test_import_adapter_removes_only_lib023_while_manifest_policy_keeps_its_mapping() -> None:
    bans = library_policy.python_banned_api()

    assert "logging" not in bans
    assert bans["argparse"].startswith("LIB001:")
    assert bans["requests"].startswith("LIB004:")
    assert next(item for item in library_policy.catalog() if item.id == "LIB023").packages == ("logging",)


def test_invalid_selected_python_encoding_is_a_policy_failure(tmp_path: Path) -> None:
    selected = tmp_path / "service.py"
    selected.write_bytes(b"# coding: unknown-source-encoding\nimport logging\n")

    with pytest.raises(library_policy.ManifestPolicyError, match="cannot decode selected Python"):
        library_policy.scan_paths(tmp_path, [], python_paths=[selected])


@pytest.mark.parametrize(
    ("body", "expected_count"),
    [
        (
            'import logging\nfrom vendor import configure\nconfigure(logging.__dict__)\nlogging.warning("event")\n',
            0,
        ),
        (
            'import logging\nfrom vendor import send\nlogging.__dict__["warning"] = send\nlogging.warning("event")\n',
            0,
        ),
        ('import logging\nlevel = logging.WARNING\nlogging.log(level, "event")\n', 1),
    ],
    ids=["escaped-module-namespace", "replaced-module-emitter", "ordinary-module-constant"],
)
def test_module_namespace_provenance_is_preserved_through_canonical_analysis(
    tmp_path: Path, body: str, expected_count: int
) -> None:
    source = _source(tmp_path, "service.py", body)

    findings = library_policy.scan_paths(tmp_path, [], python_paths=[source])
    report = api.Standards(tmp_path).analyze([str(source)], mode=api.AnalysisMode.RAW)

    assert [item.id for item in findings] == (["LIB023"] if expected_count else [])
    assert len([item for item in report.diagnostics if item.source == "sarj-library-policy"]) == expected_count


@pytest.mark.parametrize(
    ("body", "expected_count"),
    [
        (
            'import logging\nfrom vendor import configure\nconfigure(logging.root.__dict__)\nlogging.root.warning("event")\n',
            0,
        ),
        (
            'import logging\nfrom vendor import send\nlogging.root.__dict__["warning"] = send\nlogging.root.warning("event")\n',
            0,
        ),
        (
            'import logging\nfrom vendor import configure\nconfigure(logging.getLogger("app").__dict__)\nlogging.getLogger("app").warning("event")\n',
            0,
        ),
        (
            'import logging\nfrom vendor import send\nlogging.getLogger("app").__dict__["warning"] = send\nlogging.getLogger("app").warning("event")\n',
            0,
        ),
        (
            'import logging as primary\nimport logging as secondary\nfrom vendor import configure\nconfigure(primary.__dict__)\nsecondary.warning("event")\n',
            0,
        ),
        ('import logging\nlogging.root.setLevel(logging.WARNING)\nlogging.root.warning("event")\n', 1),
        (
            'import logging\nlogging.getLogger("app").setLevel(logging.WARNING)\nlogging.getLogger("app").warning("event")\n',
            1,
        ),
        (
            'import logging\nimport unrelated\nfrom vendor import configure\nconfigure(unrelated.__dict__)\nlogging.warning("event")\n',
            1,
        ),
        ('import logging\nfrom vendor import configure\nconfigure(logging.__dict__)\nlogging.warning("event")\n', 0),
        (
            'import logging\nfrom logging import root as events\nfrom vendor import configure\nconfigure(events.__dict__)\nlogging.root.warning("event")\n',
            0,
        ),
        (
            'import logging\nfrom logging import root as events\nfrom vendor import configure\nconfigure(logging.root.__dict__)\nevents.warning("event")\n',
            0,
        ),
    ],
    ids=[
        "root_namespace_escaped",
        "root_namespace_replaced",
        "factory_namespace_escaped",
        "factory_namespace_replaced",
        "module_alias_namespace_cross_alias",
        "ordinary_root_routing",
        "ordinary_factory_routing",
        "unrelated_namespace",
        "existing_module_namespace_escape",
        "imported_root_escape_then_module_root",
        "module_root_escape_then_imported_root",
    ],
)
def test_shared_logger_namespaces_preserve_canonical_provenance(tmp_path: Path, body: str, expected_count: int) -> None:
    source = _source(tmp_path, "service.py", body)

    findings = library_policy.scan_paths(tmp_path, [], python_paths=[source])
    report = api.Standards(tmp_path).analyze([str(source)], mode=api.AnalysisMode.RAW)

    assert [item.id for item in findings] == (["LIB023"] if expected_count else [])
    assert len([item for item in report.diagnostics if item.source == "sarj-library-policy"]) == expected_count
