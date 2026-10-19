from __future__ import annotations

import stat
from typing import TYPE_CHECKING

import pytest

from sarj_standards.api import Standards
from sarj_standards.libs.adoption import lifecycle, manifest
from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode, baseline
from sarj_standards.libs.linting import shell_format, textlint
from sarj_standards.libs.linting.external import analyze_external
from sarj_standards.libs.rules import EvaluationCase, ExpectedOutcome, Language, RuleProblem


if TYPE_CHECKING:
    from pathlib import Path


PROBLEM = RuleProblem(
    key="shell-formatting",
    summary="Shell sources need one deterministic formatter in check and fix.",
    harm="Local editor settings and unformatted changed files produce inconsistent CI reviews.",
    languages=frozenset({Language.SHELL}),
    bad_examples=("if true; then\necho ok\nfi\n",),
    good_examples=("if true; then\n  echo ok\nfi\n",),
    exclusions=("Generated Gradle launchers",),
)


POSITION_PROBLEM = RuleProblem(
    key="shell-format-physical-position",
    summary="Formatter diagnostics must point to the first changed physical shell line.",
    harm="Literal separators and trailing blank lines produce misleading CI source locations.",
    languages=frozenset({Language.SHELL}),
    bad_examples=("# comment\u2028data\nprintf  '%s'   ok\n", "printf ok\n\n"),
    good_examples=("# comment\u2028data\nprintf '%s' ok\n", "printf ok\n"),
)


BYTE_LOSS_PROBLEM = RuleProblem(
    key="shell-native-format-byte-loss",
    summary="A native formatting fix must not remove literal shell control bytes.",
    harm="Removing a vertical tab changes an argument; replacing a form feed can activate comment data.",
    languages=frozenset({Language.SHELL}),
    bad_examples=("printf '%s' before\vafter\n", "# comment\fprintf '%s' accidental\n"),
    good_examples=("printf '%b' 'before\\vafter'\n", "printf '%b' 'before\\fafter'\n"),
)


@pytest.mark.parametrize("separator", ["\v", "\f", "\r", "\x85", "\u2028", "\u2029"])
def test_formatter_position_counts_physical_shell_lines(separator: str) -> None:
    case = EvaluationCase(
        "literal-separator", Language.SHELL, f"# comment{separator}data\nprintf  '%s'   ok\n", ExpectedOutcome.MATCH
    )
    assert case.language in POSITION_PROBLEM.languages
    formatted = case.source.replace("printf  '%s'   ok", "printf '%s' ok")
    finding = shell_format.format_diagnostic(path="job.sh", source=case.source, formatted=formatted, line=4)
    position = finding.location.position
    assert position is not None
    assert (position.line, position.byte_offset) == (5, case.source.encode().index(b"printf"))


@pytest.mark.parametrize("separator", ["\r", "\x85", "\u2028", "\u2029"])
def test_native_formatter_position_preserves_literal_comment_data(tmp_path: Path, separator: str) -> None:
    source = f"# comment{separator}data\nprintf  '%s'   ok\n"
    path = tmp_path / "job.sh"
    path.write_bytes(source.encode())
    [report] = shell_format.analyze_sources(root=tmp_path, paths=(str(path),))
    assert report.completion is Completion.COMPLETE
    [finding] = report.diagnostics
    position = finding.location.position
    assert position is not None
    assert (position.line, position.byte_offset) == (1, source.encode().index(b"printf"))


@pytest.mark.parametrize(
    ("source", "formatted", "line", "offset"),
    [
        pytest.param("printf ok\n\n", "printf ok\n", 1, 10, id="removed-trailing-line"),
        pytest.param("printf ok\n", "printf ok\n\n", 1, 10, id="added-trailing-line"),
        pytest.param("printf ok", "printf ok\n", 0, 0, id="missing-final-newline"),
        pytest.param("printf ok\n\n\n", "printf ok\n", 1, 10, id="several-removed-lines"),
    ],
)
def test_formatter_position_includes_unequal_suffixes(source: str, formatted: str, line: int, offset: int) -> None:
    case = EvaluationCase("suffix-boundary", Language.SHELL, source)
    finding = shell_format.format_diagnostic(path="job.sh", source=case.source, formatted=formatted, line=4)
    position = finding.location.position
    assert position is not None
    assert (position.line, position.byte_offset) == (4 + line, offset)


def test_formatter_position_accepts_the_empty_policy_placeholder() -> None:
    finding = shell_format.format_diagnostic(path="job.sh", source="", formatted="", line=4)
    position = finding.location.position
    assert position is not None
    assert (position.line, position.byte_offset) == (4, 0)


