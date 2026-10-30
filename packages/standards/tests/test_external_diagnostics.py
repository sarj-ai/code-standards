from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from deptry.cli import cli as deptry_cli
from pydantic import ValidationError
import pytest

from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode
from sarj_standards.libs.linting import external as external_module
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.external import (
    ProcessOutput,
    analyze_external,
    parse_basedpyright,
    parse_deptry,
    parse_eslint,
    parse_ktlint,
    parse_mobsfscan,
    parse_react_doctor,
    parse_ruff,
    parse_sarif,
    parse_shellcheck,
    parse_swiftformat,
    parse_swiftlint,
)
from sarj_standards.libs.linting.process import ProcessRequest, RequestExecutor
from sarj_standards.libs.linting.runner import GroupedPaths
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


def _eslint_files(argv: Sequence[str]) -> Sequence[str]:
    boundary = max(index for index, value in enumerate(argv) if value == "--") + 1
    return argv[boundary:]


def _eslint_clean_payload(argv: Sequence[str], cwd: Path) -> str:
    return json.dumps([{"filePath": str((cwd / value).resolve()), "messages": []} for value in _eslint_files(argv)])


def test_eslint_passes_on_unpruned_suppressions_only_when_requested() -> None:
    command = ("npx", "eslint", "--", "app.ts")

    strict = external_module._eslint_json_argv(command)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _eslint_json_argv contract directly with controlled fixture data.
    scoped_baseline = external_module._eslint_json_argv(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _eslint_json_argv contract directly with controlled fixture data.
        command, pass_on_unpruned_suppressions=True
    )

    assert "--pass-on-unpruned-suppressions" not in strict
    assert scoped_baseline.count("--pass-on-unpruned-suppressions") == 1
    assert scoped_baseline.index("--pass-on-unpruned-suppressions") < scoped_baseline.index("--")


def test_eslint_ignored_selected_file_is_incomplete_coverage(tmp_path: Path) -> None:
    source = tmp_path / "src" / "ignored.ts"
    source.parent.mkdir()
    source.write_text("export const ignored = true;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text('export default [{ ignores: ["src/ignored.ts"] }];\n', encoding="utf-8")

    def ignored(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert "--no-warn-ignored" in argv
        assert cwd == tmp_path
        return ProcessOutput(0, "[]", "")

    reports = analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        runner=FakeProcessExecutor(ignored),
        capabilities=frozenset({"eslint"}),
    )

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].kind == "coverage-missing"
    assert reports[0].file_count == 1


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


@pytest.mark.parametrize("select_directories", [False, True])
@pytest.mark.parametrize(
    ("separate_configs", "expected_counts", "expected_projects"),
    [(False, [252], [{"alpha", "beta"}]), (True, [251, 1], [{"alpha"}, {"beta"}])],
)
def test_eslint_batches_preserve_every_file_and_configuration_owner(
    tmp_path: Path,
    select_directories: bool,
    separate_configs: bool,
    expected_counts: list[int],
    expected_projects: list[set[str]],
) -> None:
    for project in ("apps/alpha", "apps/beta"):
        directory = tmp_path / project
        directory.mkdir(parents=True)
        (directory / "tsconfig.json").write_text("{}\n", encoding="utf-8")
        if separate_configs:
            (directory / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    paths = [*(f"apps/alpha/item-{index:03}.ts" for index in range(251)), "apps/beta/item.ts"]
    for relative in paths:
        (tmp_path / relative).write_text("export const value = 1;\n", encoding="utf-8")
    calls: list[tuple[Path, tuple[str, ...]]] = []
    expected_cwds = {tmp_path / "apps/alpha", tmp_path / "apps/beta"} if separate_configs else {tmp_path}

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd in expected_cwds
        calls.append((cwd, tuple(argv)))
        return ProcessOutput(0, _eslint_clean_payload(argv, cwd), "")

    selection = ["apps/alpha", "apps/beta"] if select_directories else paths
    reports = analyze_external(
        selection,
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        runner=FakeProcessExecutor(run),
        capabilities=frozenset({"eslint"}),
        grouped=GroupedPaths(typescript=selection),
    )

    selected = [[(cwd / file).relative_to(tmp_path).as_posix() for file in _eslint_files(argv)] for cwd, argv in calls]
    assert sorted(file for batch in selected for file in batch) == sorted(paths)
    assert list(map(len, selected)) == expected_counts
    assert [{Path(file).parts[1] for file in batch} for batch in selected] == expected_projects
    assert len({report.invocation_id for report in reports}) == len(expected_counts)
    assert [report.file_count for report in reports] == expected_counts
    assert all(report.completion is Completion.COMPLETE for report in reports)


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_eslint_large_batches_are_bounded_by_encoded_arguments(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- check both platform encodings without a platform-specific runtime.
        sys, "platform", platform
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise an explicit portable command-line bound.
        external_module, "_ESLINT_ARGV_BUDGET", 24 * 1024
    )
    prefix = ("eslint", "--")
    paths = tuple(f"src/{'unicode-λ-' * 20}{index}.ts" for index in range(1_200))
    batches = external_module._eslint_path_batches(prefix, paths)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _eslint_path_batches contract directly with controlled fixture data.
    assert tuple(path for batch in batches for path in batch) == paths
    encoding = "utf-16-le" if platform == "win32" else "utf-8"
    assert all(len(batch) <= 1_000 for batch in batches)
    assert all(
        sum(len(value.encode(encoding)) + 2 for value in (*prefix, *batch)) + 8 * 1024 <= 24 * 1024 for batch in batches
    )
    with pytest.raises(ValueError, match="command-line budget"):
        external_module._eslint_path_batches(prefix, ("x" * (24 * 1024),))  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _eslint_path_batches contract directly with controlled fixture data.


def test_eslint_batch_failure_keeps_partial_findings_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise a multi-batch failure without a thousand fixture files.
        external_module, "_ESLINT_ANALYSIS_BATCH_SIZE", 250
    )
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    paths = [f"item-{index:03}.ts" for index in range(251)]
    for relative in paths:
        (tmp_path / relative).write_text("export const value = 1;\n", encoding="utf-8")

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        files = argv[max(index for index, value in enumerate(argv) if value == "--") + 1 :]
        if len(files) == 1:
            return ProcessOutput(2, "", "FATAL ERROR: Reached heap limit")
        payload = [
            {
                "filePath": str(cwd / files[0]),
                "messages": [
                    {"ruleId": "no-alert", "severity": 2, "message": "Unexpected alert.", "line": 1, "column": 1}
                ],
            }
        ]
        return ProcessOutput(1, json.dumps(payload), "")

    reports = analyze_external(
        paths,
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        runner=FakeProcessExecutor(run),
        capabilities=frozenset({"eslint"}),
    )

    assert len(reports) == 2
    assert len(reports[0].diagnostics) == 1
    assert reports[1].completion is Completion.FAILED
    assert reports[1].issues


def test_eslint_batches_do_not_reset_the_aggregate_deadline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    paths = [f"item-{index:03}.ts" for index in range(251)]
    for relative in paths:
        (tmp_path / relative).write_text("export const value = 1;\n", encoding="utf-8")
    elapsed = 0.0
    calls = 0
    monkeypatch.setattr(time, "monotonic", lambda: elapsed)  # sarj-noqa: SARJ445 -- intercepts external tool routing

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal calls, elapsed
        assert "eslint" in argv
        assert cwd == tmp_path
        calls += 1
        elapsed = 301.0
        return ProcessOutput(0, _eslint_clean_payload(argv, cwd), "")

    reports = analyze_external(
        paths,
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        runner=FakeProcessExecutor(run),
        capabilities=frozenset({"eslint"}),
    )

    assert calls == 1
    assert reports[-1].completion is Completion.FAILED
    assert [issue.kind for issue in reports[-1].issues] == ["aggregate-timeout"]


@pytest.mark.parametrize("finding_count", [0, 1])
def test_eslint_final_batch_over_deadline_keeps_findings_and_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, finding_count: int
) -> None:
    source = tmp_path / "app.ts"
    source.write_text("alert('hello');\n", encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    elapsed = 0.0
    monkeypatch.setattr(time, "monotonic", lambda: elapsed)  # sarj-noqa: SARJ445 -- intercepts external tool routing

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal elapsed
        assert "eslint" in argv
        assert cwd == tmp_path
        elapsed = 301.0
        payload = [
            {
                "filePath": str(source),
                "messages": [
                    {"ruleId": "no-alert", "severity": 2, "message": "Unexpected alert.", "line": 1, "column": 1}
                ][:finding_count],
            }
        ]
        return ProcessOutput(finding_count, json.dumps(payload), "")

    reports = analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        runner=FakeProcessExecutor(run),
        capabilities=frozenset({"eslint"}),
    )

    assert len(reports[0].diagnostics) == finding_count
    assert reports[-1].completion is Completion.FAILED
    assert [issue.kind for issue in reports[-1].issues] == ["aggregate-timeout"]


