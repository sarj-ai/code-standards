import asyncio
import inspect
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rules.async_cleanup_registered_synchronously import AsyncCleanupRegisteredSynchronously


if TYPE_CHECKING:
    from collections.abc import Callable


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
    "replacement",
    [
        "[(close := synchronous) for _ in (0,)]",
        "{(close := synchronous) for _ in (0,)}",
        "{key: (close := synchronous) for key in (0,)}",
        "tuple((close := synchronous) for _ in (0,))",
        "[[(close := synchronous) for _ in (0,)] for _ in (0,)]",
    ],
    ids=("list", "set", "dict", "generator", "nested-comprehensions"),
)
@pytest.mark.parametrize("module_scope", [False, True], ids=("function", "module"))
def test_comprehension_walrus_rebinds_the_containing_scope(replacement: str, module_scope: bool) -> None:
    setup = "def synchronous():\n    pass\n"
    if module_scope:
        source = _BASE.replace("async def run():", f"{setup}{replacement}\nasync def run():")
    else:
        source = _BASE.replace("async def run():", f"{setup}async def run():\n    {replacement}")

    assert AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), source) == []


@pytest.mark.parametrize(
    "statement",
    [
        "[close for close in (synchronous,)]",
        "[lambda: (close := synchronous) for _ in (0,)]",
    ],
    ids=("iteration-binding", "lambda-local-walrus"),
)
def test_comprehension_local_bindings_do_not_shadow_the_outer_callback(statement: str) -> None:
    source = _BASE.replace(
        "async def run():",
        f"def synchronous():\n    pass\n{statement}\nasync def run():",
    )

    assert len(AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), source)) == 1


def test_comprehension_rebinding_registers_a_synchronous_callback_at_runtime() -> None:
    events: list[str] = []

    async def original() -> None:
        await asyncio.sleep(0)
        events.append("async")

    def synchronous() -> None:
        events.append("sync")

    async def run() -> None:
        from contextlib import AsyncExitStack  # ruff: ignore[import-outside-top-level] -- mirror the production resource API locally.

        close: Callable[[], object] = original
        [(close := synchronous) for _ in (0,)]
        async with AsyncExitStack() as stack:
            stack.callback(close)

    asyncio.run(run())

    assert events == ["sync"]


@pytest.mark.parametrize(
    "statement",
    [
        "def nested(value=(close := synchronous)):\n    pass",
        "def nested(*, value=(close := synchronous)):\n    pass",
        "nested = lambda value=(close := synchronous): value",
        "@(close := identity)\ndef nested():\n    pass",
        "class Nested((close := SyncBase)):\n    pass",
        "class Nested(metaclass=(close := construct)):\n    pass",
        "@(close := identity)\nclass Nested:\n    pass",
    ],
    ids=("default", "keyword-default", "lambda-default", "function-decorator", "base", "keyword", "class-decorator"),
)
@pytest.mark.parametrize("module_scope", [False, True], ids=("function", "module"))
def test_evaluated_header_walrus_binds_the_enclosing_scope(statement: str, module_scope: bool) -> None:
    setup = (
        "def synchronous():\n    pass\ndef identity(value=None):\n    return value\nclass SyncBase:\n    pass\n"
        "def construct(name='Built', bases=(), namespace=None):\n    return type(name, bases, {} if namespace is None else namespace)\n"
    )
    if module_scope:
        source = _BASE.replace("async def run():", f"{setup}{statement}\nasync def run():")
    else:
        body = "\n".join(f"    {line}" for line in statement.splitlines())
        source = _BASE.replace("async def run():", f"{setup}async def run():\n{body}")

    assert AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), source) == []


@pytest.mark.parametrize(
    "statement",
    [
        "def nested(close=synchronous):\n    pass",
        "def nested():\n    close = synchronous",
        "nested = lambda close: synchronous",
        "class Nested:\n    close = synchronous",
    ],
    ids=("parameter", "function-body", "lambda-parameter", "class-body"),
)
def test_header_scope_does_not_relocate_parameters_or_bodies(statement: str) -> None:
    body = "\n".join(f"    {line}" for line in statement.splitlines())
    source = _BASE.replace("async def run():", f"def synchronous():\n    pass\nasync def run():\n{body}")

    assert len(AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), source)) == 1


@pytest.mark.parametrize(
    "definition",
    ["def capture(close=close):\n    return close", "capture = lambda close=close: close"],
    ids=("function-default", "lambda-default"),
)
def test_default_capture_does_not_resolve_to_its_own_parameter(definition: str) -> None:
    source = _BASE.replace("async def run", f"{definition}\nasync def run")

    assert AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), source) == []


def test_default_walrus_registers_a_synchronous_callback_at_runtime() -> None:
    events: list[str] = []

    def synchronous() -> None:
        events.append("sync")

    async def run() -> None:
        from contextlib import AsyncExitStack  # ruff: ignore[import-outside-top-level] -- exercise the native cleanup boundary.

        def nested(value: Callable[[], None] = (close := synchronous)) -> None:
            pass

        async with AsyncExitStack() as stack:
            stack.callback(close)

    asyncio.run(run())

    assert events == ["sync"]


@pytest.mark.parametrize(
    ("body", "coroutine"),
    [
        ("    def values():\n        yield 1\n    await finish()", True),
        ("    async def values():\n        yield 1\n    await finish()", True),
        ("    factory = lambda: (yield 1)\n    await finish()", True),
        ("    class Values:\n        def values(self):\n            yield 1\n    await finish()", True),
        ("    def values(default=(yield 1)):\n        pass", False),
        ("    factory = lambda default=(yield 1): default", False),
        ("    class Values((yield 1)):\n        pass", False),
    ],
    ids=(
        "nested-sync",
        "nested-async",
        "nested-lambda",
        "nested-method",
        "evaluated-default",
        "lambda-default",
        "evaluated-base",
    ),
)
def test_callback_kind_uses_its_own_yields(body: str, coroutine: bool) -> None:
    source = _BASE.replace("    await finish()", body)
    namespace: dict[str, object] = {}
    exec(source, namespace)  # ruff: ignore[exec-builtin] -- inspect compiler flags for fixed synthetic Python scope cases.

    assert inspect.iscoroutinefunction(namespace["close"]) is coroutine
    assert len(AsyncCleanupRegisteredSynchronously().check(Path("app/resources.py"), source)) == int(coroutine)


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
