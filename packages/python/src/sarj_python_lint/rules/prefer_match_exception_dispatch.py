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


_MIN_TYPE_BRANCHES = 3
_MIN_REFINEMENTS = 2
_ISINSTANCE_ARGUMENTS = 2
_EXCEPTION_ANNOTATIONS = frozenset({"BaseException", "Exception"})
_EXCEPTION_SUFFIXES = ("Error", "Exception")
_BUILTIN_EXCEPTION_TYPES = frozenset(
    {
        "ArithmeticError",
        "AssertionError",
        "AttributeError",
        "BufferError",
        "EOFError",
        "Exception",
        "FileExistsError",
        "FileNotFoundError",
        "FloatingPointError",
        "ImportError",
        "IndentationError",
        "IndexError",
        "InterruptedError",
        "IsADirectoryError",
        "KeyError",
        "LookupError",
        "MemoryError",
        "ModuleNotFoundError",
        "NameError",
        "NotADirectoryError",
        "NotImplementedError",
        "OSError",
        "OverflowError",
        "PermissionError",
        "ProcessLookupError",
        "RecursionError",
        "ReferenceError",
        "RuntimeError",
        "SyntaxError",
        "SystemError",
        "TabError",
        "TimeoutError",
        "TypeError",
        "UnboundLocalError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "UnicodeError",
        "UnicodeTranslateError",
        "ValueError",
        "ZeroDivisionError",
    }
)


class _TypeBranch(NamedTuple):
    subject: str
    types: frozenset[str]


@final
class PreferMatchExceptionDispatch(Rule):
    id: str = "prefer-match-exception-dispatch"
    code: str = "SARJ453"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Prefer guarded match/case for refined exception type dispatch.",
        rationale=(
            "A long exception classifier that repeats isinstance checks and then refines one exception type hides "
            "the ordered set of provider outcomes. Guarded class cases make the type and refinement order explicit."
        ),
        remediation=(
            "Consider repeated guarded class cases while preserving subclass order, guard evaluation, and "
            "fallthrough. Keep constant comparisons in guards; a bare name in a class-pattern field captures "
            "instead of comparing."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only functions whose dispatch subject is a simple parameter annotated Exception or BaseException are checked.",
            "The classifier must contain at least three adjacent isinstance branches and an immediate return or raise fallback; one or more branches must contain two or more terminating refinement checks.",
            "Type operands must be unshadowed builtin or imported names ending in Error or Exception, including literal tuples and PEP 604 unions. Imported runtime groups with plural or unrelated names are excluded.",
            "This is an advisory, not a safe automatic rewrite: imported bindings and custom instance checks cannot be proven from syntax, and guarded cases must preserve overlap and fallthrough.",
            "Generated files and projects proven to support Python before 3.10 are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="refined-provider-error-classifier",
                scenario="refined-exception-dispatch",
                title="Repeated type checks hide an ordered provider error classifier",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/errors.py",
                        "from providers import APIConnectionError, APIStatusError, APITimeoutError\n\n"
                        "def category(error: BaseException) -> str:\n"
                        "    if isinstance(error, TimeoutError | APITimeoutError):\n"
                        "        return 'timeout'\n"
                        "    if isinstance(error, APIStatusError):\n"
                        "        if error.status_code == 429:\n"
                        "            return 'rate_limit'\n"
                        "        if error.status_code >= 500:\n"
                        "            return 'provider_5xx'\n"
                        "    if isinstance(error, APIConnectionError):\n"
                        "        return 'connection'\n"
                        "    return 'unknown'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/errors.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="guarded-provider-error-cases",
                scenario="refined-exception-dispatch",
                title="Guarded class cases retain refinement fallthrough",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/errors.py",
                        "from providers import APIConnectionError, APIStatusError, APITimeoutError\n\n"
                        "def category(error: BaseException) -> str:\n"
                        "    match error:\n"
                        "        case TimeoutError() | APITimeoutError():\n"
                        "            return 'timeout'\n"
                        "        case APIStatusError() if error.status_code == 429:\n"
                        "            return 'rate_limit'\n"
                        "        case APIStatusError() if error.status_code >= 500:\n"
                        "            return 'provider_5xx'\n"
                        "        case APIConnectionError():\n"
                        "            return 'connection'\n"
                        "        case _:\n"
                        "            return 'unknown'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/errors.py"),
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
        if not imports.builtin_is_unshadowed("isinstance") or _has_wildcard_import(tree) or _has_local_import(tree):
            return []
        findings = [
            _diagnostic(path, self.code, first, subject)
            for function in _functions(tree)
            for subject in _exception_subjects(function, imports)
            for first in _classifier_starts(function.body, subject, imports)
        ]
        if findings and self.has_declared_python_support_before(path, (3, 10)):
            return []
        findings.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return findings