@pytest.mark.parametrize(
    "case",
    [
        EvaluationCase("indentation", Language.SHELL, "if true; then\necho ok\nfi\n", ExpectedOutcome.MATCH),
        EvaluationCase("formatted", Language.SHELL, "if true; then\n  echo ok\nfi\n"),
        EvaluationCase("comment", Language.SHELL, "# if true; then echo ok; fi\n"),
    ],
    ids=("indentation", "formatted", "comment"),
)
def test_labeled_formatter_cases(tmp_path: Path, case: EvaluationCase) -> None:
    assert case.language in PROBLEM.languages
    path = tmp_path / "library.bash"
    path.write_text(case.source)
    [report] = shell_format.analyze_sources(root=tmp_path, paths=(str(path),))
    assert bool(report.diagnostics) == (case.expected is ExpectedOutcome.MATCH)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "#!/bin/bash\nif true; then\necho ok\nfi\n",
            "#!/bin/bash\nif true; then\n  echo ok\nfi\n",
            id="bash-indentation",
        ),
        pytest.param(
            "#!/bin/sh\ncase x in\nx) echo ok;;\nesac\n",
            "#!/bin/sh\ncase x in\n  x) echo ok ;;\nesac\n",
            id="posix-case-indentation",
        ),
        pytest.param(
            "#!/bin/zsh\nif true; then\necho ok\nfi\n",
            "#!/bin/zsh\nif true; then\n  echo ok\nfi\n",
            id="zsh-shebang-in-sh-file",
        ),
        pytest.param(
            "#!/bin/bash\ncat <<'DATA'\n  literal $value\nDATA\n",
            "#!/bin/bash\ncat <<'DATA'\n  literal $value\nDATA\n",
            id="heredoc-payload",
        ),
        pytest.param(
            "#!/bin/bash\necho '  quoted data  '\n", "#!/bin/bash\necho '  quoted data  '\n", id="quoted-data"
        ),
    ],
)
def test_native_formatting_preserves_source_and_converges(tmp_path: Path, source: str, expected: str) -> None:
    path = tmp_path / "entry.sh"
    path.write_text(source)
    path.chmod(0o755)
    (tmp_path / ".editorconfig").write_text("root = true\n[*]\nindent_style = tab\nindent_size = 8\n")

    [before] = shell_format.analyze_sources(root=tmp_path, paths=(str(path),))
    assert before.completion is Completion.COMPLETE
    assert bool(before.diagnostics) == (source != expected)
    assert all(item.severity is Severity.WARNING and item.rule_id == "format" for item in before.diagnostics)
    assert shell_format.fix_sources(tmp_path, (str(path),)) == 0
    assert path.read_text() == expected
    assert stat.S_IMODE(path.stat().st_mode) == 0o755
    assert shell_format.fix_sources(tmp_path, (str(path),)) == 0
    [after] = shell_format.analyze_sources(root=tmp_path, paths=(str(path),))
    assert after.diagnostics == ()


@pytest.mark.parametrize(
    ("name", "source", "dialect"),
    [
        pytest.param("job.sh", "#!/usr/bin/env -S zsh -e\ntrue\n", "zsh", id="env-shebang"),
        pytest.param("job.sh", "#!/usr/bin/python3\nprint(1)\n", None, id="non-shell-shebang"),
        pytest.param("job", "#!/bin/bash\ntrue\n", "bash", id="extensionless"),
        pytest.param("library.sh", "true\n", "sh", id="sourced-file-fallback"),
    ],
)
def test_runtime_interpreter_owns_file_dialect(tmp_path: Path, name: str, source: str, dialect: str | None) -> None:
    path = tmp_path / name
    path.write_text(source)
    assert textlint.shell_dialect(path) == dialect


def test_malformed_shell_prevents_all_planned_writes(tmp_path: Path) -> None:
    good = tmp_path / "a.sh"
    bad = tmp_path / "b.sh"
    original = "#!/bin/bash\nif true; then\necho ok\nfi\n"
    good.write_text(original)
    bad.write_text("#!/bin/bash\nif true; then\n")
    [report] = shell_format.analyze_sources(root=tmp_path, paths=(str(bad),))
    assert report.completion is Completion.FAILED
    assert shell_format.fix_sources(tmp_path, (str(good), str(bad))) == 2
    assert good.read_text() == original


