from pathlib import Path
from textwrap import dedent, indent

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_swallowed_asyncio_cancellation import NoSwallowedAsyncioCancellation


def _source(handler: str, caught: str = "asyncio.CancelledError", imports: str = "import asyncio") -> str:
    return f"{imports}\n\nasync def worker():\n    try:\n        await operation()\n    except {caught}:\n{indent(handler, '        ')}\n"


CASES = (
    EvaluationCase("returns-none", Language.PYTHON, _source("return None"), ExpectedOutcome.MATCH),
    EvaluationCase("falls-through", Language.PYTHON, _source("pass"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "logs-and-returns", Language.PYTHON, _source("logger.info('cancelled')\nreturn False"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "logs-and-falls-through", Language.PYTHON, _source("logger.info('cancelled')"), ExpectedOutcome.MATCH
    ),
    EvaluationCase("cleans-and-returns", Language.PYTHON, _source("await cleanup()\nreturn []"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _source("pass", "aio.CancelledError", "import asyncio as aio"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "symbol-alias",
        Language.PYTHON,
        _source("pass", "Cancelled", "from asyncio import CancelledError as Cancelled"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "tuple-catch", Language.PYTHON, _source("pass", "(TimeoutError, asyncio.CancelledError)"), ExpectedOutcome.MATCH
    ),
    EvaluationCase("reraises", Language.PYTHON, _source("raise")),
    EvaluationCase("cleanup-reraises", Language.PYTHON, _source("await cleanup()\nraise")),
    EvaluationCase("translates-exception", Language.PYTHON, _source("raise Shutdown()")),
    EvaluationCase(
        "guarded-reraise", Language.PYTHON, _source("if asyncio.current_task().cancelling():\n    raise\nreturn None")
    ),
    EvaluationCase("compound-handler", Language.PYTHON, _source("if stopped:\n    return None\nraise")),
    EvaluationCase("explicit-uncancel", Language.PYTHON, _source("asyncio.current_task().uncancel()\nreturn None")),
    EvaluationCase(
        "other-cancellation",
        Language.PYTHON,
        _source("pass", "CancelledError", "from concurrent.futures import CancelledError"),
    ),
    EvaluationCase("unproven-cancellation", Language.PYTHON, _source("pass", "CancelledError", "")),
    EvaluationCase(
        "shadowed-module", Language.PYTHON, _source("pass", imports="import asyncio\nasyncio = replacement")
    ),
    EvaluationCase(
        "synchronous-function",
        Language.PYTHON,
        _source("pass").replace("async def", "def").replace("await operation()", "operation()"),
    ),
    EvaluationCase(
        "malformed-input",
        Language.PYTHON,
        _source("pass", "asyncio.CancelledError  # sarj-noqa: SARJ458").replace("SARJ458:", "SARJ458"),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    diagnostics = NoSwallowedAsyncioCancellation().check(Path("worker.py"), case.source)
    assert len(diagnostics) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(item.severity is Severity.WARNING for item in diagnostics)


def test_documented_examples() -> None:
    verify_native_rule(NoSwallowedAsyncioCancellation, analyze)


@pytest.mark.parametrize("path", ["tests/test_worker.py", "conftest.py", "generated/worker_pb2.py"])
def test_excluded_files(path: str) -> None:
    assert not NoSwallowedAsyncioCancellation().check(Path(path), _source("pass"))


def test_exact_suppression_on_handler() -> None:
    source = _source("pass").replace(
        "except asyncio.CancelledError:", "except asyncio.CancelledError:  # sarj-noqa: SARJ458"
    )
    assert not NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)


def test_unrelated_suppression_keeps_warning() -> None:
    source = _source("pass").replace(
        "except asyncio.CancelledError:", "except asyncio.CancelledError:  # sarj-noqa: SARJ411"
    )
    assert len(NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)) == 1


def test_owned_child_cancel_then_await_is_cleanup() -> None:
    source = dedent("""
        import asyncio
        async def owner():
            task = asyncio.create_task(operation())
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    """)
    assert not NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)


def test_unowned_cancelled_task_is_not_inferred_cleanup() -> None:
    source = dedent("""
        import asyncio
        async def owner(task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    """)
    assert len(NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)) == 1


@pytest.mark.parametrize("finalizer", ["raise Shutdown()", "return None", "if cancelled:\n    raise Shutdown()"])
def test_control_transferring_finalizer_is_not_inferred(finalizer: str) -> None:
    source = _source("pass") + f"    finally:\n{indent(finalizer, '        ')}\n"
    assert not NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)


def test_nested_sync_handler_is_not_an_async_handler() -> None:
    source = "import asyncio\nasync def outer():\n" + indent(
        _source("pass", imports="").replace("async def", "def").replace("await operation()", "operation()"), "    "
    )
    assert not NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)


@pytest.mark.parametrize(
    "mutation",
    [
        "task = other",
        "task.cancel = other",
    ],
)
def test_rebound_task_does_not_prove_owned_cleanup(mutation: str) -> None:
    source = f"""import asyncio
async def owner():
    task = asyncio.create_task(operation())
    {mutation}
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
"""
    assert len(NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)) == 1


def test_outer_finalizer_that_raises_excludes_nested_handler() -> None:
    source = (
        "import asyncio\nasync def worker():\n    try:\n"
        + indent("try:\n    await operation()\nexcept asyncio.CancelledError:\n    pass\n", "        ")
        + "    finally:\n        raise Shutdown()\n"
    )
    assert not NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)


def test_nested_async_handler_is_reported_once() -> None:
    source = "import asyncio\nasync def outer():\n" + indent(_source("pass", imports=""), "    ")
    diagnostics = NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)
    assert len(diagnostics) == 1
    assert diagnostics == NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)


def test_cleanup_finalizer_preserves_warning() -> None:
    source = _source("return None") + "    finally:\n        close_resource()\n"
    assert len(NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)) == 1


def test_generated_header_is_excluded() -> None:
    source = "# @generated\n" + _source("pass")
    assert not NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)


def test_shadowed_import_parameter_is_not_asyncio_cancellation() -> None:
    source = _source("pass").replace("worker()", "worker(asyncio)")
    assert not NoSwallowedAsyncioCancellation().check(Path("worker.py"), source)
