from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rules.async_cleanup_registered_synchronously import AsyncCleanupRegisteredSynchronously


_BASE = "from contextlib import AsyncExitStack\nasync def close():\n    await finish()\nasync def run():\n    async with AsyncExitStack() as stack:\n        stack.callback(close)\n"
CASES = (
    EvaluationCase("async-stack", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "sync-stack",
        Language.PYTHON,
        _BASE.replace("AsyncExitStack", "ExitStack").replace("async with", "with"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("correct-api", Language.PYTHON, _BASE.replace("stack.callback", "stack.push_async_callback")),
    EvaluationCase(
        "sync-callback",
        Language.PYTHON,
        _BASE.replace("async def close():\n    await finish()", "def close():\n    finish()"),
    ),
    EvaluationCase("generator-callback", Language.PYTHON, _BASE.replace("await finish()", "yield 1")),
    EvaluationCase("decorated-callback", Language.PYTHON, _BASE.replace("async def close", "@adapt\nasync def close")),
    EvaluationCase(
        "unknown-callback", Language.PYTHON, _BASE.replace("stack.callback(close)", "stack.callback(client.aclose)")
    ),
    EvaluationCase(
        "shadowed-stack", Language.PYTHON, _BASE.replace("async def run():", "async def run(AsyncExitStack):")
    ),
    EvaluationCase(
        "rebound-stack",
        Language.PYTHON,
        _BASE.replace("        stack.callback", "        stack = custom()\n        stack.callback"),
    ),
    EvaluationCase("rebound-callback", Language.PYTHON, _BASE + "close = adapt(close)\n"),
    EvaluationCase(
        "escaped-stack",
        Language.PYTHON,
        _BASE.replace("        stack.callback", "        configure(stack)\n        stack.callback"),
    ),
    EvaluationCase(
        "mutated-method",
        Language.PYTHON,
        _BASE.replace(
            "        stack.callback(close)", "        stack.callback = custom\n        stack.callback(close)"
        ),
    ),
    EvaluationCase("wildcard-import", Language.PYTHON, "from custom import *\n" + _BASE),
    EvaluationCase(
        "suppression",
        Language.PYTHON,
        _BASE.replace("stack.callback(close)", "stack.callback(close)  # sarj-noqa: SARJ462"),
    ),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase(
        "alias",
        Language.PYTHON,
        _BASE.replace("async def run", "cleanup = close\nasync def run").replace(
            "stack.callback(close)", "stack.callback(cleanup)"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _BASE.replace("from contextlib import AsyncExitStack", "import contextlib as ctx").replace(
            "AsyncExitStack()", "ctx.AsyncExitStack()"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "stack-assignment",
        Language.PYTHON,
        _BASE.replace(
            "    async with AsyncExitStack() as stack:", "    stack = AsyncExitStack()\n    async with stack:"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "callback-arguments",
        Language.PYTHON,
        _BASE.replace("stack.callback(close)", "stack.callback(close, value, reason='done')"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("malformed", Language.PYTHON, "async with:"),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)


@pytest.mark.parametrize(
    "source",
    [
        _BASE.replace(
            "    async with",
            "    try:\n        work()\n    except Error as AsyncExitStack:\n        pass\n    async with",
        ),
        _BASE.replace(
            "    async with",
            "    match value:\n        case {'stack': AsyncExitStack}:\n            pass\n    async with",
        ),
        _BASE.replace("async def close", "if flag:\n    async def close").replace(
            "    await finish()", "        await finish()"
        ),
        _BASE.replace("    async with", "    configure(AsyncExitStack)\n    async with"),
        _BASE.replace("    async with", "    alias = AsyncExitStack\n    alias.callback = custom\n    async with"),
    ],
    ids=[
        "exception-shadow",
        "match-shadow",
        "conditional-callback",
        "constructor-escape",
        "constructor-alias-mutation",
    ],
)
def test_uncertain_binding_exclusions(source: str) -> None:
    assert not AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), source)
