from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import devops, manifest
from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode
from sarj_standards.libs.linting.external import ProcessOutput, analyze_external
from sarj_standards.libs.linting.unused_modules import analyze_application_modules


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _application(root: Path, *, application: bool = True) -> None:
    adopted = manifest.Manifest("8.47.0", ("eslint",), ".", ".", knip_application=application)
    (root / manifest.MANIFEST_NAME).write_text(adopted.render())
    (root / "package.json").write_text(json.dumps({"name": "example", "private": True}))
    (root / "knip.json").write_text(json.dumps({"entry": ["src/index.ts!"], "project": ["src/**/*.ts!"]}))
    (root / "src").mkdir()
    (root / "src/index.ts").write_text("export const application = true;\n")


def _report(*files: str, unresolved: bool = False) -> str:
    issues = [{"file": file, "files": [{"name": ""}]} for file in files]
    if unresolved:
        issues.append({"file": "src/index.ts", "unresolved": [{"name": "./missing"}]})
    return json.dumps({"issues": issues})


def test_native_production_scan_reports_authored_application_modules_as_warnings(tmp_path: Path) -> None:
    _application(tmp_path)
    for name in ("orphan.ts", "ignored.ts", "generated.ts", "test_support.test.ts", "contract.d.mts"):
        (tmp_path / "src" / name).write_text("export const value = true;\n")
    (tmp_path / "src/generated.ts").write_text("// @generated; do not edit\nexport const value = true;\n")
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        calls.append(tuple(argv))
        if argv[1:] == ("--version",):
            return ProcessOutput(0, "6.41.0\n", "")
        return ProcessOutput(
            0,
            _report(
                *(
                    f"src/{name}"
                    for name in ("orphan.ts", "ignored.ts", "generated.ts", "test_support.test.ts", "contract.d.mts")
                )
            ),
            "",
        )

    result = analyze_application_modules(
        root=tmp_path, trust=TrustMode.TRUSTED, allows_path=lambda path: path != "src/ignored.ts", runner=runner
    )

    assert result.completion is Completion.COMPLETE
    assert result.version == "6.41.0"
    assert [(item.location.path, item.severity, item.rule_id) for item in result.diagnostics] == [
        ("src/orphan.ts", Severity.WARNING, "files")
    ]
    assert result.diagnostics[0].help is not None
    assert "not an automatic deletion" in result.diagnostics[0].help
    assert calls[1][-6:] == (
        "--include",
        "unresolved",
        "--reporter",
        "json",
        "--no-progress",
        "--treat-config-hints-as-errors",
    )
    assert "--production" not in calls[1]
    assert "--no-exit-code" not in calls[1]
    assert calls[2][-7:] == (
        "--production",
        "--include",
        "files,unresolved",
        "--reporter",
        "json",
        "--no-progress",
        "--no-exit-code",
    )
    assert all("--fix" not in call for call in calls)


@pytest.mark.parametrize(
    ("application", "config", "package", "trust"),
    [
        (False, {}, {}, TrustMode.TRUSTED),
        (True, {"entry": [], "project": []}, {}, TrustMode.TRUSTED),
        (True, {"workspaces": {"apps/*": {}}}, {}, TrustMode.TRUSTED),
        (True, {"ignoreUnresolved": ["./dynamic"]}, {}, TrustMode.TRUSTED),
        (True, {"ignoreIssues": {"src/index.ts": ["unresolved"]}}, {}, TrustMode.TRUSTED),
        (True, {"ignore": ["src/index.ts"]}, {}, TrustMode.TRUSTED),
        (True, {"rules": {"unresolved": "off"}}, {}, TrustMode.TRUSTED),
        (True, {}, {"workspaces": ["packages/*"]}, TrustMode.TRUSTED),
        (True, {}, {"private": False}, TrustMode.TRUSTED),
        (True, {}, {"knip": {}}, TrustMode.TRUSTED),
        (True, {"entry": ["src/index.ts!"], "project": ["src/**/*.ts!"]}, {}, TrustMode.SAFE),
    ],
    ids=[
        "library",
        "no-production-roots",
        "workspace-config",
        "hidden-unresolved",
        "suppressed-unresolved",
        "ignored-unresolved-source",
        "disabled-unresolved-rule",
        "workspace-package",
        "public-package",
        "package-config",
        "untrusted",
    ],
)
def test_unknown_or_non_application_topology_is_inconclusive_without_execution(
    tmp_path: Path, application: bool, config: dict[str, object], package: dict[str, object], trust: TrustMode
) -> None:
    _application(tmp_path, application=application)
    (tmp_path / "knip.json").write_text(json.dumps({"entry": ["src/index.ts!"], "project": ["src/**/*.ts!"], **config}))
    (tmp_path / "package.json").write_text(json.dumps({"private": True, **package}))

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        pytest.fail(f"Unknown application graph must not run Knip: {argv!r} in {cwd}")

    result = analyze_application_modules(root=tmp_path, trust=trust, allows_path=lambda _path: True, runner=runner)

    assert result.completion is Completion.PARTIAL
    assert result.diagnostics == ()
    assert result.issues[0].kind == "graph-inconclusive"