@pytest.mark.usefixtures("_fixed_host_memory")
@pytest.mark.parametrize("decorated", [False, True], ids=("bare", "recording"))
def test_eslint_batches_pass_only_remaining_time_to_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, decorated: bool
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- keep two transport calls to verify deadline sharing.
        external_module, "_ESLINT_ANALYSIS_BATCH_SIZE", 250
    )
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    binary = tmp_path / "node_modules" / ".bin" / "eslint"
    binary.parent.mkdir(parents=True)
    binary.touch()
    paths = [f"item-{index:03}.ts" for index in range(251)]
    for relative in paths:
        (tmp_path / relative).write_text("export const value = 1;\n", encoding="utf-8")
    elapsed = 0.0
    timeouts: list[float] = []
    monkeypatch.setattr(time, "monotonic", lambda: elapsed)  # sarj-noqa: SARJ445 -- intercepts external tool routing

    def run(request: ProcessRequest) -> ProcessOutput:
        nonlocal elapsed
        argv, cwd, environment = request.argv, request.cwd, request.environment
        assert Path(argv[0]).name == "node"
        assert Path(argv[1]).name == "eslint-selected-rules.mts"
        assert json.loads(argv[2])["full"] is True
        assert cwd == tmp_path
        assert environment["NODE_OPTIONS"] == "--max-old-space-size=4096"
        assert request.deadline is not None
        timeouts.append(request.deadline - time.monotonic())
        elapsed += 125.0
        return ProcessOutput(0, _eslint_clean_payload(argv, cwd), "")

    monkeypatch.setattr(external_module, "_run_process", run)  # sarj-noqa: SARJ445 -- intercepts external tool routing
    runner = (
        RequestExecutor(external_module.DEFAULT_EXECUTOR.run, external_module.DEFAULT_EXECUTOR.capabilities)
        if decorated
        else None
    )
    reports = analyze_external(
        paths, root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"eslint"}), runner=runner
    )

    assert timeouts == [300.0, 175.0]
    assert all(report.completion is Completion.COMPLETE for report in reports)


def test_eslint_subprocess_obeys_remaining_timeout(tmp_path: Path) -> None:
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        external_module._run_eslint_process(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _run_eslint_process contract directly with controlled fixture data.
            (sys.executable, "-c", "import time; time.sleep(10)"), cwd=tmp_path, timeout_seconds=0.05
        )
    assert caught.value.timeout == pytest.approx(0.05)


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


def test_react_doctor_v3_json_becomes_a_blocking_canonical_region(tmp_path: Path) -> None:
    source = tmp_path / "src" / "button.tsx"
    source.parent.mkdir()
    source.write_text("export const Button = () => <button />;\n", encoding="utf-8")
    diagnostic: dict[str, JsonValue] = {
        "filePath": "src/button.tsx",
        "plugin": "react-doctor",
        "rule": "button-has-type",
        "severity": "error",
        "message": "Button needs an explicit type.",
        "help": "Add type=button.",
        "line": 1,
        "column": 28,
        "endLine": 1,
        "endColumn": 36,
        "category": "Bugs",
        "id": "stable-id",
        "normalizedFilePath": "src/button.tsx",
        "tags": [],
    }
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "mode": "full",
            "reactDetected": True,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "directory": str(tmp_path),
            "diff": None,
            "projects": [
                {
                    "directory": str(tmp_path),
                    "packageRoot": str(tmp_path),
                    "framework": "react",
                    "project": {},
                    "diagnostics": [diagnostic],
                    "score": None,
                    "skippedChecks": [],
                    "analyzedFiles": ["src/button.tsx"],
                    "analyzedFileCount": 1,
                    "complete": True,
                    "scannedFileCount": 1,
                    "elapsedMilliseconds": 1,
                }
            ],
            "skippedProjects": [],
            "diagnostics": [diagnostic],
            "summary": {
                "errorCount": 1,
                "warningCount": 0,
                "affectedFileCount": 1,
                "totalDiagnosticCount": 1,
                "score": None,
                "scoreLabel": None,
            },
            "elapsedMilliseconds": 1,
            "error": None,
        }
    )

    finding = parse_react_doctor(payload, root=tmp_path)[0]

    assert finding.code == "react-doctor/button-has-type"
    assert finding.rule_id == "react-doctor/button-has-type"
    assert finding.severity is Severity.ERROR
    assert finding.location.path == "src/button.tsx"
    assert finding.location.region is not None


def test_react_doctor_rejects_empty_project_coverage(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [],
            "error": None,
        }
    )

    with pytest.raises(ValueError, match="no analyzed projects"):
        parse_react_doctor(payload, root=tmp_path)


def test_react_doctor_accepts_empty_staged_report_without_analyzable_sources(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [],
            "diagnostics": [],
            "error": None,
        }
    )

    assert (
        parse_react_doctor(
            payload,
            root=tmp_path,
            expected_projects=frozenset({tmp_path.resolve()}),
            allow_empty_projects=True,
        )
        == ()
    )


def test_react_doctor_rejects_empty_report_with_top_level_diagnostics(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [],
            "diagnostics": [
                {
                    "filePath": "component.tsx",
                    "plugin": "react-doctor",
                    "rule": "example",
                    "severity": "warning",
                    "message": "example",
                    "line": 1,
                    "column": 1,
                }
            ],
            "error": None,
        }
    )

    with pytest.raises(ValueError, match="diagnostics without an analyzed project"):
        parse_react_doctor(payload, root=tmp_path, allow_empty_projects=True)


def test_react_doctor_zero_coordinates_become_a_path_only_location(tmp_path: Path) -> None:
    source = tmp_path / "package.json"
    source.write_text('{"private": true}\n', encoding="utf-8")
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "reactDetected": True,
            "baselineDegraded": False,
            "projects": [
                {
                    "directory": str(tmp_path),
                    "complete": True,
                    "skippedChecks": [],
                    "analyzedFileCount": 2,
                    "scannedFileCount": 2,
                    "diagnostics": [
                        {
                            "filePath": "package.json",
                            "plugin": "react-doctor",
                            "rule": "project-configuration",
                            "severity": "warning",
                            "message": "Project configuration needs attention.",
                            "line": 0,
                            "column": 0,
                            "endLine": 0,
                            "endColumn": 0,
                        }
                    ],
                }
            ],
            "skippedProjects": [],
            "error": None,
        }
    )

    finding = parse_react_doctor(payload, root=tmp_path, include_warnings=True)[0]

    assert finding.location.path == "package.json"
    assert finding.location.position is None
    assert finding.location.region is None


def test_react_doctor_accepts_omitted_false_baseline_degraded_metadata(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "reactDetected": True,
            "projects": [
                {
                    "directory": str(tmp_path),
                    "complete": True,
                    "skippedChecks": [],
                    "analyzedFileCount": 1,
                    "scannedFileCount": 1,
                }
            ],
            "skippedProjects": [],
            "error": None,
        }
    )

    assert parse_react_doctor(payload, root=tmp_path, expected_projects=frozenset({tmp_path.resolve()})) == ()


def test_react_doctor_rejects_incomplete_projects(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [{"directory": str(tmp_path), "complete": False}],
            "skippedProjects": [],
            "error": None,
        }
    )

    with pytest.raises(ValueError, match="did not complete"):
        parse_react_doctor(payload, root=tmp_path)


@pytest.mark.parametrize(
    "coverage",
    [
        pytest.param({"complete": False}, id="native-incomplete"),
        pytest.param({"complete": True, "skippedChecks": ["lint"]}, id="skipped-check"),
        pytest.param(
            {"complete": True, "skippedCheckReasons": {"lint:partial": "worker stopped"}}, id="skipped-reason"
        ),
    ],
)
def test_react_doctor_incomplete_context_remains_blocking(tmp_path: Path, coverage: dict[str, JsonValue]) -> None:
    payload = _react_coverage_payload(tmp_path, coverage)

    with pytest.raises(ValueError, match="React Doctor") as caught:
        parse_react_doctor(payload, root=tmp_path)

    message = str(caught.value)
    assert "analyzed=7, scanned=11" in message
    assert "skipped_checks=" in message
    assert "skipped_check_reasons=" in message


def test_react_doctor_incomplete_context_preserves_unreported_coverage(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [{"directory": str(tmp_path), "complete": False}],
            "error": None,
        }
    )

    with pytest.raises(ValueError, match="did not complete") as caught:
        parse_react_doctor(payload, root=tmp_path)

    assert "analyzed=None, scanned=None, skipped_checks=None" in str(caught.value)


def _react_coverage_payload(root: Path, coverage: dict[str, JsonValue]) -> str:
    return json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "reactDetected": True,
            "projects": [
                {
                    "directory": str(root),
                    "complete": True,
                    "skippedChecks": [],
                    "analyzedFileCount": 7,
                    "scannedFileCount": 11,
                    **coverage,
                }
            ],
            "error": None,
        }
    )


@pytest.mark.parametrize(
    "reasons",
    [
        pytest.param(None, id="null-map"),
        pytest.param([], id="array"),
        pytest.param("worker stopped", id="string"),
        pytest.param({"lint": None}, id="null-reason"),
        pytest.param({"lint": 3}, id="numeric-reason"),
    ],
)
def test_react_doctor_skipped_reasons_require_native_string_map(tmp_path: Path, reasons: JsonValue) -> None:
    with pytest.raises(ValidationError, match="skippedCheckReasons"):
        parse_react_doctor(_react_coverage_payload(tmp_path, {"skippedCheckReasons": reasons}), root=tmp_path)


