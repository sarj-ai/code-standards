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


def test_fix_refuses_linked_targets(tmp_path: Path) -> None:
    source = tmp_path / "source.sh"
    original = "#!/bin/bash\nif true; then\necho ok\nfi\n"
    source.write_text(original)
    link = tmp_path / "link.sh"
    link.symlink_to(source)
    assert shell_format.fix_sources(tmp_path, (str(link),)) == 2
    assert source.read_text() == original


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