def test_competing_native_configurations_are_inconclusive_without_choosing_an_owner(tmp_path: Path) -> None:
    _application(tmp_path)
    (tmp_path / "knip.ts").write_text("export default {};\n")

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        pytest.fail(f"Competing configuration must not run Knip: {argv!r} in {cwd}")

    result = analyze_application_modules(
        root=tmp_path, trust=TrustMode.TRUSTED, allows_path=lambda _path: True, runner=runner
    )

    assert result.completion is Completion.PARTIAL
    assert result.diagnostics == ()


def test_pnpm_workspace_topology_is_inconclusive_without_execution(tmp_path: Path) -> None:
    _application(tmp_path)
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - apps/*\n")

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        pytest.fail(f"Workspace topology must not run Knip: {argv!r} in {cwd}")

    result = analyze_application_modules(
        root=tmp_path, trust=TrustMode.TRUSTED, allows_path=lambda _path: True, runner=runner
    )

    assert result.completion is Completion.PARTIAL
    assert result.diagnostics == ()


@pytest.mark.parametrize(
    ("output", "production"),
    [
        (ProcessOutput(0, _report("src/index.ts", unresolved=True), ""), False),
        (ProcessOutput(0, _report("src/index.ts"), "Configuration hint: missing entry\n"), False),
        (ProcessOutput(0, _report("src/index.ts", unresolved=True), ""), True),
        (ProcessOutput(0, _report("src/index.ts"), "Configuration hint: missing entry\n"), True),
        (ProcessOutput(1, _report(), ""), False),
    ],
    ids=[
        "preflight-unresolved-import",
        "preflight-configuration-hint",
        "production-unresolved-import",
        "production-configuration-hint",
        "native-configuration-hint-exit",
    ],
)
def test_incomplete_native_graph_never_produces_deletion_findings(
    tmp_path: Path, output: ProcessOutput, production: bool
) -> None:
    _application(tmp_path)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[1:] == ("--version",):
            return ProcessOutput(0, "6.41.0\n", "")
        if production and "--production" not in argv:
            return ProcessOutput(0, _report(), "")
        return output

    result = analyze_application_modules(
        root=tmp_path, trust=TrustMode.TRUSTED, allows_path=lambda _path: True, runner=runner
    )

    assert result.completion is Completion.PARTIAL
    assert result.diagnostics == ()


@pytest.mark.parametrize(
    "output",
    [ProcessOutput(0, '{"files": []}', ""), ProcessOutput(0, _report("../outside.ts"), ""), ProcessOutput(2, "", "")],
    ids=["unsupported-reporter-contract", "outside-application", "native-failure"],
)
def test_invalid_native_evidence_fails_analysis(tmp_path: Path, output: ProcessOutput) -> None:
    _application(tmp_path)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        return ProcessOutput(0, "6.41.0\n", "") if argv[1:] == ("--version",) else output

    result = analyze_application_modules(
        root=tmp_path, trust=TrustMode.TRUSTED, allows_path=lambda _path: True, runner=runner
    )

    assert result.completion is Completion.FAILED
    assert result.diagnostics == ()
    assert result.issues[0].kind == "tool-failure"


def test_native_missing_production_entry_is_inconclusive_before_file_findings(tmp_path: Path) -> None:
    _application(tmp_path)
    (tmp_path / "knip.json").write_text(json.dumps({"entry": ["src/missing.ts!"], "project": ["src/**/*.ts!"]}))
    (tmp_path / "src/orphan.ts").write_text("export const value = true;\n")

    result = analyze_application_modules(root=tmp_path, trust=TrustMode.TRUSTED, allows_path=lambda _path: True)

    assert result.completion is Completion.PARTIAL
    assert result.diagnostics == ()
    assert result.issues[0].kind == "graph-inconclusive"
    assert "configuration hints" in result.issues[0].message


