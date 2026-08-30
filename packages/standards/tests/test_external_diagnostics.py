from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from typing import TYPE_CHECKING

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


if TYPE_CHECKING:
    from collections.abc import Sequence


def _write_detekt_report(command: Sequence[str], payload: str = '{"runs":[]}') -> Path:
    report = command[command.index("--report") + 1]
    assert report.startswith("sarif:")
    path = Path(report.removeprefix("sarif:"))
    assert path.is_absolute()
    assert path.parent.is_dir()
    path.write_text(payload, encoding="utf-8")
    return path


def test_eslint_passes_on_unpruned_suppressions_only_when_requested() -> None:
    command = ("npx", "eslint", "--", "app.ts")

    strict = external_module._eslint_json_argv(command)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
    scoped_baseline = external_module._eslint_json_argv(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        command, pass_on_unpruned_suppressions=True
    )

    assert "--pass-on-unpruned-suppressions" not in strict
    assert scoped_baseline.count("--pass-on-unpruned-suppressions") == 1
    assert scoped_baseline.index("--pass-on-unpruned-suppressions") < scoped_baseline.index("--")


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
    payload: dict[str, object] = {
        "errors": [{"level": "warn", "type": ["PartialParsing", []], "message": "unsupported Swift macro"}],
        "results": [],
        "paths": {"scanned": [str(swift)]},
    }

    assert parse_mobsfscan(json.dumps(payload), root=tmp_path, expected_paths=(str(swift),)) == ()


