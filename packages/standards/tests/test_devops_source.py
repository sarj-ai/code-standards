from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting.devops_source import (
    analyze_sources,
    parse_actionlint,
    parse_hadolint,
    parse_terraform,
    parse_tflint,
    parse_zizmor,
)
from sarj_standards.libs.linting.external import ProcessOutput


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _file(root: Path, name: str, source: str = "example\n") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return path


def test_actionlint_clean_empty_protocol(tmp_path: Path) -> None:
    _file(tmp_path, ".github/workflows/test.yml")
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        calls.append(tuple(argv))
        return ProcessOutput(
            0, "version: 0.11.0" if argv[0] == "shellcheck" else "1.7.12" if "-version" in argv else "", ""
        )

    reports = analyze_sources(
        root=tmp_path, paths=(".github/workflows/test.yml",), selected=frozenset({"actionlint"}), runner=runner
    )
    assert reports[0].completion is Completion.COMPLETE
    assert any(argument.startswith("-shellcheck=") and argument != "-shellcheck=" for argument in calls[-1])
    assert "-pyflakes=" in calls[-1]


@pytest.mark.parametrize(("status", "payload"), [(1, "[]"), (0, "{}"), (3, "[]")])
def test_actionlint_broken_protocol_is_fatal(tmp_path: Path, status: int, payload: str) -> None:
    _file(tmp_path, ".github/workflows/test.yml")

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        return (
            ProcessOutput(0, "version: 0.11.0", "")
            if argv[0] == "shellcheck"
            else ProcessOutput(0, "1.7.12", "")
            if "-version" in argv
            else ProcessOutput(status, payload, "")
        )

    reports = analyze_sources(
        root=tmp_path, paths=(".github/workflows/test.yml",), selected=frozenset({"actionlint"}), runner=runner
    )
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues


def test_actionlint_authored_byte_column(tmp_path: Path) -> None:
    _file(tmp_path, "workflow.yml", "é x\n")
    payload = '[{"kind":"syntax-check","message":"bad","filepath":"workflow.yml","line":1,"column":4}]'
    findings = parse_actionlint(payload, tmp_path)
    assert findings[0].location.position is not None
    assert findings[0].location.position.character == 2


def test_hadolint_json_strict_severity(tmp_path: Path) -> None:
    _file(tmp_path, "Dockerfile")
    payload = '[{"code":"DL3008","message":"pin","file":"Dockerfile","line":1,"column":1,"level":"warning"}]'
    assert parse_hadolint(payload, tmp_path)[0].severity.value == "error"
    with pytest.raises(ValueError, match="unknown severity"):
        parse_hadolint(payload.replace("warning", "unknown"), tmp_path)


@pytest.mark.parametrize(
    ("name", "selected"),
    [
        pytest.param("Dockerfile", True, id="canonical"),
        pytest.param("python/integration/Dockerfile.migrate", True, id="dockerfile-variant"),
        pytest.param("containers/release.dockerfile", True, id="dockerfile-extension"),
        pytest.param("containers/DOCKERFILE.Debug", True, id="case-insensitive-variant"),
        pytest.param(".dockerignore", False, id="root-ignore"),
        pytest.param("python/integration/Dockerfile.migrate.dockerignore", False, id="variant-ignore"),
        pytest.param("Dockerfile.dockerignore", False, id="canonical-ignore"),
        pytest.param("dockerfile-example.txt", False, id="unrelated-name"),
    ],
)
def test_hadolint_selects_dockerfile_variants_without_ignore_files(
    tmp_path: Path, name: str, *, selected: bool
) -> None:
    path = _file(tmp_path, name, "FROM scratch\n")
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        calls.append(tuple(argv))
        return ProcessOutput(0, "Haskell Dockerfile Linter 2.15.1" if "--version" in argv else "[]", "")

    reports = analyze_sources(root=tmp_path, paths=(name,), selected=frozenset({"hadolint"}), runner=runner)
    if selected:
        assert len(reports) == 1
        assert reports[0].completion is Completion.COMPLETE
        assert reports[0].file_count == 1
        assert calls[-1][-1] == str(path)
    else:
        assert reports == ()
        assert calls == []