@pytest.mark.parametrize(
    "coverage",
    [pytest.param({}, id="omitted"), pytest.param({"skippedCheckReasons": {}}, id="empty-map")],
)
def test_react_doctor_optional_empty_reasons_preserve_complete_coverage(
    tmp_path: Path, coverage: dict[str, JsonValue]
) -> None:
    payload = _react_coverage_payload(tmp_path, {"scannedFileCount": 7, **coverage})
    assert parse_react_doctor(payload, root=tmp_path) == ()


@pytest.mark.parametrize("returncode", [0, 1])
def test_react_doctor_incomplete_report_retains_bounded_redacted_native_context(
    tmp_path: Path, returncode: int
) -> None:
    package = tmp_path / "package.json"
    package.write_text('{"dependencies":{"react":"19.0.0"}}\n', encoding="utf-8")
    coverage: dict[str, JsonValue] = {
        "complete": False,
        "skippedChecks": ["lint"],
        "skippedCheckReasons": {
            "lint:partial": f"token=reason-credential {tmp_path}/source.tsx " + "x" * 4000,
        },
    }
    stderr = (
        "password=stderr-credential /outside/private/file.tsx Authorization: Bearer bearer-credential\n" + "y" * 4000
    )
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        seen.append(tuple(argv))
        return ProcessOutput(returncode, _react_coverage_payload(tmp_path, coverage), stderr)

    reports = analyze_external(
        (str(package),),
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
        capabilities=frozenset({"eslint"}),
        include_react_doctor=True,
        react_doctor_full_scan=True,
        eslint=False,
    )

    report = next(item for item in reports if item.name == "react-doctor")
    assert report.completion is Completion.FAILED
    assert not report.diagnostics
    issue = report.issues[0]
    assert issue.kind == "tool-failure"
    assert issue.exit_code == returncode
    assert "analyzed=7, scanned=11, skipped_checks=1" in issue.message
    assert "lint:partial" in issue.message
    assert "stderr:" in issue.message
    assert "password=<redacted>" in issue.message
    assert "<path>" in issue.message
    assert len(issue.message) <= 1024
    for private in (str(tmp_path), "reason-credential", "stderr-credential", "bearer-credential", "/outside/private"):
        assert private not in issue.message
    assert len(seen) == 1
    assert seen[0][seen[0].index("--scope") + 1] == "full"
    assert 60 < float(seen[0][seen[0].index("--max-duration") + 1]) <= 900


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"reactDetected": False}, "did not detect React"),
        ({"baselineDegraded": True}, "baseline degraded"),
    ],
)
def test_react_doctor_fails_closed_on_degraded_coverage(
    tmp_path: Path, extra: dict[str, JsonValue], message: str
) -> None:
    payload = {
        "schemaVersion": 3,
        "version": manifest.eslint_peers()["react-doctor"],
        "ok": True,
        "projects": [{"directory": str(tmp_path), "complete": True}],
        "skippedProjects": [],
        "error": None,
        **extra,
    }

    with pytest.raises(ValueError, match=message):
        parse_react_doctor(json.dumps(payload), root=tmp_path)


def test_react_doctor_protocol_rejects_coerced_schema_types(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": "3",
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [],
            "skippedProjects": [],
            "error": None,
        }
    )

    with pytest.raises(ValidationError, match="schemaVersion"):
        parse_react_doctor(payload, root=tmp_path)


def test_react_doctor_protocol_rejects_boolean_coordinates(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "schemaVersion": 3,
            "version": manifest.eslint_peers()["react-doctor"],
            "ok": True,
            "projects": [
                {
                    "directory": str(tmp_path),
                    "complete": True,
                    "diagnostics": [
                        {
                            "filePath": "app.tsx",
                            "plugin": "react-doctor",
                            "rule": "example",
                            "severity": "error",
                            "message": "example",
                            "line": True,
                            "column": 1,
                        }
                    ],
                }
            ],
            "skippedProjects": [],
            "error": None,
        }
    )

    with pytest.raises(ValidationError, match="line"):
        parse_react_doctor(payload, root=tmp_path)


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
        ("eslint",),
        ".",
        ".",
        doctor_excluded_paths=("demos/**",),
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    selection = external_module._selected_react_doctor_projects(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _selected_react_doctor_projects contract directly with controlled fixture data.
        tmp_path,
        enabled=True,
        has_typescript=True,
        capabilities=frozenset({"eslint"}),
    )

    assert selection == (tmp_path, (included.resolve(),))


@pytest.mark.parametrize("metadata_name", ["package.json", "tsconfig.base.json", "vite.config.ts"])
def test_react_metadata_only_scope_still_runs_doctor(tmp_path: Path, metadata_name: str) -> None:
    package = tmp_path / "package.json"
    package.write_text('{"dependencies":{"react":"19.0.0"}}\n', encoding="utf-8")
    metadata = tmp_path / metadata_name
    if metadata != package:
        metadata.write_text("{}\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append(tuple(argv))
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": True,
                    "baselineDegraded": False,
                    "projects": [
                        {
                            "directory": str(cwd),
                            "complete": True,
                            "skippedChecks": [],
                            "analyzedFileCount": 1,
                            "scannedFileCount": 1,
                        }
                    ],
                    "skippedProjects": [],
                    "error": None,
                }
            ),
            "",
        )

    reports = analyze_external(
        (str(metadata),),
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
        include_react_doctor=True,
    )

    assert "react-doctor" in [item.name for item in reports]
    assert any("react-doctor" in item for command in seen for item in command)


@pytest.mark.parametrize(
    ("changed", "expected_completion"),
    [
        (
            "doctor.config.json\0diagnostic-baseline.json\0apps/web/package.json\0apps/web/package-lock.json\0",
            Completion.COMPLETE,
        ),
        ("apps/web/src/component.tsx\0", Completion.FAILED),
        ("apps/web/src/component.cjs\0", Completion.COMPLETE),
        ("apps/web/src/component.cts\0", Completion.COMPLETE),
    ],
)
def test_react_doctor_only_accepts_empty_degraded_changed_scope_without_project_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    changed: str,
    expected_completion: Completion,
) -> None:
    base = "a" * 40
    monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append(tuple(argv))
        if argv[:2] == ("git", "rev-parse"):
            assert cwd == tmp_path
            if argv[-1] == "HEAD^{commit}":
                return ProcessOutput(128, "", "HEAD unavailable")
            return ProcessOutput(0, f"{base}\n", "")
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            assert cwd == tmp_path
            return ProcessOutput(0, "", "")
        if argv[:2] == ("git", "diff"):
            assert cwd == tmp_path
            return ProcessOutput(0, changed, "")
        assert cwd == project
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "mode": "diff",
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "baselineDegraded": True,
                    "diff": {
                        "baseBranch": base,
                        "changedFileCount": len(
                            tuple(item for item in changed.split("\0") if item.startswith("apps/web/"))
                        ),
                    },
                    "projects": [],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        project,
        projects=(project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert report.completion is expected_completion
    doctor_commands = [command for command in seen if "react-doctor" in command]
    assert len(doctor_commands) == 1
    doctor_command = doctor_commands[0]
    assert doctor_command[doctor_command.index("--base") + 1] == base
    assert (
        "git",
        "diff",
        base,
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
        "--",
    ) in seen
    if expected_completion is Completion.FAILED:
        assert "baseline degraded" in report.issues[0].message


def test_react_doctor_skips_changed_scope_without_selected_project_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = "a" * 40
    head = "b" * 40
    monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append(tuple(argv))
        assert cwd == tmp_path
        if argv[:2] == ("git", "rev-parse"):
            return ProcessOutput(0, f"{head if argv[-1] == 'HEAD^{commit}' else base}\n", "")
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            return ProcessOutput(0, "", "")
        if argv[:2] == ("git", "status"):
            return ProcessOutput(0, "", "")
        if argv[:2] == ("git", "diff"):
            return ProcessOutput(0, "apps/worker/src/job.ts\0apps/worker/test/job.test.ts\0", "")
        pytest.fail(f"React Doctor must not run for an unrelated changed scope: {argv!r}")

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=True,
        file_count=2,
        staged=False,
    )

    assert report.completion is Completion.COMPLETE
    assert report.diagnostics == ()
    assert report.issues == ()
    assert report.file_count == 0
    assert report.invocation_id == "react-doctor:."
    assert seen == [
        ("git", "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"),
        ("git", "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"),
        ("git", "merge-base", "--is-ancestor", base, head),
        (
            "git",
            "diff",
            f"{base}...{head}",
            "--name-only",
            "--no-renames",
            "-z",
            "--",
        ),
        ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--"),
        ("git", "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"),
    ]


