from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rules.subprocess_kill_without_reap import SubprocessKillWithoutReap


_BASE = "import subprocess\ndef run(args):\n    process = subprocess.Popen(args)\n    try:\n        process.communicate(timeout=1)\n    except subprocess.TimeoutExpired:\n        process.kill()\n"
CASES = (
    EvaluationCase("kill-only", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase("wait-timeout", Language.PYTHON, _BASE.replace("communicate", "wait"), ExpectedOutcome.MATCH),
    EvaluationCase("reaped", Language.PYTHON, _BASE + "        process.wait()\n"),
    EvaluationCase("drained", Language.PYTHON, _BASE + "        process.communicate()\n"),
    EvaluationCase("later-reap", Language.PYTHON, _BASE + "    process.wait()\n"),
    EvaluationCase("finally-reap", Language.PYTHON, _BASE + "    finally:\n        process.wait()\n"),
    EvaluationCase("poll-after-kill", Language.PYTHON, _BASE + "    return process.poll()\n"),
    EvaluationCase("transferred-process", Language.PYTHON, _BASE + "    return process\n"),
    EvaluationCase(
        "external-cleanup", Language.PYTHON, _BASE.replace("    try:", "    register_cleanup(process.wait)\n    try:")
    ),
    EvaluationCase("unknown-process", Language.PYTHON, _BASE.replace("subprocess.Popen(args)", "start(args)")),
    EvaluationCase("shadowed-subprocess", Language.PYTHON, _BASE.replace("run(args)", "run(args, subprocess)")),
    EvaluationCase("rebound-process", Language.PYTHON, _BASE.replace("    try:", "    process = other\n    try:")),
    EvaluationCase(
        "unknown-exception", Language.PYTHON, _BASE.replace("except subprocess.TimeoutExpired", "except RuntimeError")
    ),
    EvaluationCase(
        "unrelated-timeout",
        Language.PYTHON,
        _BASE.replace("process.communicate(timeout=1)", "other.communicate(timeout=1)"),
    ),
    EvaluationCase("custom-kill", Language.PYTHON, _BASE.replace("    try:", "    process.kill = custom\n    try:")),
    EvaluationCase(
        "suppression", Language.PYTHON, _BASE.replace("process.kill()", "process.kill()  # sarj-noqa: SARJ463")
    ),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _BASE.replace("import subprocess", "import subprocess as sp").replace("subprocess.", "sp."),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "constructor-alias",
        Language.PYTHON,
        _BASE.replace("import subprocess", "from subprocess import Popen as spawn, TimeoutExpired as Expired")
        .replace("subprocess.Popen", "spawn")
        .replace("subprocess.TimeoutExpired", "Expired"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("malformed", Language.PYTHON, "try:"),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = SubprocessKillWithoutReap().check(Path("app/processes.py"), case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)


@pytest.mark.parametrize(
    "source",
    [
        _BASE.replace("    process = subprocess.Popen(args)", "    with subprocess.Popen(args) as process:")
        .replace("    try:", "        try:")
        .replace("        process.communicate", "            process.communicate")
        .replace("    except subprocess.TimeoutExpired:", "        except subprocess.TimeoutExpired:")
        .replace("        process.kill", "            process.kill"),
        _BASE.replace(
            "def run(args):\n    process = subprocess.Popen(args)", "process = subprocess.Popen(args)\ndef run(args):"
        ),
        _BASE.replace("    try:", "    configure(subprocess)\n    try:"),
        _BASE.replace("    try:", "    match custom:\n        case subprocess:\n            pass\n    try:"),
    ],
    ids=["context-managed", "module-owned", "module-escape", "match-shadow"],
)
def test_managed_borrowed_and_mutated_resources_are_excluded(source: str) -> None:
    assert not SubprocessKillWithoutReap().check(Path("app/processes.py"), source)
