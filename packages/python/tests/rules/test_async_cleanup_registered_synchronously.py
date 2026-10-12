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
        _BASE.replace("stack.callback(close)", "stack.callback(close)  # sarj-noqa: SARJ463"),
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


@pytest.mark.parametrize(
    "change",
    [
        pytest.param("alias = close\nalias.__code__ = synchronous.__code__", id="alias-code-mutation"),
        pytest.param("alias = close\nother = alias\nother.__code__ = synchronous.__code__", id="alias-chain-mutation"),
        pytest.param("alias: object = close\nalias.__code__ = synchronous.__code__", id="annotated-alias-mutation"),
        pytest.param("callbacks = [close]\ncallbacks[0].__code__ = synchronous.__code__", id="container-escape"),
        pytest.param("configure(close)", id="unknown-function-escape"),
        pytest.param("def exported():\n    return close", id="returned-function"),
        pytest.param("close.__setattr__('__code__', synchronous.__code__)", id="bound-code-setter"),
        pytest.param("close.__globals__['close'].__code__ = synchronous.__code__", id="function-global-escape"),
        pytest.param("globals()['close'] = synchronous", id="global-binding-write"),
        pytest.param("namespace = globals()\nnamespace['close'] = synchronous", id="global-namespace-escape"),
        pytest.param("def change():\n    global close\n    close = synchronous\nchange()", id="global-declaration"),
        pytest.param("namespace = globals\nnamespace()['close'] = synchronous", id="aliased-global-function"),
        pytest.param(
            "from builtins import globals as namespace\nnamespace()['close'] = synchronous",
            id="imported-global-function",
        ),
    ],
)
def test_mutated_or_escaped_coroutine_contracts(change: str) -> None:
    source = _BASE.replace("async def run", "def synchronous():\n    finish()\n" + change + "\nasync def run")
    assert not AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), source)


def test_unmutated_aliases_and_direct_calls_remain_checked() -> None:
    source = _BASE.replace("async def run", "cleanup = close\nasync def run").replace(
        "    async with", "    await cleanup()\n    async with"
    )
    assert len(AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), source)) == 1


def test_bound_stack_setter_invalidates_callback_proof() -> None:
    source = _BASE.replace(
        "        stack.callback(close)",
        "        stack.__setattr__('callback', stack.push_async_callback)\n        stack.callback(close)",
    )
    assert not AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), source)


@pytest.mark.parametrize(
    "change",
    [
        "contextlib.AsyncExitStack.callback = proper_callback",
        "klass = contextlib.AsyncExitStack\nklass.callback = proper_callback",
        "setattr(contextlib.AsyncExitStack, 'callback', proper_callback)",
        "class Holder:\n    import contextlib as local_c\n    local_c.AsyncExitStack.callback = proper_callback",
        "class Holder:\n    import contextlib as local_c\n    klass = local_c.AsyncExitStack\n    klass.callback = proper_callback",
    ],
)
def test_canonical_stack_aliases_can_replace_the_registration_api(change: str) -> None:
    source = "import contextlib\n" + _BASE.replace("async def run", change + "\nasync def run")
    assert not AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), source)


def test_relative_import_is_not_a_proven_stdlib_stack() -> None:
    assert not AsyncCleanupRegisteredSynchronously().check(
        Path("app/resources.py"), _BASE.replace("from contextlib", "from .contextlib")
    )


@pytest.mark.parametrize(
    "change",
    [
        "from contextlib import _BaseExitStack\n_BaseExitStack.callback = proper_callback",
        "from contextlib import _BaseExitStack as Provider\nconfigure(Provider)",
        "class Holder:\n    from contextlib import _BaseExitStack as Provider\n    Provider.callback = proper_callback",
    ],
)
def test_inherited_stack_provider_mutations_invalidate_callback_proof(change: str) -> None:
    source = _BASE.replace("async def run", change + "\nasync def run")
    assert not AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), source)
