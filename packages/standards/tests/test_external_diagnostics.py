from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

from deptry.cli import cli as deptry_cli
from pydantic import ValidationError
import pytest

from sarj_standards.cli.main import main as cli_main
from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.diagnostics import Completion, Conclusion, Severity, TrustMode
from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.linting import external as external_module
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.external import (
    ProcessOutput,
    analyze_external,
    parse_basedpyright,
    parse_deptry,
    parse_ktlint,
    parse_mobsfscan,
    parse_ruff,
    parse_sarif,
    parse_shellcheck,
    parse_swiftformat,
    parse_swiftlint,
)
from sarj_standards.libs.linting.process import ProcessCapabilities, ToolResolution
from tests.process_fakes import FakeProcessExecutor


if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic import JsonValue


@pytest.fixture
def _fixed_host_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- analyzer tests use a deterministic small-host budget
        external_module, "_physical_memory_bytes", lambda: 8 * 1024**3
    )


def _write_detekt_report(command: Sequence[str], payload: str = '{"runs":[]}') -> Path:
    report = command[command.index("--report") + 1]
    assert report.startswith("sarif:")
    path = Path(report.removeprefix("sarif:"))
    assert path.is_absolute()
    assert path.parent.is_dir()
    path.write_text(payload, encoding="utf-8")
    return path


def _write_controlled_project_analyzer(project: Path, tool: str) -> Path:
    project.mkdir(parents=True, exist_ok=True)
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\n", encoding="utf-8")
    (project / "app.py").write_text("value = 1\n", encoding="utf-8")
    executable = project / ".venv" / "bin" / tool
    executable.parent.mkdir(parents=True)
    marker = project / "analyzer-executed.json"
    payload = '{"generalDiagnostics":[]}' if tool == "basedpyright" else ""
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json\nfrom pathlib import Path\nimport sys\n"
        f"Path({str(marker)!r}).write_text("
        "json.dumps({'argv': sys.argv, 'cwd': str(Path.cwd())}), encoding='utf-8')\n"
        f"sys.stdout.write({payload!r})\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return marker


def test_parse_deptry_normalizes_selected_rules_as_warnings(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("import missing\n", encoding="utf-8")
    payload = (
        "Scanning 1 file...\n"
        "::warning file=src/app.py,line=1,col=8,title=DEP001::"
        "'missing' imported but missing from dependency definitions\n"
        "::warning file=pyproject.toml,line=1,title=DEP002::'unused' defined but not used\n"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nversion='1'\n", encoding="utf-8")

    diagnostics = parse_deptry(payload, root=tmp_path)

    assert [(item.code, item.severity, item.location.path) for item in diagnostics] == [
        ("DEP001", Severity.WARNING, "src/app.py"),
        ("DEP002", Severity.WARNING, "pyproject.toml"),
    ]


def test_deptry_runs_once_per_python_project_with_only_selected_warning_rules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "packages" / "api" / "src" / "api.py"
    source.parent.mkdir(parents=True)
    source.write_text("import transitive\n", encoding="utf-8")
    (source.parent / "helper.py").write_text("", encoding="utf-8")
    project = source.parents[1]
    (project / "pyproject.toml").write_text("[project]\nname='api'\nversion='1'\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == project
        seen.append(tuple(argv))
        return ProcessOutput(
            0,
            "",
            "::warning file=src/api.py,line=1,col=8,title=DEP003::'transitive' is a transitive dependency\n",
        )

    reports = analyze_external(
        (str(source),),
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        runner=FakeProcessExecutor(run),
        capabilities=frozenset({"deptry"}),
    )

    assert [report.name for report in reports] == ["deptry"]
    assert reports[0].completion is Completion.COMPLETE
    assert [item.code for item in reports[0].diagnostics] == ["DEP003"]
    assert "DEP004,DEP005" in seen[0]
    assert "DEP001,DEP002,DEP003" in seen[0]
    assert seen[0][1] == "src"
    monkeypatch.chdir(project)
    with deptry_cli.make_context("deptry", list(seen[0][1:])) as context:
        assert context.params["known_first_party"] == ("api", "helper")


def test_deptry_refuses_unbounded_project_fanout(tmp_path: Path) -> None:
    sources: list[str] = []
    for index in range(33):
        project = tmp_path / f"project-{index:02}"
        project.mkdir()
        (project / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1'\n", encoding="utf-8")
        source = project / "app.py"
        source.write_text("value = 1\n", encoding="utf-8")
        sources.append(str(source))
    called = False

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal called
        called = True
        pytest.fail(f"Deptry must not run after the project limit is exceeded: {argv!r} in {cwd}")

    reports = analyze_external(
        sources,
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        runner=FakeProcessExecutor(run),
        capabilities=frozenset({"deptry"}),
    )

    assert not called
    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].kind == "project-limit"


def test_deptry_allows_the_bounded_project_limit(tmp_path: Path) -> None:
    sources: list[str] = []
    for index in range(32):
        project = tmp_path / f"project-{index:02}"
        project.mkdir()
        (project / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1'\n", encoding="utf-8")
        source = project / "app.py"
        source.write_text("value = 1\n", encoding="utf-8")
        sources.append(str(source))
    calls = 0

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal calls
        assert cwd.parent == tmp_path
        assert argv[0]
        calls += 1
        return ProcessOutput(0, "", "")

    reports = analyze_external(
        sources,
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        runner=FakeProcessExecutor(run),
        capabilities=frozenset({"deptry"}),
    )

    assert calls == 32
    assert len(reports) == 32
    assert all(report.completion is Completion.COMPLETE for report in reports)


def test_deptry_skips_python_without_dependency_metadata(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("import argparse\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 120\n", encoding="utf-8")

    reports = analyze_external(
        (str(source),),
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        capabilities=frozenset({"deptry"}),
    )

    assert reports == ()


def test_ruff_json_becomes_an_exact_canonical_region(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("import os\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filename": str(source),
                "location": {"row": 1, "column": 1},
                "end_location": {"row": 1, "column": 7},
                "code": "F401",
                "message": "unused import",
                "url": "https://docs.astral.sh/ruff/rules/unused-import/",
            }
        ]
    )

    finding = parse_ruff(payload, root=tmp_path)[0]

    assert finding.code == "F401"
    assert finding.location.path == "example.py"
    assert finding.location.region is not None
    assert finding.location.region.start.byte_offset == 0
    assert finding.location.region.end.byte_offset == 6


def test_ruff_name_becomes_code_when_plugin_diagnostic_omits_code(tmp_path: Path) -> None:
    source = tmp_path / "conftest.py"
    source.write_text("@pytest.fixture(autouse=True)\ndef fixture(): ...\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filename": str(source),
                "location": {"row": 1, "column": 17},
                "end_location": {"row": 1, "column": 29},
                "code": None,
                "name": "pytest-fixture-autouse",
                "message": "Avoid using `autouse=True` in `pytest.fixture` decorators",
                "url": "https://docs.astral.sh/ruff/rules/pytest-fixture-autouse/",
            }
        ]
    )

    finding = parse_ruff(payload, root=tmp_path)[0]

    assert finding.code == "pytest-fixture-autouse"
    assert finding.rule_id == "pytest-fixture-autouse"
    serialized = finding.as_dict()
    assert "ruleKey" in serialized
    assert serialized["ruleKey"] == "ruff:pytest-fixture-autouse"


def test_mobile_protocols_become_canonical_diagnostics(tmp_path: Path) -> None:
    swift = tmp_path / "Screen.swift"
    swift.write_text("struct Screen {}\n", encoding="utf-8")
    kotlin = tmp_path / "Screen.kt"
    kotlin.write_text("class Screen\n", encoding="utf-8")

    swiftformat = parse_swiftformat(
        f"{swift}:1:1: warning: replace braces (emptyBraces)\n",
        root=tmp_path,
    )[0]
    swiftlint = parse_swiftlint(
        json.dumps(
            [
                {
                    "file": str(swift),
                    "line": 1,
                    "character": None,
                    "reason": "Prefer a final declaration",
                    "rule_id": "redundant_final",
                    "severity": "Warning",
                }
            ]
        ),
        root=tmp_path,
    )[0]
    ktlint = parse_ktlint(
        json.dumps(
            [
                {
                    "file": str(kotlin),
                    "errors": [{"line": 1, "column": 1, "rule": "standard:final-newline", "message": "newline"}],
                }
            ]
        ),
        root=tmp_path,
    )[0]
    detekt = parse_sarif(
        json.dumps(
            {
                "runs": [
                    {
                        "results": [
                            {
                                "ruleId": "GlobalCoroutineUsage",
                                "level": "error",
                                "message": {"text": "Do not use GlobalScope"},
                                "locations": [
                                    {
                                        "physicalLocation": {
                                            "artifactLocation": {"uri": str(kotlin)},
                                            "region": {"startLine": 1, "startColumn": 1},
                                        }
                                    }
                                ],
                            }
                        ]
                    }
                ]
            }
        ),
        root=tmp_path,
    )[0]
    mobsf = parse_mobsfscan(
        json.dumps(
            {
                "errors": [],
                "results": [
                    {
                        "check_id": "ios_insecure_random",
                        "path": str(swift),
                        "start": {"line": 1, "col": 1},
                        "end": {"line": 1, "col": 2},
                        "extra": {"severity": "ERROR", "message": "Insecure random source"},
                    }
                ],
            }
        ),
        root=tmp_path,
    )[0]

    assert (swiftformat.source, swiftformat.code, swiftformat.location.path) == (
        "swiftformat",
        "emptyBraces",
        "Screen.swift",
    )
    assert (swiftlint.source, swiftlint.code, swiftlint.severity) == (
        "swiftlint",
        "redundant_final",
        Severity.WARNING,
    )
    assert (ktlint.source, ktlint.code) == ("ktlint", "standard:final-newline")
    assert (detekt.source, detekt.code, detekt.severity) == (
        "detekt",
        "GlobalCoroutineUsage",
        Severity.ERROR,
    )
    assert (mobsf.source, mobsf.code, mobsf.severity) == (
        "mobsfscan",
        "ios_insecure_random",
        Severity.ERROR,
    )


def test_mobsfscan_tolerates_known_swift_preview_partial_parsing_with_exact_coverage(tmp_path: Path) -> None:
    swift = tmp_path / "ContentView.swift"
    swift.write_text("#Preview { ContentView() }\n", encoding="utf-8")
    payload: dict[str, JsonValue] = {
        "errors": [{"level": "warn", "type": ["PartialParsing", []], "message": "unsupported Swift macro"}],
        "results": [],
        "paths": {"scanned": [str(swift)]},
    }

    assert parse_mobsfscan(json.dumps(payload), root=tmp_path, expected_paths=(str(swift),)) == ()


def test_mobsfscan_rejects_partial_parsing_without_proven_exact_coverage(tmp_path: Path) -> None:
    payload: dict[str, JsonValue] = {
        "errors": [{"level": "warn", "type": ["PartialParsing", []], "message": "unsupported Swift macro"}],
        "results": [],
    }

    with pytest.raises(ValueError, match="Semgrep engine reported 1 error"):
        parse_mobsfscan(json.dumps(payload), root=tmp_path)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param({"level": "error", "type": ["PartialParsing", [0]]}, id="error-level"),
        pytest.param({"level": "warn", "type": ["InvalidRuleSchema", [0]]}, id="unknown-warning"),
        pytest.param({"level": "warn", "type": "PartialParsing"}, id="malformed-type"),
    ],
)
def test_mobsfscan_rejects_fatal_or_malformed_semgrep_errors(tmp_path: Path, error: dict[str, JsonValue]) -> None:
    with pytest.raises(ValueError, match="Semgrep engine reported 1 error"):
        parse_mobsfscan(json.dumps({"errors": [error], "results": []}), root=tmp_path)


