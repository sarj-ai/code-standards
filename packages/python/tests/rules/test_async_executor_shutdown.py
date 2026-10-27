import json
from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Rule, Severity
from sarj_python_lint.rules.async_executor_shutdown import AsyncExecutorShutdown
from sarj_python_lint.rules.async_subprocess_cancellation_cleanup import AsyncSubprocessCancellationCleanup
from sarj_python_lint.rules.cancel_owned_task_without_join import CancelOwnedTaskWithoutJoin


_BASE = "from concurrent.futures import ThreadPoolExecutor\n\nasync def close():\n    executor = ThreadPoolExecutor()\n    executor.shutdown(wait=True)\n"
CASES = (
    EvaluationCase("direct-wait", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase("default-wait", Language.PYTHON, _BASE.replace("wait=True", ""), ExpectedOutcome.MATCH),
    EvaluationCase("positional-wait", Language.PYTHON, _BASE.replace("wait=True", "True"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "cancel-futures", Language.PYTHON, _BASE.replace("wait=True", "cancel_futures=True"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "process-pool",
        Language.PYTHON,
        _BASE.replace("ThreadPoolExecutor", "ProcessPoolExecutor"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "annotated-binding",
        Language.PYTHON,
        _BASE.replace("executor =", "executor: ThreadPoolExecutor ="),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "ordinary-argument-use",
        Language.PYTHON,
        _BASE.replace("    executor.shutdown", "    queue = EncodeQueue(executor)\n    executor.shutdown"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _BASE.replace("from concurrent.futures import ThreadPoolExecutor", "import concurrent.futures as cf").replace(
            "= ThreadPoolExecutor()", "= cf.ThreadPoolExecutor()"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "constructor-alias",
        Language.PYTHON,
        _BASE.replace("ThreadPoolExecutor", "Pool").replace("import Pool", "import ThreadPoolExecutor as Pool"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("nonwaiting", Language.PYTHON, _BASE.replace("wait=True", "wait=False")),
    EvaluationCase("synchronous", Language.PYTHON, _BASE.replace("async def", "def")),
    EvaluationCase("dynamic-wait", Language.PYTHON, _BASE.replace("wait=True", "wait=policy")),
    EvaluationCase("unknown-keywords", Language.PYTHON, _BASE.replace("wait=True", "**policy")),
    EvaluationCase("unknown-factory", Language.PYTHON, _BASE.replace("= ThreadPoolExecutor()", "= make_executor()")),
    EvaluationCase("custom-shutdown", Language.PYTHON, _BASE.replace("= ThreadPoolExecutor()", "= CustomExecutor()")),
    EvaluationCase(
        "reassigned",
        Language.PYTHON,
        _BASE.replace("    executor.shutdown", "    executor = CustomExecutor()\n    executor.shutdown"),
    ),
    EvaluationCase(
        "method-replaced",
        Language.PYTHON,
        _BASE.replace("    executor.shutdown", "    executor.shutdown = custom\n    executor.shutdown"),
    ),
    EvaluationCase(
        "bound-setter",
        Language.PYTHON,
        _BASE.replace("    executor.shutdown", "    executor.__setattr__('shutdown', custom)\n    executor.shutdown"),
    ),
    EvaluationCase(
        "receiver-alias",
        Language.PYTHON,
        _BASE.replace(
            "    executor.shutdown", "    alias = executor\n    alias.shutdown = custom\n    executor.shutdown"
        ),
    ),
    EvaluationCase(
        "namespace-alias",
        Language.PYTHON,
        _BASE.replace("async def", "Pool = ThreadPoolExecutor\nPool.shutdown = custom\n\nasync def"),
    ),
    EvaluationCase(
        "other-import-mutation",
        Language.PYTHON,
        _BASE.replace(
            "async def",
            "from concurrent.futures import ThreadPoolExecutor as Pool\nPool.shutdown = custom\n\nasync def",
        ),
    ),
    EvaluationCase("shadowed-constructor", Language.PYTHON, _BASE.replace("close()", "close(ThreadPoolExecutor)")),
    EvaluationCase(
        "borrowed-receiver",
        Language.PYTHON,
        _BASE.replace("close()", "close(executor)").replace("    executor = ThreadPoolExecutor()\n", ""),
    ),
    EvaluationCase(
        "nested-sync-callback",
        Language.PYTHON,
        _BASE.replace("    executor.shutdown(wait=True)", "    def callback():\n        executor.shutdown(wait=True)"),
    ),
    EvaluationCase(
        "nested-lambda",
        Language.PYTHON,
        _BASE.replace("    executor.shutdown(wait=True)", "    callback = lambda: executor.shutdown(wait=True)"),
    ),
    EvaluationCase(
        "suppressed",
        Language.PYTHON,
        _BASE.replace("wait=True)", "wait=True)  # sarj-noqa: SARJ540 -- explicit shutdown boundary"),
    ),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase(
        "reflection",
        Language.PYTHON,
        _BASE.replace("async def", "globals()['ThreadPoolExecutor'] = custom\n\nasync def"),
    ),
    EvaluationCase("wildcard", Language.PYTHON, "from custom import *\n" + _BASE),
    EvaluationCase(
        "conditional-import",
        Language.PYTHON,
        _BASE.replace(
            "from concurrent.futures import ThreadPoolExecutor",
            "if enabled:\n    from concurrent.futures import ThreadPoolExecutor",
        ),
    ),
    EvaluationCase("malformed", Language.PYTHON, "async def close(:"),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = AsyncExecutorShutdown().check(Path("app/lifecycle.py"), case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(finding.severity is Severity.WARNING and not finding.fixes for finding in findings)


def test_shutdown_offloaded_to_a_thread() -> None:
    source = "import asyncio\n" + _BASE.replace(
        "    executor.shutdown(wait=True)", "    await asyncio.to_thread(executor.shutdown, wait=True)"
    )
    assert not AsyncExecutorShutdown().check(Path("app/lifecycle.py"), source)


def test_closure_receiver_retains_its_proven_constructor() -> None:
    source = "from concurrent.futures import ThreadPoolExecutor\n\ndef create_app():\n    executor = ThreadPoolExecutor(max_workers=1)\n    queue = EncodeQueue(executor)\n    async def lifespan():\n        executor.shutdown(wait=True)\n    return lifespan\n"
    findings = AsyncExecutorShutdown().check(Path("app/lifecycle.py"), source)
    assert [(finding.line, finding.code, finding.severity) for finding in findings] == [
        (7, "SARJ540", Severity.WARNING)
    ]


def test_ordinary_keyword_argument_use_preserves_constructor_identity() -> None:
    source = _BASE.replace("    executor.shutdown", "    queue = EncodeQueue(executor=executor)\n    executor.shutdown")
    assert len(AsyncExecutorShutdown().check(Path("app/lifecycle.py"), source)) == 1


def test_documented_examples() -> None:
    verify_native_rule(AsyncExecutorShutdown, analyze)


@pytest.mark.parametrize(
    ("rule_type", "example_id"),
    [
        (AsyncExecutorShutdown, "waiting-shutdown-in-async"),
        (CancelOwnedTaskWithoutJoin, "cancel-without-settlement"),
        (AsyncSubprocessCancellationCleanup, "async-wait-without-cancellation-cleanup"),
    ],
)
def test_new_lifecycle_warnings_do_not_block_or_enter_error_baselines(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    rule_type: type[Rule],
    example_id: str,
) -> None:
    example = next(case for case in rule_type.public_examples() if case.example_id == example_id)
    target = tmp_path / "lifecycle.py"
    target.write_text(example.focus_file.source)
    baseline = tmp_path / "baseline.json"
    command = ["check", "--rule", rule_type.id]
    assert main([*command, str(target)]) == 0
    assert f"{rule_type.code} warning:" in capsys.readouterr().out
    assert main([*command, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {}
