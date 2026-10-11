from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import lifecycle, manifest
from sarj_standards.libs.diagnostics import Completion, TrustMode
from sarj_standards.libs.linting import devops_source, embedded_shell, shell_format
from sarj_standards.libs.linting.devops_programs import execution_blocks
from sarj_standards.libs.linting.external import analyze_external
from sarj_standards.libs.rules import EvaluationCase, ExpectedOutcome, Language, RuleProblem


if TYPE_CHECKING:
    from pathlib import Path


PROBLEM = RuleProblem(
    key="embedded-shell-coverage",
    summary="Executable CI shell fields need the same upstream analyzers as standalone scripts.",
    harm="Shell defects in inline CI programs evade the shared policy or receive duplicate workflow findings.",
    languages=frozenset({Language.SHELL}),
    bad_examples=("echo $value\n",),
    good_examples=('echo "$value"\n',),
    exclusions=("Non-shell interpreters", "Hadolint-owned Docker shell semantics"),
)


def _workflow(body: str, *, shell: str = "bash", style: str = "|") -> str:
    run = "".join(f"          {line}\n" for line in body.splitlines())
    return f"name: checks\n'on': push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - shell: {shell}\n        run: {style}\n{run}        name: checks\n"


def _path(root: Path, relative: str, source: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source.encode("utf-8"))
    return path


@pytest.mark.parametrize(
    "case",
    [
        EvaluationCase("unquoted-variable", Language.SHELL, "echo $value\n", ExpectedOutcome.MATCH),
        EvaluationCase("quoted-variable", Language.SHELL, 'echo "$value"\n'),
        EvaluationCase("comment-only", Language.SHELL, "# echo $value\ntrue\n"),
    ],
    ids=("unquoted-variable", "quoted-variable", "comment-only"),
)
def test_labeled_workflow_shellcheck_cases_map_to_authored_source(tmp_path: Path, case: EvaluationCase) -> None:
    assert case.language in PROBLEM.languages
    path = _path(tmp_path, ".github/workflows/checks.yml", _workflow(case.source))
    [report] = embedded_shell.analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shellcheck"}))
    assert report.completion is Completion.COMPLETE
    findings = [item for item in report.diagnostics if item.rule_id == "SC2086"]
    assert bool(findings) == (case.expected is ExpectedOutcome.MATCH)
    if findings:
        [finding] = findings
        assert finding.location.path == ".github/workflows/checks.yml"
        assert finding.location.region is not None
        assert finding.location.region.start.line == 8
        assert finding.location.region.start.character == 15
        assert finding.location.region.start.byte_offset == path.read_bytes().index(b"$value")


@pytest.mark.parametrize("style", ["|", "|-", "|+", "|2-"])
def test_literal_yaml_fixes_converge_and_preserve_execution(tmp_path: Path, style: str) -> None:
    body = "if true; then\necho ok\nfi\ncat <<'DATA'\n  literal $value\nDATA\n"
    source = _workflow(body, style=style)
    path = _path(tmp_path, ".github/workflows/checks.yml", source)
    before = execution_blocks(path.relative_to(tmp_path).as_posix(), source)
    [report] = embedded_shell.analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shfmt"}))
    assert report.completion is Completion.COMPLETE
    assert report.diagnostics
    assert shell_format.fix_sources(tmp_path, (str(path),)) == 0
    updated = path.read_text()
    assert f"run: {style}\n" in updated
    assert "            echo ok\n" in updated
    assert "            literal $value\n" in updated
    assert "        name: checks\n" in updated
    assert shell_format.fix_sources(tmp_path, (str(path),)) == 0
    assert path.read_text() == updated
    after = execution_blocks(path.relative_to(tmp_path).as_posix(), updated)
    assert len(after) == len(before)
    assert after[0].source.endswith("  literal $value\nDATA" + ("\n" if style in {"|", "|+"} else ""))


def test_crlf_yaml_and_non_ascii_positions(tmp_path: Path) -> None:
    source = _workflow('echo "😀" $value\nif true; then\necho ok\nfi\n').replace("\n", "\r\n")
    path = _path(tmp_path, ".github/workflows/checks.yml", source)
    [report] = embedded_shell.analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shellcheck"}))
    finding = next(item for item in report.diagnostics if item.rule_id == "SC2086")
    assert finding.location.region is not None
    assert finding.location.region.start.byte_offset == path.read_bytes().index(b"$value")
    assert finding.location.region.start.character == 20
    assert shell_format.fix_sources(tmp_path, (str(path),)) == 0
    assert b"\r\n            echo ok\r\n" in path.read_bytes()
    assert b"\n" not in path.read_bytes().replace(b"\r\n", b"")


