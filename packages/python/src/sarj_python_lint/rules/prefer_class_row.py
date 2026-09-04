from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

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
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path


_DICT_ROW = "dict_row"
_FETCH_METHODS = frozenset({"fetchall", "fetchmany", "fetchone"})
_MODEL_VALIDATE = "model_validate"
_PSYCOPG = "psycopg"
_ROW_FACTORY = "row_factory"
_ROWS = "rows"
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


class _BoundCursor(NamedTuple):
    variable: str
    factory: ast.expr


class _FetchedValue(NamedTuple):
    name: str
    line: int
    many: bool


@final
class PreferClassRow(Rule):
    id: str = "prefer-class-row"
    code: str = "SARJ013"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Avoid fetching a Psycopg dictionary row only to construct the same model manually.",
        rationale=(
            "Folding an immediate model conversion into the row factory removes an intermediate mapping and gives "
            "fetches the declared model type."
        ),
        remediation=(
            "Use `row_factory=class_row(Model)` when selected column names map directly to that model; retain "
            "`dict_row` for dynamic, derived, connection-wide, or multi-shape results."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only maintained production code with a locally bound `.cursor(row_factory=dict_row)` is analyzed.",
            "The fetched value must flow unchanged into `Model(**row)` or `Model.model_validate(row)` in the same scope.",
            "Renamed fields, preprocessing, connection-level factories, dynamic models, and multi-shape cursors are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="dict-row-then-model",
                title="Fetched dictionary is immediately converted",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        "from psycopg.rows import dict_row\n\nasync def load(conn):\n    async with conn.cursor(row_factory=dict_row) as cursor:\n        row = await cursor.fetchone()\n        return Task.model_validate(row)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/task_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="model-row-factory",
                title="Cursor constructs the model directly",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/task_store.py",
                        "from psycopg.rows import class_row\n\nasync def load(conn):\n    async with conn.cursor(row_factory=class_row(Task)) as cursor:\n        return await cursor.fetchone()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/task_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or is_test_path(path) or "migrations" in {part.lower() for part in path.parts}:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = _PsycopgImports.from_tree(tree)
        diagnostics: list[Diagnostic] = []
        for function in _functions(tree):
            shadowed = _scope_bindings(function)
            for cursor in _bound_cursors(function):
                if not imports.is_dict_row(cursor.factory, shadowed):
                    continue
                models = _models_built_from_cursor(function, cursor.variable)
                if len(models) != 1:
                    continue
                model = next(iter(models))
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=cursor.factory.lineno,
                        col=cursor.factory.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=(
                            f"this dict row is immediately converted to `{model}`; use `class_row({model})` to "
                            "construct it during fetch"
                        ),
                    )
                )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


class _PsycopgImports:
    def __init__(self) -> None:
        self.direct: set[str] = set()
        self.row_modules: set[str] = set()
        self.psycopg_modules: set[str] = set()

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _PsycopgImports:
        imports = cls()
        for statement in tree.body:
            if isinstance(statement, ast.Import):
                imports._add_import(statement)
            elif isinstance(statement, ast.ImportFrom):
                imports._add_from_import(statement)
            else:
                imports._remove(_bound_names((statement,)))
        return imports

    def _add_import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == _PSYCOPG:
                self.psycopg_modules.add(alias.asname or _PSYCOPG)
            elif alias.name == "psycopg.rows":
                if alias.asname is None:
                    self.psycopg_modules.add(_PSYCOPG)
                else:
                    self.row_modules.add(alias.asname)

    def _add_from_import(self, node: ast.ImportFrom) -> None:
        if node.level:
            return
        if node.module == "psycopg.rows":
            self.direct.update(alias.asname or alias.name for alias in node.names if alias.name == _DICT_ROW)
        elif node.module == _PSYCOPG:
            self.row_modules.update(alias.asname or alias.name for alias in node.names if alias.name == _ROWS)

    def _remove(self, names: frozenset[str]) -> None:
        self.direct.difference_update(names)
        self.row_modules.difference_update(names)
        self.psycopg_modules.difference_update(names)

    def is_dict_row(self, node: ast.expr, shadowed: frozenset[str]) -> bool:
        if isinstance(node, ast.NamedExpr):
            node = node.value
        if isinstance(node, ast.Name):
            return node.id in self.direct and node.id not in shadowed
        if not isinstance(node, ast.Attribute) or node.attr != _DICT_ROW:
            return False
        receiver = node.value
        if isinstance(receiver, ast.Name):
            return receiver.id in self.row_modules and receiver.id not in shadowed
        return (
            isinstance(receiver, ast.Attribute)
            and receiver.attr == _ROWS
            and isinstance(receiver.value, ast.Name)
            and receiver.value.id in self.psycopg_modules
            and receiver.value.id not in shadowed
        )


class _BindingVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    @override
    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    @override
    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node

    @override
    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)

    @override
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names)


def _bound_names(statements: Iterable[ast.stmt]) -> frozenset[str]:
    visitor = _BindingVisitor()
    for statement in statements:
        visitor.visit(statement)
    return frozenset(visitor.names)


def _scope_bindings(function: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    args = function.args
    parameters = {
        *(arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)),
        *((args.vararg.arg,) if args.vararg is not None else ()),
        *((args.kwarg.arg,) if args.kwarg is not None else ()),
    }
    return frozenset(parameters) | _bound_names(function.body)


