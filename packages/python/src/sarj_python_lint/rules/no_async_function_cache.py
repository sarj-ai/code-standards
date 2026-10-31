from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._ast_index import has_own_yield
from sarj_python_lint.rules._imports import ambiguous_import_names as _nested_import_names


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_FUNCTOOLS = frozenset({"functools"})
_COROUTINE_CACHES = frozenset({"cache", "cached_property", "lru_cache"})
_LRU_CACHE_POSITIONAL_ARGUMENTS = 2


@final
class NoAsyncFunctionCache(Rule):
    id = "no-async-function-cache"
    code = "SARJ507"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Standard library cache decorates a coroutine function and retains single-use coroutine objects.",
        rationale=(
            "`functools.cache`, `lru_cache`, and `cached_property` store the coroutine object returned by an async "
            "function rather than its awaited value. A subsequent cache hit can raise `RuntimeError: cannot reuse "
            "already awaited coroutine`."
        ),
        remediation="Remove the standard library cache or use an async-aware cache that stores completed results.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only a proven functools import used as the innermost decorator on a coroutine function is reported.",
            "Async generators, transformed functions, ambiguous or rebound imports, and generated files are excluded.",
            "Wildcard imports and names rebound by relative imports or imports outside the module body are excluded conservatively.",
            "lru_cache with disabled, dynamic, or unpacked maxsize arguments is excluded; an omitted size or literal positive integer or None is required.",
            "Visible mutations, deletion, or escape of functools providers invalidate their native identity conservatively.",
            "Indirect wrapping calls and opaque runtime or interprocedural mutations are not resolved. Test code is checked because coroutine reuse fails there too.",
            "No automatic rewrite is offered because cache lifetime, cancellation, and concurrency require an explicit design decision.",
        ),
        examples=(
            RuleExample(
                example_id="cached-coroutine-function",
                title="A standard cache retains an exhausted coroutine",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/cache.py",
                        "from functools import cache\n\n@cache\nasync def load() -> int:\n    return 1\n",
                    ),
                ),
                focus_path=PurePosixPath("app/cache.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="fresh-coroutine-function",
                title="Each call creates a fresh coroutine",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/cache.py", "async def load() -> int:\n    return 1\n"),),
                focus_path=PurePosixPath("app/cache.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "async" not in context.source or context.generated or context.tree is None:
            return []
        shadowed = _nested_import_names(context)
        if "*" in shadowed:
            return []
        diagnostics: list[Diagnostic] = []
        for function in context.nodes(ast.AsyncFunctionDef):
            if not function.decorator_list:
                continue
            decorator = function.decorator_list[-1]
            if (
                not _is_coroutine_cache(decorator, context.imports, shadowed)
                or has_own_yield(function)
                or is_suppressed(context.source_lines, decorator.lineno, self.code)
            ):
                continue
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            qualified = context.imports.resolved_qualified_name(target)
            if qualified is None or not context.static_resource_provenance.imported(target, qualified):
                continue
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=decorator.lineno,
                    col=decorator.col_offset + 1,
                    code=self.code,
                    message=(
                        "Standard library cache retains a single-use coroutine; remove it or use an async-aware "
                        "cache that stores awaited results."
                    ),
                    severity=Severity.ERROR,
                ),
            )
        return diagnostics


def _is_coroutine_cache(decorator: ast.expr, imports: ImportIndex, shadowed: frozenset[str]) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    root = target
    while isinstance(root, ast.Attribute):
        root = root.value
    if isinstance(root, ast.Name) and root.id in shadowed:
        return False
    symbol = imports.resolved_symbol(target, sources=_FUNCTOOLS)
    if symbol not in _COROUTINE_CACHES:
        return False
    if not isinstance(decorator, ast.Call):
        return True
    if symbol != "lru_cache" or any(keyword.arg is None for keyword in decorator.keywords):
        return False
    if len(decorator.args) > _LRU_CACHE_POSITIONAL_ARGUMENTS or any(
        isinstance(argument, ast.Starred) for argument in decorator.args
    ):
        return False
    sizes = [keyword.value for keyword in decorator.keywords if keyword.arg == "maxsize"]
    if decorator.args:
        sizes.append(decorator.args[0])
    if not sizes:
        return True
    if len(sizes) != 1:
        return False
    match sizes[0]:
        case ast.Constant(value=None):
            return True
        case ast.Constant(value=int() as size) | ast.UnaryOp(op=ast.UAdd(), operand=ast.Constant(value=int() as size)):
            return size > 0
        case _:
            return False
