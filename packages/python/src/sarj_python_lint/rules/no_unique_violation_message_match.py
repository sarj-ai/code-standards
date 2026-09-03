from __future__ import annotations

import ast
from dataclasses import dataclass
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
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_PSYCOPG_ERROR_SOURCES = frozenset({"psycopg.errors", "psycopg2.errors"})
_ASYNCPG_ERROR_SOURCES = frozenset({"asyncpg", "asyncpg.exceptions"})
_MESSAGE_TRANSFORMS = frozenset({"casefold", "lower", "lstrip", "rstrip", "strip", "upper"})
_MESSAGE_PREDICATES = frozenset({"endswith", "startswith"})
_MESSAGE_ATTRIBUTES = frozenset({"message_detail", "message_primary", "pgerror"})
_REGEX_PREDICATES = frozenset({"fullmatch", "match", "search"})
_REGEX_MESSAGE_POSITION = 1


@dataclass(frozen=True, slots=True)
class _HandlerContext:
    exception_name: str
    driver: str
    aliases: frozenset[str]
    imports: ImportIndex


@final
class NoUniqueViolationMessageMatch(Rule):
    id = "no-unique-violation-message-match"
    code = "SARJ404"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Do not make unique-violation control flow depend on rendered exception text.",
        rationale=(
            "Database error text is localized and can change with driver or server versions; supported PostgreSQL "
            "drivers expose the violated constraint as structured diagnostic data."
        ),
        remediation=(
            "Compare the driver's structured constraint field: `exc.diag.constraint_name` for psycopg or "
            "`exc.constraint_name` for asyncpg. SQLSTATE 23505 identifies the violation category, not the constraint."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule recognizes import-proven psycopg/psycopg2 UniqueViolation and asyncpg UniqueViolationError handlers whose translating branch matches direct or single-assignment rendered-message data.",
            "Generic IntegrityError handlers, driver wrappers, branch-ambiguous aliases, and interprocedural message helpers remain outside its scope.",
            "Tests and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="message-matched-constraint",
                title="Unique constraint selected from error text",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/store.py",
                        "from psycopg import errors\n\ntry:\n    save()\nexcept errors.UniqueViolation as exc:\n    if 'user_email_key' in str(exc):\n        raise DuplicateEmail from exc\n    raise\n",
                    ),
                ),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="structured-constraint-check",
                title="Unique constraint selected from structured diagnostics",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/store.py",
                        "from psycopg import errors\n\ntry:\n    save()\nexcept errors.UniqueViolation as exc:\n    if exc.diag.constraint_name == 'user_email_key':\n        raise DuplicateEmail from exc\n    raise\n",
                    ),
                ),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source) or "UniqueViolation" not in source:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = _module_import_index(tree)
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        findings: list[tuple[ast.expr, _HandlerContext]] = []
        for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)):
            driver = _caught_driver(handler.type, imports)
            if (
                handler.name is None
                or driver is None
                or _locally_shadows_exception(handler.type, handler, parents)
                or _handler_rebinds(handler, handler.name)
                or not _builtins_are_available(tree, handler, parents)
            ):
                continue
            context = _HandlerContext(
                exception_name=handler.name,
                driver=driver,
                aliases=_stable_message_aliases(handler, handler.name),
                imports=imports,
            )
            findings.extend((node, context) for node in _classification_matches(handler.body, context))
        findings.sort(key=lambda item: (item[0].lineno, item[0].col_offset))
        return [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=_message(context),
                severity=Severity.ERROR,
            )
            for node, context in findings
        ]


def _caught_driver(node: ast.expr | None, imports: ImportIndex) -> str | None:
    if node is None:
        return None
    candidates = node.elts if isinstance(node, ast.Tuple) else (node,)
    drivers = {_exception_driver(candidate, imports) for candidate in candidates}
    if None in drivers or not drivers:
        return None
    return drivers.pop() if len(drivers) == 1 else "supported PostgreSQL driver"


def _exception_driver(node: ast.expr, imports: ImportIndex) -> str | None:
    if imports.resolves(node, sources=_PSYCOPG_ERROR_SOURCES, symbol="UniqueViolation"):
        return "psycopg"
    if imports.resolves(node, sources=_ASYNCPG_ERROR_SOURCES, symbol="UniqueViolationError"):
        return "asyncpg"
    return None