def _degraded_react_doctor_output(base: str) -> ProcessOutput:
    return ProcessOutput(
        0,
        json.dumps(
            {
                "schemaVersion": 3,
                "mode": "diff",
                "version": manifest.eslint_peers()["react-doctor"],
                "ok": True,
                "baselineDegraded": True,
                "diff": {"baseBranch": base, "changedFileCount": 1},
                "projects": [],
                "diagnostics": [],
                "skippedProjects": [],
                "error": None,
            }
        ),
        "",
    )


@pytest.mark.parametrize(
    ("timeout", "deadline", "remaining"),
    [
        pytest.param(900, None, 900, id="default-finite-budget"),
        pytest.param(120.5, None, 120.5, id="full-scan-over-sixty-seconds"),
        pytest.param(900, 150, 50, id="stricter-absolute-deadline"),
        pytest.param(0.5, None, 0.5, id="positive-fractional-timeout"),
        pytest.param(10, 100.25, 0.25, id="positive-fractional-deadline"),
        pytest.param(0, None, 0, id="zero-timeout-no-launch"),
        pytest.param(900, 99, 0, id="expired-deadline-no-launch"),
    ],
)
def test_react_doctor_dispatch_uses_remaining_request_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, timeout: float, deadline: float | None, remaining: float
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the production monotonic lookup; test-only clock injection would change the adapter wiring under test.
        time, "monotonic", lambda: 100.0
    )

    def clean_output(_argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        return ProcessOutput(0, "{}", "")

    execute = FakeProcessExecutor(clean_output)
    bounded = external_module._react_doctor_budget_runner(execute)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- verify native duration and subprocess deadline use the same remaining budget.
    request = ProcessRequest(
        ("react-doctor", "--max-duration", "900.0", "--json"),
        tmp_path,
        {"CI": "true"},
        timeout_seconds=timeout,
        deadline=deadline,
        input_bytes=b"prepared input",
        max_input_bytes=32,
        max_stdout_bytes=128,
        max_stderr_bytes=64,
    )
    if remaining == 0:
        with pytest.raises(subprocess.TimeoutExpired):
            bounded.run(request)
        assert not execute.requests
        return

    assert bounded.run(request) == ProcessOutput(0, "{}", "")
    dispatched = execute.requests[0]
    assert float(dispatched.argv[dispatched.argv.index("--max-duration") + 1]) == pytest.approx(remaining)
    assert dispatched.deadline == pytest.approx(100 + remaining)
    assert replace(dispatched, argv=request.argv, deadline=request.deadline) == request
    assert bounded.capabilities == execute.capabilities


def test_react_doctor_fallback_retains_a_stricter_initial_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = [100.0]
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- control the existing monotonic boundary through real retry/fallback wiring without adding a test-only clock API.
        time, "monotonic", lambda: clock[0]
    )

    def clean_output(_argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        return ProcessOutput(0, "{}", "")

    execute = FakeProcessExecutor(clean_output)
    bounded = external_module._react_doctor_budget_runner(execute)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- full fallback must not renew a stricter first dispatch budget.
    bounded.run(
        ProcessRequest(("react-doctor", "--staged", "--max-duration", "900.0"), tmp_path, {}, timeout_seconds=30)
    )
    clock[0] += 5
    bounded.run(ProcessRequest(("react-doctor", "--scope", "full", "--max-duration", "900.0"), tmp_path, {}))
    assert [float(item.argv[-1]) for item in execute.requests] == [30, 25]
    assert [item.deadline for item in execute.requests] == [130, 130]
    clock[0] = 130
    with pytest.raises(subprocess.TimeoutExpired):
        bounded.run(ProcessRequest(("react-doctor", "--scope", "full", "--max-duration", "900.0"), tmp_path, {}))
    assert len(execute.requests) == 2


def test_react_doctor_budget_leaves_git_requests_unchanged(tmp_path: Path) -> None:
    def clean_output(_argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        return ProcessOutput(0, "{}", "")

    execute = FakeProcessExecutor(clean_output)
    bounded = external_module._react_doctor_budget_runner(execute)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- a git path matching the native flag is still a scope preflight, not a doctor scan.
    request = ProcessRequest(("git", "diff", "--", "--max-duration"), tmp_path, {}, deadline=1)
    assert bounded.run(request) == ProcessOutput(0, "{}", "")
    assert execute.requests == [request]
    assert execute.requests[0] is request


@pytest.mark.parametrize(
    ("elapsed", "expired"),
    [pytest.param(20, False, id="retry-shares-remainder"), pytest.param(200, True, id="expired-retry-no-launch")],
)
def test_react_doctor_baseline_retry_shares_the_dispatch_deadline(
    monkeypatch: pytest.MonkeyPatch, elapsed: float, expired: bool
) -> None:
    clock = [100.0]
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- control the existing monotonic boundary through real retry/fallback wiring without adding a test-only clock API.
        time, "monotonic", lambda: clock[0]
    )
    base, head = "a" * 40, "b" * 40
    command = ("react-doctor", "--scope", "changed", "--base", base, "--max-duration", "900.0")
    calls = 0

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal calls
        assert cwd == Path("/repo")
        if argv[0] == "react-doctor":
            calls += 1
            clock[0] += elapsed
            return _degraded_react_doctor_output(base) if calls == 1 else ProcessOutput(0, "{}", "")
        clock[0] += 2
        if argv[:2] == ("git", "rev-parse"):
            return ProcessOutput(0, f"{base if argv[-1].startswith(base) else head}\n", "")
        assert argv[:3] == ("git", "merge-base", "--is-ancestor")
        return ProcessOutput(0, "", "")

    execute = FakeProcessExecutor(runner)
    budget = external_module._react_doctor_budget_runner(execute)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- compose the real retry outside the same doctor dispatch budget.
    bounded = external_module._react_doctor_baseline_retry_runner(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise retry git checks and exact original argv matching.
        command, root=Path("/repo"), runner=budget, explicit_base=base
    )
    request = ProcessRequest(command, Path("/repo"), {}, timeout_seconds=200, deadline=250.5)
    if expired:
        with pytest.raises(subprocess.TimeoutExpired):
            bounded.run(request)
        assert calls == 1
    else:
        assert bounded.run(request) == ProcessOutput(0, "{}", "")
        assert calls == 2
    doctor_requests = [item for item in execute.requests if "--max-duration" in item.argv]
    assert [item.deadline for item in doctor_requests] == [250.5] * calls
    assert float(doctor_requests[0].argv[-1]) == pytest.approx(148.5)
    if not expired:
        assert float(doctor_requests[1].argv[-1]) == pytest.approx(122.5)


def test_react_doctor_retries_one_valid_upstream_baseline_degradation() -> None:
    base = "a" * 40
    head = "b" * 40
    command = ("react-doctor", "--scope", "changed", "--base", base)
    doctor_calls = 0

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal doctor_calls
        assert cwd == Path("/repo")
        if tuple(argv) == command:
            doctor_calls += 1
            return _degraded_react_doctor_output(base) if doctor_calls == 1 else ProcessOutput(0, "{}", "")
        if argv[:2] == ("git", "rev-parse"):
            return ProcessOutput(0, f"{base if argv[-1].startswith(base) else head}\n", "")
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            return ProcessOutput(0, "", "")
        pytest.fail(f"unexpected command: {argv!r}")

    bounded = external_module._react_doctor_baseline_retry_runner(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _react_doctor_baseline_retry_runner contract directly with controlled fixture data.
        command,
        root=Path("/repo"),
        runner=FakeProcessExecutor(runner),
        explicit_base=base,
    )

    assert bounded.run(external_module.process_request(command, cwd=Path("/repo"))) == ProcessOutput(0, "{}", "")
    assert doctor_calls == 2


def test_react_doctor_repeated_baseline_degradation_is_not_retried_twice() -> None:
    base = "a" * 40
    head = "b" * 40
    command = ("react-doctor", "--scope", "changed", "--base", base)
    doctor_calls = 0

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal doctor_calls
        assert cwd == Path("/repo")
        if tuple(argv) == command:
            doctor_calls += 1
            return _degraded_react_doctor_output(base)
        if argv[:2] == ("git", "rev-parse"):
            return ProcessOutput(0, f"{base if argv[-1].startswith(base) else head}\n", "")
        return ProcessOutput(0, "", "")

    bounded = external_module._react_doctor_baseline_retry_runner(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _react_doctor_baseline_retry_runner contract directly with controlled fixture data.
        command,
        root=Path("/repo"),
        runner=FakeProcessExecutor(runner),
        explicit_base=base,
    )

    assert bounded.run(external_module.process_request(command, cwd=Path("/repo"))) == _degraded_react_doctor_output(
        base
    )
    assert doctor_calls == 2


def test_react_doctor_baseline_retry_stops_when_head_moves() -> None:
    base = "a" * 40
    initial_head = "b" * 40
    moved_head = "c" * 40
    command = ("react-doctor", "--scope", "changed", "--base", base)
    head_reads = 0
    doctor_calls = 0

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal doctor_calls, head_reads
        assert cwd == Path("/repo")
        if tuple(argv) == command:
            doctor_calls += 1
            return _degraded_react_doctor_output(base)
        if argv[:2] == ("git", "rev-parse"):
            if argv[-1].startswith(base):
                return ProcessOutput(0, f"{base}\n", "")
            head_reads += 1
            return ProcessOutput(0, f"{initial_head if head_reads == 1 else moved_head}\n", "")
        pytest.fail(f"unexpected command: {argv!r}")

    bounded = external_module._react_doctor_baseline_retry_runner(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _react_doctor_baseline_retry_runner contract directly with controlled fixture data.
        command,
        root=Path("/repo"),
        runner=FakeProcessExecutor(runner),
        explicit_base=base,
    )

    assert bounded.run(external_module.process_request(command, cwd=Path("/repo"))) == _degraded_react_doctor_output(
        base
    )
    assert doctor_calls == 1


@pytest.mark.parametrize(
    ("status", "changed"),
    [
        ("?? apps/web/untracked.tsx\0", "apps/worker/src/job.ts\0"),
        ("", "apps/web/deleted.tsx\0"),
        ("", "apps/web/package.json\0apps/worker/package.json\0"),
    ],
)
def test_react_doctor_disjoint_preflight_fails_closed_for_dirty_deleted_or_renamed_project_inputs(
    tmp_path: Path,
    status: str,
    changed: str,
) -> None:
    base = "a" * 40
    head = "b" * 40
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append(tuple(argv))
        assert cwd == tmp_path
        if argv[:2] == ("git", "rev-parse"):
            return ProcessOutput(0, f"{head if argv[-1] == 'HEAD^{commit}' else base}\n", "")
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            return ProcessOutput(0, "", "")
        if argv[:2] == ("git", "status"):
            return ProcessOutput(0, status, "")
        if argv[:2] == ("git", "diff"):
            assert "--no-renames" in argv
            assert not any(item.startswith("--diff-filter") for item in argv)
            return ProcessOutput(0, changed, "")
        pytest.fail(f"unexpected command: {argv!r}")

    assert not external_module._react_doctor_changed_scope_is_disjoint(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _react_doctor_changed_scope_is_disjoint contract directly with controlled fixture data.
        (project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        scope_root=tmp_path,
        reported_base=base,
    )
    if status:
        assert next(index for index, argv in enumerate(seen) if argv[:2] == ("git", "diff")) < next(
            index for index, argv in enumerate(seen) if argv[:2] == ("git", "status")
        )


@pytest.mark.parametrize(
    "changed",
    [
        "apps/web/package.json\0",
        "package.json\0",
        "tsconfig.base.json\0",
        "apps/tsconfig.base.json\0",
        "eslint.config.ts\0",
    ],
)
def test_react_doctor_changed_scope_runs_for_project_or_ancestor_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    changed: str,
) -> None:
    base = "a" * 40
    head = "b" * 40
    monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    source = project / "component.tsx"
    source.write_text("export const Component = () => <button />;\n", encoding="utf-8")
    analyzer_seen = False

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal analyzer_seen
        if argv[:2] == ("git", "rev-parse"):
            return ProcessOutput(0, f"{head if argv[-1] == 'HEAD^{commit}' else base}\n", "")
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            return ProcessOutput(0, "", "")
        if argv[:2] == ("git", "status"):
            return ProcessOutput(0, "", "")
        if argv[:2] == ("git", "diff"):
            assert "--no-renames" in argv
            assert not any(item.startswith("--diff-filter") for item in argv)
            return ProcessOutput(0, changed, "")
        analyzer_seen = True
        assert cwd == tmp_path
        return ProcessOutput(
            1,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": True,
                    "baselineDegraded": False,
                    "projects": [
                        {
                            "directory": str(project),
                            "complete": True,
                            "skippedChecks": [],
                            "analyzedFileCount": 1,
                            "scannedFileCount": 1,
                            "diagnostics": [
                                {
                                    "filePath": str(source),
                                    "plugin": "react-doctor",
                                    "rule": "button-has-type",
                                    "severity": "error",
                                    "message": "Button needs an explicit type.",
                                    "line": 1,
                                    "column": 32,
                                }
                            ],
                        }
                    ],
                    "skippedProjects": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert analyzer_seen
    assert report.completion is Completion.COMPLETE
    assert tuple(item.location.path for item in report.diagnostics) == ("apps/web/component.tsx",)


def test_react_doctor_disjoint_preflight_checks_every_selected_project(tmp_path: Path) -> None:
    base = "a" * 40
    head = "b" * 40
    web = tmp_path / "apps" / "web"
    admin = tmp_path / "apps" / "admin"
    web.mkdir(parents=True)
    admin.mkdir(parents=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[-1:] == (f"{base}^{{commit}}",):
            return ProcessOutput(0, f"{base}\n", "")
        if argv[-1:] == ("HEAD^{commit}",):
            return ProcessOutput(0, f"{head}\n", "")
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            return ProcessOutput(0, "", "")
        if argv[:2] == ("git", "status"):
            return ProcessOutput(0, "", "")
        if argv[:2] == ("git", "diff"):
            return ProcessOutput(0, "apps/admin/src/page.tsx\0", "")
        pytest.fail(f"unexpected command: {argv!r}")

    assert not external_module._react_doctor_changed_scope_is_disjoint(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _react_doctor_changed_scope_is_disjoint contract directly with controlled fixture data.
        (web, admin),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        scope_root=tmp_path,
        reported_base=base,
    )


def test_react_doctor_disjoint_preflight_fails_closed_when_head_moves(tmp_path: Path) -> None:
    base = "a" * 40
    initial_head = "b" * 40
    moved_head = "c" * 40
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    head_reads = 0

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal head_reads
        assert cwd == tmp_path
        if argv[-1:] == (f"{base}^{{commit}}",):
            return ProcessOutput(0, f"{base}\n", "")
        if argv[-1:] == ("HEAD^{commit}",):
            head_reads += 1
            resolved = initial_head if head_reads == 1 else moved_head
            return ProcessOutput(0, f"{resolved}\n", "")
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            return ProcessOutput(0, "", "")
        if argv[:2] == ("git", "diff"):
            return ProcessOutput(0, "apps/worker/src/job.ts\0", "")
        if argv[:2] == ("git", "status"):
            return ProcessOutput(0, "", "")
        pytest.fail(f"unexpected command: {argv!r}")

    assert not external_module._react_doctor_changed_scope_is_disjoint(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _react_doctor_changed_scope_is_disjoint contract directly with controlled fixture data.
        (project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        scope_root=tmp_path,
        reported_base=base,
    )
    assert head_reads == 2


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            (
                "a" * 40,
                ".sarj-standards.toml\0diagnostic-baseline.json\0apps/landing-page/package.json\0apps/landing-page/package-lock.json\0",
                2,
                0,
                0,
                Completion.COMPLETE,
            ),
            id="repo-and-react-root-config-only-scope",
        ),
        pytest.param(
            ("a" * 40, "apps/landing-page/src/page.tsx\0", 1, 0, 0, Completion.FAILED),
            id="react-source-remains-blocking",
        ),
        pytest.param(
            (
                "a" * 40,
                ".sarj-standards.toml\0diagnostic-baseline.json\0apps/landing-page/package.json\0",
                2,
                0,
                0,
                Completion.FAILED,
            ),
            id="react-root-changed-file-count-mismatch",
        ),
        pytest.param(
            ("../unsafe", ".sarj-standards.toml\0", 1, 0, 0, Completion.FAILED),
            id="unsafe-reported-base",
        ),
        pytest.param(
            ("main", ".sarj-standards.toml\0", 1, 128, 0, Completion.FAILED),
            id="unresolved-reported-base",
        ),
        pytest.param(
            ("main", ".sarj-standards.toml\0", 1, 0, 1, Completion.FAILED),
            id="no-shared-ancestor-reported-base",
        ),
    ],
)
def test_react_doctor_validates_reported_degraded_changed_scope_before_allowing_empty_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[str, str, int, int, int, Completion],
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts external tool routing
        external_module, "change_scope_base", lambda: ""
    )
    reported_base, changed, reported_count, resolve_status, ancestor_status, expected_completion = case
    resolved_base = "b" * 40
    project = tmp_path / "apps" / "landing-page"
    project.mkdir(parents=True)
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append(tuple(argv))
        if argv[:2] == ("git", "rev-parse"):
            assert cwd == tmp_path
            return ProcessOutput(resolve_status, f"{resolved_base}\n" if resolve_status == 0 else "", "")
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            assert cwd == tmp_path
            return ProcessOutput(ancestor_status, "", "")
        if argv[:2] == ("git", "merge-base"):
            return ProcessOutput(1, "", "No shared ancestor")
        if argv[:2] == ("git", "diff"):
            assert cwd == tmp_path
            return ProcessOutput(0, changed, "")
        assert cwd == project
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "mode": "diff",
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "baselineDegraded": True,
                    "diff": {"baseBranch": reported_base, "changedFileCount": reported_count},
                    "projects": [],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        project,
        projects=(project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=2,
        staged=False,
    )

    assert report.completion is expected_completion
    if expected_completion is Completion.COMPLETE:
        assert report.diagnostics == ()
        assert report.issues == ()
        assert ("git", "diff", resolved_base, "--name-only", "--diff-filter=ACMR", "-z", "--") in seen
    else:
        assert "baseline degraded" in report.issues[0].message


