from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex


if TYPE_CHECKING:
    from pathlib import Path


_APP_TYPES = frozenset({("fastapi", "FastAPI"), ("starlette.applications", "Starlette")})
_EVENT_NAMES = frozenset({"startup", "shutdown"})


@final
class NoFastapiOnEvent(Rule):
    id = "no-fastapi-on-event"
    code = "SARJ427"
    documentation = RuleDocumentation(
        summary="Deprecated FastAPI or Starlette on_event lifecycle registration.",
        rationale=(
            "The on_event API is deprecated and splits related startup and shutdown state across callbacks; lifespan "
            "keeps acquisition and cleanup in one async context manager and is the supported lifecycle contract."
        ),
        remediation="Define an async lifespan context manager and pass it as FastAPI(lifespan=...) or Starlette(lifespan=...).",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only decorators on a directly constructed FastAPI/Starlette application or a parameter annotated with one are checked.",
            "Factory-returned applications and dynamically selected event names are intentionally not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="deprecated-startup-event",
                title="Do not register startup through on_event",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/main.py",
                        'from fastapi import FastAPI\napp = FastAPI()\n\n@app.on_event("startup")\nasync def start() -> None:\n    pass\n',
                    ),
                ),
                focus_path=PurePosixPath("app/main.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="lifespan-context-manager",
                title="Pair startup and shutdown in lifespan",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/main.py",
                        "from contextlib import asynccontextmanager\nfrom fastapi import FastAPI\n\n"
                        "@asynccontextmanager\nasync def lifespan(app: FastAPI):\n    yield\n\napp = FastAPI(lifespan=lifespan)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/main.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree)
        return _scope_diagnostics(path, tree.body, imports)


def _scope_diagnostics(
    path: Path,
    statements: list[ast.stmt],
    imports: ImportIndex,
    *,
    extra_app_names: frozenset[str] = frozenset(),
) -> list[Diagnostic]:
    app_names = _assigned_app_names(statements, imports) | extra_app_names
    findings: list[Diagnostic] = []
    for statement in statements:
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        findings.extend(
            Diagnostic(
                path=path,
                line=decorator.lineno,
                col=decorator.col_offset + 1,
                code="SARJ427",
                message=(
                    "FastAPI/Starlette on_event is deprecated. Put startup and shutdown work in an async lifespan "
                    "context manager and pass it to the application constructor."
                ),
            )
            for decorator in statement.decorator_list
            if _is_on_event_decorator(decorator, app_names)
        )
        findings.extend(
            _scope_diagnostics(
                path,
                statement.body,
                imports,
                extra_app_names=_annotated_app_parameters(statement.args, imports),
            )
        )
    return findings


def _assigned_app_names(statements: list[ast.stmt], imports: ImportIndex) -> frozenset[str]:
    names: set[str] = set()
    for statement in statements:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        value = statement.value
        if not isinstance(value, ast.Call) or not any(
            imports.resolves(value.func, sources=frozenset({source}), symbol=symbol) for source, symbol in _APP_TYPES
        ):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        names.update(target.id for target in targets if isinstance(target, ast.Name))
    return frozenset(names)


def _annotated_app_parameters(arguments: ast.arguments, imports: ImportIndex) -> frozenset[str]:
    parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        parameters.append(arguments.vararg)
    if arguments.kwarg is not None:
        parameters.append(arguments.kwarg)
    return frozenset(
        parameter.arg
        for parameter in parameters
        if parameter.annotation is not None
        and any(
            imports.resolves(parameter.annotation, sources=frozenset({source}), symbol=symbol)
            for source, symbol in _APP_TYPES
        )
    )


def _is_on_event_decorator(node: ast.expr, app_names: frozenset[str]) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "on_event"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in app_names
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value in _EVENT_NAMES
    )