def test_mobsfscan_rejects_partial_parsing_without_proven_exact_coverage(tmp_path: Path) -> None:
    payload: dict[str, object] = {
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
def test_mobsfscan_rejects_fatal_or_malformed_semgrep_errors(tmp_path: Path, error: object) -> None:
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
        if executable == "swiftformat":
            return ProcessOutput(0, "", "")
        if executable in {"swiftlint", "ktlint"}:
            return ProcessOutput(0, "[]", "")
        if executable == "detekt":
            detekt_reports.append(_write_detekt_report(command))
            return ProcessOutput(0, "stdout is not the Detekt protocol", "")
        if executable == "semgrep":
            return ProcessOutput(
                0,
                json.dumps({"errors": [], "paths": {"scanned": [str(swift), str(kotlin)]}, "results": []}),
                "",
            )
        raise AssertionError(command)

    reports = analyze_external(
        [str(swift), str(kotlin)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=runner,
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
        runner=runner,
        capabilities=frozenset({"swiftformat", "swiftlint", "ktlint", "detekt"}),
    )

    assert all(report.completion is Completion.COMPLETE for report in reports)
    mint_commands = [command for command in seen if command[0] == "mint"]
    assert mint_commands
    assert all(command[:5] == ("mint", "run", "--silent", "--mintfile", str(mintfile)) for command in mint_commands)
    assert any(
        ("--config", str(swift_config)) == (command[-3], command[-2]) for command in seen if "swiftlint" in command
    )
    assert any(str(format_config) in command for command in seen if "swiftformat" in command)
    assert all("--" not in command for command in seen if "swiftformat" in command)
    assert any(f"--editorconfig={editorconfig}" in command for command in seen if command[0] == "ktlint")
    assert all("--log-level=none" in command for command in seen if command[0] == "ktlint")
    assert any(str(detekt_config) in command for command in seen if command[0] == "detekt")
    detekt_command = next(command for command in seen if command[0] == "detekt")
    assert detekt_command[detekt_command.index("--input") + 1] == str(kotlin)
    report_argument = detekt_command[detekt_command.index("--report") + 1]
    assert report_argument.startswith("sarif:")
    assert report_argument != "sarif:/dev/stdout"


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
        runner=runner,
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
    monkeypatch.setattr(external_module, "_MAX_STDOUT_BYTES", 8)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        _write_detekt_report(argv, '{"runs":[]}')
        return ProcessOutput(0, "", "")

    reports = analyze_external(
        [str(kotlin)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=runner,
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

    argv = external_module._mobsfscan_argv(Path("rules"), config=config)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]

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
        external_module._mobsfscan_argv(Path("rules"), config=path)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]


def test_managed_swift_commands_ignore_repository_mintfiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "Mintfile.mobile.strict").write_text("attacker/tool@main\n", encoding="utf-8")

    def managed_command(name: str) -> tuple[str, ...]:
        assert name == "mint"
        return ("/managed/mint",)

    monkeypatch.setattr(external_module.mobile_tools, "command", managed_command)

    command = external_module._swift_command(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
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

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        nonlocal invoked
        _ = argv
        assert cwd == tmp_path
        invoked = True
        return ProcessOutput(0, "", "")

    reports = analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=runner,
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
        external_module._mobsfscan_argv(Path("rules"), config=linked)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]

    oversized = tmp_path / "mobsf.strict.yml"
    oversized.write_text("12345", encoding="utf-8")
    monkeypatch.setattr(external_module, "_MAX_MOBILE_CONFIG_BYTES", 4)
    with pytest.raises(external_module.OutputLimitError, match="exceeds 4 bytes"):
        external_module._mobsfscan_argv(Path("rules"), config=oversized)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]


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
        runner=runner,
        capabilities=frozenset({"shellcheck"}),
    )

    assert [item.name for item in reports] == ["shellcheck"]
    assert reports[0].completion is Completion.COMPLETE
    assert seen == [
        (
            "shellcheck",
            "--norc",
            "--extended-analysis=true",
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
        runner=forbidden,
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
def test_shellcheck_rejects_malformed_protocol_fields(tmp_path: Path, field: str, value: object, message: str) -> None:
    source = tmp_path / "release.sh"
    source.write_text("echo ok\n", encoding="utf-8")
    item: dict[str, object] = {
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
    def old_version(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(0, "ShellCheck\nversion: 0.10.0\n", "")

    monkeypatch.setattr(
        external_module,
        "run_process",
        old_version,
    )

    issue = external_module._shellcheck_version_issue(tmp_path)  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]

    assert issue is not None
    assert issue.kind == "version-mismatch"
    assert "0.11.0" in issue.message


def test_react_doctor_v3_json_becomes_a_blocking_canonical_region(tmp_path: Path) -> None:
    source = tmp_path / "src" / "button.tsx"
    source.parent.mkdir()
    source.write_text("export const Button = () => <button />;\n", encoding="utf-8")
    diagnostic: dict[str, object] = {
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
    ("extra", "message"),
    [
        ({"reactDetected": False}, "did not detect React"),
        ({"baselineDegraded": True}, "baseline degraded"),
    ],
)
def test_react_doctor_fails_closed_on_degraded_coverage(tmp_path: Path, extra: dict[str, object], message: str) -> None:
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

    assert external_module._react_project_roots(tmp_path) == (  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
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

    selection = external_module._selected_react_doctor_projects(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
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
        runner=runner,
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
        ("apps/web/src/component.cjs\0", Completion.FAILED),
        ("apps/web/src/component.cts\0", Completion.FAILED),
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        project,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert report.completion is expected_completion
    assert (
        "git",
        "diff",
        f"{base}...HEAD",
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
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

    assert not external_module._react_doctor_changed_scope_is_disjoint(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        (project,),
        root=tmp_path,
        runner=runner,
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
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

    assert not external_module._react_doctor_changed_scope_is_disjoint(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        (web, admin),
        root=tmp_path,
        runner=runner,
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

    assert not external_module._react_doctor_changed_scope_is_disjoint(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        (project,),
        root=tmp_path,
        runner=runner,
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
            id="non-ancestor-reported-base",
        ),
    ],
)
def test_react_doctor_validates_reported_degraded_changed_scope_before_allowing_empty_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[str, str, int, int, int, Completion],
) -> None:
    monkeypatch.setattr(external_module, "change_scope_base", lambda: "")
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        project,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=2,
        staged=False,
    )

    assert report.completion is expected_completion
    if expected_completion is Completion.COMPLETE:
        assert report.diagnostics == ()
        assert report.issues == ()
        assert ("git", "diff", f"{resolved_base}...HEAD", "--name-only", "--diff-filter=ACMR", "-z", "--") in seen
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=3,
        staged=True,
    )

    assert report.completion is Completion.COMPLETE
    assert report.diagnostics == ()
    assert report.issues == ()
    assert seen[0] == ("git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", "--")
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert report.completion is Completion.FAILED
    assert "baseline degraded" in report.issues[0].message


def test_react_doctor_staged_non_detection_falls_back_to_full_and_filters_exact_paths(tmp_path: Path) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)
    staged_source = project / "staged.tsx"
    staged_source.write_text('export const Image = () => <img src="avatar.png" />;\n', encoding="utf-8")
    unrelated_source = project / "unrelated.tsx"
    unrelated_source.write_text('export const Other = () => <img src="other.png" />;\n', encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def diagnostic(path: Path) -> dict[str, object]:
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
            return ProcessOutput(0, "apps/web/staged.tsx\0", "")
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=True,
    )

    assert report.completion is Completion.COMPLETE
    assert tuple(item.location.path for item in report.diagnostics) == ("apps/web/staged.tsx",)
    assert report.diagnostics[0].code == "react-doctor/alt-text"
    assert seen[0] == ("git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", "--")
    assert "--staged" in seen[1]
    assert seen[2] == seen[0]
    scope_index = seen[3].index("--scope")
    assert seen[3][scope_index + 1] == "full"
    duration_index = seen[3].index("--max-duration")
    assert int(seen[3][duration_index + 1]) >= 60


def test_react_doctor_full_scan_still_rejects_non_detection(tmp_path: Path) -> None:
    project = tmp_path / "apps" / "web"
    project.mkdir(parents=True)

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(project,),
        root=tmp_path,
        runner=runner,
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

    report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=runner,
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

    changed_report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=runner,
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
    github_report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert tuple(item.location.path for item in github_report.diagnostics) == ("component.tsx",)
    github_base_index = seen[2].index("--base")
    assert seen[2][github_base_index + 1] == event_base

    monkeypatch.setenv("SARJ_REACT_DOCTOR_BASE", "0123456789abcdef")
    ci_report = external_module._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=runner,
        use_local_binary=False,
        file_count=1,
        staged=False,
    )

    assert ci_report.completion is Completion.COMPLETE
    assert tuple(item.location.path for item in ci_report.diagnostics) == ("component.tsx",)

    base_index = seen[3].index("--base")
    assert seen[3][base_index + 1] == "0123456789abcdef"
    assert git_seen == [
        ("git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", "--"),
        ("git", "rev-parse", "--verify", "--end-of-options", f"{event_base}^{{commit}}"),
        ("git", "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"),
        ("git", "rev-parse", "--verify", "--end-of-options", "0123456789abcdef^{commit}"),
        ("git", "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"),
    ]
    assert "--no-cache" in seen[0]
    duration_index = seen[0].index("--max-duration")
    assert seen[0][duration_index + 1] == "12"


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
    payload: dict[str, object],
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

    environment = external_module._analysis_environment()  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]

    assert "SARJ_AUDIT_SECRET" not in environment
    assert "NODE_OPTIONS" not in environment
    assert environment["PATH"] == "/usr/bin"
    assert environment["LC_ALL"] == "C"