def test_react_doctor_accepts_empty_staged_scope_without_selected_project_source(tmp_path: Path) -> None:
    project = tmp_path / "typescript" / "packages" / "app"
    project.mkdir(parents=True)
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        seen.append(tuple(argv))
        if argv[0] == "git":
            return ProcessOutput(
                0,
                "typescript/eslint.strict.mjs\0typescript/packages/app/package.json\0diagnostic-baseline.json\0",
                "",
            )
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "mode": "staged",
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "projects": [],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=3,
        staged=True,
    )

    assert report.completion is Completion.COMPLETE
    assert report.diagnostics == ()
    assert report.issues == ()
    assert seen[0] == ("git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z", "--")
    assert "--staged" in seen[1]
    assert len(seen) == 2


@pytest.mark.parametrize(
    "staged_path",
    [
        "apps/web/src/component.tsx",
        "apps/web/src/page.astro",
        "apps/web/public/fragment.html",
        "../apps/web/src/unsafe.tsx",
    ],
)
def test_react_doctor_rejects_empty_staged_scope_with_candidate_or_unsafe_path(
    tmp_path: Path,
    staged_path: str,
) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[0] == "git":
            return ProcessOutput(0, f"{staged_path}\0", "")
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "mode": "staged",
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "projects": [],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.FAILED
    assert "no analyzed projects" in report.issues[0].message


