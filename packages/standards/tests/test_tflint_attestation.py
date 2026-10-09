from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting import devops_source
from sarj_standards.libs.linting.devops_source import analyze_sources
from sarj_standards.libs.linting.devops_tools import TOOLS, NativeTool
from sarj_standards.libs.linting.external import ProcessOutput, run_process


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _source(*, root: Path, project: str) -> str:
    relative = f"{project}/main.tf"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('output "example" { value = "public" }\n')
    return relative


def test_tflint_reuses_attestation_per_project_without_cross_invocation_cache(*, tmp_path: Path) -> None:
    paths = tuple(_source(root=tmp_path, project=project) for project in ("one", "two"))
    calls: list[tuple[Path, str, bool]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        calls.append(
            (cwd, "version" if "--version" in argv else "analysis", tuple(argv[1:]) != TOOLS["tflint"].version_args)
        )
        if "--version" in argv:
            return ProcessOutput(0, "TFLint version 0.63.1\n+ ruleset.google (0.39.0)", "")
        return ProcessOutput(0, '{"errors":[],"issues":[]}', "")

    for _ in range(2):
        calls.clear()
        reports = analyze_sources(
            root=tmp_path, paths=paths, selected=frozenset({"tflint"}), trust_repository_code=True, runner=runner
        )
        assert all(report.completion is Completion.COMPLETE for report in reports)
        assert all(report.version == "0.63.1" for report in reports)
        assert calls == [
            (tmp_path / "one", "version", False),
            (tmp_path / "one", "version", True),
            (tmp_path / "one", "analysis", True),
            (tmp_path / "two", "version", False),
            (tmp_path / "two", "version", True),
            (tmp_path / "two", "analysis", True),
        ]


@pytest.mark.parametrize(
    ("version", "version_status", "plugin", "plugin_status", "payload", "status"),
    [
        pytest.param("0.63.0", 0, "0.39.0", 0, '{"errors":[],"issues":[]}', 0, id="wrong-binary-version"),
        pytest.param("0.63.1", 1, "0.39.0", 0, '{"errors":[],"issues":[]}', 0, id="failed-attestation"),
        pytest.param("0.63.1", 0, "0.38.0", 0, '{"errors":[],"issues":[]}', 0, id="wrong-plugin-version"),
        pytest.param("0.63.1", 0, "", 0, '{"errors":[],"issues":[]}', 0, id="missing-plugin"),
        pytest.param("0.63.1", 0, "0.39.0", 1, '{"errors":[],"issues":[]}', 0, id="failed-plugin-version"),
        pytest.param("0.63.1", 0, "0.39.0", 0, "not json", 0, id="malformed-json"),
        pytest.param("0.63.1", 0, "0.39.0", 0, "{}", 0, id="missing-fields"),
        pytest.param(
            "0.63.1", 0, "0.39.0", 0, '{"errors":[{"message":"failure"}],"issues":[]}', 0, id="reported-errors"
        ),
        pytest.param("0.63.1", 0, "0.39.0", 0, '{"errors":[],"issues":[]}', 2, id="finding-exit-without-findings"),
        pytest.param("0.63.1", 0, "0.39.0", 0, '{"errors":[],"issues":[]}', 1, id="unexpected-exit"),
    ],
)
def test_tflint_reuse_preserves_fail_closed_protocols(
    *, tmp_path: Path, version: str, version_status: int, plugin: str, plugin_status: int, payload: str, status: int
) -> None:
    path = _source(root=tmp_path, project="project")

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path / "project"
        if "--version" in argv:
            if tuple(argv[1:]) == TOOLS["tflint"].version_args:
                return ProcessOutput(version_status, f"TFLint version {version}", "")
            return ProcessOutput(plugin_status, f"TFLint version {version}\n+ ruleset.google ({plugin})", "")
        return ProcessOutput(status, payload, "")

    reports = analyze_sources(
        root=tmp_path, paths=(path,), selected=frozenset({"tflint"}), trust_repository_code=True, runner=runner
    )
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues
    assert not reports[0].diagnostics


@pytest.mark.parametrize("status", [0, 2])
def test_tflint_reuse_retains_native_diagnostic_locations(*, tmp_path: Path, status: int) -> None:
    path = _source(root=tmp_path, project="project")
    payload = json.dumps(
        {
            "errors": [],
            "issues": [
                {
                    "rule": {"name": "example", "severity": "warning"},
                    "message": "example",
                    "range": {"filename": "main.tf", "start": {"line": 1, "column": 1}},
                }
            ],
        }
    )

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path / "project"
        if "--version" in argv:
            return ProcessOutput(0, "TFLint version 0.63.1\n+ ruleset.google (0.39.0)", "")
        return ProcessOutput(status, payload, "")

    reports = analyze_sources(
        root=tmp_path, paths=(path,), selected=frozenset({"tflint"}), trust_repository_code=True, runner=runner
    )
    assert reports[0].completion is Completion.COMPLETE
    assert len(reports[0].diagnostics) == 1
    assert reports[0].diagnostics[0].location.path == path
    assert reports[0].diagnostics[0].severity.value == "error"


def test_tflint_untrusted_inputs_never_attest_or_execute(*, tmp_path: Path) -> None:
    path = _source(root=tmp_path, project="project")

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        pytest.fail(f"untrusted input must not execute {argv!r} at {cwd!r}")

    reports = analyze_sources(root=tmp_path, paths=(path,), selected=frozenset({"tflint"}), runner=runner)
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues


@pytest.mark.parametrize("requested", ["true", "false", "malformed"])
@pytest.mark.parametrize(
    "arguments", [pytest.param(("--version",), id="version"), pytest.param(("--format=json",), id="analysis")]
)
def test_native_process_disables_tflint_update_checks(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requested: str, arguments: tuple[str, ...]
) -> None:
    probe = tmp_path / "environment_probe.py"
    probe.write_text(
        'import json\nimport os\nprint(json.dumps({"disabled": os.getenv("TFLINT_DISABLE_VERSION_CHECK"), "lang": os.getenv("LANG"), "secret": "SARJ_PROBE_SECRET" in os.environ}))\n'
    )
    monkeypatch.setenv("TFLINT_DISABLE_VERSION_CHECK", requested)
    monkeypatch.setenv("LANG", "C")
    monkeypatch.setenv("SARJ_PROBE_SECRET", "private")
    result = run_process((sys.executable, str(probe), *arguments), cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"disabled": "true", "lang": "C", "secret": False}


def test_tflint_analysis_uses_the_executable_that_attested_its_plugin(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _source(root=tmp_path, project="project")
    verified = tmp_path / "verified-tflint"
    replacement = tmp_path / "replacement-tflint"
    lookups: list[Path] = []
    calls: list[tuple[str, ...]] = []

    def checked_tool(name: str, *, root: Path, runner: object) -> NativeTool:
        assert name == "tflint"
        assert root == tmp_path / "project"
        assert callable(runner)
        binary = verified if not lookups else replacement
        lookups.append(binary)
        return NativeTool(
            name=name,
            version="0.63.1",
            version_args=("--version",),
            version_pattern="",
            finding_exits=frozenset({2}),
            executable=binary,
        )

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path / "project"
        calls.append(tuple(argv))
        if "--version" in argv:
            return ProcessOutput(0, "TFLint version 0.63.1\n+ ruleset.google (0.39.0)", "")
        return ProcessOutput(0, '{"errors":[],"issues":[]}', "")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- default executable discovery is under test; injected process runners bypass its absolute-path resolver.
        devops_source, "checked_tool", checked_tool
    )
    reports = analyze_sources(
        root=tmp_path, paths=(path,), selected=frozenset({"tflint"}), trust_repository_code=True, runner=runner
    )
    assert reports[0].completion is Completion.COMPLETE
    assert lookups == [verified]
    assert [argv[0] for argv in calls] == [str(verified), str(verified)]