def _module_import_index(tree: ast.Module) -> ImportIndex:
    body: list[ast.stmt] = []
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and statement.module in {"psycopg", "psycopg2"}:
            regular_names = [alias for alias in statement.names if alias.name != "errors"]
            if regular_names:
                body.append(ast.ImportFrom(module=statement.module, names=regular_names, level=statement.level))
            body.extend(
                ast.Import(
                    names=[ast.alias(name=f"{statement.module}.errors", asname=alias.asname or alias.name)]
                )
                for alias in statement.names
                if alias.name == "errors"
            )
            continue
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            body.append(statement)
            continue
        body.extend(
            ast.Assign(targets=[ast.Name(id=name, ctx=ast.Store())], value=ast.Constant(None))
            for name in _statement_bound_names(statement)
        )
    return ImportIndex.from_tree(ast.Module(body=body, type_ignores=[]))


def _statement_bound_names(statement: ast.stmt) -> frozenset[str]:
    names: set[str] = set()
    match statement:
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            names.add(statement.name)
        case _:
            for node in ast.walk(statement):
                if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                    names.add(node.id)
                elif isinstance(node, ast.alias):
                    names.add(node.asname or node.name.partition(".")[0])
    return frozenset(names)


def _locally_shadows_exception(
    caught: ast.expr | None,
    handler: ast.ExceptHandler,
    parents: dict[int, ast.AST],
) -> bool:
    roots = _exception_root_names(caught)
    owner: ast.AST = handler
    while (parent := parents.get(id(owner))) is not None:
        owner = parent
        if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return any(
                _binds_name(node, roots)
                for root in (*owner.args.posonlyargs, *owner.args.args, *owner.args.kwonlyargs, *owner.body)
                for node in _walk_same_scope(root)
            )
    return False


def _exception_root_names(node: ast.expr | None) -> set[str]:
    if node is None:
        return set()
    candidates = node.elts if isinstance(node, ast.Tuple) else (node,)
    roots: set[str] = set()
    for candidate in candidates:
        current = candidate
        while isinstance(current, ast.Attribute):
            current = current.value
        if isinstance(current, ast.Name):
            roots.add(current.id)
    return roots


def _handler_rebinds(handler: ast.ExceptHandler, name: str) -> bool:
    for statement in handler.body:
        for node in _walk_same_scope(statement):
            if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del)):
                return True
            if isinstance(node, ast.ExceptHandler) and node.name == name:
                return True
    return False