@pytest.mark.parametrize("form", ["template", "folded", "alias", "parent-alias", "argv"])
def test_check_only_forms_never_rewrite_the_owner(tmp_path: Path, form: str) -> None:
    relative = ".github/workflows/checks.yml"
    source = _workflow("if true; then\necho ok\nfi\n")
    if form == "template":
        source = _workflow('if true; then\necho "${{ github.ref }}"\nfi\n')
    elif form == "folded":
        source = _workflow("if true; then\necho ok; fi\n", style=">-")
    elif form == "alias":
        source = source.replace("run: |", "run: &program |") + "      - shell: bash\n        run: *program\n"
    elif form == "parent-alias":
        source = source.replace("- shell: bash", "- &step\n        shell: bash") + "      - *step\n"
    elif form == "argv":
        relative = "cloudbuild.yaml"
        source = "steps:\n  - name: bash\n    entrypoint: bash\n    args: ['-c', 'if true; then echo ok; fi']\n"
    path = _path(tmp_path, relative, source)
    reports = embedded_shell.analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shfmt"}))
    assert reports
    assert all(item.completion is Completion.COMPLETE for item in reports)
    assert all("manually" in item.help for report in reports for item in report.diagnostics if item.help)
    assert shell_format.fix_sources(tmp_path, (str(path),)) == 0
    assert path.read_text() == source


@pytest.mark.parametrize(
    ("shell", "expected"),
    [
        pytest.param("python", False, id="python-default"),
        pytest.param("bash -e {0}", True, id="custom-bash"),
        pytest.param("pwsh", False, id="powershell"),
    ],
)
def test_inherited_shell_and_custom_argv_choose_actual_language(tmp_path: Path, shell: str, *, expected: bool) -> None:
    source = _workflow("echo $value\n").replace("      - shell: bash\n", "      - id: check\n")
    source = source.replace("jobs:\n", f"defaults:\n  run:\n    shell: {shell}\njobs:\n")
    path = _path(tmp_path, ".github/workflows/checks.yml", source)
    reports = embedded_shell.analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shellcheck"}))
    assert bool(reports) is expected
    assert all(item.completion is Completion.COMPLETE for item in reports)


@pytest.mark.parametrize("shebang", ["#!/usr/bin/env python3", "#!/bin/sh", "#!/usr/bin/env -S zsh -e"])
def test_cloudbuild_script_shebang_controls_native_coverage(tmp_path: Path, shebang: str) -> None:
    path = _path(
        tmp_path, "cloudbuild.yml", f"steps:\n  - name: image\n    script: |\n      {shebang}\n      echo $value\n"
    )
    reports = embedded_shell.analyze_sources(
        root=tmp_path, paths=(str(path),), selected=frozenset({"shellcheck", "shfmt"})
    )
    if "python" in shebang:
        assert reports == ()
    elif "zsh" in shebang:
        assert next(item for item in reports if item.name == "shellcheck").completion is Completion.FAILED
        assert next(item for item in reports if item.name == "shfmt").completion is Completion.COMPLETE
    else:
        assert next(item for item in reports if item.name == "shellcheck").diagnostics


def test_make_mise_composite_and_shell_argv_share_shellcheck(tmp_path: Path) -> None:
    sources = {
        "Makefile": "check:\n\techo $$value\n",
        "mise.toml": '[tasks.check]\nrun = "echo $value"\n',
        "action.yml": "name: check\nruns:\n  using: composite\n  steps:\n    - shell: bash\n      run: echo $value\n",
        "cloudbuild.yaml": "steps:\n  - name: image\n    entrypoint: bash\n    args: ['-c', 'echo $$value']\n",
    }
    paths = tuple(str(_path(tmp_path, name, source)) for name, source in sources.items())
    reports = embedded_shell.analyze_sources(root=tmp_path, paths=paths, selected=frozenset({"shellcheck"}))
    assert len(reports) == len(sources)
    assert all(item.completion is Completion.COMPLETE for item in reports)
    assert all(any(finding.rule_id == "SC2086" for finding in item.diagnostics) for item in reports)


