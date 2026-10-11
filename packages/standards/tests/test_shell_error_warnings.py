from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode
from sarj_standards.libs.linting.devops_tools import checked_tool, invoke
from sarj_standards.libs.linting.external import analyze_external, parse_shellcheck
from sarj_standards.libs.repository import shell_checks
from sarj_standards.libs.rules import EvaluationCase, ExpectedOutcome, Language, RuleProblem


if TYPE_CHECKING:
    from pathlib import Path


PROBLEM = RuleProblem(
    key="shell-suppressed-errexit",
    summary="Bash silently ignores errexit in some function-call contexts.",
    harm="CI scripts can continue after failures in conditional functions or command substitutions.",
    languages=frozenset({Language.SHELL}),
    bad_examples=("set -e\nf() { false; echo continued; }\nif f; then :; fi\n",),
    good_examples=("set -e\nf() { false || return; echo continued; }\nf\n",),
    exclusions=("Intentional predicate functions require human review",),
)


@pytest.mark.parametrize(
    ("case", "rule"),
    [
        pytest.param(
            EvaluationCase(
                "conditional-call",
                Language.SHELL,
                "set -e\nf() { false; echo continued; }\nif f; then :; fi\n",
                ExpectedOutcome.MATCH,
            ),
            "SC2310",
            id="conditional-call",
        ),
        pytest.param(
            EvaluationCase(
                "substitution-call",
                Language.SHELL,
                'set -e\nf() { false; echo continued; }\nvalue=$(f)\nprintf "%s\\n" "$value"\n',
                ExpectedOutcome.MATCH,
            ),
            "SC2311",
            id="substitution-call",
        ),
        pytest.param(
            EvaluationCase(
                "direct-checked-call", Language.SHELL, "set -e\nf() { false || return; echo continued; }\nf\n"
            ),
            "SC2310",
            id="direct-checked-call",
        ),
        pytest.param(
            EvaluationCase("no-errexit", Language.SHELL, "f() { false; echo continued; }\nif f; then :; fi\n"),
            "SC2310",
            id="no-errexit",
        ),
        pytest.param(
            EvaluationCase(
                "intentional-predicate-review",
                Language.SHELL,
                "set -e\npredicate() { test -f optional; }\nif predicate; then :; fi\n",
                ExpectedOutcome.MATCH,
            ),
            "SC2310",
            id="intentional-predicate-review",
        ),
        pytest.param(
            EvaluationCase(
                "inline-suppression",
                Language.SHELL,
                "set -e\nf() { false; echo continued; }\n# shellcheck disable=SC2310\nif f; then :; fi\n",
            ),
            "SC2310",
            id="inline-suppression",
        ),
        pytest.param(
            EvaluationCase("comment-data", Language.SHELL, "set -e\n# if f; then :; fi\nprintf '%s\\n' 'value=$(f)'\n"),
            "SC2311",
            id="comment-data",
        ),
    ],
)
def test_labeled_suppressed_errexit_findings_are_warnings(tmp_path: Path, case: EvaluationCase, rule: str) -> None:
    assert case.language in PROBLEM.languages
    path = tmp_path / "job.bash"
    path.write_text("#!/bin/bash\n" + case.source)
    [report] = analyze_external(
        (str(path),), root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"shellcheck"})
    )
    assert report.completion is Completion.COMPLETE
    findings = [item for item in report.diagnostics if item.rule_id == rule]
    assert bool(findings) == (case.expected is ExpectedOutcome.MATCH)
    assert all(item.severity is Severity.WARNING for item in findings)


@pytest.mark.parametrize(
    ("relative", "prefix", "expected"),
    [
        pytest.param(".github/workflows/warnings.yml", "", True, id="actions-implied-errexit"),
        pytest.param("cloudbuild.yaml", "#!/usr/bin/env -S bash -e\n", True, id="cloudbuild-shebang-errexit"),
        pytest.param("cloudbuild.yaml", "#!/bin/bash\n", False, id="cloudbuild-without-errexit"),
    ],
)
def test_embedded_warning_coverage_follows_runtime_errexit(
    tmp_path: Path, relative: str, prefix: str, *, expected: bool
) -> None:
    program = prefix + "f() { false; echo continued; }\nif f; then :; fi\n"
    if relative.startswith(".github/"):
        source = "name: checks\n'on': push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - shell: bash\n        run: |\n"
        indentation = "          "
    else:
        source = "steps:\n  - name: bash\n    script: |\n"
        indentation = "      "
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source + "".join(indentation + line + "\n" for line in program.splitlines()))
    [report] = analyze_external(
        (str(path),), root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"shellcheck"})
    )
    assert report.completion is Completion.COMPLETE
    findings = [item for item in report.diagnostics if item.rule_id == "SC2310"]
    assert bool(findings) is expected
    assert all(item.severity is Severity.WARNING and item.location.path == relative for item in findings)
    for finding in findings:
        assert finding.location.region is not None
        offset = finding.location.region.start.byte_offset
        assert offset is not None
        assert path.read_bytes()[offset : offset + 1] == b"f"


@pytest.mark.parametrize(
    ("source", "status", "rule"),
    [
        pytest.param(
            "set -e\nf() { false; echo continued; }\nif f; then :; fi\n", 0, "SC2310", id="new-warning-nonblocking"
        ),
        pytest.param('set -e\nprintf "%s\\n" "$(false)"\n', 1, "SC2312", id="existing-masked-return-gate"),
        pytest.param("echo $1\n", 1, "SC2086", id="existing-word-splitting-gate"),
    ],
)
def test_native_repository_gate_keeps_new_review_rules_nonblocking(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], source: str, status: int, rule: str
) -> None:
    scripts = tmp_path / ".github/scripts"
    scripts.mkdir(parents=True)
    (scripts / "job.sh").write_text("#!/bin/bash\n" + source)
    assert shell_checks.check(tmp_path, tool="shellcheck") == status
    output = capsys.readouterr().out
    assert ".github/scripts/job.sh:" in output
    assert rule in output


@pytest.mark.parametrize(
    ("source", "status", "rules"),
    [
        pytest.param(
            "set -e\nf() { false; echo continued; }\nif f; then :; fi\n",
            0,
            frozenset[str](),
            id="conditional-call-advisory",
        ),
        pytest.param(
            'set -e\nf() { false; echo continued; }\nvalue=$(f)\nprintf "%s\\n" "$value"\n',
            0,
            frozenset[str](),
            id="substitution-call-advisory",
        ),
        pytest.param(
            'set -e\nprintf "%s\\n" "$(false)"\n',
            1,
            frozenset({"SC2312"}),
            id="masked-return-still-blocks",
        ),
        pytest.param("echo $1\n", 1, frozenset({"SC2086"}), id="word-splitting-still-blocks"),
    ],
)
def test_direct_native_config_preserves_advisory_exit_behavior(
    tmp_path: Path, source: str, status: int, rules: frozenset[str]
) -> None:
    config = tmp_path / ".shellcheckrc"
    config.write_bytes((CONFIGS_DIR / "shellcheck.strict.rc").read_bytes())
    script = tmp_path / "job.sh"
    script.write_text("#!/bin/bash\n" + source)
    output = invoke(
        checked_tool("shellcheck", root=tmp_path),
        ("--rcfile", str(config), "--format=json1", str(script)),
        root=tmp_path,
    )
    assert output.returncode == status
    assert frozenset(item.rule_id for item in parse_shellcheck(output.stdout, root=tmp_path)) == rules