def test_react_doctor_empty_staged_scope_fails_closed_when_git_diff_fails(tmp_path: Path) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[0] == "git":
            return ProcessOutput(128, "", "index unavailable")
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "mode": "staged",
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "projects": [],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.FAILED
    assert "no analyzed projects" in report.issues[0].message


def test_react_doctor_empty_degraded_scope_fails_closed_when_git_diff_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SARJ_STANDARDS_BASE", "b" * 40)
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[0] == "git":
            return ProcessOutput(128, "", "invalid base")
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "baselineDegraded": True,
                    "projects": [],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert report.completion is Completion.FAILED
    assert "baseline degraded" in report.issues[0].message


def test_react_doctor_staged_non_detection_falls_back_to_full_and_filters_exact_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = [100.0]
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- control the existing monotonic boundary through real retry/fallback wiring without adding a test-only clock API.
        time, "monotonic", lambda: clock[0]
    )
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    staged_source = project / "staged.tsx"
    staged_source.write_text('export const Image = () => <img src="avatar.png" />;\n', encoding="utf-8")
    unrelated_source = project / "unrelated.tsx"
    unrelated_source.write_text('export const Other = () => <img src="other.png" />;\n', encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def diagnostic(path: Path) -> dict[str, JsonValue]:
        return {
            "filePath": str(path),
            "plugin": "react-doctor",
            "rule": "alt-text",
            "severity": "error",
            "message": "Image elements must have alternative text.",
            "line": 1,
            "column": 28,
        }

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        seen.append(tuple(argv))
        if argv[0] == "git":
            clock[0] += 5
            return ProcessOutput(0, "apps/web/staged.tsx\0", "")
        clock[0] += 20
        is_full = "--scope" in argv and argv[argv.index("--scope") + 1] == "full"
        diagnostics = [diagnostic(staged_source), diagnostic(unrelated_source)] if is_full else []
        return ProcessOutput(
            1 if diagnostics else 0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": is_full,
                    "projects": [
                        {
                            "directory": str(project),
                            "complete": True,
                            "skippedChecks": [],
                            "analyzedFileCount": 2 if is_full else 1,
                            "scannedFileCount": 2 if is_full else 1,
                            "diagnostics": diagnostics,
                        }
                    ],
                    "diagnostics": diagnostics,
                    "error": None,
                }
            ),
            "",
        )

    execute = FakeProcessExecutor(runner)
    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=execute,
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.COMPLETE
    assert tuple(item.location.path for item in report.diagnostics) == ("apps/web/staged.tsx",)
    assert report.diagnostics[0].code == "react-doctor/alt-text"
    assert seen[0] == ("git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z", "--")
    assert "--staged" in seen[1]
    assert seen[2] == seen[0]
    scope_index = seen[3].index("--scope")
    assert seen[3][scope_index + 1] == "full"
    duration_index = seen[3].index("--max-duration")
    assert float(seen[1][seen[1].index("--max-duration") + 1]) == pytest.approx(895)
    assert float(seen[3][duration_index + 1]) == pytest.approx(870)
    assert [item.deadline for item in execute.requests if "--max-duration" in item.argv] == [1000, 1000]


def test_react_doctor_full_scan_still_rejects_non_detection(tmp_path: Path) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)

    def runner(
        argv: Sequence[str],  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        *,
        cwd: Path,
    ) -> ProcessOutput:
        assert cwd == tmp_path
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": False,
                    "projects": [{"directory": str(project), "complete": True}],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=1,
        staged=False,
        full_scan=True,
    )

    assert report.completion is Completion.FAILED
    assert "did not detect React" in report.issues[0].message


def test_react_doctor_staged_fallback_rejects_malformed_scoped_coverage(tmp_path: Path) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        seen.append(tuple(argv))
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": False,
                    "projects": [{"directory": str(project), "complete": False}],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.FAILED
    assert "did not complete" in report.issues[0].message
    assert len(seen) == 2