def test_non_execution_data_and_docker_semantics_do_not_duplicate_shellcheck(tmp_path: Path) -> None:
    sources = {
        "settings.yaml": "note: 'echo $value'\n",
        "Dockerfile": "FROM alpine\nRUN echo $value\n",
        "cloudbuild.yaml": "steps:\n  - name: image\n    entrypoint: echo\n    args: ['$value']\n",
    }
    paths = tuple(str(_path(tmp_path, name, source)) for name, source in sources.items())
    assert embedded_shell.analyze_sources(root=tmp_path, paths=paths, selected=frozenset({"shellcheck"})) == ()


def test_malformed_block_prevents_standalone_and_yaml_partial_fixes(tmp_path: Path) -> None:
    shell = _path(tmp_path, "a.sh", "#!/bin/bash\nif true; then\necho ok\nfi\n")
    config = _path(tmp_path, ".github/workflows/checks.yml", _workflow("if true; then\n"))
    original = shell.read_bytes()
    [report] = embedded_shell.analyze_sources(root=tmp_path, paths=(str(config),), selected=frozenset({"shfmt"}))
    assert report.completion is Completion.FAILED
    assert shell_format.fix_sources(tmp_path, (str(shell), str(config))) == 2
    assert shell.read_bytes() == original


@pytest.mark.parametrize("body", ["if true; then\necho ok\nfi\n", "if true; then\n"])
def test_literal_formatting_obeys_scoped_manifest_exclusion(tmp_path: Path, body: str) -> None:
    path = _path(tmp_path, ".github/workflows/checks.yml", _workflow(body))
    before = path.read_bytes()
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=(),
        python_dest=".",
        typescript_dest=".",
        exclusion_overrides=(manifest.ExclusionOverride((".github/**",), ("shfmt:format",), "fixture"),),
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render())
    assert embedded_shell.analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shfmt"})) == ()
    assert shell_format.fix_sources(tmp_path, (str(path),)) == 0
    assert path.read_bytes() == before


def test_actionlint_disables_builtin_shellcheck_only_with_shared_coverage(tmp_path: Path) -> None:
    source = _workflow("echo $value\n")
    path = _path(tmp_path, ".github/workflows/checks.yml", source)
    reports = analyze_external(
        (str(path),), root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"actionlint", "shellcheck"})
    )
    assert any(item.name == "shellcheck" and item.diagnostics for item in reports)
    assert not any(
        item.source == "actionlint" and "SC2086" in item.message for report in reports for item in report.diagnostics
    )
    [legacy] = devops_source.analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"actionlint"}))
    assert any("SC2086" in item.message for item in legacy.diagnostics)
    commands = lifecycle.selected_format_commands(tmp_path, (str(path),))
    assert any(item.label == "Shell format" for item in commands)


@pytest.mark.parametrize(
    ("shell", "completion"),
    [
        pytest.param("env bash -e {0}", Completion.COMPLETE, id="env-wrapper"),
        pytest.param("bash --invented {0}", Completion.FAILED, id="unproven-shell-option"),
        pytest.param("bash -e", Completion.FAILED, id="missing-script-placeholder"),
        pytest.param("bash -c {0}", Completion.FAILED, id="command-template-does-not-execute-script"),
    ],
)
def test_custom_interpreter_flags_use_shared_argv_grammar(tmp_path: Path, shell: str, completion: Completion) -> None:
    path = _path(tmp_path, ".github/workflows/checks.yml", _workflow("echo $value\n", shell=shell))
    [report] = embedded_shell.analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shellcheck"}))
    assert report.completion is completion


def test_windows_default_does_not_get_bash_analysis(tmp_path: Path) -> None:
    source = _workflow("Write-Host hello\n").replace("runs-on: ubuntu-latest", "runs-on: windows-latest")
    source = source.replace("      - shell: bash\n", "      - id: check\n")
    path = _path(tmp_path, ".github/workflows/checks.yml", source)
    assert (
        embedded_shell.analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shellcheck", "shfmt"}))
        == ()
    )


def test_cloudbuild_shebang_flags_preserve_script_coverage_and_literal_fixes(tmp_path: Path) -> None:
    path = _path(
        tmp_path,
        "cloudbuild.yaml",
        "steps:\n  - name: bash\n    script: |\n      #!/usr/bin/env -S bash -e\n      if true; then\n      echo $value\n      fi\n",
    )
    reports = embedded_shell.analyze_sources(
        root=tmp_path, paths=(str(path),), selected=frozenset({"shellcheck", "shfmt"})
    )
    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert any(item.rule_id == "SC2086" for report in reports for item in report.diagnostics)
    assert shell_format.fix_sources(tmp_path, (str(path),)) == 0
    assert "        echo $value\n" in path.read_text()