def test_mobile_capabilities_run_only_for_mobile_files(tmp_path: Path) -> None:
    swift = tmp_path / "Screen.swift"
    swift.write_text("struct Screen {}\n", encoding="utf-8")
    kotlin = tmp_path / "Screen.kt"
    kotlin.write_text("class Screen\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []
    detekt_reports: list[Path] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        command = tuple(argv)
        seen.append(command)
        executable = command[0]
        match executable:
            case "swiftformat":
                return ProcessOutput(0, "", "")
            case "swiftlint" | "ktlint":
                return ProcessOutput(0, "[]", "")
            case "detekt":
                detekt_reports.append(_write_detekt_report(command))
                return ProcessOutput(0, "stdout is not the Detekt protocol", "")
            case "semgrep":
                return ProcessOutput(
                    0,
                    json.dumps({"errors": [], "paths": {"scanned": [str(swift), str(kotlin)]}, "results": []}),
                    "",
                )
            case _:
                raise AssertionError(command)

    reports = analyze_external(
        [str(swift), str(kotlin)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
        capabilities=frozenset({"swiftformat", "swiftlint", "ktlint", "detekt", "mobile-security"}),
    )

    assert {report.name for report in reports} == {"swiftformat", "swiftlint", "ktlint", "detekt", "mobsfscan"}
    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert {command[0] for command in seen} == {"swiftformat", "swiftlint", "ktlint", "detekt", "semgrep"}
    security_command = next(command for command in seen if command[0] == "semgrep")
    assert security_command[1:3] == ("scan", "--metrics=off")
    assert "--disable-nosem" in security_command
    assert "--no-git-ignore" in security_command
    assert "--max-target-bytes=2097152" in security_command
    assert security_command[security_command.index("--") + 1 :] == (str(kotlin), str(swift))
    assert security_command[security_command.index("--config") + 1] == "mobsfscan-rules"
    assert "--severity" in security_command
    assert "mobsfscan" not in security_command
    assert len(detekt_reports) == 1
    assert not detekt_reports[0].exists()
    assert not detekt_reports[0].parent.exists()


def test_mobile_analyzers_use_manifest_destinations_and_pinned_mintfile(tmp_path: Path) -> None:
    ios = tmp_path / "ios"
    android = tmp_path / "android"
    ios.mkdir()
    android.mkdir()
    swift = ios / "Screen.swift"
    swift.write_text("struct Screen {}\n", encoding="utf-8")
    kotlin = android / "Screen.kt"
    kotlin.write_text("class Screen\n", encoding="utf-8")
    swift_config = ios / ".swiftlint.yml"
    swift_config.write_text("strict: true\n", encoding="utf-8")
    format_config = ios / ".swiftformat"
    format_config.write_text("--swiftversion 6.0\n", encoding="utf-8")
    detekt_config = android / "config/detekt/detekt.yml"
    detekt_config.parent.mkdir(parents=True)
    detekt_config.write_text("build:\n  maxIssues: 0\n", encoding="utf-8")
    editorconfig = android / ".editorconfig"
    editorconfig.write_text("root = true\n", encoding="utf-8")
    mintfile = tmp_path / "Mintfile.mobile.strict"
    mintfile.write_text("realm/SwiftLint@0.65.0\n", encoding="utf-8")
    (tmp_path / manifest.MANIFEST_NAME).write_text(
        'schema = 4\nbundle = "1.2.3"\n[dest]\npython = "."\ntypescript = "."\nswift = "ios"\nkotlin = "android"\n',
        encoding="utf-8",
    )
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        command = tuple(argv)
        seen.append(command)
        if "swiftformat" in command:
            return ProcessOutput(0, "", "")
        if "swiftlint" in command or command[0] == "ktlint":
            return ProcessOutput(0, "[]", "")
        if command[0] == "detekt":
            _write_detekt_report(command)
            return ProcessOutput(0, "", "")
        raise AssertionError(command)

    reports = analyze_external(
        [str(swift), str(kotlin)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
        capabilities=frozenset({"swiftformat", "swiftlint", "ktlint", "detekt"}),
    )

    assert all(report.completion is Completion.COMPLETE for report in reports)
    _assert_swift_commands(seen, mintfile, swift_config, format_config)
    assert any(f"--editorconfig={editorconfig}" in command for command in seen if command[0] == "ktlint")
    assert all("--log-level=none" in command for command in seen if command[0] == "ktlint")
    assert any(str(detekt_config) in command for command in seen if command[0] == "detekt")
    detekt_command = next(command for command in seen if command[0] == "detekt")
    assert detekt_command[detekt_command.index("--input") + 1] == str(kotlin)
    report_argument = detekt_command[detekt_command.index("--report") + 1]
    assert report_argument.startswith("sarif:")
    assert report_argument != "sarif:/dev/stdout"


def _assert_swift_commands(
    seen: list[tuple[str, ...]], mintfile: Path, swift_config: Path, format_config: Path
) -> None:
    mint_commands = [command for command in seen if command[0] == "mint"]
    assert mint_commands
    assert all(command[:5] == ("mint", "run", "--silent", "--mintfile", str(mintfile)) for command in mint_commands)
    assert any(
        ("--config", str(swift_config)) == (command[-3], command[-2]) for command in seen if "swiftlint" in command
    )
    assert any(str(format_config) in command for command in seen if "swiftformat" in command)
    assert all("--" not in command for command in seen if "swiftformat" in command)


def test_mobile_analyzers_ignore_same_language_files_outside_manifest_destinations(tmp_path: Path) -> None:
    ios = tmp_path / "ios"
    android = tmp_path / "android"
    server = tmp_path / "server"
    ios.mkdir()
    android.mkdir()
    server.mkdir()
    included_swift = ios / "Screen.swift"
    included_kotlin = android / "Screen.kt"
    excluded_swift = server / "Service.swift"
    excluded_kotlin = server / "Service.kt"
    for path in (included_swift, included_kotlin, excluded_swift, excluded_kotlin):
        path.write_text("// source\n", encoding="utf-8")
    (tmp_path / manifest.MANIFEST_NAME).write_text(
        manifest.Manifest(
            version="1.2.3",
            configs=("swiftformat", "ktlint", "mobile-security"),
            python_dest=".",
            typescript_dest=".",
            swift_dest="ios",
            kotlin_dest="android",
        ).render(),
        encoding="utf-8",
    )
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        command = tuple(argv)
        seen.append(command)
        if "swiftformat" in command:
            return ProcessOutput(0, "", "")
        if command[0] == "ktlint":
            return ProcessOutput(0, "[]", "")
        if command[0] == "semgrep":
            return ProcessOutput(
                0,
                json.dumps(
                    {
                        "errors": [],
                        "paths": {"scanned": [str(included_kotlin), str(included_swift)]},
                        "results": [],
                    }
                ),
                "",
            )
        raise AssertionError(command)

    reports = analyze_external(
        [str(included_swift), str(included_kotlin), str(excluded_swift), str(excluded_kotlin)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
        capabilities=frozenset({"swiftformat", "ktlint", "mobile-security"}),
    )

    assert all(report.completion is Completion.COMPLETE for report in reports)
    flattened = {argument for command in seen for argument in command}
    assert str(included_swift) in flattened
    assert str(included_kotlin) in flattened
    assert str(excluded_swift) not in flattened
    assert str(excluded_kotlin) not in flattened


def test_mobsfscan_requires_exact_selected_file_coverage(tmp_path: Path) -> None:
    first = tmp_path / "First.swift"
    second = tmp_path / "Second.swift"
    first.touch()
    second.touch()
    payload = json.dumps({"errors": [], "paths": {"scanned": [str(first)]}, "results": []})

    with pytest.raises(ValueError, match=r"coverage mismatch: expected 2 selected file.*scanned 1"):
        parse_mobsfscan(payload, root=tmp_path, expected_paths=(str(first), str(second)))


def test_detekt_fails_closed_when_the_sarif_report_exceeds_the_output_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kotlin = tmp_path / "Screen.kt"
    kotlin.write_text("class Screen\n", encoding="utf-8")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts external tool routing
        external_module, "_MAX_STDOUT_BYTES", 8
    )

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        _write_detekt_report(argv, '{"runs":[]}')
        return ProcessOutput(0, "", "")

    reports = analyze_external(
        [str(kotlin)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
        capabilities=frozenset({"detekt"}),
    )

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].kind == "tool-failure"
    assert "exceeded 8 bytes" in reports[0].issues[0].message


def test_managed_mobsf_config_translates_strict_filters_and_exclusions(tmp_path: Path) -> None:
    config = tmp_path / ".mobsf"
    config.write_text(
        "- severity-filter: [WARNING, ERROR]\n"
        "  ignore-rules: []\n"
        "  ignore-paths: [vendor]\n"
        "  ignore-filenames: [Generated.swift]\n"
        "  severity-overrides: {}\n",
        encoding="utf-8",
    )

    argv = external_module._mobsfscan_argv(Path("rules"), config=config)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _mobsfscan_argv contract directly with controlled fixture data.

    assert argv[:2] == ("semgrep", "scan")
    assert argv.count("--severity") == 2
    assert "--exclude-rule" not in argv
    assert argv.count("--exclude") == 2


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ("- severity-filter: [ERROR]\n  ignore-rules: []\n", "must contain both WARNING and ERROR"),
        ("- severity-filter: [WARNING, ERROR]\n  ignore-rules: [ios_insecure_random]\n", "must remain empty"),
    ],
)
def test_managed_mobsf_config_cannot_weaken_the_strict_rule_floor(config: str, message: str, tmp_path: Path) -> None:
    path = tmp_path / ".mobsf"
    path.write_text(config, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        external_module._mobsfscan_argv(Path("rules"), config=path)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _mobsfscan_argv contract directly with controlled fixture data.


def test_managed_swift_commands_ignore_repository_mintfiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "Mintfile.mobile.strict").write_text("attacker/tool@main\n", encoding="utf-8")

    def managed_command(name: str) -> tuple[str, ...]:
        assert name == "mint"
        return ("/managed/mint",)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts external tool routing
        external_module.mobile_tools, "command", managed_command
    )

    command = external_module._swift_command(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _swift_command contract directly with controlled fixture data.
        tmp_path, "swiftlint", managed=True
    )

    mintfile = Path(command[command.index("--mintfile") + 1])
    assert command[:3] == ("/managed/mint", "run", "--silent")
    assert mintfile.name == "Mintfile.mobile.strict"
    assert mintfile != tmp_path / "Mintfile.mobile.strict"
    assert "attacker/tool" not in mintfile.read_text(encoding="utf-8")


