"""External analyzer adapters preserve native structure and trust boundaries."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs.libs.diagnostics import Completion, Severity, TrustMode
from sarj_lint_configs.libs.linting import external as external_module
from sarj_lint_configs.libs.linting.external import (
    ProcessOutput,
    analyze_external,
    parse_basedpyright,
    parse_eslint,
    parse_ruff,
)


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


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


def test_external_analyzers_do_not_inherit_caller_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SARJ_AUDIT_SECRET", "must-not-leak")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("LC_ALL", "C")

    environment = external_module._analysis_environment()  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]

    assert "SARJ_AUDIT_SECRET" not in environment
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

    monkeypatch.setattr(external_module.sys, "executable", str(interpreter))  # pyright: ignore[reportPrivateLocalImportUsage]
    monkeypatch.setattr(external_module.shutil, "which", which)  # pyright: ignore[reportPrivateLocalImportUsage]

    assert external_module._analyzer_executable("basedpyright") == str(tmp_path / "bin" / "basedpyright")  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
    assert calls == [("basedpyright", str(tmp_path / "bin"))]


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

    def fatal(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(1, payload, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.TRUSTED, runner=fatal)

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues
    assert not reports[0].diagnostics


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

    def forbidden(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        pytest.fail("safe mode executed repository code")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=forbidden)

    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].kind == "trust-required"


def test_string_safe_mode_never_executes_repository_eslint_config(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("throw new Error('must not execute');\n", encoding="utf-8")
    source = tmp_path / "example.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")

    def forbidden(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        pytest.fail("string safe mode executed repository code")

    reports = analyze_external([str(source)], root=tmp_path, trust="safe", runner=forbidden)

    assert reports[0].issues[0].kind == "trust-required"


def test_signal_terminated_tool_is_an_execution_failure(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def terminated(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(-9, "[]", "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=terminated)

    assert all(report.completion is Completion.FAILED for report in reports)
    assert all(report.issues[0].exit_code == -9 for report in reports)


def test_finding_exit_without_diagnostics_fails_the_external_protocol(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def empty_finding_exit(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = cwd
        payload = '{"generalDiagnostics":[]}' if argv[0] == "basedpyright" else "[]"
        return ProcessOutput(1, payload, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=empty_finding_exit)

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
    monkeypatch.setattr(external_module, "_MAX_STDOUT_BYTES", 128)
    monkeypatch.setattr(external_module, "_MAX_STDERR_BYTES", 64)

    with pytest.raises(external_module.OutputLimitError, match="output exceeded"):
        external_module.run_process(
            (sys.executable, "-c", "import sys; sys.stdout.write('x' * 10000)"),
            cwd=tmp_path,
        )


def test_malformed_nested_json_becomes_a_bounded_tool_failure(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def nested(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(0, "[" * 100_000, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=nested)

    assert all(report.completion is Completion.FAILED for report in reports)
    assert all(len(report.issues[0].message) <= 1024 for report in reports)


def test_external_failure_redacts_secrets_and_absolute_paths(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")

    def failed(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(
            2,
            "",
            f"token=SUPERSECRET {cwd}/src/config /Users/alice/private/config https://docs.example.com/remediation",
        )

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=failed)
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


def test_python_external_tools_use_structured_output_without_uv(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = cwd
        seen.append(tuple(argv))
        if argv[0] == "ruff":
            return ProcessOutput(0, "[]", "")
        return ProcessOutput(0, '{"generalDiagnostics":[]}', "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=runner)

    assert [report.name for report in reports] == ["ruff", "basedpyright"]
    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert all(argv[0] != "uv" for argv in seen)


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
        runner=runner,
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


def test_external_analyzer_cannot_leak_a_path_outside_repository(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    outside = tmp_path.parent / "private.py"

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = cwd
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

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=runner)
    ruff = next(report for report in reports if report.name == "ruff")

    assert ruff.completion is Completion.FAILED
    assert ruff.issues[0].message == "ValueError: analyzer reported a path outside the repository root"
    assert str(tmp_path.parent) not in ruff.issues[0].message
