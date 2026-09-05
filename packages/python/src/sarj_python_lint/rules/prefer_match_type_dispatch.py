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
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_MIN_BRANCHES = 3
_ISINSTANCE_ARGS = 2
_BUILTIN_TYPES = frozenset(
    {
        "bool",
        "bytearray",
        "bytes",
        "complex",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "memoryview",
        "object",
        "range",
        "set",
        "str",
        "tuple",
        "type",
    }
)
_LOWERCASE_AST_TYPES = frozenset(
    {
        "alias",
        "arg",
        "arguments",
        "boolop",
        "cmpop",
        "comprehension",
        "excepthandler",
        "expr",
        "expr_context",
        "keyword",
        "match_case",
        "mod",
        "operator",
        "pattern",
        "slice",
        "stmt",
        "type_ignore",
        "type_param",
        "unaryop",
        "withitem",
    }
)


class _TypeBranch(NamedTuple):
    subject: str
    types: frozenset[str]


class _Dispatch(NamedTuple):
    subject: str
    branch_count: int


@final
class PreferMatchTypeDispatch(Rule):
    id: str = "prefer-match-type-dispatch"
    code: str = "SARJ080"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Prefer `match` for three-or-more-branch runtime type dispatch.",
        rationale=(
            "A long mutually exclusive `isinstance` dispatch repeats its subject and hides the closed list of "
            "runtime shapes; class patterns put that dispatch in one explicit construct."
        ),
        remediation=(
            "Replace the branches with `match subject` and one class-pattern arm per distinct type; combine types "
            "that share behavior with an OR-pattern."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only three or more adjacent, unguarded `isinstance` branches over the same simple name are checked.",
            "The checked types must be unshadowed builtins, unshadowed module-local classes, or proven stdlib ast classes; unresolved imports, runtime type groups, repeated type references, generated files, and non-terminating sibling checks are excluded.",
            "A terminal-looking context-manager body does not prove a sibling branch terminates: exceptions can be suppressed. An unconditional return or raise after the context manager remains eligible.",
            "Declared support for Python before 3.10 suppresses this recommendation when proven by the nearest project metadata or exact installed-distribution ownership. Missing or ambiguous target metadata retains advisory behavior; it does not prove a modern target.",
        ),
        examples=(
            RuleExample(
                example_id="three-branch-type-dispatch",
                title="Repeated branches dispatch on runtime type",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/parser.py",
                        "def parse(value: object):\n"
                        "    if isinstance(value, str):\n"
                        "        return parse_text(value)\n"
                        "    elif isinstance(value, bytes):\n"
                        "        return parse_bytes(value)\n"
                        "    elif isinstance(value, dict):\n"
                        "        return parse_mapping(value)\n"
                        "    raise TypeError(type(value))\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parser.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="match-type-cases",
                title="Class patterns make the type dispatch explicit",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/parser.py",
                        "def parse(value: object):\n"
                        "    match value:\n"
                        "        case str():\n"
                        "            return parse_text(value)\n"
                        "        case bytes():\n"
                        "            return parse_bytes(value)\n"
                        "        case dict():\n"
                        "            return parse_mapping(value)\n"
                        "        case _:\n"
                        "            raise TypeError(type(value))\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parser.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree)
        all_nodes = tuple(ast.walk(tree))
        unsafe_bindings = _unsafe_local_bound_names(tree, all_nodes)
        has_wildcard_import = any(
            isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names) for node in all_nodes
        )
        if not imports.builtin_is_unshadowed("isinstance") or "isinstance" in unsafe_bindings or has_wildcard_import:
            return []
        local_classes = _unshadowed_module_classes(tree, all_nodes)
        findings = _ladder_findings(
            all_nodes,
            path,
            self.code,
            imports,
            local_classes,
            unsafe_bindings=unsafe_bindings,
        )
        findings.extend(
            _sibling_findings(
                all_nodes,
                path,
                self.code,
                imports,
                local_classes,
                unsafe_bindings=unsafe_bindings,
            )
        )
        if findings and self.has_declared_python_support_before(path, (3, 10)):
            return []
        findings.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return findings


def _unshadowed_module_classes(tree: ast.Module, all_nodes: tuple[ast.AST, ...]) -> frozenset[str]:
    classes = [statement.name for statement in tree.body if isinstance(statement, ast.ClassDef)]
    rebound = {
        candidate.id
        for candidate in all_nodes
        if isinstance(candidate, ast.Name) and isinstance(candidate.ctx, (ast.Store, ast.Del))
    }
    rebound.update(candidate.arg for candidate in all_nodes if isinstance(candidate, ast.arg))
    rebound.update(
        candidate.name
        for candidate in all_nodes
        if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and (not isinstance(candidate, ast.ClassDef) or candidate not in tree.body)
    )
    rebound.update(
        alias.asname or alias.name.partition(".")[0]
        for statement in tree.body
        if isinstance(statement, (ast.Import, ast.ImportFrom))
        for alias in statement.names
        if alias.name != "*"
    )
    return frozenset(name for name in classes if classes.count(name) == 1 and name not in rebound)


def _unsafe_local_bound_names(tree: ast.Module, all_nodes: tuple[ast.AST, ...]) -> frozenset[str]:
    module_imports = {id(statement) for statement in tree.body if isinstance(statement, (ast.Import, ast.ImportFrom))}
    names = {
        alias.asname or alias.name.partition(".")[0]
        for statement in all_nodes
        if isinstance(statement, (ast.Import, ast.ImportFrom)) and id(statement) not in module_imports
        for alias in statement.names
    }
    names.update(
        candidate.name
        for candidate in all_nodes
        if isinstance(candidate, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and candidate.name is not None
    )
    names.update(
        candidate.rest
        for candidate in all_nodes
        if isinstance(candidate, ast.MatchMapping) and candidate.rest is not None
    )
    return frozenset(names)


def _ladder_findings(
    all_nodes: tuple[ast.AST, ...],
    path: Path,
    code: str,
    imports: ImportIndex,
    local_classes: frozenset[str],
    *,
    unsafe_bindings: frozenset[str],
) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    continuations: set[int] = set()
    for node in all_nodes:
        if not isinstance(node, ast.If) or id(node) in continuations:
            continue
        branches = [node]
        child_ids: list[int] = []
        current = node
        while len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
            current = current.orelse[0]
            branches.append(current)
            child_ids.append(id(current))
        dispatch = _dispatch(branches, imports, local_classes, unsafe_bindings)
        if dispatch is not None:
            continuations.update(child_ids)
            findings.append(_diagnostic(path, code, node, dispatch, "isinstance ladder"))
    return findings


def _sibling_findings(
    all_nodes: tuple[ast.AST, ...],
    path: Path,
    code: str,
    imports: ImportIndex,
    local_classes: frozenset[str],
    *,
    unsafe_bindings: frozenset[str],
) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    for owner in all_nodes:
        for statements in _statement_blocks(owner):
            index = 0
            while index < len(statements):
                run: list[ast.If] = []
                cursor = index
                subject: str | None = None
                seen: set[str] = set()
                while cursor < len(statements):
                    statement = statements[cursor]
                    if not isinstance(statement, ast.If) or statement.orelse or not _body_terminates(statement.body):
                        break
                    branch = _type_branch(statement.test, imports, local_classes, unsafe_bindings)
                    if (
                        branch is None
                        or (subject is not None and branch.subject != subject)
                        or bool(seen & branch.types)
                    ):
                        break
                    run.append(statement)
                    subject = branch.subject
                    seen.update(branch.types)
                    cursor += 1
                dispatch = _dispatch(run, imports, local_classes, unsafe_bindings)
                if dispatch is not None:
                    findings.append(_diagnostic(path, code, run[0], dispatch, "terminating isinstance sequence"))
                index = max(cursor, index + 1)
    return findings


def _dispatch(
    branches: list[ast.If],
    imports: ImportIndex,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
) -> _Dispatch | None:
    if len(branches) < _MIN_BRANCHES:
        return None
    parsed = [_type_branch(branch.test, imports, local_classes, unsafe_bindings) for branch in branches]
    if any(branch is None for branch in parsed):
        return None
    typed = [branch for branch in parsed if branch is not None]
    subjects = {branch.subject for branch in typed}
    if len(subjects) != 1:
        return None
    seen: set[str] = set()
    for branch in typed:
        if seen & branch.types:
            return None
        seen.update(branch.types)
    if len(seen) < _MIN_BRANCHES:
        return None
    return _Dispatch(subjects.pop(), len(branches))


def _type_branch(
    test: ast.expr,
    imports: ImportIndex,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
) -> _TypeBranch | None:
    if not (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id == "isinstance"
        and len(test.args) == _ISINSTANCE_ARGS
        and not test.keywords
        and isinstance(test.args[0], ast.Name)
    ):
        return None
    types = _type_references(test.args[1], imports, local_classes, unsafe_bindings)
    return _TypeBranch(test.args[0].id, types) if types else None


def _type_references(
    expression: ast.expr,
    imports: ImportIndex,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
) -> frozenset[str] | None:
    if isinstance(expression, ast.Tuple):
        parts = expression.elts
    elif isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.BitOr):
        parts = _flatten_union(expression)
    else:
        parts = [expression]
    references = [_type_reference(part, imports, local_classes, unsafe_bindings) for part in parts]
    if any(reference is None for reference in references):
        return None
    return frozenset(reference for reference in references if reference is not None)


def _flatten_union(expression: ast.expr) -> list[ast.expr]:
    if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.BitOr):
        return [*_flatten_union(expression.left), *_flatten_union(expression.right)]
    return [expression]