def test_mobile_config_parse_failures_return_a_failed_tool_report(tmp_path: Path) -> None:
    source = tmp_path / "Screen.swift"
    source.write_text("internal struct Screen {}\n", encoding="utf-8")
    (tmp_path / ".mobsf").write_text("[unterminated", encoding="utf-8")
    invoked = False

    def runner(
        argv: Sequence[str],  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        *,
        cwd: Path,
    ) -> ProcessOutput:
        nonlocal invoked
        assert cwd == tmp_path
        invoked = True
        return ProcessOutput(0, "", "")

    reports = analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
        capabilities=frozenset({"mobile-security"}),
    )

    assert not invoked
    assert reports[-1].name == "mobile-tools"
    assert reports[-1].completion is Completion.FAILED
    assert reports[-1].issues[0].kind == "provisioning-failure"


def test_managed_mobsf_config_rejects_symlinks_and_oversized_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "outside.yml"
    target.write_text("- severity-filter: [ERROR]\n", encoding="utf-8")
    linked = tmp_path / ".mobsf"
    linked.symlink_to(target)

    with pytest.raises(OSError, match="not a regular file"):
        external_module._mobsfscan_argv(Path("rules"), config=linked)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _mobsfscan_argv contract directly with controlled fixture data.

    oversized = tmp_path / "mobsf.strict.yml"
    oversized.write_text("12345", encoding="utf-8")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts external tool routing
        external_module, "_MAX_MOBILE_CONFIG_BYTES", 4
    )
    with pytest.raises(external_module.OutputLimitError, match="exceeds 4 bytes"):
        external_module._mobsfscan_argv(Path("rules"), config=oversized)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _mobsfscan_argv contract directly with controlled fixture data.


def test_shellcheck_json_preserves_native_rule_and_warning_rollout(tmp_path: Path) -> None:
    source = tmp_path / "release.sh"
    source.write_text("echo $name\n", encoding="utf-8")
    payload = json.dumps(
        {
            "comments": [
                {
                    "file": str(source),
                    "line": 1,
                    "endLine": 1,
                    "column": 6,
                    "endColumn": 11,
                    "level": "warning",
                    "code": 2086,
                    "message": "Double quote to prevent globbing and word splitting.",
                }
            ]
        }
    )

    finding = parse_shellcheck(payload, root=tmp_path)[0]

    assert finding.code == "SC2086"
    assert finding.rule_id == "SC2086"
    assert finding.source == "shellcheck"
    assert finding.severity is Severity.WARNING
    assert finding.location.path == "release.sh"
    assert finding.location.region is not None


def test_shellcheck_runs_hermetically_for_supported_shell(tmp_path: Path) -> None:
    source = tmp_path / "release.sh"
    source.write_text("echo ok\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        seen.append(tuple(argv))
        return ProcessOutput(0, '{"comments":[]}', "")

    reports = analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
        capabilities=frozenset({"shellcheck"}),
    )

    assert [item.name for item in reports] == ["shellcheck"]
    assert reports[0].completion is Completion.COMPLETE
    assert seen == [
        (
            "shellcheck",
            "--norc",
            "--extended-analysis=true",
            "--enable=check-extra-masked-returns,check-set-e-suppressed",
            "--severity=info",
            "--source-path=SCRIPTDIR",
            "--format=json1",
            "--",
            str(source),
        )
    ]


def test_shellcheck_reports_zsh_as_uncovered_without_invocation(tmp_path: Path) -> None:
    source = tmp_path / "release.zsh"
    source.write_text("print ok\n", encoding="utf-8")

    def forbidden(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        raise AssertionError((argv, cwd))

    reports = analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(forbidden),
        capabilities=frozenset({"shellcheck"}),
    )

    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].kind == "coverage-missing"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("level", "notice", "unsupported ShellCheck severity"),
        ("line", True, r"comments\.0\.line"),
        ("code", 0, r"comments\.0\.code"),
    ],
)
def test_shellcheck_rejects_malformed_protocol_fields(
    tmp_path: Path, field: str, value: str | int, message: str
) -> None:
    source = tmp_path / "release.sh"
    source.write_text("echo ok\n", encoding="utf-8")
    item: dict[str, JsonValue] = {
        "file": str(source),
        "line": 1,
        "endLine": 1,
        "column": 1,
        "endColumn": 5,
        "level": "info",
        "code": 2086,
        "message": "example",
    }
    item[field] = value

    with pytest.raises((TypeError, ValueError), match=message):
        parse_shellcheck(json.dumps({"comments": [item]}), root=tmp_path)


