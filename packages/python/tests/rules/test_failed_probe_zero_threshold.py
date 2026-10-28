from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.failed_probe_zero_threshold import FailedProbeZeroThreshold


_SOURCE = """import subprocess

def read_status():
    try:
        result = subprocess.run(["service", "status"], capture_output=True, text=True, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return None if result.returncode else result.stdout

def active_count():
    output = read_status()
    return None if output is None else output.count("active")

def recovered(baseline: int) -> bool:
    if (active_count() or 0) >= baseline:
        return True
    return False
"""
_CASES = (
    EvaluationCase("error-accepted-as-zero", Language.PYTHON, _SOURCE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "literal-zero-threshold", Language.PYTHON, _SOURCE.replace(">= baseline", ">= 0"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "optional-int-threshold",
        Language.PYTHON,
        _SOURCE.replace("baseline: int", "baseline: int | None").replace(
            "    if (active_count()", "    if baseline is None:\n        return True\n    if (active_count()"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _SOURCE.replace("import subprocess", "import subprocess as commands").replace("subprocess.", "commands."),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "symbol-alias",
        Language.PYTHON,
        _SOURCE.replace("import subprocess", "from subprocess import run as execute, TimeoutExpired")
        .replace("subprocess.run", "execute")
        .replace("subprocess.TimeoutExpired", "TimeoutExpired"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("positive-threshold", Language.PYTHON, _SOURCE.replace(">= baseline", ">= 1")),
    EvaluationCase(
        "explicit-zero-skip",
        Language.PYTHON,
        _SOURCE.replace("    if (active_count()", "    if baseline == 0:\n        return True\n    if (active_count()"),
    ),
    EvaluationCase(
        "validated-baseline",
        Language.PYTHON,
        _SOURCE.replace("    if (active_count()", "    require_positive(baseline)\n    if (active_count()"),
    ),
    EvaluationCase("failure-sentinel-not-none", Language.PYTHON, _SOURCE.replace("return None", "return 0")),
    EvaluationCase(
        "optional-business-value",
        Language.PYTHON,
        _SOURCE.replace("result = subprocess.run", "result = read_optional_count"),
    ),
    EvaluationCase("not-text-output", Language.PYTHON, _SOURCE.replace("text=True", "text=False")),
    EvaluationCase("unknown-run-options", Language.PYTHON, _SOURCE.replace("check=False", "**options")),
    EvaluationCase(
        "imported-count-helper",
        Language.PYTHON,
        _SOURCE.replace("def active_count():", "from metrics import active_count\n\ndef unused_count():"),
    ),
    EvaluationCase("rebound-count-helper", Language.PYTHON, _SOURCE + "\nactive_count = replacement\n"),
    EvaluationCase("escaped-count-helper", Language.PYTHON, _SOURCE + "\nregister(active_count)\n"),
    EvaluationCase("module-escape", Language.PYTHON, _SOURCE + "\nconfigure(subprocess)\n"),
    EvaluationCase("api-escape", Language.PYTHON, _SOURCE + "\nexecute = subprocess.run\n"),
    EvaluationCase(
        "cross-alias-mutation",
        Language.PYTHON,
        _SOURCE + "\nimport subprocess as commands\ncommands.run = replacement\n",
    ),
    EvaluationCase(
        "parameter-shadow", Language.PYTHON, _SOURCE.replace("def read_status():", "def read_status(subprocess):")
    ),
    EvaluationCase(
        "result-rebinding",
        Language.PYTHON,
        _SOURCE.replace(
            "    return None if result.returncode", "    result = replacement\n    return None if result.returncode"
        ),
    ),
    EvaluationCase("reflection", Language.PYTHON, _SOURCE + "\nexec(configuration)\n"),
    EvaluationCase("wildcard", Language.PYTHON, "from extension import *\n" + _SOURCE),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _SOURCE),
    EvaluationCase("malformed", Language.PYTHON, "def recovered(:"),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_probe_cases(case: EvaluationCase) -> None:
    findings = FailedProbeZeroThreshold().check(Path("app/recovery.py"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)


def test_warning_is_at_the_fallback_and_can_be_suppressed() -> None:
    rule = FailedProbeZeroThreshold()
    findings = rule.check(Path("app/recovery.py"), _SOURCE)
    assert [(item.code, item.line, item.col, item.severity) for item in findings] == [
        ("SARJ538", 15, 9, Severity.WARNING)
    ]
    suppressed = _SOURCE.replace(
        ">= baseline:", ">= baseline:  # sarj-noqa: SARJ538 -- explicit optional zero recovery policy"
    )
    assert rule.check(Path("app/recovery.py"), suppressed) == []


def test_none_return_before_proven_raising_failure_is_a_success_sink() -> None:
    source = _SOURCE.replace("def recovered(baseline: int) -> bool:", "def recovered(baseline: int) -> None:")
    source = source.replace("return True", "return").replace("    return False", "    fail()")
    source += "\ndef fail():\n    raise RuntimeError('Recovery failed')\n"
    assert len(FailedProbeZeroThreshold().check(Path("app/recovery.py"), source)) == 1


@pytest.mark.parametrize("finalizer", ["return False", "raise RuntimeError('Rejected')"])
def test_finally_can_override_the_apparent_success(finalizer: str) -> None:
    original = "    if (active_count() or 0) >= baseline:\n        return True\n    return False"
    replacement = (
        "    try:\n        if (active_count() or 0) >= baseline:\n            return True\n        return False\n    finally:\n        "
        + finalizer
    )
    source = _SOURCE.replace(original, replacement)
    assert FailedProbeZeroThreshold().check(Path("app/recovery.py"), source) == []


def test_runtime_test_files_are_excluded() -> None:
    assert FailedProbeZeroThreshold().check(Path("tests/test_recovery.py"), _SOURCE) == []


def test_documented_examples() -> None:
    assert verify_native_rule(FailedProbeZeroThreshold, analyze) == 2