def _type_reference(
    expression: ast.expr,
    imports: ImportIndex,
    local_classes: frozenset[str],
    unsafe_bindings: frozenset[str],
) -> str | None:
    if isinstance(expression, ast.Name):
        if (
            expression.id in _BUILTIN_TYPES
            and imports.builtin_is_unshadowed(expression.id)
            and expression.id not in unsafe_bindings
        ):
            return expression.id
        if expression.id in local_classes and expression.id not in unsafe_bindings:
            return expression.id
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    if isinstance(root, ast.Name) and root.id in unsafe_bindings:
        return None
    symbol = imports.resolved_symbol(expression, sources=frozenset({"ast"}))
    if symbol is None or not (symbol[:1].isupper() or symbol in _LOWERCASE_AST_TYPES):
        return None
    return f"ast.{symbol}"


def _diagnostic(path: Path, code: str, node: ast.If, dispatch: _Dispatch, shape: str) -> Diagnostic:
    return Diagnostic(
        path=path,
        line=node.lineno,
        col=node.col_offset + 1,
        code=code,
        severity=Severity.WARNING,
        message=(
            f"{dispatch.branch_count}-branch {shape} on '{dispatch.subject}' — use match/case class patterns "
            "so the mutually exclusive runtime type dispatch is explicit."
        ),
    )


def _body_terminates(body: list[ast.stmt]) -> bool:
    if not body:
        return False
    last = body[-1]
    match last:
        case ast.Return() | ast.Raise() | ast.Break() | ast.Continue():
            return True
        case ast.If(body=if_body, orelse=else_body):
            return bool(else_body) and _body_terminates(if_body) and _body_terminates(else_body)
        case _:
            return False


def _statement_blocks(node: ast.AST) -> tuple[list[ast.stmt], ...]:
    match node:
        case ast.Module() | ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return (node.body,)
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            return node.body, node.orelse
        case ast.With() | ast.AsyncWith() | ast.ExceptHandler() | ast.match_case():
            return (node.body,)
        case ast.Try() | ast.TryStar():
            return node.body, node.orelse, node.finalbody, *(handler.body for handler in node.handlers)
        case _:
            return ()