def test_shellcheck_rejects_reported_paths_outside_repository(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.sh"
    outside.write_text("echo ok\n", encoding="utf-8")
    payload = json.dumps(
        {
            "comments": [
                {
                    "file": str(outside),
                    "line": 1,
                    "endLine": 1,
                    "column": 1,
                    "endColumn": 5,
                    "level": "info",
                    "code": 2086,
                    "message": "example",
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="outside the repository"):
        parse_shellcheck(payload, root=tmp_path)


def test_shellcheck_exact_version_is_attested(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def old_version(
        argv: Sequence[str],  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        return ProcessOutput(0, "ShellCheck\nversion: 0.10.0\n", "")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts external tool routing
        external_module.DEFAULT_EXECUTOR,
        "run",
        FakeProcessExecutor(old_version).run,
    )

    issue = external_module._shellcheck_version_issue(tmp_path)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _shellcheck_version_issue contract directly with controlled fixture data.

    assert issue is not None
    assert issue.kind == "version-mismatch"
    assert "0.11.0" in issue.message


def test_react_doctor_discovers_independent_react_projects(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"private": true}\n', encoding="utf-8")
    react_project = tmp_path / "apps" / "react-app"
    next_project = tmp_path / "demos" / "next-app"
    ignored_project = tmp_path / "node_modules" / "third-party"
    for project, package in (
        (react_project, "react"),
        (next_project, "next"),
        (ignored_project, "react"),
    ):
        project.mkdir(parents=True)
        (project / "package.json").write_text(
            json.dumps({"dependencies": {package: "1.0.0"}}),
            encoding="utf-8",
        )

    assert external_module._react_project_roots(tmp_path) == (  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _react_project_roots contract directly with controlled fixture data.
        react_project.resolve(),
        next_project.resolve(),
    )


def test_react_doctor_honors_manifest_doctor_project_exclusions(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"private": true}\n', encoding="utf-8")
    included = tmp_path / "apps" / "web"
    excluded = tmp_path / "demos" / "historical"
    for project in (included, excluded):
        project.mkdir(parents=True)
        (project / "package.json").write_text('{"dependencies":{"react":"19.0.0"}}\n', encoding="utf-8")
    adopted = manifest.Manifest(
        "5.13.5",
        ("typescript",),
        ".",
        ".",
        doctor_excluded_paths=("demos/**",),
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    selection = external_module._selected_react_doctor_projects(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _selected_react_doctor_projects contract directly with controlled fixture data.
        tmp_path,
        enabled=True,
        has_typescript=True,
        capabilities=frozenset({"typescript"}),
    )

    assert selection == (tmp_path, (included.resolve(),))


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"ref": "refs/heads/feature", "repository": {"default_branch": "main"}}, True),
        ({"ref": "refs/heads/main", "repository": {"default_branch": "main"}}, False),
        (
            {
                "ref": "refs/heads/feature",
                "repository": {"default_branch": "main"},
                "pull_request": {"base": {"sha": "f" * 40}},
            },
            False,
        ),
        ({"ref": "refs/tags/v1.0.0", "repository": {"default_branch": "main"}}, False),
    ],
)
def test_non_default_github_push_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, JsonValue],
    expected: bool,
) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))

    assert external_module.is_non_default_github_push() is expected


def test_non_default_branch_is_not_treated_as_a_push_for_other_github_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"ref": "refs/heads/feature", "repository": {"default_branch": "main"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))

    assert not external_module.is_non_default_github_push()


def test_external_analyzers_do_not_inherit_caller_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SARJ_AUDIT_SECRET", "must-not-leak")
    monkeypatch.setenv("NODE_OPTIONS", "--require=/tmp/untrusted-preload.cjs")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("LC_ALL", "C")

    environment = external_module._analysis_environment()  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _analysis_environment contract directly with controlled fixture data.

    assert "SARJ_AUDIT_SECRET" not in environment
    assert "NODE_OPTIONS" not in environment
    assert environment["PATH"] == "/usr/bin"
    assert environment["LC_ALL"] == "C"


def test_external_analyzers_prefer_the_isolated_python_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    interpreter = tmp_path / "bin" / "python"
    calls: list[tuple[str, str | None]] = []

    def which(name: str, path: str | None = None) -> str | None:
        calls.append((name, path))
        return str(tmp_path / "bin" / name) if path is not None else f"/system/{name}"

    monkeypatch.setattr(sys, "executable", str(interpreter))  # sarj-noqa: SARJ445 -- intercepts external tool routing
    monkeypatch.setattr(shutil, "which", which)  # sarj-noqa: SARJ445 -- intercepts external tool routing

    assert external_module._analyzer_executable("basedpyright") == str(tmp_path / "bin" / "basedpyright")  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _analyzer_executable contract directly with controlled fixture data.
    assert calls == [("basedpyright", str(tmp_path / "bin"))]


@pytest.mark.parametrize(
    "prefix",
    [
        "updated ./.basedpyright-baseline.json with 1503 errors (went down by 6)",
        "updated ./.basedpyright/baseline.json with 1 error (went down by 1)",
        "updated undefined with 0 errors (went down by 2)",
    ],
)
def test_basedpyright_accepts_the_native_baseline_shrink_notice(tmp_path: Path, prefix: str) -> None:
    assert parse_basedpyright(prefix + '\n\n{"generalDiagnostics":[]}', root=tmp_path) == ()


@pytest.mark.parametrize(
    "payload",
    [
        'unexpected log\n\n{"generalDiagnostics":[]}',
        'updated baseline with 1 error (went up by 1)\n\n{"generalDiagnostics":[]}',
        'updated baseline with 1 error (went down by 0)\n\n{"generalDiagnostics":[]}',
        'updated baseline with 1 errors (went down by 1)\n\n{"generalDiagnostics":[]}',
        'updated baseline with 1 error (went down by 1)\n{"generalDiagnostics":[]}',
        'updated baseline with 1 error (went down by 1)\n\nunexpected log\n{"generalDiagnostics":[]}',
        'updated baseline with 1 error (went down by 1)\n\n{"generalDiagnostics":[]}\ntrailing log',
        'updated baseline with 1 error (went down by 1)\n\n{"generalDiagnostics":',
        "updated baseline with 1 error (went down by 1)\n\n{}",
    ],
)
def test_basedpyright_rejects_unknown_framing_and_invalid_reports(tmp_path: Path, payload: str) -> None:
    with pytest.raises(ValidationError):
        parse_basedpyright(payload, root=tmp_path)


@pytest.mark.parametrize("returncode", [1, 2])
@pytest.mark.parametrize(
    "notice",
    [
        "updated baseline with 0 errors (went down by 1)",
        "baseline file is outdated, run without `--baselinemode=discard` to update it. (went down by 1)",
    ],
)
def test_basedpyright_native_notice_does_not_override_failure_status(
    tmp_path: Path, returncode: int, notice: str
) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n")
    payload = notice + '\n\n{"generalDiagnostics":[]}'

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert argv == ("basedpyright", "--outputjson", "--baselinemode=discard", str(source))
        assert cwd == tmp_path
        return ProcessOutput(returncode, payload, "")

    reports = analyze_external(
        (str(source),),
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
        capabilities=frozenset({"pyright"}),
    )

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].kind == ("protocol-mismatch" if returncode == 1 else "tool-failure")