def test_tflint_scope_is_relative_to_project(tmp_path: Path) -> None:
    _file(tmp_path, "iac/main.tf")
    payload = json.dumps(
        {
            "errors": [],
            "issues": [
                {
                    "rule": {"name": "terraform_typed_variables", "severity": "warning"},
                    "message": "type",
                    "range": {"filename": "main.tf", "start": {"line": 1, "column": 1}},
                }
            ],
        }
    )
    assert parse_tflint(payload, tmp_path, cwd=tmp_path / "iac")[0].location.path == "iac/main.tf"
    with pytest.raises(ValueError, match="execution errors"):
        parse_tflint('{"errors":[{"message":"plugin failure"}],"issues":[]}', tmp_path)


def test_terraform_validate_counts_and_missing_providers(tmp_path: Path) -> None:
    assert parse_terraform('{"format_version":"1.0","valid":true,"error_count":0,"diagnostics":[]}', tmp_path) == ()
    with pytest.raises(ValueError, match="validity and error count"):
        parse_terraform('{"format_version":"1.0","valid":false,"error_count":0,"diagnostics":[]}', tmp_path)
    with pytest.raises(ValueError, match="Missing required provider"):
        parse_terraform(
            '{"format_version":"1.0","valid":false,"error_count":1,"diagnostics":[{"severity":"error","summary":"Missing required provider"}]}',
            tmp_path,
        )


def test_zizmor_preserves_exact_byte_region_and_ignored_findings(tmp_path: Path) -> None:
    _file(tmp_path, "workflow.yml", "é x\n")
    payload = json.dumps(
        [
            {
                "ident": "unpinned-uses",
                "desc": "pin",
                "url": "https://docs.zizmor.sh/audits/",
                "determinations": {"severity": "Low", "confidence": "High"},
                "ignored": True,
                "locations": [
                    {
                        "symbolic": {"kind": "Primary", "key": {"Local": {"verbatim_path": "workflow.yml"}}},
                        "concrete": {"location": {"offset_span": {"start": 3, "end": 4}}},
                    }
                ],
            }
        ]
    )
    findings = parse_zizmor(payload, tmp_path)
    assert findings[0].location.region is not None
    assert findings[0].location.region.start.character == 2
    assert findings[0].location.region.end.character == 3


def test_untrusted_terraform_only_formats_and_never_initializes(tmp_path: Path) -> None:
    _file(tmp_path, "iac/main.tf")
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        calls.append(tuple(argv))
        if "version" in argv:
            return ProcessOutput(0, "Terraform v1.15.8", "")
        return ProcessOutput(0, "", "")

    reports = analyze_sources(
        root=tmp_path, paths=("iac/main.tf",), selected=frozenset({"terraform", "tflint"}), runner=runner
    )
    assert reports[0].completion is Completion.COMPLETE
    assert reports[1].completion is Completion.FAILED
    assert reports[2].completion is Completion.FAILED
    assert not any("init" in call or "validate" in call for call in calls)


def test_compose_static_contract_is_explicit(tmp_path: Path) -> None:
    _file(tmp_path, "compose.yaml")
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        calls.append(tuple(argv))
        return ProcessOutput(0, '{"version":"v5.1.2"}' if "version" in argv else '{"services":{}}', "")

    reports = analyze_sources(
        root=tmp_path, paths=("compose.yaml",), selected=frozenset({"compose"}), runner=runner, compose_version="5.1.2"
    )
    assert reports[0].name == "compose-static"
    assert reports[0].completion is Completion.COMPLETE
    assert "--no-interpolate" in calls[-1]
    assert "--no-env-resolution" in calls[-1]


def test_compose_missing_consumer_pin_is_fatal(tmp_path: Path) -> None:
    _file(tmp_path, "compose.yaml")
    reports = analyze_sources(root=tmp_path, paths=("compose.yaml",), selected=frozenset({"compose"}))
    assert reports[0].completion is Completion.FAILED
    assert reports[0].diagnostics == ()
    assert "compose_version" in reports[0].issues[0].message


def test_json_terraform_is_never_passed_to_native_formatter(tmp_path: Path) -> None:
    _file(tmp_path, "main.tf.json", "{}\n")
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        calls.append(tuple(argv))
        return ProcessOutput(0, "Terraform v1.15.8", "")

    reports = analyze_sources(root=tmp_path, paths=("main.tf.json",), selected=frozenset({"terraform"}), runner=runner)
    assert reports[0].file_count == 0
    assert reports[1].completion is Completion.FAILED
    assert not any("fmt" in call or "init" in call for call in calls)


def test_reported_path_cannot_escape_repository(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not in the subpath"):
        parse_actionlint(
            '[{"kind":"syntax","message":"bad","filepath":"../outside.yml","line":1,"column":1}]', tmp_path
        )