def test_only_eslint_receives_the_fixed_node_heap_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NODE_OPTIONS", "--require=/tmp/untrusted-preload.cjs")
    command = (
        sys.executable,
        "-c",
        "import os; print(os.environ.get('NODE_OPTIONS', 'missing'))",
    )

    generic = external_module.run_process(command, cwd=tmp_path)
    eslint = external_module._run_eslint_process(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        command,
        cwd=tmp_path,
    )

    assert generic.stdout.strip() == "missing"
    assert eslint.stdout.strip() == "--max-old-space-size=4096"


def test_external_analyzers_prefer_the_isolated_python_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    interpreter = tmp_path / "bin" / "python"
    calls: list[tuple[str, str | None]] = []

    def which(name: str, path: str | None = None) -> str | None:
        calls.append((name, path))
        return str(tmp_path / "bin" / name) if path is not None else f"/system/{name}"

    monkeypatch.setattr(sys, "executable", str(interpreter))
    monkeypatch.setattr(shutil, "which", which)

    assert external_module._analyzer_executable("basedpyright") == str(tmp_path / "bin" / "basedpyright")  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
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
                str(external_module._ESLINT_FORMATTER),  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
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
                str(external_module._ESLINT_FORMATTER),  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
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
    assert external_module._eslint_json_argv(argv) == expected  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
    assert external_module._argv_file_count(argv) == 1  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]


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