def test_native_basedpyright_shrink_and_new_diagnostic_contract(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text('first: int = "bad"\nsecond: int = "bad"\n')
    (tmp_path / "pyrightconfig.json").write_text('{"include":["example.py"],"typeCheckingMode":"strict"}')
    baseline = tmp_path / ".basedpyright" / "baseline.json"
    initialized = subprocess.run(
        (sys.executable, "-m", "basedpyright", "--writebaseline", "--outputjson"),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert initialized.returncode in {0, 1}, initialized.stderr
    assert baseline.is_file()
    before = baseline.read_bytes()

    source.write_text('first: int = 1\nsecond: int = "bad"\n')
    # Explicit auto mode exercises the same local retirement behavior when this test runs in CI.
    retired = subprocess.run(
        (sys.executable, "-m", "basedpyright", "--baselinemode=auto", "--outputjson"),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert retired.returncode == 0, retired.stderr
    assert retired.stdout.startswith("updated ./.basedpyright/baseline.json with 1 error (went down by 1)\n\n")
    assert parse_basedpyright(retired.stdout, root=tmp_path) == ()
    shrunk = baseline.read_bytes()
    assert shrunk != before

    source.write_text('first: int = 1\nsecond: int = 2\nthird: int = "new"\n')
    failed = subprocess.run(
        (sys.executable, "-m", "basedpyright", "--baselinemode=auto", "--outputjson"),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert failed.returncode == 1, failed.stderr
    findings = parse_basedpyright(failed.stdout, root=tmp_path)
    assert len(findings) == 1
    assert findings[0].rule_id == "reportAssignmentType"
    assert findings[0].severity is Severity.ERROR
    assert baseline.read_bytes() == shrunk


def test_native_protocol_contracts_preserve_cached_descriptor_boundary(tmp_path: Path) -> None:
    template = """from dataclasses import dataclass
from functools import cached_property
from typing import Protocol

class Service(Protocol):
    @property
    def label(self) -> str: ...

class ServiceValue:
    @property
    def label(self) -> str:
        return "ready"

    @property
    def revision(self) -> int:
        return 7

class ConsumerContext(Protocol):
    @property
    def service(self) -> Service: ...

class ProducerContext:
    @DECORATOR
    def service(self) -> ServiceValue:
        return ServiceValue()

def forward(value: ProducerContext | ConsumerContext) -> ConsumerContext:
    return value

def service_value(value: ProducerContext) -> Service:
    return value.service

@dataclass(frozen=True, slots=True)
class ServiceView[ServiceType]:
    service: ServiceType

def focused_view(value: ProducerContext) -> ServiceView[ServiceValue]:
    return ServiceView(service=value.service)

def compatible_view(value: ProducerContext) -> ConsumerContext:
    return focused_view(value)

def consume(value: ConsumerContext) -> str:
    return value.service.label

def consume_view(value: ProducerContext) -> str:
    return consume(focused_view(value))

def retained_information(value: ProducerContext) -> int:
    return focused_view(value).service.revision
"""
    sources: list[str] = []
    for descriptor in ("cached_property", "property"):
        source = tmp_path / f"{descriptor}.py"
        source.write_text(template.replace("DECORATOR", descriptor), encoding="utf-8")
        sources.append(str(source))
    (tmp_path / "pyrightconfig.json").write_text(
        json.dumps({"typeCheckingMode": "basic", "pythonVersion": "3.14", "reportMissingImports": "error"}),
        encoding="utf-8",
    )

    reports = analyze_external(
        sources,
        root=tmp_path,
        trust=TrustMode.SAFE,
        capabilities=frozenset({"pyright"}),
    )

    assert len(reports) == 1
    report = reports[0]
    assert report.completion is Completion.COMPLETE
    assert report.file_count == 2
    assert not report.issues
    assert [(item.rule_id, item.location.path) for item in report.diagnostics] == [
        ("reportReturnType", "cached_property.py")
    ]


def test_basedpyright_utf16_range_preserves_astral_character(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = '😀'\n", encoding="utf-8")
    payload = json.dumps(
        {
            "generalDiagnostics": [
                {
                    "file": str(source),
                    "severity": "warning",
                    "message": "example",
                    "rule": "reportExample",
                    "range": {
                        "start": {"line": 0, "character": 9},
                        "end": {"line": 0, "character": 11},
                    },
                }
            ]
        }
    )

    finding = parse_basedpyright(payload, root=tmp_path)[0]

    assert finding.severity is Severity.WARNING
    assert finding.location.region is not None
    assert finding.location.region.start.byte_offset == 9
    assert finding.location.region.end.byte_offset == 13


def test_basedpyright_preserves_project_diagnostic_without_range(tmp_path: Path) -> None:
    source = tmp_path / "theme.py"
    source.write_text("from . import ui\n", encoding="utf-8")
    payload = json.dumps(
        {
            "generalDiagnostics": [
                {
                    "file": str(source),
                    "severity": "error",
                    "message": "Cycle detected in import chain",
                    "rule": "reportImportCycles",
                }
            ]
        }
    )

    finding = parse_basedpyright(payload, root=tmp_path)[0]

    assert finding.code == "reportImportCycles"
    assert finding.location.path == "theme.py"
    assert finding.location.position is None
    assert finding.location.region is None


@pytest.mark.parametrize(
    ("name", "source", "line", "severity", "completion"),
    [
        ("tests/helpers.py", "def _unused() -> int:\n    return 1\n", 0, Severity.WARNING, Completion.COMPLETE),
        ("src/dispatch.py", "def _callback() -> int:\n    return 1\n", 0, Severity.ERROR, Completion.COMPLETE),
        ("tests/helpers.py", "@fixture\ndef _resource() -> int:\n    return 1\n", 1, None, Completion.COMPLETE),
        ("tests/helpers.py", "def public_helper() -> int:\n    return 1\n", 0, None, Completion.COMPLETE),
        (
            "tests/helpers.py",
            "class Hook:\n    def __callback(self) -> int:\n        return 1\n",
            1,
            None,
            Completion.COMPLETE,
        ),
        (
            "tests/generated.py",
            "# @generated; do not edit\ndef _unused() -> int:\n    return 1\n",
            1,
            None,
            Completion.COMPLETE,
        ),
        ("tests/helpers.py", "def _unused() -> int:\n    return 1\ninvalid (\n", 0, None, Completion.PARTIAL),
    ],
    ids=[
        "private-helper",
        "production-config",
        "decorated-fixture",
        "public-contract",
        "class-hook",
        "generated",
        "unknown-source",
    ],
)
def test_unused_function_diagnostics_are_bounded_advisory_test_helpers(
    tmp_path: Path, name: str, source: str, line: int, *, severity: Severity | None, completion: Completion
) -> None:
    path = tmp_path / name
    path.parent.mkdir()
    path.write_text(source)
    payload = json.dumps(
        {
            "generalDiagnostics": [
                {
                    "file": str(path),
                    "severity": "error",
                    "message": "Function is not accessed",
                    "rule": "reportUnusedFunction",
                    "range": {"start": {"line": line, "character": 4}, "end": {"line": line, "character": 11}},
                }
            ]
        }
    )

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert argv == ("basedpyright", "--outputjson", "--baselinemode=discard", str(path))
        assert cwd == tmp_path
        return ProcessOutput(1, payload, "")

    reports = analyze_external(
        (str(path),),
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
        capabilities=frozenset({"pyright"}),
    )
    findings = tuple(item for report in reports for item in report.diagnostics)

    assert all(report.completion is completion for report in reports)
    assert len(findings) == int(severity is not None)
    if severity is not None:
        assert findings[0].severity is severity
        assert findings[0].rule_id == "reportUnusedFunction"
    if completion is Completion.PARTIAL:
        assert reports[0].issues[0].kind == "helper-source-inconclusive"


def test_basedpyright_accepts_range_ending_at_trailing_newline_eof(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    payload = json.dumps(
        {
            "generalDiagnostics": [
                {
                    "file": str(source),
                    "severity": "error",
                    "message": "example",
                    "rule": "reportExample",
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 1, "character": 0},
                    },
                }
            ]
        }
    )

    finding = parse_basedpyright(payload, root=tmp_path)[0]

    assert finding.location.region is not None
    assert finding.location.region.end.byte_offset == len("value = 1\n")


def test_signal_terminated_tool_is_an_execution_failure(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def terminated(
        argv: Sequence[str],  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        return ProcessOutput(-9, "[]", "")

    reports = analyze_external(
        [str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=FakeProcessExecutor(terminated)
    )

    assert all(report.completion is Completion.FAILED for report in reports)
    assert all(report.issues[0].exit_code == -9 for report in reports)


def test_finding_exit_without_diagnostics_fails_the_external_protocol(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def empty_finding_exit(
        argv: Sequence[str],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        payload = '{"generalDiagnostics":[]}' if argv[0] == "basedpyright" else "[]"
        return ProcessOutput(1, payload, "")

    reports = analyze_external(
        [str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=FakeProcessExecutor(empty_finding_exit)
    )

    assert all(report.completion is Completion.FAILED for report in reports)
    assert all(report.issues[0].kind == "protocol-mismatch" for report in reports)


def test_basedpyright_parser_rejects_unknown_severity(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    payload = json.dumps(
        {
            "generalDiagnostics": [
                {
                    "file": str(source),
                    "severity": "fatal",
                    "message": "bad severity",
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 1},
                    },
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="severity"):
        parse_basedpyright(payload, root=tmp_path)


def test_external_process_output_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts external tool routing
        external_module, "_MAX_STDOUT_BYTES", 128
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts external tool routing
        external_module, "_MAX_STDERR_BYTES", 64
    )

    with pytest.raises(external_module.OutputLimitError, match="output exceeded"):
        external_module.run_process(
            (sys.executable, "-c", "import sys; sys.stdout.write('x' * 10000)"),
            cwd=tmp_path,
        )


def test_malformed_nested_json_becomes_a_bounded_tool_failure(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def nested(
        argv: Sequence[str],  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        return ProcessOutput(0, "[" * 100_000, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=FakeProcessExecutor(nested))

    assert all(report.completion is Completion.FAILED for report in reports)
    assert all(len(report.issues[0].message) <= 1024 for report in reports)


def test_external_failure_redacts_secrets_and_absolute_paths(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def failed(
        argv: Sequence[str],  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        *,
        cwd: Path,
    ) -> ProcessOutput:
        return ProcessOutput(
            2,
            "",
            f"token=SUPERSECRET {cwd}/src/config /Users/alice/private/config https://docs.example.com/remediation",
        )

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=FakeProcessExecutor(failed))
    messages = "\n".join(issue.message for report in reports for issue in report.issues)

    assert "SUPERSECRET" not in messages
    assert "/Users/alice" not in messages
    assert "<redacted>" in messages
    assert "./src/config" in messages
    assert "https://docs.example.com/remediation" in messages


@pytest.mark.parametrize("filename", ["example.py", "example.pyi"], ids=("implementation", "stub"))
def test_python_external_tools_use_structured_output_without_uv(tmp_path: Path, filename: str) -> None:
    source = tmp_path / filename
    source.write_text("value = 1\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(
        argv: Sequence[str],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        seen.append(tuple(argv))
        if argv[0] == "ruff":
            return ProcessOutput(0, "[]", "")
        return ProcessOutput(0, '{"generalDiagnostics":[]}', "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=FakeProcessExecutor(runner))

    assert [report.name for report in reports] == ["ruff", "basedpyright"]
    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert all(argv[0] != "uv" for argv in seen)
    assert all(report.file_count == 1 for report in reports)


def test_python_external_tools_run_once_per_nearest_project(tmp_path: Path) -> None:
    first = tmp_path / "services" / "first"
    second = tmp_path / "services" / "second"
    for project in (first, second):
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text("[project]\nname = 'fixture'\nversion = '0'\n", encoding="utf-8")
        (project / "pyrightconfig.json").write_text("{}\n", encoding="utf-8")
    sources = (first / "app.py", second / "app.py")
    for source in sources:
        source.write_text("value = 1\n", encoding="utf-8")
    seen: list[tuple[str, Path, tuple[str, ...]]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append((argv[0], cwd, tuple(argv)))
        payload = "[]" if argv[0] == "ruff" else '{"generalDiagnostics":[]}'
        return ProcessOutput(0, payload, "")

    reports = analyze_external(
        [str(source) for source in sources],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
    )

    assert [(name, cwd) for name, cwd, _argv in seen] == [
        ("ruff", tmp_path),
        ("basedpyright", first),
        ("basedpyright", second),
    ]
    assert [report.file_count for report in reports] == [2, 1, 1]
    assert [report.invocation_id for report in reports] == [
        "ruff",
        "basedpyright:services/first",
        "basedpyright:services/second",
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="controlled fixture uses a POSIX executable entry point")
@pytest.mark.parametrize("tool", ["basedpyright", "deptry"])
@pytest.mark.parametrize(
    "trust",
    [
        pytest.param(TrustMode.SAFE, id="safe-enum"),
        pytest.param("safe", id="safe-string"),
        pytest.param(TrustMode.TRUSTED, id="trusted"),
    ],
)
def test_local_project_analyzer_requires_explicit_trust(tmp_path: Path, tool: str, trust: TrustMode | str) -> None:
    project = tmp_path / "python"
    marker = _write_controlled_project_analyzer(project, tool)
    assert not marker.exists()

    reports = analyze_external(
        (str(project / "app.py"),),
        root=project,
        trust=trust,
        runner=None,
        capabilities=frozenset({"pyright" if tool == "basedpyright" else "deptry"}),
        include_react_doctor=False,
        typescript=False,
    )

    assert len(reports) == 1
    report = reports[0]
    assert report.name == report.analyzer_id == tool
    assert report.invocation_id == f"{tool}:."
    assert report.file_count == 1
    if TrustMode(trust) is TrustMode.SAFE:
        assert not marker.exists(), "SAFE executed the project-local analyzer"
        assert report.completion is Completion.FAILED
        assert not report.diagnostics
        assert [issue.kind for issue in report.issues] == ["trust-required"]
        assert "--trust-repository-code" in report.issues[0].message
        aggregate = report_from_tools(project, reports)
        assert aggregate.exit_code == 2
        assert aggregate.conclusion is Conclusion.INCONCLUSIVE
    else:
        assert marker.exists()
        observed = parse_unique_json(marker.read_text(encoding="utf-8"))
        assert isinstance(observed, dict)
        arguments = observed["argv"]
        assert isinstance(arguments, list)
        assert arguments
        assert isinstance(arguments[0], str)
        assert arguments[0] == str(project / ".venv" / "bin" / tool)
        assert isinstance(observed["cwd"], str)
        assert observed["cwd"] == str(project)
        assert report.completion is Completion.COMPLETE
        assert not report.diagnostics
        assert not report.issues


@pytest.mark.parametrize(
    "layout",
    [
        pytest.param(("bin", "basedpyright"), id="posix-entry-point"),
        pytest.param(("Scripts", "basedpyright.exe"), id="windows-entry-point"),
    ],
)
@pytest.mark.parametrize("resolution", [ToolResolution.LOCAL, ToolResolution.PROVIDED])
def test_parent_analyzer_preserves_resolution_and_other_tool_findings(
    tmp_path: Path, layout: tuple[str, str], resolution: ToolResolution
) -> None:
    project = tmp_path / "python"
    analyzer = project / ".venv" / layout[0] / layout[1]
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("controlled candidate\n", encoding="utf-8")
    package = project / "service"
    package.mkdir()
    (package / "pyproject.toml").write_text("[project]\nname='service'\nversion='0'\n[tool.ruff]\n", encoding="utf-8")
    source = package / "app.py"
    source.write_text("import os\n", encoding="utf-8")

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        if argv[0] == "ruff":
            assert cwd == package
            payload = [
                {
                    "code": "F401",
                    "message": "unused import",
                    "filename": str(source),
                    "location": {"row": 1, "column": 8},
                    "end_location": {"row": 1, "column": 10},
                }
            ]
            return ProcessOutput(1, json.dumps(payload), "")
        assert resolution is ToolResolution.PROVIDED, "blocked project analyzer was dispatched"
        assert argv[0] == str(analyzer)
        assert cwd == project
        return ProcessOutput(0, '{"generalDiagnostics":[]}', "")

    reports = analyze_external(
        (str(source),),
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner, capabilities=ProcessCapabilities(resolution)),
        capabilities=frozenset({"ruff", "pyright"}),
        typescript=False,
    )

    assert [report.name for report in reports] == ["ruff", "basedpyright"]
    assert [item.code for item in reports[0].diagnostics] == ["F401"]
    assert reports[1].invocation_id == "basedpyright:python"
    assert reports[1].file_count == 1
    aggregate = report_from_tools(tmp_path, reports)
    assert aggregate.conclusion is Conclusion.FINDINGS
    if resolution is ToolResolution.LOCAL:
        assert [issue.kind for issue in reports[1].issues] == ["trust-required"]
        assert aggregate.completion is Completion.PARTIAL
        assert aggregate.exit_code == 2
    else:
        assert reports[1].completion is Completion.COMPLETE
        assert not reports[1].issues
        assert aggregate.completion is Completion.COMPLETE
        assert aggregate.exit_code == 1


@pytest.mark.skipif(sys.platform == "win32", reason="controlled fixture uses a POSIX executable entry point")
@pytest.mark.parametrize("command", ["init", "update"])
def test_baseline_refuses_untrusted_project_analyzer_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    marker = _write_controlled_project_analyzer(tmp_path, "basedpyright")
    output = tmp_path / "diagnostic-baseline.json"
    original = b"existing baseline must remain unchanged\n"
    if command == "update":
        output.write_bytes(original)

    status = cli_main(["--root", str(tmp_path), "baseline", command, str(tmp_path / "app.py")])

    assert status == 2
    assert "trust-required" in capsys.readouterr().err
    assert not marker.exists()
    if command == "update":
        assert output.read_bytes() == original
    else:
        assert not output.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="controlled fixture uses a POSIX executable entry point")
def test_baseline_explicit_trust_runs_project_analyzer(tmp_path: Path) -> None:
    marker = _write_controlled_project_analyzer(tmp_path, "basedpyright")

    status = cli_main(
        ["--root", str(tmp_path), "baseline", "init", "--trust-repository-code", str(tmp_path / "app.py")]
    )

    assert status == 0
    assert marker.exists()
    assert (tmp_path / "diagnostic-baseline.json").is_file()


def test_basedpyright_uses_the_project_environment_for_import_resolution(tmp_path: Path) -> None:
    project = tmp_path / "python"
    analyzer = project / ".venv" / "bin" / "basedpyright"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("#!/bin/sh\n", encoding="utf-8")
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\n", encoding="utf-8")
    source = project / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(
        argv: Sequence[str],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        seen.append(tuple(argv))
        payload = "[]" if argv[0] == "ruff" else '{"generalDiagnostics":[]}'
        return ProcessOutput(0, payload, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=FakeProcessExecutor(runner))

    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert seen[1][0] == str(analyzer)


def test_python_type_check_can_be_left_to_repository_ci(tmp_path: Path) -> None:
    project = tmp_path / "python"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\n", encoding="utf-8")
    source = project / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    seen: list[str] = []

    def runner(
        argv: Sequence[str],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        seen.append(Path(argv[0]).name)
        return ProcessOutput(0, "[]", "")

    reports = analyze_external(
        [str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=FakeProcessExecutor(runner), python_type_check=False
    )

    assert [report.name for report in reports] == ["ruff"]
    assert seen == ["ruff"]


def test_basedpyright_prefers_a_parent_environment_over_a_nested_package_manifest(tmp_path: Path) -> None:
    project = tmp_path / "python"
    analyzer = project / ".venv" / "bin" / "basedpyright"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("#!/bin/sh\n", encoding="utf-8")
    package = project / "service"
    package.mkdir()
    (package / "pyproject.toml").write_text("[project]\nname='service'\nversion='0'\n", encoding="utf-8")
    source = package / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    seen: list[tuple[tuple[str, ...], Path]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append((tuple(argv), cwd))
        payload = "[]" if argv[0] == "ruff" else '{"generalDiagnostics":[]}'
        return ProcessOutput(0, payload, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=FakeProcessExecutor(runner))

    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert seen[1] == ((str(analyzer), "--outputjson", "--baselinemode=discard", str(source)), project)


def test_basedpyright_selects_files_and_filters_unselected_diagnostics(tmp_path: Path) -> None:
    project = tmp_path / "python"
    project.mkdir()
    (project / "pyrightconfig.json").write_text('{"include":["."]}\n', encoding="utf-8")
    selected = project / "selected.py"
    unselected = project / "unselected.py"
    selected.write_text("value = 1\n", encoding="utf-8")
    unselected.write_text("value = 2\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(
        argv: Sequence[str],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        seen.append(tuple(argv))
        if argv[0] == "ruff":
            return ProcessOutput(0, "[]", "")
        diagnostics = [
            {
                "file": str(path),
                "severity": "error",
                "message": "fixture error",
                "rule": "reportGeneralTypeIssues",
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
            }
            for path in (selected, unselected)
        ]
        return ProcessOutput(1, json.dumps({"generalDiagnostics": diagnostics}), "")

    reports = analyze_external([str(selected)], root=tmp_path, trust=TrustMode.SAFE, runner=FakeProcessExecutor(runner))

    basedpyright = next(report for report in reports if report.name == "basedpyright")
    assert seen[1] == ("basedpyright", "--outputjson", "--baselinemode=discard", str(selected))
    assert basedpyright.completion is Completion.COMPLETE
    assert [diagnostic.location.path for diagnostic in basedpyright.diagnostics] == ["python/selected.py"]


def test_python_tools_use_the_adopted_config_for_files_outside_its_directory(tmp_path: Path) -> None:
    project = tmp_path / "python"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\nname='fixture'\nversion='0'\n[tool.ruff]\nextend='.ruff-strict.toml'\n"
        "[tool.pyright]\nextends='.pyright-strict.json'\n",
        encoding="utf-8",
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    source = scripts / "release.py"
    source.write_text("value = 1\n", encoding="utf-8")
    adopted = manifest.Manifest(
        "5.6.8",
        ("ruff", "pyright", "markdownlint", "taplo", "yamllint"),
        "python",
        ".",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    seen: list[tuple[tuple[str, ...], Path]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append((tuple(argv), cwd))
        payload = "[]" if argv[0] == "ruff" else '{"generalDiagnostics":[]}'
        return ProcessOutput(0, payload, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=FakeProcessExecutor(runner))

    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert seen == [
        (
            (
                "ruff",
                "check",
                "--output-format",
                "json",
                "--config",
                str(project / "pyproject.toml"),
                "--",
                str(source),
            ),
            tmp_path,
        ),
        (("basedpyright", "--outputjson", "--baselinemode=discard", str(source)), project),
    ]


def test_external_analyzer_cannot_leak_a_path_outside_repository(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    outside = tmp_path.parent / "private.py"

    def runner(
        argv: Sequence[str],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        if argv[0] == "ruff":
            return ProcessOutput(
                1,
                json.dumps(
                    [
                        {
                            "filename": str(outside),
                            "location": {"row": 1, "column": 1},
                            "end_location": {"row": 1, "column": 2},
                            "code": "E001",
                            "message": "outside",
                        }
                    ]
                ),
                "",
            )
        return ProcessOutput(0, '{"generalDiagnostics":[]}', "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=FakeProcessExecutor(runner))
    ruff = next(report for report in reports if report.name == "ruff")

    assert ruff.completion is Completion.FAILED
    assert ruff.issues[0].message == "ValueError: analyzer reported a path outside the repository root"
    assert str(tmp_path.parent) not in ruff.issues[0].message


@pytest.mark.parametrize(
    ("host_gib", "groups", "limits", "expected"),
    [
        pytest.param(8, "0::/\n", {"memory.max": "max"}, 4096, id="small-host"),
        pytest.param(16, "0::/\n", {"memory.max": "max"}, 8192, id="large-host"),
        pytest.param(None, "0::/\n", {"memory.max": "max"}, 4096, id="unknown-host"),
        pytest.param(
            32, "0::/job\n", {"memory.max": "max", "job/memory.max": str(8 * 1024**3)}, 4096, id="v2-job-limit"
        ),
        pytest.param(
            32,
            "0::/jobs/task\n",
            {"memory.max": "max", "jobs/memory.max": str(8 * 1024**3), "jobs/task/memory.max": str(16 * 1024**3)},
            4096,
            id="v2-parent-limit",
        ),
        pytest.param(
            32, "2:memory:/job\n", {"memory/job/memory.limit_in_bytes": str(8 * 1024**3)}, 4096, id="v1-job-limit"
        ),
        pytest.param(
            32, "2:memory:/job\n", {"memory/job/memory.limit_in_bytes": str(16 * 1024**3)}, 8192, id="v1-large-job"
        ),
        pytest.param(32, "0::/job\n", {}, 4096, id="unreadable-limits"),
        pytest.param(32, "0::/\n", {"memory.max": "invalid"}, 4096, id="malformed-limit"),
        pytest.param(32, "0::/\n", {"memory.max": "0"}, 4096, id="zero-limit"),
        pytest.param(32, "0::/../../job\n", {"memory.max": "max"}, 4096, id="unreachable-namespace"),
        pytest.param(32, "unknown\n", {"memory.max": "max"}, 4096, id="malformed-cgroup"),
    ],
)
def test_node_heap_respects_host_and_process_container_limits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    host_gib: int | None,
    groups: str,
    limits: dict[str, str],
    expected: int,
) -> None:
    root = tmp_path / "cgroup"
    process = tmp_path / "process-cgroups"
    process.write_text(groups)
    for relative, value in limits.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test supplies the OS memory query without allocating it
        external_module, "_physical_memory_bytes", lambda: None if host_gib is None else host_gib * 1024**3
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise Linux hierarchy parsing on every test platform
        sys, "platform", "linux"
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test uses a private cgroup filesystem
        external_module, "_CGROUP_ROOT", root
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test owns the process membership record
        external_module, "_PROCESS_CGROUPS", process
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- root and nested limits all belong to the fixture
        external_module, "_CGROUP_MEMORY_LIMIT_FILES", (root / "memory.max", root / "memory/memory.limit_in_bytes")
    )
    assert external_module._node_options() == f"--max-old-space-size={expected}"  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _node_options contract directly with controlled fixture data.


@pytest.mark.parametrize("unused", [False, True], ids=("declared-used", "seeded-unused"))
@pytest.mark.parametrize("select_child", [False, True], ids=("root-script", "root-and-child"))
def test_deptry_scans_declared_wheel_sources_for_root_scripts_without_unrelated_children(
    tmp_path: Path, unused: bool, select_child: bool
) -> None:
    dependencies = ["packaging", "typer"] if unused else ["packaging"]
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "application"\nversion = "1"\n'
        f"dependencies = {json.dumps(dependencies)}\n"
        '\n[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
        '\n[tool.hatch.build.targets.wheel]\npackages = ["packages/application/src/application"]\n',
        encoding="utf-8",
    )
    script = tmp_path / ".github/scripts/verify.py"
    script.parent.mkdir(parents=True)
    script.write_text("from pathlib import Path\nprint(Path.cwd())\n", encoding="utf-8")
    source = tmp_path / "packages/application/src/application/__init__.py"
    source.parent.mkdir(parents=True)
    source.write_text("from packaging.version import Version\nVERSION = Version('1')\n", encoding="utf-8")
    project = source.parents[2]
    (project / "pyproject.toml").write_text(
        '[project]\nname = "application"\nversion = "1"\ndependencies = ["packaging"]\n', encoding="utf-8"
    )
    unrelated = tmp_path / "packages/unrelated"
    unrelated.mkdir()
    (unrelated / "pyproject.toml").write_text(
        '[project]\nname = "unrelated"\nversion = "1"\ndependencies = ["typer"]\n', encoding="utf-8"
    )
    (unrelated / "app.py").write_text("import typer\n", encoding="utf-8")
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        calls.append((cwd, tuple(argv)))
        return external_module.run_process(argv, cwd=cwd)

    selected = [str(script), str(source)] if select_child else [str(script)]
    reports = analyze_external(
        selected,
        root=tmp_path,
        trust=TrustMode.SAFE,
        capabilities=frozenset({"deptry"}),
        runner=FakeProcessExecutor(run),
    )
    assert len(calls) == (2 if select_child else 1)
    assert all(report.completion is Completion.COMPLETE for report in reports)
    diagnostics = [item for report in reports for item in report.diagnostics]
    assert [(item.code, item.location.path) for item in diagnostics] == (
        [("DEP002", "pyproject.toml")] if unused else []
    )
    if unused:
        assert "typer" in diagnostics[0].message
    root_call = next(argv for cwd, argv in calls if cwd == tmp_path)
    assert "packages/application/src/application" in root_call
    assert "packages/unrelated" not in root_call


@pytest.mark.parametrize("backend", ["hatchling.build", "uv_build"])
def test_deptry_declared_sources_overlap_without_duplicate_missing_dependency_findings(
    tmp_path: Path, backend: str
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "application"\nversion = "1"\ndependencies = []\n'
        f'\n[build-system]\nrequires = ["hatchling", "uv_build>=0.12.7,<0.13"]\nbuild-backend = "{backend}"\n'
        '\n[tool.hatch.build.targets.wheel]\npackages = ["src/application"]\n',
        encoding="utf-8",
    )
    source = tmp_path / "src/application/__init__.py"
    source.parent.mkdir(parents=True)
    source.write_text("import deptry_missing_fixture\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        calls.append(tuple(argv))
        return external_module.run_process(argv, cwd=cwd)

    reports = analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        capabilities=frozenset({"deptry"}),
        runner=FakeProcessExecutor(run),
    )
    assert len(reports) == 1
    assert reports[0].completion is Completion.COMPLETE
    assert [(item.code, item.location.path) for item in reports[0].diagnostics] == [
        ("DEP001", "src/application/__init__.py")
    ]
    assert calls[0][1] == "src/application"
    assert "src" not in calls[0]


@pytest.mark.parametrize("unused", [False, True], ids=("all-used", "true-unused"))
@pytest.mark.parametrize("select_owned", [False, True], ids=("changed-test", "changed-owned-source"))
@pytest.mark.parametrize(
    ("project_name", "settings", "package_paths"),
    [
        ("application", 'module-name = "owned_package"\n', ("src/owned_package",)),
        ("Demo..App---Tool", "", ("src/demo_app_tool",)),
        ("application", 'module-name = "Application"\nmodule-root = ""\n', ("Application",)),
        ("application", 'module-name = "owned"\nmodule-root = "src/../lib"\n', ("lib/owned",)),
        (
            "application",
            'module-name = ["shared.alpha", "shared.beta"]\nmodule-root = "lib"\n',
            ("lib/shared/alpha", "lib/shared/beta"),
        ),
    ],
    ids=(
        "explicit-name-default-root",
        "normalized-defaults",
        "flat-case-sensitive",
        "normalized-root",
        "namespace-modules",
    ),
)
def test_deptry_uv_build_owns_only_declared_modules_for_selected_tests(
    tmp_path: Path,
    project_name: str,
    settings: str,
    package_paths: Sequence[str],
    *,
    unused: bool,
    select_owned: bool,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "{project_name}"\nversion = "1"\ndependencies = ["packaging", "typer"]\n'
        '\n[build-system]\nrequires = ["uv_build>=0.12.7,<0.13"]\nbuild-backend = "uv_build"\n'
        f"\n[tool.uv.build-backend]\n{settings}",
        encoding="utf-8",
    )
    selected = tmp_path / "tests/test_smoke.py"
    selected.parent.mkdir()
    selected.write_text("from pathlib import Path\nassert Path.cwd().is_dir()\n", encoding="utf-8")
    for relative in package_paths:
        package = tmp_path / relative
        package.mkdir(parents=True)
        package.joinpath("__init__.py").write_text(
            "from packaging.version import Version\nVERSION = Version('1')\n"
            + ("" if unused else "import typer\nAPP = typer.Typer()\n"),
            encoding="utf-8",
        )
    if len(package_paths) > 1:
        first_source = tmp_path / package_paths[0] / "__init__.py"
        first_source.write_text(first_source.read_text(encoding="utf-8") + "import shared.beta\n", encoding="utf-8")
    # An independently owned sibling cannot make the parent's unused dependency
    # look used, even when it lives beside a declared module under the same root.
    unrelated = tmp_path / Path(package_paths[0]).parent / "unrelated"
    unrelated.mkdir()
    unrelated.joinpath("pyproject.toml").write_text(
        '[project]\nname = "unrelated"\nversion = "1"\ndependencies = ["typer"]\n', encoding="utf-8"
    )
    unrelated.joinpath("__init__.py").write_text("import typer\n", encoding="utf-8")
    if select_owned:
        selected = tmp_path / package_paths[0] / "__init__.py"
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        calls.append(tuple(argv))
        return external_module.run_process(argv, cwd=cwd)

    reports = analyze_external(
        [str(selected)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        capabilities=frozenset({"deptry"}),
        runner=FakeProcessExecutor(run),
    )
    assert len(calls) == len(reports) == 1
    assert reports[0].completion is Completion.COMPLETE
    assert [(item.code, item.location.path) for item in reports[0].diagnostics] == (
        [("DEP002", "pyproject.toml")] if unused else []
    )
    if unused:
        assert "typer" in reports[0].diagnostics[0].message
    scan_roots = calls[0][1 : calls[0].index("--config")]
    assert set(scan_roots) == (set(package_paths) if select_owned else {"tests", *package_paths})
    if len(package_paths) > 1:
        first_party = {calls[0][index + 1] for index, option in enumerate(calls[0]) if option == "--known-first-party"}
        assert "shared" in first_party
        assert first_party.isdisjoint({"alpha", "beta"})


@pytest.mark.parametrize(
    "settings",
    [
        "module-name = 1\n",
        'module-name = ["owned", 1]\n',
        "module-name = []\n",
        'module-name = ""\n',
        'module-name = "owned..child"\n',
        'module-name = "../outside"\n',
        'module-name = "/outside"\n',
        'module-name = "owned"\nmodule-root = ["src"]\n',
        'module-name = "owned"\nmodule-root = "../outside"\n',
        'module-name = "owned"\nmodule-root = ".."\n',
        'module-name = "owned"\nmodule-root = "linked"\n',
    ],
    ids=(
        "integer",
        "mixed-list",
        "empty-list",
        "empty-name",
        "empty-segment",
        "parent",
        "absolute",
        "root-type",
        "root-escape",
        "root-reentry",
        "symlink-escape",
    ),
)
def test_deptry_uv_build_rejects_invalid_module_ownership_before_running(tmp_path: Path, settings: str) -> None:
    project = tmp_path / "owned"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "application"\nversion = "1"\ndependencies = []\n'
        '\n[build-system]\nrequires = ["uv_build>=0.12.7,<0.13"]\nbuild-backend = "uv_build"\n'
        f"\n[tool.uv.build-backend]\n{settings}",
        encoding="utf-8",
    )
    selected = project / "tests/test_smoke.py"
    selected.parent.mkdir()
    selected.write_text("pass\n", encoding="utf-8")
    if 'module-root = "linked"' in settings:
        outside = project.with_name(f"{project.name}-outside")
        outside.mkdir()
        (project / "linked").symlink_to(outside, target_is_directory=True)

    def unexpected(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        message = f"invalid module ownership reached Deptry: {argv} in {cwd}"
        raise AssertionError(message)

    reports = analyze_external(
        [str(selected)],
        root=project,
        trust=TrustMode.SAFE,
        capabilities=frozenset({"deptry"}),
        runner=FakeProcessExecutor(unexpected),
    )
    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].diagnostics == ()
    assert len(reports[0].issues) == 1
    assert reports[0].issues[0].kind == "tool-failure"
    assert any(text in reports[0].issues[0].message for text in ("uv_build", "within its Python project"))


def test_deptry_ignores_uv_ownership_settings_for_other_backends(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "application"\nversion = "1"\ndependencies = ["packaging", "typer"]\n'
        '\n[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n'
        '\n[tool.uv.build-backend]\nmodule-name = "unrelated"\nmodule-root = "../outside"\n',
        encoding="utf-8",
    )
    selected = tmp_path / "tools/verify.py"
    selected.parent.mkdir()
    selected.write_text("import packaging\n", encoding="utf-8")
    reports = analyze_external([str(selected)], root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"deptry"}))
    assert len(reports) == 1
    assert reports[0].completion is Completion.COMPLETE
    assert [(item.code, item.location.path) for item in reports[0].diagnostics] == [("DEP002", "pyproject.toml")]
    assert "typer" in reports[0].diagnostics[0].message


@pytest.mark.parametrize("directory", [".", "tools/scripts"], ids=("root-maintenance", "nested-maintenance"))
def test_deptry_keeps_unchanged_same_project_maintenance_imports(tmp_path: Path, directory: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "application"\nversion = "1"\ndependencies = ["packaging", "typer"]\n'
        '\n[build-system]\nrequires = ["uv_build>=0.12.7,<0.13"]\nbuild-backend = "uv_build"\n',
        encoding="utf-8",
    )
    package = tmp_path / "src/application"
    package.mkdir(parents=True)
    package.joinpath("__init__.py").write_text("import packaging\n", encoding="utf-8")
    maintenance = tmp_path / directory
    maintenance.mkdir(parents=True, exist_ok=True)
    selected = maintenance / "verify.py"
    selected.write_text("from pathlib import Path\nprint(Path.cwd())\n", encoding="utf-8")
    maintenance.joinpath("maintenance_helper.py").write_text("import typer\n", encoding="utf-8")

    reports = analyze_external([str(selected)], root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"deptry"}))

    assert len(reports) == 1
    assert reports[0].completion is Completion.COMPLETE
    assert reports[0].diagnostics == ()


def test_deptry_uv_build_default_stub_package_ownership(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "Demo.App-stubs"\nversion = "1"\ndependencies = ["packaging"]\n'
        '\n[build-system]\nrequires = ["uv_build>=0.12.7,<0.13"]\nbuild-backend = "uv_build"\n',
        encoding="utf-8",
    )
    package = tmp_path / "src/demo_app-stubs"
    package.mkdir(parents=True)
    package.joinpath("__init__.pyi").write_text("def identity(value: int) -> int: ...\n", encoding="utf-8")
    selected = tmp_path / "tools/verify.py"
    selected.parent.mkdir()
    selected.write_text("import packaging\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        calls.append(tuple(argv))
        return external_module.run_process(argv, cwd=cwd)

    reports = analyze_external(
        [str(selected)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        capabilities=frozenset({"deptry"}),
        runner=FakeProcessExecutor(run),
    )

    assert len(calls) == len(reports) == 1
    assert reports[0].completion is Completion.COMPLETE
    assert reports[0].diagnostics == ()
    assert set(calls[0][1 : calls[0].index("--config")]) == {"src/demo_app-stubs", "tools"}
    first_party = {calls[0][index + 1] for index, option in enumerate(calls[0]) if option == "--known-first-party"}
    assert "demo_app" in first_party
    assert "demo_app-stubs" not in first_party
