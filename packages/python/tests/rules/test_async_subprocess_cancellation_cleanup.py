from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.async_subprocess_cancellation_cleanup import AsyncSubprocessCancellationCleanup
from sarj_python_lint.rules.subprocess_kill_without_reap import SubprocessKillWithoutReap


_ASYNC_BASE = "import asyncio\n\nasync def run(args):\n    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)\n    return await process.communicate()\n"
ASYNC_CASES = (
    EvaluationCase("async-communicate", Language.PYTHON, _ASYNC_BASE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "async-wait",
        Language.PYTHON,
        _ASYNC_BASE.replace("process.communicate()", "process.wait()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "async-shell",
        Language.PYTHON,
        _ASYNC_BASE.replace("create_subprocess_exec(*args", "create_subprocess_shell(command"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "async-factory-alias",
        Language.PYTHON,
        _ASYNC_BASE.replace(
            "import asyncio", "import asyncio\nfrom asyncio import create_subprocess_exec as spawn"
        ).replace("await asyncio.create_subprocess_exec", "await spawn"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "async-module-alias",
        Language.PYTHON,
        _ASYNC_BASE.replace("import asyncio", "import asyncio as aio").replace("asyncio.", "aio."),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "borrowed-async-handle", Language.PYTHON, "async def run(process):\n    return await process.communicate()\n"
    ),
    EvaluationCase(
        "unknown-async-factory", Language.PYTHON, _ASYNC_BASE.replace("asyncio.create_subprocess_exec", "spawn")
    ),
    EvaluationCase("shadowed-asyncio", Language.PYTHON, _ASYNC_BASE.replace("run(args)", "run(args, asyncio)")),
    EvaluationCase(
        "transferred-async-handle",
        Language.PYTHON,
        _ASYNC_BASE.replace("    return await", "    supervisor.add(process)\n    return await"),
    ),
    EvaluationCase(
        "async-handle-alias",
        Language.PYTHON,
        _ASYNC_BASE.replace("    return await", "    alias = process\n    return await"),
    ),
    EvaluationCase(
        "async-cleanup-callback",
        Language.PYTHON,
        _ASYNC_BASE.replace("    return await", "    register_cleanup(process.wait)\n    return await"),
    ),
    EvaluationCase(
        "async-method-replaced",
        Language.PYTHON,
        _ASYNC_BASE.replace("    return await", "    process.communicate = custom\n    return await"),
    ),
    EvaluationCase(
        "conditional-async-owner",
        Language.PYTHON,
        _ASYNC_BASE.replace("    process =", "    if enabled:\n        process ="),
    ),
    EvaluationCase(
        "observed-async-returncode",
        Language.PYTHON,
        _ASYNC_BASE.replace(
            "    return await",
            "    if process.returncode is not None:\n        return process.returncode\n    return await",
        ),
    ),
    EvaluationCase(
        "async-shield",
        Language.PYTHON,
        _ASYNC_BASE.replace("await process.communicate()", "await asyncio.shield(process.communicate())"),
    ),
    EvaluationCase(
        "async-namespace-mutation",
        Language.PYTHON,
        _ASYNC_BASE.replace("async def run", "asyncio.create_subprocess_exec = custom\n\nasync def run"),
    ),
    EvaluationCase(
        "async-suppression",
        Language.PYTHON,
        _ASYNC_BASE.replace(
            "process.communicate()", "process.communicate()  # sarj-noqa: SARJ537 -- external child supervisor"
        ),
    ),
    EvaluationCase("async-generated", Language.PYTHON, "# @generated\n" + _ASYNC_BASE),
    EvaluationCase(
        "async-reflection",
        Language.PYTHON,
        _ASYNC_BASE.replace("async def run", "globals()['asyncio'] = custom\n\nasync def run"),
    ),
)


@pytest.mark.parametrize("case", ASYNC_CASES, ids=tuple(case.case_id for case in ASYNC_CASES))
def test_owned_async_subprocess_cases(case: EvaluationCase) -> None:
    findings = AsyncSubprocessCancellationCleanup().check(Path("app/processes.py"), case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(finding.severity is Severity.WARNING and not finding.fixes for finding in findings)


def test_async_subprocess_cancellation_handler_owns_settlement() -> None:
    source = _ASYNC_BASE.replace(
        "    return await process.communicate()",
        "    try:\n        return await process.communicate()\n    except asyncio.CancelledError:\n        process.kill()\n        await process.communicate()\n        raise",
    )
    assert not AsyncSubprocessCancellationCleanup().check(Path("app/processes.py"), source)


def test_async_subprocess_finalizer_owns_settlement() -> None:
    source = _ASYNC_BASE.replace(
        "    return await process.communicate()",
        "    try:\n        return await process.communicate()\n    finally:\n        if process.returncode is None:\n            process.kill()\n        await process.communicate()",
    )
    assert not AsyncSubprocessCancellationCleanup().check(Path("app/processes.py"), source)


def test_a_later_unguarded_wait_does_not_cover_cancellation_of_the_first_wait() -> None:
    source = _ASYNC_BASE.replace(
        "    return await process.communicate()", "    await process.communicate()\n    return await process.wait()"
    )
    findings = AsyncSubprocessCancellationCleanup().check(Path("app/processes.py"), source)
    assert len(findings) == 1
    assert findings[0].line == 5


def test_status_polling_can_settle_the_child_before_the_final_wait() -> None:
    source = _ASYNC_BASE.replace(
        "    return await process.communicate()",
        "    while process.returncode is None:\n        await asyncio.sleep(.01)\n    return await process.communicate()",
    )
    assert not AsyncSubprocessCancellationCleanup().check(Path("app/processes.py"), source)


def test_status_inspection_after_wait_retains_local_ownership() -> None:
    source = _ASYNC_BASE.replace(
        "    return await process.communicate()",
        "    stdout, stderr = await process.communicate()\n    if process.returncode != 0:\n        raise RuntimeError(stderr.decode())\n    return stdout.decode()",
    )
    assert len(AsyncSubprocessCancellationCleanup().check(Path("app/processes.py"), source)) == 1


_LEGACY_BAD = "import subprocess\ndef run(args):\n    process = subprocess.Popen(args)\n    try:\n        process.communicate(timeout=1)\n    except subprocess.TimeoutExpired:\n        process.kill()\n"


def test_documented_examples() -> None:
    verify_native_rule(AsyncSubprocessCancellationCleanup, analyze)


@pytest.mark.parametrize(
    ("source", "expected_code", "expected_severity"),
    [
        (_ASYNC_BASE, "SARJ537", Severity.WARNING),
        (_LEGACY_BAD, "SARJ464", Severity.ERROR),
    ],
    ids=("async-warning-owner", "legacy-error-owner"),
)
def test_owner_selection_preserves_independent_severity(
    tmp_path: Path, source: str, expected_code: str, expected_severity: Severity
) -> None:
    path = tmp_path / "app" / "processes.py"
    path.parent.mkdir()
    path.write_text(source)
    findings = analyze(["async-subprocess-cancellation-cleanup", "subprocess-kill-without-reap"], [path], root=tmp_path)
    assert len(findings) == 1
    assert findings[0].code == expected_code
    assert findings[0].severity is expected_severity
    assert not findings[0].fixes


@pytest.mark.parametrize(
    "prefix",
    [
        "from os import waitpid as reap\n",
        "import signal\nsignal.signal(signal.SIGCHLD, signal.SIG_IGN)\n",
        "import os\nalias = os\n",
    ],
    ids=("external-reaper", "child-signal-owner", "unknown-module-consumer"),
)
def test_shared_child_ownership_exclusions_are_preserved(prefix: str) -> None:
    assert not AsyncSubprocessCancellationCleanup().check(Path("app/processes.py"), prefix + _ASYNC_BASE)


def test_malformed_source_remains_outside_the_profile() -> None:
    source = "import asyncio\nasync def run(args):\n    process = await asyncio.create_subprocess_exec("
    assert not AsyncSubprocessCancellationCleanup().check(Path("app/processes.py"), source)


def test_legacy_selection_does_not_claim_the_async_profile() -> None:
    assert not SubprocessKillWithoutReap().check(Path("app/processes.py"), _ASYNC_BASE)