def _functions(tree: ast.Module) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    return tuple(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))


def _exception_subjects(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
) -> frozenset[str]:
    arguments = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    if function.args.vararg is not None:
        arguments = (*arguments, function.args.vararg)
    if function.args.kwarg is not None:
        arguments = (*arguments, function.args.kwarg)
    return frozenset(
        argument.arg
        for argument in arguments
        if isinstance(argument.annotation, ast.Name)
        and argument.annotation.id in _EXCEPTION_ANNOTATIONS
        and imports.builtin_is_unshadowed(argument.annotation.id)
    )


def _classifier_starts(
    body: list[ast.stmt],
    subject: str,
    imports: ImportIndex,
) -> tuple[ast.If, ...]:
    findings: list[ast.If] = []
    for statements in _nested_statement_lists(body):
        index = 0
        while index < len(statements):
            candidates, cursor = _adjacent_bare_ifs(statements, index)
            branches = _validated_branches(candidates, subject, imports)
            if branches is not None and _is_classifier(branches, statements, cursor):
                findings.append(branches[0][0])
                index = cursor + 1
            else:
                index = max(cursor, index + 1)
    return tuple(findings)


def _adjacent_bare_ifs(statements: list[ast.stmt], start: int) -> tuple[list[ast.If], int]:
    cursor = start
    candidates: list[ast.If] = []
    while cursor < len(statements):
        candidate = statements[cursor]
        if not isinstance(candidate, ast.If) or candidate.orelse:
            break
        candidates.append(candidate)
        cursor += 1
    return candidates, cursor


def _validated_branches(
    candidates: list[ast.If],
    subject: str,
    imports: ImportIndex,
) -> list[tuple[ast.If, _TypeBranch, bool]] | None:
    branches: list[tuple[ast.If, _TypeBranch, bool]] = []
    for statement in candidates:
        branch = _type_branch(statement.test, imports)
        if branch is None or branch.subject != subject:
            return None
        refined = _is_refinement_body(statement.body, subject)
        if not refined and not _body_terminates(statement.body):
            return None
        branches.append((statement, branch, refined))
    return branches


def _nested_statement_lists(body: list[ast.stmt]) -> tuple[list[ast.stmt], ...]:
    blocks: list[list[ast.stmt]] = [body]

    def visit(statements: list[ast.stmt]) -> None:
        for statement in statements:
            match statement:
                case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Lambda():
                    continue
                case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
                    children = (statement.body, statement.orelse)
                case ast.With() | ast.AsyncWith():
                    children = (statement.body,)
                case ast.Try() | ast.TryStar():
                    children = (statement.body, statement.orelse, statement.finalbody)
                    children = (*children, *(handler.body for handler in statement.handlers))
                case ast.Match():
                    children = tuple(case.body for case in statement.cases)
                case _:
                    children = ()
            for child in children:
                blocks.append(child)
                visit(child)

    visit(body)
    return tuple(blocks)


def _is_classifier(
    branches: list[tuple[ast.If, _TypeBranch, bool]],
    statements: list[ast.stmt],
    fallback_index: int,
) -> bool:
    if len(branches) < _MIN_TYPE_BRANCHES or fallback_index >= len(statements):
        return False
    if not isinstance(statements[fallback_index], (ast.Return, ast.Raise)):
        return False
    if not any(refined for _, _, refined in branches):
        return False
    seen: set[str] = set()
    bodies: set[tuple[str, ...]] = set()
    for statement, branch, _ in branches:
        if seen.intersection(branch.types):
            return False
        seen.update(branch.types)
        body = tuple(ast.dump(child) for child in statement.body)
        if body in bodies:
            return False
        bodies.add(body)
    return len(seen) >= _MIN_TYPE_BRANCHES