@pytest.mark.parametrize(
    ("failure", "expected_message"),
    [
        ("git", "index unavailable"),
        ("full-exit", "full scan crashed"),
        ("full-empty", "empty structured output"),
    ],
)
def test_react_doctor_staged_fallback_failures_remain_blocking(
    tmp_path: Path,
    failure: str,
    expected_message: str,
) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[0] == "git":
            if failure == "git":
                return ProcessOutput(128, "", "index unavailable")
            return ProcessOutput(0, "apps/web/staged.tsx\0", "")
        if "--scope" in argv:
            if failure == "full-exit":
                return ProcessOutput(2, "", "full scan crashed")
            return ProcessOutput(0, "", "")
        return ProcessOutput(
            0,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": False,
                    "projects": [
                        {
                            "directory": str(project),
                            "complete": True,
                            "skippedChecks": [],
                            "analyzedFileCount": 1,
                            "scannedFileCount": 1,
                            "diagnostics": [],
                        }
                    ],
                    "diagnostics": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.FAILED
    assert expected_message in report.issues[0].message


def test_react_doctor_uses_native_staged_scope_for_precommit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("SARJ_STANDARDS_BASE", raising=False)
    (tmp_path / "package.json").write_text(
        '{"packageManager":"npm@11.5.2","dependencies":{"react":"19.0.0"}}\n',
        encoding="utf-8",
    )
    source = tmp_path / "component.tsx"
    source.write_text("export const Component = () => <button />;\n", encoding="utf-8")
    untouched = tmp_path / "untouched.tsx"
    untouched.write_text("export const Untouched = () => <button />;\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []
    git_seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        if argv[0] == "git":
            git_seen.append(tuple(argv))
            return ProcessOutput(0, "component.tsx\0", "")
        seen.append(tuple(argv))
        return ProcessOutput(
            1,
            json.dumps(
                {
                    "schemaVersion": 3,
                    "version": manifest.eslint_peers()["react-doctor"],
                    "ok": True,
                    "reactDetected": True,
                    "baselineDegraded": False,
                    "projects": [
                        {
                            "directory": str(tmp_path),
                            "complete": True,
                            "skippedChecks": [],
                            "analyzedFileCount": 2,
                            "scannedFileCount": 2,
                            "diagnostics": [
                                {
                                    "filePath": str(source),
                                    "plugin": "react-doctor",
                                    "rule": "button-has-type",
                                    "severity": "error",
                                    "message": "Button needs an explicit type.",
                                    "line": 1,
                                    "column": 32,
                                },
                                {
                                    "filePath": str(untouched),
                                    "plugin": "react-doctor",
                                    "rule": "button-has-type",
                                    "severity": "warning",
                                    "message": "Button needs an explicit type.",
                                    "line": 1,
                                    "column": 32,
                                },
                            ],
                        }
                    ],
                    "skippedProjects": [],
                    "error": None,
                }
            ),
            "",
        )

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.COMPLETE
    assert tuple(item.location.path for item in report.diagnostics) == ("component.tsx",)
    assert report.diagnostics[0].severity is Severity.ERROR
    assert report_from_tools(tmp_path, (report,)).exit_code == 1
    assert "--staged" in seen[0]
    assert "--scope" not in seen[0]
    blocking_index = seen[0].index("--blocking")
    assert seen[0][blocking_index + 1] == "error"
    assert "--no-warnings" in seen[0]

    changed_report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert changed_report.completion is Completion.COMPLETE
    scope_index = seen[1].index("--scope")
    assert seen[1][scope_index + 1] == "changed"
    assert "--base" not in seen[1]

    event_base = "f" * 40
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"base": {"sha": event_base}}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    github_report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert tuple(item.location.path for item in github_report.diagnostics) == ("component.tsx",)
    github_base_index = seen[2].index("--base")
    assert seen[2][github_base_index + 1] == event_base

    monkeypatch.setenv("SARJ_REACT_DOCTOR_BASE", "0123456789abcdef")
    ci_report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _invoke_react_doctor contract directly with controlled fixture data.
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=FakeProcessExecutor(runner),
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert ci_report.completion is Completion.COMPLETE
    assert tuple(item.location.path for item in ci_report.diagnostics) == ("component.tsx",)

    base_index = seen[3].index("--base")
    assert seen[3][base_index + 1] == "0123456789abcdef"
    assert ("git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z", "--") in git_seen
    assert ("git", "rev-parse", "--verify", "--end-of-options", f"{event_base}^{{commit}}") in git_seen
    assert (
        "git",
        "rev-parse",
        "--verify",
        "--end-of-options",
        "0123456789abcdef^{commit}",
    ) in git_seen
    assert git_seen.count(("git", "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}")) >= 2
    assert "--no-cache" in seen[0]
    duration_index = seen[0].index("--max-duration")
    assert 60 < float(seen[0][duration_index + 1]) <= 900


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


@pytest.mark.parametrize("memory_gib", [8, 16])
def test_only_eslint_receives_the_bounded_node_heap_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    memory_gib: int,
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test controls the host budget without allocating memory
        external_module, "_physical_memory_bytes", lambda: memory_gib * 1024**3
    )
    limit = tmp_path / "memory.max"
    limit.write_text("max\n")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- this process-isolation test covers an unconstrained host
        external_module, "_cgroup_memory_limit_files", lambda: [limit]
    )
    monkeypatch.setenv("NODE_OPTIONS", "--require=/tmp/untrusted-preload.cjs")
    command = (
        sys.executable,
        "-c",
        "import os; print(os.environ.get('NODE_OPTIONS', 'missing'))",
    )

    generic = external_module.run_process(command, cwd=tmp_path)
    eslint = external_module._run_eslint_process(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _run_eslint_process contract directly with controlled fixture data.
        command,
        cwd=tmp_path,
    )

    assert generic.stdout.strip() == "missing"
    assert eslint.stdout.strip() == f"--max-old-space-size={8192 if memory_gib >= 12 else 4096}"


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
    ("argv", "expected"),
    [
        pytest.param(
            ("npm", "exec", "--offline", "--", "eslint", "--", "app.ts"),
            (
                "npm",
                "exec",
                "--offline",
                "--",
                "eslint",
                "--format",
                str(external_module._ESLINT_FORMATTER),  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _ESLINT_FORMATTER contract directly with controlled fixture data.
                "--no-warn-ignored",
                "--no-cache",
                "--",
                "app.ts",
            ),
            id="npm-package-manager-delimiter",
        ),
        pytest.param(
            ("pnpm", "exec", "eslint", "--", "app.ts"),
            (
                "pnpm",
                "exec",
                "eslint",
                "--format",
                str(external_module._ESLINT_FORMATTER),  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _ESLINT_FORMATTER contract directly with controlled fixture data.
                "--no-warn-ignored",
                "--no-cache",
                "--",
                "app.ts",
            ),
            id="pnpm-local-exec",
        ),
    ],
)
def test_eslint_json_flags_follow_the_executable_not_the_package_manager_delimiter(
    argv: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    assert external_module._eslint_json_argv(argv) == expected  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _eslint_json_argv contract directly with controlled fixture data.
    assert external_module._argv_file_count(argv) == 1  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _argv_file_count contract directly with controlled fixture data.


def test_eslint_fatal_message_is_an_execution_failure(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filePath": str(source),
                "messages": [
                    {
                        "fatal": True,
                        "severity": 2,
                        "message": "parser could not load",
                        "line": 1,
                        "column": 1,
                    }
                ],
            }
        ]
    )

    def fatal(
        argv: Sequence[str],  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        return ProcessOutput(1, payload, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.TRUSTED, runner=FakeProcessExecutor(fatal))

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues
    assert not reports[0].diagnostics


def test_missing_local_eslint_fails_before_package_manager_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")

    def forbidden(
        argv: Sequence[str],  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        pytest.fail("the package manager ran without a local ESLint installation")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts external tool routing
        external_module.DEFAULT_EXECUTOR, "run", FakeProcessExecutor(forbidden).run
    )

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.TRUSTED)

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].kind == "missing-dependency"
    assert "node_modules/.bin/eslint is missing" in reports[0].issues[0].message
    assert "code-standards setup" in reports[0].issues[0].message


def test_hoisted_eslint_above_analysis_root_is_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "workspace" / "app"
    root.mkdir(parents=True)
    source = root / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    (root / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (root / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (root / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")
    binary = tmp_path / "node_modules" / ".bin" / "eslint"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    called: list[tuple[str, ...]] = []

    def successful(request: ProcessRequest) -> ProcessOutput:
        argv, cwd = request.argv, request.cwd
        assert request.deadline is not None
        assert 0 < request.deadline - time.monotonic() <= 300
        called.append(tuple(argv))
        return ProcessOutput(0, _eslint_clean_payload(argv, cwd), "")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts external tool routing
        external_module.DEFAULT_EXECUTOR, "run", successful
    )

    reports = analyze_external([str(source)], root=root, trust=TrustMode.TRUSTED)

    assert called
    assert Path(called[0][0]).name == "node"
    assert Path(called[0][1]).name == "eslint-selected-rules.mts"
    assert json.loads(called[0][2])["full"] is True
    assert reports[0].completion is Completion.COMPLETE


def test_eslint_empty_output_preserves_package_manager_stderr(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")

    def missing(
        argv: Sequence[str],  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        return ProcessOutput(1, "", "ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL Command 'eslint' not found")

    reports = analyze_external(
        [str(source)], root=tmp_path, trust=TrustMode.TRUSTED, runner=FakeProcessExecutor(missing)
    )

    assert len(reports) == 1
    issue = reports[0].issues[0]
    assert issue.kind == "tool-failure"
    assert issue.exit_code == 1
    assert issue.message == "ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL Command 'eslint' not found"
    assert "JSONDecodeError" not in issue.message


def test_eslint_malformed_output_preserves_stderr_without_json_exception_name(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")

    def broken(
        argv: Sequence[str],  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        return ProcessOutput(1, "not-json", "eslint could not load its local configuration")

    reports = analyze_external(
        [str(source)], root=tmp_path, trust=TrustMode.TRUSTED, runner=FakeProcessExecutor(broken)
    )

    issue = reports[0].issues[0]
    assert issue.kind == "protocol-mismatch"
    assert issue.message == "eslint could not load its local configuration"
    assert "JSONDecodeError" not in issue.message


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


def test_eslint_without_end_location_keeps_a_truthful_point(tmp_path: Path) -> None:
    source = tmp_path / "example.ts"
    source.write_text("const value = 1;\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filePath": str(source),
                "messages": [
                    {
                        "ruleId": "prefer-const",
                        "severity": 2,
                        "message": "use const",
                        "line": 1,
                        "column": 1,
                    }
                ],
            }
        ]
    )

    finding = parse_eslint(payload, root=tmp_path)[0]

    assert finding.location.position is not None
    assert finding.location.region is None
    assert finding.severity is Severity.ERROR


def test_eslint_line_zero_keeps_a_truthful_path_level_diagnostic(tmp_path: Path) -> None:
    source = tmp_path / "example.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filePath": str(source),
                "messages": [
                    {
                        "ruleId": "configuration-rule",
                        "severity": 2,
                        "message": "project-level diagnostic",
                        "line": 0,
                        "column": 1,
                        "endLine": 0,
                        "endColumn": 1,
                    }
                ],
            }
        ]
    )

    finding = parse_eslint(payload, root=tmp_path)[0]

    assert finding.location.path == "example.ts"
    assert finding.location.position is None
    assert finding.location.region is None


def test_eslint_ignored_file_warning_without_position_is_path_level(tmp_path: Path) -> None:
    source = tmp_path / "next-env.d.ts"
    source.write_text("// generated\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filePath": str(source),
                "messages": [
                    {
                        "ruleId": None,
                        "fatal": False,
                        "severity": 1,
                        "message": "File ignored because of a matching ignore pattern.",
                    }
                ],
            }
        ]
    )

    finding = parse_eslint(payload, root=tmp_path)[0]

    assert finding.code == "eslint/file"
    assert finding.location.path == "next-env.d.ts"
    assert finding.location.position is None


def test_safe_mode_never_executes_repository_eslint_config(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("throw new Error('must not execute');\n", encoding="utf-8")
    source = tmp_path / "example.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")

    def forbidden(
        argv: Sequence[str],  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        pytest.fail("safe mode executed repository code")

    reports = analyze_external(
        [str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=FakeProcessExecutor(forbidden)
    )

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].kind == "trust-required"


def test_string_safe_mode_never_executes_repository_eslint_config(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("throw new Error('must not execute');\n", encoding="utf-8")
    source = tmp_path / "example.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")

    def forbidden(
        argv: Sequence[str],  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessOutput:
        pytest.fail("string safe mode executed repository code")

    reports = analyze_external([str(source)], root=tmp_path, trust="safe", runner=FakeProcessExecutor(forbidden))

    assert reports[0].issues[0].kind == "trust-required"


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


@pytest.mark.parametrize(("severity", "message"), [(99, "bad severity"), (True, "bad")], ids=("unknown", "boolean"))
def test_eslint_parser_rejects_invalid_severity(tmp_path: Path, severity: int | bool, message: str) -> None:
    source = tmp_path / "example.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filePath": str(source),
                "messages": [{"severity": severity, "message": message, "line": 1, "column": 1}],
            }
        ]
    )

    with pytest.raises(ValueError, match="severity"):
        parse_eslint(payload, root=tmp_path)


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