def test_generated_gradle_wrapper_is_excluded_by_generator_marker(tmp_path: Path) -> None:
    wrapper = tmp_path / "gradlew"
    wrapper.write_text(
        "#!/bin/sh\n# Gradle start up script for POSIX generated by Gradle.\nif true; then\necho ok\nfi\n"
    )
    assert shell_format.analyze_sources(root=tmp_path, paths=(str(wrapper),)) == ()
    assert shell_format.fix_sources(tmp_path, (str(wrapper),)) == 0
    assert "\necho ok\n" in wrapper.read_text()


def test_explicit_shfmt_capability_keeps_zsh_semantic_coverage_separate(tmp_path: Path) -> None:
    path = tmp_path / "job.sh"
    path.write_text("#!/bin/zsh\nif true; then\necho ok\nfi\n")
    reports = analyze_external(
        [str(path)], root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"shfmt", "shellcheck"})
    )
    assert next(item for item in reports if item.name == "shfmt").completion is Completion.COMPLETE
    assert next(item for item in reports if item.name == "shellcheck").issues[0].kind == "coverage-missing"


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("printf '%s\\n' 'Gradle start up script for POSIX generated by Gradle.'", id="string-data"),
        pytest.param(
            "# Documentation mentions Gradle start up script for POSIX generated by Gradle.", id="comment-prose"
        ),
        pytest.param("cat <<'EOF'\n# Gradle start up script for POSIX generated by Gradle.\nEOF", id="heredoc-data"),
    ],
)
def test_incidental_generator_text_does_not_exempt_authored_shell(tmp_path: Path, line: str) -> None:
    path = tmp_path / "job.sh"
    path.write_text(f"#!/bin/bash\n{line}\nif true; then\necho ok\nfi\n")
    [report] = shell_format.analyze_sources(root=tmp_path, paths=[str(path)])
    assert report.completion is Completion.COMPLETE
    assert len(report.diagnostics) == 1
    assert shell_format.fix_sources(tmp_path, [str(path)]) == 0
    assert not shell_format.analyze_sources(root=tmp_path, paths=[str(path)])[0].diagnostics


def test_fix_refuses_linked_targets(tmp_path: Path) -> None:
    source = tmp_path / "source.sh"
    original = "#!/bin/bash\nif true; then\necho ok\nfi\n"
    source.write_text(original)
    link = tmp_path / "link.sh"
    link.symlink_to(source)
    assert shell_format.fix_sources(tmp_path, (str(link),)) == 2
    assert source.read_text() == original


def test_fix_refuses_native_carriage_return_data_loss_atomically(tmp_path: Path) -> None:
    safe = tmp_path / "a.sh"
    safe.write_text("#!/bin/bash\nif true; then\necho ok\nfi\n")
    source = tmp_path / "z.sh"
    original = b"#!/bin/bash\nprintf '%s' 'first\r\nsecond\n'\n"
    source.write_bytes(original)
    safe_before = safe.read_bytes()
    assert shell_format.fix_sources(tmp_path, [str(safe), str(source)]) == 2
    assert safe.read_bytes() == safe_before
    assert source.read_bytes() == original


def test_format_check_remains_available_for_carriage_return_source(tmp_path: Path) -> None:
    source = tmp_path / "job.sh"
    source.write_bytes(b"#!/bin/bash\nprintf '%s' 'first\r\nsecond\n'\n")
    [report] = shell_format.analyze_sources(root=tmp_path, paths=[str(source)])
    assert report.completion is Completion.COMPLETE
    assert len(report.diagnostics) == 1


@pytest.mark.parametrize(
    "case",
    [
        EvaluationCase("vertical-tab-argument", Language.SHELL, "printf '%s' before\vafter\n", ExpectedOutcome.MATCH),
        EvaluationCase(
            "form-feed-comment",
            Language.SHELL,
            "# comment\fprintf '%s' accidental\nprintf '%s' retained\n",
            ExpectedOutcome.MATCH,
        ),
    ],
    ids=("vertical-tab-argument", "form-feed-comment"),
)
def test_fix_refuses_native_non_shell_whitespace_data_loss_atomically(tmp_path: Path, case: EvaluationCase) -> None:
    assert case.language in BYTE_LOSS_PROBLEM.languages
    safe = tmp_path / "a.sh"
    safe.write_text("#!/bin/bash\nif true; then\necho ok\nfi\n")
    source = tmp_path / "z.sh"
    source.write_bytes(case.source.encode())
    safe_before = safe.read_bytes()
    assert shell_format.fix_sources(tmp_path, [str(safe), str(source)]) == 2
    assert safe.read_bytes() == safe_before
    assert source.read_bytes() == case.source.encode()
    [report] = shell_format.analyze_sources(root=tmp_path, paths=[str(source)])
    assert report.completion is Completion.COMPLETE
    assert len(report.diagnostics) == 1