def _walk_same_scope(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    for child in ast.iter_child_nodes(node):
        yield from _walk_same_scope(child)


def _builtins_are_available(
    tree: ast.Module,
    handler: ast.ExceptHandler,
    parents: dict[int, ast.AST],
) -> bool:
    owner: ast.AST = handler
    while (parent := parents.get(id(owner))) is not None:
        owner = parent
        if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return not any(
                _binds_name(node, {"repr", "str"})
                for root in (*owner.args.posonlyargs, *owner.args.args, *owner.args.kwonlyargs, *owner.body)
                for node in _walk_same_scope(root)
            )
    return not any(
        _binds_name(node, {"repr", "str"}) for statement in tree.body for node in _walk_same_scope(statement)
    )


def _binds_name(node: ast.AST, names: set[str]) -> bool:
    if isinstance(node, ast.arg):
        return node.arg in names
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return node.id in names
    if isinstance(node, ast.alias):
        return (node.asname or node.name.partition(".")[0]) in names
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names


def _stable_message_aliases(handler: ast.ExceptHandler, exception_name: str) -> frozenset[str]:
    stores: dict[str, int] = {}
    assignments: list[tuple[str, ast.expr]] = []
    for statement in handler.body:
        for node in _walk_same_scope(statement):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                stores[node.id] = stores.get(node.id, 0) + 1
        if isinstance(statement, (ast.Assign, ast.AnnAssign)) and isinstance(statement.value, ast.expr):
            targets = statement.targets if isinstance(statement, ast.Assign) else (statement.target,)
            assignments.extend((target.id, statement.value) for target in targets if isinstance(target, ast.Name))
    aliases: set[str] = set()
    changed = True
    empty_imports = ImportIndex.from_tree(ast.Module(body=[], type_ignores=[]))
    while changed:
        changed = False
        context = _HandlerContext(exception_name, "", frozenset(aliases), empty_imports)
        for name, value in assignments:
            if stores.get(name) == 1 and name not in aliases and _is_message_value(value, context):
                aliases.add(name)
                changed = True
    return frozenset(aliases)


def _classification_matches(statements: list[ast.stmt], context: _HandlerContext) -> list[ast.expr]:
    found: dict[int, ast.expr] = {}
    for statement in statements:
        for node in _walk_same_scope(statement):
            if isinstance(node, ast.If) and _branch_translates(node.body):
                for match in _message_matches(node.test, context):
                    found.setdefault(id(match), match)
            elif isinstance(node, ast.Return) and node.value is not None:
                for match in _message_matches(node.value, context):
                    found.setdefault(id(match), match)
    return list(found.values())


def _branch_translates(statements: list[ast.stmt]) -> bool:
    return any(isinstance(node, (ast.Raise, ast.Return)) for statement in statements for node in _walk_same_scope(statement))


def _message_matches(node: ast.expr, context: _HandlerContext) -> list[ast.expr]:
    found: list[ast.expr] = []
    for candidate in _walk_same_scope(node):
        if isinstance(candidate, ast.Compare):
            operands = (candidate.left, *candidate.comparators)
            for left, operator, right in zip(operands[:-1], candidate.ops, operands[1:], strict=True):
                if isinstance(operator, (ast.In, ast.NotIn)) and _is_message_value(right, context):
                    found.append(candidate)
                    break
                if isinstance(operator, (ast.Eq, ast.NotEq)) and (
                    _is_message_value(left, context) or _is_message_value(right, context)
                ):
                    found.append(candidate)
                    break
        elif isinstance(candidate, ast.Call) and _is_message_predicate(candidate, context):
            found.append(candidate)
    return found


def _is_message_predicate(node: ast.Call, context: _HandlerContext) -> bool:
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in _MESSAGE_PREDICATES
        and bool(node.args)
        and _is_message_value(node.func.value, context)
    ):
        return True
    return (
        context.imports.resolved_symbol(node.func, sources=frozenset({"re"})) in _REGEX_PREDICATES
        and len(node.args) > _REGEX_MESSAGE_POSITION
        and _is_message_value(node.args[_REGEX_MESSAGE_POSITION], context)
    )


def _is_message_value(node: ast.expr, context: _HandlerContext) -> bool:
    match node:
        case ast.Name(id=name):
            return name in context.aliases
        case ast.Call(func=func, args=args, keywords=keywords):
            if (
                isinstance(func, ast.Name)
                and func.id in {"repr", "str"}
                and len(args) == 1
                and not keywords
                and _is_exception_reference(args[0], context.exception_name)
            ):
                return True
            return (
                isinstance(func, ast.Attribute)
                and func.attr in _MESSAGE_TRANSFORMS
                and not args
                and not keywords
                and _is_message_value(func.value, context)
            )
        case ast.Attribute(value=value, attr=attribute):
            if attribute in _MESSAGE_ATTRIBUTES and _is_exception_reference(value, context.exception_name):
                return True
            return (
                attribute in {"message_detail", "message_primary"}
                and isinstance(value, ast.Attribute)
                and value.attr == "diag"
                and _is_exception_reference(value.value, context.exception_name)
            )
        case ast.Subscript(value=ast.Attribute(value=value, attr="args")):
            return _is_exception_reference(value, context.exception_name)
        case _:
            return False


def _is_exception_reference(node: ast.expr, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _message(context: _HandlerContext) -> str:
    field = (
        f"{context.exception_name}.constraint_name"
        if context.driver == "asyncpg"
        else f"{context.exception_name}.diag.constraint_name"
    )
    return (
        "Unique-violation control flow depends on unstable rendered message text; compare the driver's structured "
        f"diagnostics instead (for constraint identity, `{field}`)."
    )