def test_eslint_rejects_boolean_coordinates(tmp_path: Path) -> None:
    source = tmp_path / "example.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    payload = json.dumps(
        [
            {
                "filePath": str(source),
                "messages": [{"severity": 2, "message": "bad", "line": True, "column": True}],
            }
        ]
    )

    with pytest.raises(TypeError, match="invalid boolean coordinates"):
        parse_eslint(payload, root=tmp_path)


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
def test_eslint_heap_respects_host_and_process_container_limits(
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
    assert external_module._eslint_node_options() == f"--max-old-space-size={expected}"  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- exercise the internal _eslint_node_options contract directly with controlled fixture data.


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


@pytest.mark.parametrize(
    ("payload_overrides", "changed_paths", "git_returncode", "expected_completion"),
    [
        pytest.param(
            {"diff": {"baseBranch": "a" * 40, "changedFileCount": 3, "isCurrentChanges": False}},
            ".sarj-standards.toml\0apps/web/package.json\0apps/web/pnpm-lock.yaml\0apps/web/pnpm-workspace.yaml\0",
            0,
            Completion.COMPLETE,
            id="native-baseline-envelope-with-only-project-metadata",
        ),
        pytest.param({}, "apps/web/package.json\0", 0, Completion.COMPLETE, id="single-project-metadata-change"),
        pytest.param(
            {},
            "apps/web/package.json\0tools/helper.ts\0",
            0,
            Completion.COMPLETE,
            id="unrelated-source-does-not-belong-to-the-selected-project",
        ),
        pytest.param({}, "apps/web/src/page.tsx\0", 0, Completion.FAILED, id="eligible-react-source-remains-required"),
        pytest.param({}, "apps/web/src/types.d.ts\0", 0, Completion.FAILED, id="declaration-source-remains-required"),
        pytest.param(
            {"diff": {"baseBranch": "a" * 40, "changedFileCount": 2, "isCurrentChanges": False}},
            "apps/web/package.json\0",
            0,
            Completion.FAILED,
            id="reported-change-count-must-match-git",
        ),
        pytest.param(
            {"diff": {"baseBranch": "c" * 40, "changedFileCount": 1, "isCurrentChanges": False}},
            "apps/web/package.json\0",
            0,
            Completion.FAILED,
            id="reported-base-must-match-selected-base",
        ),
        pytest.param(
            {"diff": {"baseBranch": "a" * 40, "changedFileCount": 1}},
            "apps/web/package.json\0",
            0,
            Completion.FAILED,
            id="missing-scope-kind-metadata",
        ),
        pytest.param(
            {"diff": {"baseBranch": "a" * 40, "changedFileCount": 1, "isCurrentChanges": True}},
            "apps/web/package.json\0",
            0,
            Completion.COMPLETE,
            id="native-working-tree-metadata-scope-is-independently-proved",
        ),
        pytest.param({"diff": None}, "apps/web/package.json\0", 0, Completion.FAILED, id="missing-diff-proof"),
        pytest.param({}, "apps/web/package.json\0", 128, Completion.FAILED, id="git-proof-failure"),
        pytest.param(
            {},
            "../package.json\0apps/web/package.json\0",
            0,
            Completion.FAILED,
            id="unsafe-git-path-cannot-establish-source-free-scope",
        ),
        pytest.param(
            {"skippedProjects": [{"directory": "apps/web"}]},
            "apps/web/package.json\0",
            0,
            Completion.FAILED,
            id="explicit-skipped-project-remains-an-error",
        ),
    ],
)
def test_react_doctor_validates_empty_baseline_changed_scope_against_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload_overrides: dict[str, JsonValue],
    changed_paths: str,
    git_returncode: int,
    expected_completion: Completion,
) -> None:
    base = "a" * 40
    head = "b" * 40
    monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    package = project / "package.json"
    package.write_text('{"dependencies":{"react":"19.0.0"}}\n', encoding="utf-8")
    adopted = manifest.Manifest("8.79.0", ("eslint",), python_dest="python", typescript_dest="apps/web")
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    native_calls: list[tuple[str, ...]] = []
    # The pinned native serializer omits reactDetected and baselineDegraded
    # when a committed metadata-only diff has no eligible React source.
    payload: dict[str, JsonValue] = {
        "schemaVersion": 3,
        "sourceRevision": head,
        "mode": "baseline",
        "baseline": {
            "baseRef": base,
            "source": "base",
            "matchedCount": 0,
            "newCount": 0,
            "fixedCount": 0,
            "baseTotalCount": 0,
        },
        "version": manifest.eslint_peers()["react-doctor"],
        "ok": True,
        "directory": str(project),
        "diff": {"baseBranch": base, "changedFileCount": 1, "isCurrentChanges": False},
        "projects": [],
        "diagnostics": [],
        "summary": {
            "errorCount": 0,
            "warningCount": 0,
            "affectedFileCount": 0,
            "totalDiagnosticCount": 0,
            "score": None,
            "scoreLabel": None,
        },
        "elapsedMilliseconds": 1,
        "error": None,
    }
    payload.update(payload_overrides)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        match argv[:2]:
            case ("git", "rev-parse"):
                assert cwd == tmp_path
                reference = argv[-1].removesuffix("^{commit}")
                return ProcessOutput(git_returncode, f"{head if reference == 'HEAD' else reference}\n", "")
            case ("git", "merge-base"):
                assert cwd == tmp_path
                return ProcessOutput(git_returncode, "", "")
            case ("git", "diff"):
                assert cwd == tmp_path
                return ProcessOutput(git_returncode, changed_paths, "")
            case ("git", "status"):
                assert cwd == tmp_path
                return ProcessOutput(git_returncode, "", "")
            case _:
                assert cwd == project
                assert any("react-doctor" in item for item in argv)
                native_calls.append(tuple(argv))
                return ProcessOutput(0, json.dumps(payload), "")

    reports = analyze_external(
        (str(package),),
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
        capabilities=frozenset({"react-doctor"}),
        include_react_doctor=True,
    )

    assert len(native_calls) == 1
    assert [item.name for item in reports] == ["react-doctor"]
    report = reports[0]
    assert report.completion is expected_completion
    assert report.diagnostics == ()
    if expected_completion is Completion.COMPLETE:
        assert report.issues == ()
    else:
        assert len(report.issues) == 1
        assert report.issues[0].kind == "tool-failure"


@pytest.mark.parametrize(
    "common_base_output",
    [
        pytest.param(ProcessOutput(1, "", "No shared ancestor"), id="unrelated-histories"),
        pytest.param(ProcessOutput(128, "", "Git failed"), id="git-error"),
        pytest.param(ProcessOutput(0, "not-a-commit\n", ""), id="malformed-object"),
        pytest.param(ProcessOutput(0, "c" * 40 + "\n" + "d" * 40 + "\n", ""), id="multiple-objects"),
    ],
)
def test_react_doctor_rejects_invalid_common_ancestor_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, common_base_output: ProcessOutput
) -> None:
    base = "a" * 40
    monkeypatch.setenv("SARJ_STANDARDS_BASE", base)
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    package = project / "package.json"
    package.write_text('{"dependencies":{"react":"19.0.0"}}\n', encoding="utf-8")
    (tmp_path / manifest.MANIFEST_NAME).write_text(
        manifest.Manifest("8.79.0", ("eslint",), python_dest="python", typescript_dest="apps/web").render(),
        encoding="utf-8",
    )
    seen: list[tuple[str, ...]] = []
    payload: dict[str, JsonValue] = {
        "schemaVersion": 3,
        "version": manifest.eslint_peers()["react-doctor"],
        "ok": True,
        "diff": {"baseBranch": base, "changedFileCount": 1, "isCurrentChanges": False},
        "projects": [],
        "diagnostics": [],
        "error": None,
    }

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        seen.append(tuple(argv))
        match argv[:2]:
            case ("git", "rev-parse"):
                return ProcessOutput(0, ("b" * 40 if argv[-1] == "HEAD^{commit}" else base) + "\n", "")
            case ("git", "merge-base"):
                return ProcessOutput(1, "", "Not an ancestor") if "--is-ancestor" in argv else common_base_output
            case ("git", "diff"):
                return ProcessOutput(0, "apps/web/package.json\0", "")
            case ("git", "status"):
                return ProcessOutput(0, "", "")
            case _:
                assert cwd == project
                return ProcessOutput(0, json.dumps(payload), "")

    reports = analyze_external(
        (str(package),),
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=FakeProcessExecutor(runner),
        capabilities=frozenset({"react-doctor"}),
        include_react_doctor=True,
    )

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert "no analyzed projects" in reports[0].issues[0].message
    assert ("git", "merge-base", base, "HEAD") in seen
