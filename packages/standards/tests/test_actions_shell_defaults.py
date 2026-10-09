from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting import textlint
from sarj_standards.libs.linting.devops_programs import ProgramProjectionError, block_embeds_program, execution_blocks
from sarj_standards.libs.linting.shell_ast import parse_shell


if TYPE_CHECKING:
    from pathlib import Path


def _workflow(
    *,
    workflow_shell: str | None = None,
    job_shell: str | None = None,
    step_shell: str | None = None,
    body: str = "pass",
) -> str:
    source = "name: shell controls\n'on': push\n"
    if workflow_shell is not None:
        source += f"defaults:\n  run:\n    shell: {workflow_shell}\n"
    source += "jobs:\n  controls:\n    runs-on: ubuntu-latest\n"
    if job_shell is not None:
        source += f"    defaults:\n      run:\n        shell: {job_shell}\n"
    source += f"    steps:\n      - run: |\n          {body}\n"
    if step_shell is not None:
        source += f"        shell: {step_shell}\n"
    return source


_CASES = (
    ("workflow-python", _workflow(workflow_shell="python"), "python", True),
    ("job-python", _workflow(job_shell="python"), "python", True),
    ("workflow-custom-python", _workflow(workflow_shell="python -u {0}"), "python -u {0}", True),
    (
        "job-custom-node",
        _workflow(workflow_shell="bash", job_shell="node {0}", body="process.exit(0)"),
        "node {0}",
        True,
    ),
    (
        "job-shell-overrides-workflow",
        _workflow(workflow_shell="python", job_shell="bash", body="python3 scripts/check.py"),
        "bash",
        False,
    ),
    (
        "step-shell-overrides-job",
        _workflow(workflow_shell="python", job_shell="python", step_shell="bash", body="python3 scripts/check.py"),
        "bash",
        False,
    ),
    (
        "step-python-overrides-bash",
        _workflow(workflow_shell="bash", job_shell="bash", step_shell="python"),
        "python",
        True,
    ),
    (
        "inherited-shell-wrapper",
        _workflow(workflow_shell="bash -e {0}", body="python3 scripts/check.py"),
        "bash -e {0}",
        False,
    ),
    ("default-shell-external-file", _workflow(body="python3 scripts/check.py"), "shell", False),
    ("inherited-inline-interpreter", _workflow(workflow_shell="bash", body="python3 -c 'print(1)'"), "bash", True),
    ("absolute-interpreter-shell", _workflow(job_shell="/usr/bin/python3 -u {0}"), "/usr/bin/python3 -u {0}", True),
    (
        "job-working-directory-inherits-shell",
        _workflow(workflow_shell="python").replace(
            "    steps:\n", "    defaults:\n      run:\n        working-directory: scripts\n    steps:\n"
        ),
        "python",
        True,
    ),
    ("non-execution-shell-data", _workflow(body="printf %s 'python -c pass'"), "shell", False),
)


@pytest.mark.parametrize(("case_id", "source", "interpreter", "embedded"), _CASES, ids=[case[0] for case in _CASES])
def test_actions_shell_precedence_controls(
    tmp_path: Path, case_id: str, source: str, interpreter: str, *, embedded: bool
) -> None:
    relative = ".github/workflows/controls.yml"
    [block] = execution_blocks(relative, source)
    assert execution_blocks(relative, source) == [block]
    assert block.interpreter == interpreter, case_id
    assert block_embeds_program(block, parse_shell=parse_shell) is embedded, case_id
    expected_line = next(number for number, line in enumerate(source.splitlines(), 1) if "- run:" in line)
    assert block.line == expected_line
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    findings = textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"}))
    assert len(findings) == int(embedded)
    assert all(finding.line == expected_line for finding in findings)


@pytest.mark.parametrize("shell", ["pwsh", "cmd", "./scripts/custom {0}", "${{ matrix.shell }}"])
def test_inherited_unknown_shell_retains_coverage_failure(shell: str) -> None:
    [block] = execution_blocks(".github/workflows/controls.yml", _workflow(workflow_shell=shell, body="make test"))
    with pytest.raises(ProgramProjectionError, match="unsupported configuration execution shell"):
        block_embeds_program(block, parse_shell=parse_shell)


def test_job_shell_does_not_leak_to_sibling_job() -> None:
    source = (
        _workflow(job_shell="python")
        + "  sibling:\n    runs-on: ubuntu-latest\n    steps:\n      - run: python3 scripts/check.py\n"
    )
    blocks = execution_blocks(".github/workflows/controls.yml", source)
    assert [block.interpreter for block in blocks] == ["python", "shell"]
    assert [block_embeds_program(block, parse_shell=parse_shell) for block in blocks] == [True, False]


def test_composite_action_projects_each_explicit_step_shell() -> None:
    source = "name: controls\ndescription: controls\nruns:\n  using: composite\n  steps:\n    - run: pass\n      shell: python\n    - run: python3 scripts/check.py\n      shell: bash\n"
    blocks = execution_blocks("action.yml", source)
    assert [block.interpreter for block in blocks] == ["python", "bash"]
    assert [block_embeds_program(block, parse_shell=parse_shell) for block in blocks] == [True, False]


def test_non_run_steps_do_not_become_execution_blocks() -> None:
    source = _workflow(workflow_shell="python").replace(
        "      - run: |\n          pass\n", "      - uses: actions/checkout@v5\n"
    )
    assert not execution_blocks(".github/workflows/controls.yml", source)


def test_aliased_default_shell_preserves_execution_use_site() -> None:
    source = "name: controls\n'on': push\ndefaults: &defaults\n  run:\n    shell: python\njobs:\n  controls:\n    runs-on: ubuntu-latest\n    defaults: *defaults\n    steps:\n      - run: pass\n"
    [block] = execution_blocks(".github/workflows/controls.yml", source)
    assert block.interpreter == "python"
    expected_line = next(number for number, line in enumerate(source.splitlines(), 1) if "- run:" in line)
    assert block.line == expected_line
    assert block_embeds_program(block, parse_shell=parse_shell)


def test_duplicate_default_shell_cannot_report_clean() -> None:
    source = _workflow(workflow_shell="python").replace("    shell: python\n", "    shell: python\n    shell: bash\n")
    with pytest.raises(ProgramProjectionError, match="duplicate YAML key: shell"):
        execution_blocks(".github/workflows/controls.yml", source)