def test_native_production_graph_keeps_aliases_dynamic_imports_side_effects_and_framework_routes(
    tmp_path: Path,
) -> None:
    _application(tmp_path)
    (tmp_path / "knip.json").write_text(
        json.dumps({"entry": ["src/index.ts!"], "project": ["src/**/*.ts!"], "ignoreFiles": ["src/legacy.ts"]})
    )
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "example", "private": True, "dependencies": {"next": "*"}})
    )
    (tmp_path / "tsconfig.json").write_text(
        json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@app/*": ["src/*"]}}})
    )
    (tmp_path / "src/index.ts").write_text(
        'import {value} from "@app/live";\nimport "./lifecycle";\n'
        'export const start = () => import("./lazy");\nconsole.log(value);\n'
    )
    for name in ("live", "lifecycle", "lazy", "route-support", "test-only", "legacy"):
        (tmp_path / "src" / f"{name}.ts").write_text("export const value = true;\n")
    (tmp_path / "src/behavior.test.ts").write_text('import {value} from "./test-only";\nconsole.log(value);\n')
    route = tmp_path / "src/app/health/route.ts"
    route.parent.mkdir(parents=True)
    route.write_text('import {value} from "../../route-support";\nexport const GET = () => value;\n')

    result = analyze_application_modules(root=tmp_path, trust=TrustMode.TRUSTED, allows_path=lambda _path: True)

    assert result.completion is Completion.COMPLETE, result.issues
    assert result.version == "6.41.0"
    assert [(item.location.path, item.severity) for item in result.diagnostics] == [
        ("src/test-only.ts", Severity.WARNING)
    ]


def test_knip_is_opt_in_and_uses_existing_native_provisioning_contract(tmp_path: Path) -> None:
    _application(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        calls.append(tuple(argv))
        return ProcessOutput(0, "6.41.0\n", "") if argv[1:] == ("--version",) else ProcessOutput(0, _report(), "")

    disabled = analyze_external(
        ("src/index.ts",), root=tmp_path, trust="trusted", capabilities=frozenset(), runner=runner
    )
    enabled = analyze_external(
        ("src/index.ts",), root=tmp_path, trust="trusted", capabilities=frozenset({"knip"}), runner=runner
    )

    assert disabled == ()
    assert [report.name for report in enabled] == ["knip"]
    assert len(calls) == 3
    assert devops.required_tools(tmp_path, (), capabilities=("knip",)) == ("knip",)
    assert "knip" not in manifest.Manifest("8.47.0", ("eslint",), ".", ".").enabled_capabilities
    assert (
        "knip"
        not in manifest.Manifest(
            "8.46.0", ("eslint",), ".", ".", disabled_capabilities=(), knip_application=True
        ).enabled_capabilities
    )
    assert (
        "knip"
        in manifest.Manifest(
            "8.47.0", ("eslint",), ".", ".", disabled_capabilities=(), knip_application=True
        ).enabled_capabilities
    )
    assert manifest.validate_excluded_rule("knip:files") == "knip:files"


@pytest.mark.parametrize(
    ("declaration", "disabled", "enabled"),
    [
        (None, (), False),
        ("", ("jscpd",), False),
        ("[knip]\napplication = false\n", ("jscpd",), False),
        ("[knip]\napplication = true\n", ("jscpd", "knip"), False),
        ("[knip]\napplication = true\n", ("jscpd",), True),
    ],
    ids=["unadopted", "no-application-declaration", "non-application", "disabled-application", "complete-opt-in"],
)
def test_manifest_driven_analysis_requires_both_knip_activation_choices(
    tmp_path: Path, declaration: str | None, disabled: tuple[str, ...], enabled: bool
) -> None:
    _application(tmp_path)
    configuration = tmp_path / manifest.MANIFEST_NAME
    if declaration is None:
        configuration.unlink()
    else:
        configuration.write_text(
            f'schema = 4\nbundle = "8.47.0"\n[capabilities]\ndisable = {json.dumps(disabled)}\n\n{declaration}'
        )
    adopted = manifest.load(tmp_path)
    capabilities = None if adopted is None else adopted.enabled_capabilities
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        calls.append(tuple(argv))
        return ProcessOutput(0, "6.41.0\n", "") if argv[1:] == ("--version",) else ProcessOutput(0, _report(), "")

    reports = analyze_external(
        (),
        root=tmp_path,
        trust="trusted",
        capabilities=None if capabilities is None else frozenset(capabilities),
        runner=runner,
    )

    assert [report.name for report in reports] == (["knip"] if enabled else [])
    assert len(calls) == (3 if enabled else 0)
    assert ("knip" in devops.required_tools(tmp_path, (), capabilities=capabilities)) is enabled


def test_explicit_knip_request_without_application_intent_stays_inconclusive(tmp_path: Path) -> None:
    _application(tmp_path, application=False)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        pytest.fail(f"Undeclared application must not run Knip: {argv!r} in {cwd}")

    reports = analyze_external((), root=tmp_path, trust="trusted", capabilities=frozenset({"knip"}), runner=runner)

    assert len(reports) == 1
    assert reports[0].completion is Completion.PARTIAL
    assert reports[0].diagnostics == ()
    assert reports[0].issues[0].kind == "graph-inconclusive"
