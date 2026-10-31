from __future__ import annotations

import asyncio
from functools import cache, cached_property, lru_cache
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.no_async_function_cache import NoAsyncFunctionCache


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

PROBLEM = RuleProblem(
    key="no-async-function-cache",
    summary="Standard library caches retain coroutine objects rather than awaited results.",
    harm="A repeated cache hit returns an exhausted coroutine and raises RuntimeError on await.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=("from functools import cache\n@cache\nasync def load():\n    return 1\n",),
    good_examples=("async def load():\n    return 1\n",),
    exclusions=("Unknown decorators, async generators, disabled or dynamic cache sizes, generated code.",),
    autofix=AutofixPolicy.NONE,
)


def _case(case_id: str, source: str, *, matches: bool = False, path: str = "app/cache.py") -> EvaluationCase:
    return EvaluationCase(
        case_id,
        Language.PYTHON,
        source,
        ExpectedOutcome.MATCH if matches else ExpectedOutcome.NO_MATCH,
        path=PurePosixPath(path),
    )


CASES = (
    *(
        _case(
            f"direct-{decorator.replace('(', '-').replace(')', '').replace('=', '-')}",
            f"from functools import cache, cached_property, lru_cache\n@{decorator}\nasync def load():\n    return 1\n",
            matches=True,
        )
        for decorator in (
            "cache",
            "cached_property",
            "lru_cache",
            "lru_cache()",
            "lru_cache(maxsize=None)",
            "lru_cache(maxsize=8)",
            "lru_cache(8, typed=True)",
            "lru_cache(8, True)",
            "lru_cache(None, False)",
            "lru_cache(None)",
            "lru_cache(maxsize=+1)",
        )
    ),
    _case(
        "import-alias", "from functools import cache as memo\n@memo\nasync def load():\n    return 1\n", matches=True
    ),
    _case("module-alias", "import functools as ft\n@ft.cache\nasync def load():\n    return 1\n", matches=True),
    _case(
        "nested-function",
        "import functools\ndef outer():\n    @functools.cache\n    async def load():\n        return 1\n",
        matches=True,
    ),
    _case(
        "nested-generator-is-separate",
        "from functools import cache\n@cache\nasync def load():\n    def values():\n        yield 1\n    return values()\n",
        matches=True,
    ),
    _case(
        "outer-decorator",
        "from functools import cache\n@identity\n@cache\nasync def load():\n    return 1\n",
        matches=True,
    ),
    _case(
        "test-code",
        "from functools import cache\n@cache\nasync def load():\n    return 1\n",
        matches=True,
        path="tests/test_cache.py",
    ),
    _case("synchronous-cache", "from functools import cache\n@cache\ndef load():\n    return 1\n"),
    _case("async-aware-cache", "from async_lru import alru_cache\n@alru_cache()\nasync def load():\n    return 1\n"),
    _case("custom-cache", "from app.memo import cache\n@cache\nasync def load():\n    return 1\n"),
    _case("unimported-cache", "@cache\nasync def load():\n    return 1\n"),
    _case(
        "shadowed-cache", "from functools import cache\ncache = custom_cache\n@cache\nasync def load():\n    return 1\n"
    ),
    _case(
        "parameter-shadow",
        "from functools import cache\ndef outer(cache):\n    @cache\n    async def load():\n        return 1\n",
    ),
    _case(
        "nested-import-shadow",
        "from functools import cache\ndef build():\n    from functools import partial as cache\n"
        "    @cache\n    async def load():\n        return 1\n    return load\n",
    ),
    _case(
        "class-import-shadow",
        "from functools import cache\nclass Service:\n    from functools import partial as cache\n"
        "    @staticmethod\n    @cache\n    async def load():\n        return 1\n",
    ),
    _case(
        "nested-module-shadow",
        "import functools as ft\ndef build():\n    from app import tools as ft\n"
        "    @ft.cache\n    async def load():\n        return 1\n",
    ),
    _case(
        "exception-shadow",
        "from functools import cache\ntry:\n    work()\nexcept CallableError as cache:\n"
        "    @cache\n    async def load():\n        return 1\n",
    ),
    _case(
        "match-shadow",
        "from functools import cache\nmatch identity:\n    case cache:\n"
        "        @cache\n        async def load():\n            return 1\n",
    ),
    _case(
        "wildcard-import",
        "from functools import cache\nfrom app.memo import *\n@cache\nasync def load():\n    return 1\n",
    ),
    _case(
        "relative-import-shadow",
        "from functools import cache\nfrom .memo import cache\n@cache\nasync def load():\n    return 1\n",
    ),
    _case("inner-transform", "from functools import cache\n@cache\n@syncify\nasync def load():\n    return 1\n"),
    _case("async-generator", "from functools import cache\n@cache\nasync def load():\n    yield 1\n"),
    _case(
        "nested-async-generator",
        "from functools import cache\n@cache\nasync def load():\n    if ready:\n        yield 1\n",
    ),
    *(
        _case(f"enclosing-yield-{case_id}", f"from functools import cache\n@cache\nasync def load():\n{body}")
        for case_id, body in (
            ("function-default", "    def inner(value=(yield 1)):\n        return value\n"),
            ("function-keyword-default", "    def inner(*, value=(yield 1)):\n        return value\n"),
            ("lambda-default", "    inner = lambda value=(yield 1): value\n"),
            ("class-base", "    class Inner((yield 1)):\n        pass\n"),
            ("class-keyword", "    class Inner(metaclass=(yield 1)):\n        pass\n"),
            ("function-decorator", "    @(yield 1)\n    def inner():\n        pass\n"),
            ("class-decorator", "    @(yield 1)\n    class Inner:\n        pass\n"),
        )
    ),
    *(
        _case(
            f"disabled-or-unknown-size-{index}",
            f"from functools import lru_cache\n@lru_cache({arguments})\nasync def load():\n    return 1\n",
        )
        for index, arguments in enumerate(
            ("0", "0, True", "maxsize=0", "maxsize=False", "-1", "maxsize=-8", "maxsize=limit", "**options")
        )
    ),
    _case("suppressed", "from functools import cache\n@cache  # sarj-noqa: SARJ507\nasync def load():\n    return 1\n"),
    _case(
        "other-suppression",
        "from functools import cache\n@cache  # sarj-noqa: SARJ431\nasync def load():\n    return 1\n",
        matches=True,
    ),
    _case("generated", "# @generated\nfrom functools import cache\n@cache\nasync def load():\n    return 1\n"),
    _case("malformed", "from functools import cache\n@cache\nasync def load(:\n"),
    _case("string-and-comment", "# @cache async def load\nsource = '@cache async def load'\n"),
    *(
        _case(
            f"proven-{import_id}-{decorator_id}",
            f"{statement}\n@{target}{arguments}\nasync def load():\n    return 1\n",
            matches=True,
        )
        for decorator_id, symbol, arguments in (
            ("cache", "cache", ""),
            ("property", "cached_property", ""),
            ("lru-bare", "lru_cache", ""),
            ("lru-default", "lru_cache", "()"),
            ("lru-unbounded", "lru_cache", "(None)"),
            ("lru-sized", "lru_cache", "(maxsize=8)"),
        )
        for import_id, statement, target in (
            ("direct", f"from functools import {symbol}", symbol),
            ("member-alias", f"from functools import {symbol} as memo", "memo"),
            ("module", "import functools", f"functools.{symbol}"),
            ("module-alias", "import functools as ft", f"ft.{symbol}"),
        )
    ),
    *(
        _case(
            f"provider-invalidated-{case_id}",
            f"import functools as ft\n{mutation}\n@ft.cache\nasync def load():\n    return 1\n",
        )
        for case_id, mutation in (
            ("member-assignment", "ft.cache = identity"),
            ("member-delete", "del ft.cache"),
            ("setattr", "setattr(ft, 'cache', identity)"),
            ("aliased-setattr", "from builtins import setattr as replace\nreplace(ft, 'cache', identity)"),
            ("delattr", "delattr(ft, 'cache')"),
            ("aliased-delattr", "from builtins import delattr as remove\nremove(ft, 'cache')"),
            ("module-alias", "tools = ft"),
            ("module-argument", "configure(ft)"),
            ("module-container", "tools = [ft]"),
            ("provider-alias", "memo = ft.cache"),
            ("provider-argument", "configure(ft.cache)"),
            ("provider-container", "decorators = [ft.cache]"),
            ("alternate-module", "import functools as other\nother.cache = identity"),
            ("alternate-member", "from functools import cache as other\nother.enabled = False"),
            ("alternate-escape", "from functools import cache as other\nconfigure(other)"),
            ("dynamic-member", "configure(getattr(ft, selected))"),
            ("module-magic-setter", "ft.__setattr__('cache', identity)"),
            ("module-magic-deleter", "ft.__delattr__('cache')"),
            ("provider-magic-setter", "ft.cache.__setattr__('enabled', False)"),
            ("provider-magic-deleter", "ft.cache.__delattr__('enabled')"),
            ("module-namespace", "ft.__dict__['cache'] = identity"),
            ("vars-namespace", "vars(ft)['cache'] = identity"),
        )
    ),
    _case(
        "unrelated-local-name-rebind",
        "import functools as ft\ncache = identity\n@ft.cache\nasync def load():\n    return 1\n",
        matches=True,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    diagnostics = NoAsyncFunctionCache().check(Path(case.path), case.source)
    assert len(diagnostics) == int(case.expected is ExpectedOutcome.MATCH)
    for diagnostic in diagnostics:
        assert diagnostic.code == "SARJ507"
        assert diagnostic.severity is Severity.ERROR
        assert "coroutine" in diagnostic.message


def test_public_examples() -> None:
    verify_native_rule(NoAsyncFunctionCache, analyze)


@pytest.mark.parametrize("decorator", [cache, lru_cache(maxsize=8)], ids=["cache", "lru-cache"])
def test_stdlib_cache_reuses_an_exhausted_coroutine(decorator: Callable[..., Callable[..., Awaitable[int]]]) -> None:
    @decorator
    async def load() -> int:
        await asyncio.sleep(0)
        return 1

    async def exercise() -> None:
        assert await load() == 1
        with pytest.raises(RuntimeError, match="cannot reuse already awaited coroutine"):
            await load()

    asyncio.run(exercise())


def test_stdlib_cached_property_reuses_an_exhausted_coroutine() -> None:
    class Service:
        @cached_property  # sarj-noqa: SARJ507 -- Reproduce coroutine reuse to verify the runtime failure.
        async def value(self) -> int:
            await asyncio.sleep(0)
            return 1

    async def exercise() -> None:
        service = Service()
        assert await service.value == 1
        with pytest.raises(RuntimeError, match="cannot reuse already awaited coroutine"):
            await service.value

    asyncio.run(exercise())


def test_multiple_functions_have_stable_distinct_locations() -> None:
    source = "from functools import cache\n@cache\nasync def first():\n    return 1\n@cache\nasync def second():\n    return 2\n"
    first = NoAsyncFunctionCache().check(Path("app/cache.py"), source)
    assert [(diagnostic.line, diagnostic.col) for diagnostic in first] == [(2, 2), (5, 2)]
    assert NoAsyncFunctionCache().check(Path("app/cache.py"), source) == first