def _functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    return (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))


def _scope_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    pending: list[ast.AST] = list(reversed(function.body))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, _SCOPE_NODES):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(node))))


def _bound_cursors(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[_BoundCursor]:
    cursors: list[_BoundCursor] = []
    for node in _scope_nodes(function):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if isinstance(item.optional_vars, ast.Name):
                    cursor = _cursor(item.context_expr, item.optional_vars.id)
                    if cursor is not None:
                        cursors.append(cursor)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            cursor = _cursor(node.value, node.targets[0].id)
            if cursor is not None:
                cursors.append(cursor)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            cursor = _cursor(node.value, node.target.id)
            if cursor is not None:
                cursors.append(cursor)
    return cursors


def _cursor(expression: ast.expr, variable: str) -> _BoundCursor | None:
    if not (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Attribute)
        and expression.func.attr == "cursor"
    ):
        return None
    factory = next((keyword.value for keyword in expression.keywords if keyword.arg == _ROW_FACTORY), None)
    return None if factory is None else _BoundCursor(variable, factory)


def _models_built_from_cursor(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    cursor: str,
) -> frozenset[str]:
    scoped_nodes = list(_scope_nodes(function))
    fetched_values = _fetched_values(scoped_nodes, cursor)
    if not fetched_values:
        return frozenset()
    models: set[str] = set()
    for fetched in fetched_values:
        if fetched.many:
            converted = _models_from_collection(scoped_nodes, fetched)
        else:
            converted = _models_from_value(scoped_nodes, fetched)
        if len(converted) != 1:
            return frozenset()
        models.update(converted)
    return frozenset(models)


def _fetched_values(scoped_nodes: list[ast.AST], cursor: str) -> list[_FetchedValue]:
    fetched: list[_FetchedValue] = []
    for node in scoped_nodes:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            method = _fetch_method(node.value, cursor)
            if method is not None:
                fetched.append(_FetchedValue(node.targets[0].id, node.lineno, method != "fetchone"))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            method = _fetch_method(node.value, cursor)
            if method is not None:
                fetched.append(_FetchedValue(node.target.id, node.lineno, method != "fetchone"))
    return fetched


def _fetch_method(expression: ast.expr, cursor: str) -> str | None:
    if isinstance(expression, ast.Await):
        expression = expression.value
    if not (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Attribute)
        and isinstance(expression.func.value, ast.Name)
        and expression.func.value.id == cursor
        and expression.func.attr in _FETCH_METHODS
    ):
        return None
    return expression.func.attr


def _models_from_value(scoped_nodes: list[ast.AST], fetched: _FetchedValue) -> set[str]:
    models: set[str] = set()
    for node in scoped_nodes:
        if not isinstance(node, ast.Call) or node.lineno <= fetched.line:
            continue
        if _is_rebound_between(scoped_nodes, fetched.name, fetched.line, node.lineno):
            continue
        model = _model_conversion(node, fetched.name)
        if model is not None:
            models.add(model)
    return models


def _models_from_collection(scoped_nodes: list[ast.AST], fetched: _FetchedValue) -> set[str]:
    models: set[str] = set()
    for node in scoped_nodes:
        if not isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)) or node.lineno <= fetched.line:
            continue
        if _is_rebound_between(scoped_nodes, fetched.name, fetched.line, node.lineno):
            continue
        for generator in node.generators:
            if not (
                isinstance(generator.iter, ast.Name)
                and generator.iter.id == fetched.name
                and isinstance(generator.target, ast.Name)
            ):
                continue
            model = _model_conversion(node.elt, generator.target.id) if isinstance(node.elt, ast.Call) else None
            if model is not None:
                models.add(model)
    return models


def _model_conversion(call: ast.Call, row: str) -> str | None:
    validated_model = _validated_model(call, row)
    if validated_model is not None:
        return validated_model
    if not any(
        keyword.arg is None and isinstance(keyword.value, ast.Name) and keyword.value.id == row
        for keyword in call.keywords
    ):
        return None
    return _model_name(call.func)


def _validated_model(call: ast.Call, row: str) -> str | None:
    if not isinstance(call.func, ast.Attribute) or call.func.attr != _MODEL_VALIDATE:
        return None
    if len(call.args) != 1 or call.keywords:
        return None
    argument = call.args[0]
    if not isinstance(argument, ast.Name) or argument.id != row:
        return None
    return _model_name(call.func.value)


def _model_name(node: ast.expr) -> str | None:
    dotted = _dotted(node)
    if dotted is None or not dotted.rpartition(".")[2][:1].isupper():
        return None
    return dotted


def _is_rebound_between(scoped_nodes: list[ast.AST], name: str, start: int, end: int) -> bool:
    return any(
        start < node.lineno < end and _writes_name(node, name) for node in scoped_nodes if isinstance(node, ast.stmt)
    )


def _writes_name(node: ast.stmt, name: str) -> bool:
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = [*node.targets]
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        targets = [node.target]
    return any(_target_root(target) == name for target in targets)


def _target_root(node: ast.expr) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _dotted(node: ast.expr) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join((node.id, *reversed(parts)))