def test_missing_local_eslint_fails_before_package_manager_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")

    def forbidden(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        pytest.fail("the package manager ran without a local ESLint installation")

    monkeypatch.setattr(external_module, "run_process", forbidden)

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

    def successful(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = cwd
        called.append(tuple(argv))
        return ProcessOutput(0, "[]", "")

    monkeypatch.setattr(external_module, "_run_eslint_process", successful)

    reports = analyze_external([str(source)], root=root, trust=TrustMode.TRUSTED)

    assert called
    assert called[0][0] == str(binary)
    assert called[0][1:5] == (
        "--format",
        str(external_module._ESLINT_FORMATTER),  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        "--no-warn-ignored",
        "--no-cache",
    )
    assert reports[0].completion is Completion.COMPLETE


def test_eslint_empty_output_preserves_package_manager_stderr(tmp_path: Path) -> None:
    source = tmp_path / "app.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text("export default [];\n", encoding="utf-8")

    def missing(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(1, "", "ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL Command 'eslint' not found")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.TRUSTED, runner=missing)

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

    def broken(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = argv, cwd
        return ProcessOutput(1, "not-json", "eslint could not load its local configuration")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.TRUSTED, runner=broken)

    issue = reports[0].issues[0]
    assert issue.kind == "protocol-mismatch"
    assert issue.message == "eslint could not load its local configuration"
    assert "JSONDecodeError" not in issue.message


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


def test_basedpyright_uses_the_project_environment_for_import_resolution(tmp_path: Path) -> None:
    project = tmp_path / "python"
    analyzer = project / ".venv" / "bin" / "basedpyright"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("#!/bin/sh\n", encoding="utf-8")
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\n", encoding="utf-8")
    source = project / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = cwd
        seen.append(tuple(argv))
        payload = "[]" if argv[0] == "ruff" else '{"generalDiagnostics":[]}'
        return ProcessOutput(0, payload, "")

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=runner)

    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert seen[1][0] == str(analyzer)


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

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=runner)

    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert seen[1] == ((str(analyzer), "--outputjson"), project)


def test_basedpyright_runs_in_project_mode_and_filters_unselected_diagnostics(tmp_path: Path) -> None:
    project = tmp_path / "python"
    project.mkdir()
    (project / "pyrightconfig.json").write_text('{"include":["."]}\n', encoding="utf-8")
    selected = project / "selected.py"
    unselected = project / "unselected.py"
    selected.write_text("value = 1\n", encoding="utf-8")
    unselected.write_text("value = 2\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        _ = cwd
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

    reports = analyze_external([str(selected)], root=tmp_path, trust=TrustMode.SAFE, runner=runner)

    basedpyright = next(report for report in reports if report.name == "basedpyright")
    assert seen[1] == ("basedpyright", "--outputjson")
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

    reports = analyze_external([str(source)], root=tmp_path, trust=TrustMode.SAFE, runner=runner)

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
            project,
        ),
        (("basedpyright", "--outputjson"), project),
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