def _type_branch(test: ast.expr, imports: ImportIndex) -> _TypeBranch | None:
    if not (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id == "isinstance"
        and len(test.args) == _ISINSTANCE_ARGUMENTS
        and not test.keywords
        and isinstance(test.args[0], ast.Name)
    ):
        return None
    types = _exception_type_references(test.args[1], imports)
    return _TypeBranch(test.args[0].id, types) if types else None


def _exception_type_references(expression: ast.expr, imports: ImportIndex) -> frozenset[str] | None:
    if isinstance(expression, ast.Tuple):
        parts = expression.elts
    elif isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.BitOr):
        parts = _flatten_union(expression)
    else:
        parts = [expression]
    references = [_exception_type_reference(part, imports) for part in parts]
    if any(reference is None for reference in references):
        return None
    return frozenset(reference for reference in references if reference is not None)


def _flatten_union(expression: ast.expr) -> list[ast.expr]:
    if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.BitOr):
        return [*_flatten_union(expression.left), *_flatten_union(expression.right)]
    return [expression]


def _exception_type_reference(expression: ast.expr, imports: ImportIndex) -> str | None:
    if (
        isinstance(expression, ast.Name)
        and expression.id in _BUILTIN_EXCEPTION_TYPES
        and imports.builtin_is_unshadowed(expression.id)
    ):
        return f"builtins.{expression.id}"
    qualified = imports.resolved_qualified_name(expression)
    if qualified is None:
        return None
    terminal = qualified.rpartition(".")[2]
    return qualified if terminal.endswith(_EXCEPTION_SUFFIXES) else None


def _is_refinement_body(body: list[ast.stmt], subject: str) -> bool:
    return len(body) >= _MIN_REFINEMENTS and all(
        isinstance(statement, ast.If)
        and not statement.orelse
        and _body_terminates(statement.body)
        and _is_subject_refinement(statement.test, subject)
        and not any(isinstance(node, ast.NamedExpr) for node in ast.walk(statement.test))
        for statement in body
    )


def _is_subject_refinement(test: ast.expr, subject: str) -> bool:
    match test:
        case ast.Compare(left=left, comparators=comparators):
            return any(_is_subject_projection(value, subject) for value in (left, *comparators))
        case ast.BoolOp(values=values):
            return bool(values) and all(_is_subject_refinement(value, subject) for value in values)
        case ast.UnaryOp(op=ast.Not(), operand=operand):
            return _is_subject_refinement(operand, subject)
        case _:
            return False


def _is_subject_projection(value: ast.expr, subject: str) -> bool:
    while isinstance(value, ast.Attribute):
        value = value.value
    return isinstance(value, ast.Name) and value.id == subject


def _body_terminates(body: list[ast.stmt]) -> bool:
    if not body:
        return False
    match body[-1]:
        case ast.Return() | ast.Raise():
            return True
        case ast.If(body=if_body, orelse=else_body):
            return bool(else_body) and _body_terminates(if_body) and _body_terminates(else_body)
        case _:
            return False


def _has_wildcard_import(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names) for node in ast.walk(tree)
    )


def _has_local_import(tree: ast.Module) -> bool:
    module_imports = {id(statement) for statement in tree.body if isinstance(statement, (ast.Import, ast.ImportFrom))}
    return any(
        isinstance(node, (ast.Import, ast.ImportFrom)) and id(node) not in module_imports for node in ast.walk(tree)
    )


def _diagnostic(path: Path, code: str, node: ast.If, subject: str) -> Diagnostic:
    return Diagnostic(
        path=path,
        line=node.lineno,
        col=node.col_offset + 1,
        code=code,
        severity=Severity.WARNING,
        message=(
            f"Refined exception type dispatch on '{subject}' — consider guarded match/case while preserving "
            "subclass order, guard evaluation, and fallthrough."
        ),
    )