@pytest.mark.parametrize("escape", [r"\v", r"\f"])
def test_native_fix_keeps_escaped_control_data_and_converges(tmp_path: Path, escape: str) -> None:
    case = EvaluationCase("escaped-control-data", Language.SHELL, f"printf  '%b'   'before{escape}after'\n")
    path = tmp_path / "job.sh"
    path.write_bytes(case.source.encode())
    assert shell_format.fix_sources(tmp_path, [str(path)]) == 0
    expected = case.source.replace("printf  '%b'   ", "printf '%b' ")
    assert path.read_bytes() == expected.encode()
    assert shell_format.fix_sources(tmp_path, [str(path)]) == 0
    [report] = shell_format.analyze_sources(root=tmp_path, paths=[str(path)])
    assert report.diagnostics == ()


@pytest.mark.parametrize("suppression", ["capability", "path", "rule", "override"])
def test_labeled_suppressions_apply_to_check_and_fix(tmp_path: Path, suppression: str) -> None:
    case = EvaluationCase("suppressed-indentation", Language.SHELL, "if true; then\necho ok\nfi\n")
    path = tmp_path / "library.sh"
    path.write_text(case.source)
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=(),
        python_dest=".",
        typescript_dest=".",
        disabled_capabilities=("shfmt",) if suppression == "capability" else (),
        excluded_paths=("library.sh",) if suppression == "path" else (),
        excluded_rules=("shfmt:format",) if suppression == "rule" else (),
        exclusion_overrides=(manifest.ExclusionOverride(("library.sh",), ("shfmt:format",), "fixture"),)
        if suppression == "override"
        else (),
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render())
    assert shell_format.analyze_sources(root=tmp_path, paths=(str(path),)) == ()
    assert lifecycle.selected_format_commands(tmp_path, (str(path),)) == []
    assert shell_format.fix_sources(tmp_path, (str(path),)) == 0
    assert path.read_text() == case.source


def test_changed_file_formatting_cannot_hide_in_an_unchanged_hunk(tmp_path: Path) -> None:
    path = tmp_path / "job.sh"
    path.write_text("#!/bin/bash\nif true; then\necho ok\nfi\n")
    [report] = shell_format.analyze_sources(root=tmp_path, paths=(str(path),))
    finding = report.diagnostics[0]
    scope = baseline.ChangedLineScope(frozenset({"job.sh"}), {"job.sh": frozenset({1})})
    assert baseline.touches_changed_lines(finding, scope)


def test_api_warns_on_legacy_drift_but_requires_selected_file_formatting(tmp_path: Path) -> None:
    path = tmp_path / "job.sh"
    path.write_text("#!/bin/bash\nif true; then\necho ok\nfi\n")
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=(),
        python_dest=".",
        typescript_dest=".",
        disabled_capabilities=tuple(name for name in manifest.ALL_CAPABILITIES if name != "shfmt"),
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render())
    standards = Standards(tmp_path)
    full = standards.analyze(external=True)
    selected = standards.analyze((str(path),), external=True)
    assert next(item for item in full.diagnostics if item.source == "shfmt").severity is Severity.WARNING
    finding = next(item for item in selected.diagnostics if item.source == "shfmt")
    assert finding.severity is Severity.ERROR
    assert not baseline.is_baselineable(finding)
    commands = lifecycle.selected_format_commands(tmp_path, (str(path),))
    assert lifecycle.execute(commands) == 0
    assert "\n  echo ok\n" in path.read_text()


def test_concurrent_formatting_reports_files_in_sorted_order(tmp_path: Path) -> None:
    names = [f"scripts/run-{index:02}.sh" for index in range(10)]
    for index, name in enumerate(names):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nprintf  ok\n" if index % 2 else "#!/bin/sh\nprintf ok\n")
    [report] = shell_format.analyze_sources(root=tmp_path, paths=tuple(reversed(names)))
    assert report.completion is Completion.COMPLETE
    assert report.file_count == len(names)
    assert [finding.location.path for finding in report.diagnostics] == names[1::2]


def test_concurrent_formatter_failure_fails_the_report(tmp_path: Path) -> None:
    names = [f"scripts/run-{index}.sh" for index in range(6)]
    for index, name in enumerate(names):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nif true; then\n" if index == 3 else "#!/bin/sh\nprintf ok\n")
    [report] = shell_format.analyze_sources(root=tmp_path, paths=tuple(names))
    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "formatting-failure"
