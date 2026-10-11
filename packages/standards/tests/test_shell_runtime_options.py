from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion, Severity
from sarj_standards.libs.linting.embedded_shell import analyze_sources
from sarj_standards.libs.linting.external import run_process
from sarj_standards.libs.rules import EvaluationCase, ExpectedOutcome, Language, RuleProblem


if TYPE_CHECKING:
    from pathlib import Path


PROBLEM = RuleProblem(
    key="shell-runtime-option-state",
    summary="CI shell diagnostics must use effective interpreter options.",
    harm="Option operands, script arguments and disabled flags currently produce false errexit warnings.",
    languages=frozenset({Language.SHELL}),
    bad_examples=("bash -e +e script.sh", "bash script.sh -e"),
    good_examples=("bash -e script.sh",),
    exclusions=("Unproven invocations remain coverage failures",),
)


@pytest.mark.parametrize(
    "shell",
    [
        pytest.param("bash {0}", id="no-options"),
        pytest.param("bash -e {0}", id="short-errexit"),
        pytest.param("bash -e +e {0}", id="short-disabled-last"),
        pytest.param("bash +e -e {0}", id="short-enabled-last"),
        pytest.param("bash -o errexit +o errexit {0}", id="named-disabled-last"),
        pytest.param("bash +o errexit -o errexit {0}", id="named-enabled-last"),
        pytest.param("bash {0} -e", id="script-argument"),
        pytest.param("bash -- {0} -e", id="option-terminator"),
        pytest.param("bash --init-file -e {0}", id="option-operand"),
        pytest.param("bash -e +o errexit {0}", id="mixed-disable"),
        pytest.param("bash -o errexit +e {0}", id="mixed-short-disable"),
        pytest.param("bash -eu +u {0}", id="unrelated-disable"),
        pytest.param("env MODE=test bash -e +e {0}", id="env-wrapper"),
    ],
)
def test_embedded_errexit_warnings_match_native_bash(tmp_path: Path, shell: str) -> None:
    script = tmp_path / "probe.sh"
    script.write_text('printf "%s\\n" "$-"\n')
    words = tuple(part.replace("{0}", str(script)) for part in shlex.split(shell))
    result = run_process(words, cwd=tmp_path)
    assert result.returncode == 0
    assert not result.stderr
    expected = "e" in result.stdout.strip()
    case = EvaluationCase(
        shell,
        Language.SHELL,
        "f() { false; echo continued; }\nif f; then :; fi\n",
        ExpectedOutcome.MATCH if expected else ExpectedOutcome.NO_MATCH,
    )
    assert case.language in PROBLEM.languages
    path = tmp_path / ".github/workflows/job.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "name: checks\n'on': push\njobs:\n  job:\n    runs-on: ubuntu-latest\n    steps:\n"
        f"      - shell: {shell}\n        run: |\n"
        + "".join("          " + line + "\n" for line in case.source.splitlines())
    )
    [report] = analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    assert report.completion is Completion.COMPLETE
    findings = [item for item in report.diagnostics if item.rule_id == "SC2310"]
    assert bool(findings) is expected
    assert all(item.severity is Severity.WARNING for item in findings)
    for finding in findings:
        assert finding.location.region is not None
        offset = finding.location.region.start.byte_offset
        assert offset is not None
        assert path.read_bytes()[offset : offset + 1] == b"f"
