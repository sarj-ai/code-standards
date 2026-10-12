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
        "suppression", Language.PYTHON, _BASE.replace("process.kill()", "process.kill()  # sarj-noqa: SARJ464")
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


@pytest.mark.parametrize(
    "cleanup",
    [
        pytest.param("process._wait(timeout=None)", id="internal-wait"),
        pytest.param("process._try_wait(0)", id="internal-try-wait"),
        pytest.param("process._internal_poll()", id="internal-poll"),
        pytest.param("process.__exit__(None, None, None)", id="explicit-context-exit"),
        pytest.param("os.waitpid(-1, 0)", id="wait-any-child"),
        pytest.param("os.wait()", id="wait"),
        pytest.param("os.wait3(0)", id="wait3"),
        pytest.param("os.wait4(-1, 0)", id="wait4"),
        pytest.param("os.waitid(os.P_ALL, 0, os.WEXITED)", id="waitid"),
    ],
)
def test_visible_alternative_reapers(cleanup: str) -> None:
    source = "import os\n" + _BASE + "    " + cleanup + "\n"
    assert not SubprocessKillWithoutReap().check(Path("app/processes.py"), source)


@pytest.mark.parametrize(
    "ownership",
    [
        pytest.param("import signal\nsignal.signal(signal.SIGCHLD, signal.SIG_IGN)\n", id="ignored-child-signal"),
        pytest.param(
            "import os, signal\ndef reap(*args): os.waitpid(-1, os.WNOHANG)\nsignal.signal(signal.SIGCHLD, reap)\n",
            id="global-signal-reaper",
        ),
        pytest.param("from signal import SIGCHLD as child_signal\nconfigure(child_signal)\n", id="signal-alias"),
        pytest.param("from os import waitpid as reap\n", id="reaper-import"),
        pytest.param("import os\nalias = os\n", id="os-module-alias"),
        pytest.param("import signal\nalias = signal\n", id="signal-module-alias"),
    ],
)
def test_global_child_ownership_is_not_inferred(ownership: str) -> None:
    assert not SubprocessKillWithoutReap().check(Path("app/processes.py"), ownership + _BASE)


@pytest.mark.parametrize(
    "ownership",
    [
        "def configure():\n    import signal as local_signal\n    local_signal.signal(local_signal.SIGCHLD, local_signal.SIG_IGN)\nconfigure()\n",
        "def reap():\n    import os as local_os\n    local_os.waitpid(-1, 0)\n",
        "def configure():\n    import signal as local_signal\n    configure_children(local_signal)\nconfigure()\n",
        "def configure():\n    import os as local_os\n    configure_children(local_os)\nconfigure()\n",
        "def reap():\n    import os as local_os\n    local_os.waitid(local_os.P_ALL, 0, local_os.WEXITED)\n",
    ],
)
def test_nested_child_ownership_is_not_inferred(ownership: str) -> None:
    source = ownership + _BASE + "    reap()\n"
    assert not SubprocessKillWithoutReap().check(Path("app/processes.py"), source)


def test_bound_process_setter_invalidates_kill_proof() -> None:
    source = _BASE.replace(
        "        process.kill()",
        "        process.__setattr__('kill', lambda: (process.terminate(), process.wait()))\n        process.kill()",
    )
    assert not SubprocessKillWithoutReap().check(Path("app/processes.py"), source)


@pytest.mark.parametrize(
    "replacement",
    [
        "globals()['subprocess'] = custom",
        "namespace = globals\nnamespace()['subprocess'] = custom",
        "import sys\nsys.modules['subprocess'].Popen = custom",
        "from importlib import import_module as load\nload('subprocess').Popen = custom",
    ],
)
def test_dynamic_process_constructors_are_not_proven(replacement: str) -> None:
    assert not SubprocessKillWithoutReap().check(
        Path("app/processes.py"), _BASE.replace("def run", replacement + "\ndef run")
    )


@pytest.mark.parametrize(
    "change",
    [
        "subprocess.Popen.kill = proper_kill",
        "klass = subprocess.Popen\nklass.kill = proper_kill",
        "setattr(subprocess.Popen, 'kill', proper_kill)",
        "class Holder:\n    import subprocess as local_s\n    local_s.Popen.kill = proper_kill",
        "class Holder:\n    import subprocess as local_s\n    klass = local_s.Popen\n    klass.kill = proper_kill",
    ],
)
def test_canonical_process_aliases_can_replace_kill_with_complete_cleanup(change: str) -> None:
    source = _BASE.replace("subprocess.Popen(args)", "Popen(args)").replace(
        "subprocess.TimeoutExpired", "TimeoutExpired"
    )
    source = source.replace("def run", "from subprocess import Popen, TimeoutExpired\n" + change + "\ndef run")
    assert not SubprocessKillWithoutReap().check(Path("app/processes.py"), source)


def test_relative_import_is_not_a_proven_stdlib_process() -> None:
    source = (
        _BASE.replace("import subprocess", "from .subprocess import Popen, TimeoutExpired")
        .replace("subprocess.Popen", "Popen")
        .replace("subprocess.TimeoutExpired", "TimeoutExpired")
    )
    assert not SubprocessKillWithoutReap().check(Path("app/processes.py"), source)
