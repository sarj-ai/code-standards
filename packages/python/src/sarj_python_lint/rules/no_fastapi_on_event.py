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
    from collections.abc import Set as AbstractSet
    from pathlib import Path


_APP_TYPES = frozenset(
    {
        ("fastapi", "APIRouter"),
        ("fastapi", "FastAPI"),
        ("starlette.applications", "Starlette"),
        ("starlette.routing", "Router"),
    }
)
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
            "Decorators on proven FastAPI, APIRouter, Starlette, and Starlette Router values or their `.router` are checked.",
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
    app_names = set(extra_app_names)
    findings: list[Diagnostic] = []
    for statement in statements:
        _update_app_names(statement, app_names, imports)
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


def _update_app_names(statement: ast.stmt, names: set[str], imports: ImportIndex) -> None:
    if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
        return
    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
    target_names = [target.id for target in targets if isinstance(target, ast.Name)]
    value = statement.value
    proven = value is not None and _is_app_expression(value, names, imports)
    if isinstance(statement, ast.AnnAssign) and _is_app_type(statement.annotation, imports):
        proven = True
    for name in target_names:
        if proven:
            names.add(name)
        else:
            names.discard(name)


def _is_app_expression(node: ast.expr, names: set[str], imports: ImportIndex) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Attribute) and node.attr == "router":
        return isinstance(node.value, ast.Name) and node.value.id in names
    return isinstance(node, ast.Call) and any(
        imports.resolves(node.func, sources=frozenset({source}), symbol=symbol) for source, symbol in _APP_TYPES
    )


def _is_app_type(node: ast.expr, imports: ImportIndex) -> bool:
    return any(imports.resolves(node, sources=frozenset({source}), symbol=symbol) for source, symbol in _APP_TYPES)


def _annotated_app_parameters(arguments: ast.arguments, imports: ImportIndex) -> frozenset[str]:
    parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        parameters.append(arguments.vararg)
    if arguments.kwarg is not None:
        parameters.append(arguments.kwarg)
    return frozenset(
        parameter.arg
        for parameter in parameters
        if parameter.annotation is not None and _is_app_type(parameter.annotation, imports)
    )


def _is_on_event_decorator(node: ast.expr, app_names: AbstractSet[str]) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "on_event"
        and _is_proven_receiver(node.func.value, app_names)
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value in _EVENT_NAMES
    )


def _is_proven_receiver(node: ast.expr, app_names: AbstractSet[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in app_names
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "router"
        and isinstance(node.value, ast.Name)
        and node.value.id in app_names
    )
