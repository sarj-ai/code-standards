from __future__ import annotations

import ast
from dataclasses import dataclass
from itertools import pairwise
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
)
from sarj_python_lint.rules._comments import comment_line_numbers
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from sarj_python_lint._file_context import PythonFileContext


_MAX_WALRUS_READS = 3
_OPAQUE_SCOPES = (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_NESTED_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_MAX_LINE_LENGTH = 120
_MAX_VALUE_LENGTH = 80
_EXPLANATORY_VALUES = (ast.Name, ast.BinOp, ast.BoolOp, ast.Compare, ast.IfExp)
_POSTFIX_VALUES = (ast.Name, ast.Attribute, ast.Call, ast.Subscript)
_EFFECTS = (ast.Call, ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr, *_OPAQUE_SCOPES)


@dataclass(frozen=True)
class _Finding:
    assignment: ast.Assign
    name: str
    value: str
    walrus: bool


@final
class InlineSingleUseLocal(Rule):
    id = "inline-single-use-local"
    code = "SARJ592"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Inline a local that only feeds the immediately following statement.",
        rationale=(
            "A one-line temporary that is read only by the next statement adds a name, a line and a "
            "reader indirection without carrying state forward. Writing the expression at its single use "
            "keeps the data flow local; binding it with `:=` at its first argument keeps one call self-contained "
            "when that call reads the value more than once."
        ),
        remediation=(
            "Replace `value = compute(); consume(value)` with `consume(compute())`. When the next call reads "
            "the value up to three times, bind it at its first argument: "
            "`Record(id=(record_id := new_id()), path=f'{record_id}.wav')`. Keep the separate statement when the "
            "name is an intentional debugging boundary or the inlined call would stop reading clearly."
        ),
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only plain single-name assignments of one-line values inside non-test functions are checked; annotated, augmented and unpacking assignments, literals and aliases are excluded. Tests keep separately named arrange and act steps.",
            "Named arithmetic, comparisons, boolean expressions, conditional expressions and comprehensions are treated as explanatory variables and kept. The consumer must start on the next line; a blank line or comment marks an intentional paragraph boundary.",
            "Values containing lambdas or comprehensions, reads inside an existing assignment expression, positions that would need parentheses (an awaited value used as an attribute, subscript or callee target), f-string positions for values other than simple attribute, subscript or argument-free call reads, values longer than 80 characters and inlined lines longer than 120 columns are excluded. Augmented assignments are excluded so effectful values do not hide inside accumulation.",
            "The name must be bound exactly once in the function, must not be global, nonlocal or captured by a nested scope, and every read must be in the header of the immediately following statement (the whole simple statement, an if test, for iterable, with items or match subject).",
            "Reads inside lambdas, comprehensions, conditional expressions, non-first boolean operands, while tests and compound-statement bodies are excluded because inlining would change how often or whether the value is evaluated.",
            "Nothing that can run code (calls, awaits, yields, assignment expressions, comprehensions, subscripts or attribute reads other than the callee) may be evaluated before the first read, so moving the value cannot reorder side effects.",
            "`return name` is owned by Ruff RET504, assertions are excluded because optimized runs remove them, and exception-constructor arguments in `raise` are excluded because Ruff EM101/EM102 require the message variable.",
            "The `:=` form is suggested only when two or three reads sit inside the next statement's top-level call and the first read is a direct argument of that call. Comments between the statements, suppressions, generated files and stubs are respected.",
        ),
        examples=(
            RuleExample(
                example_id="single-use-temporary",
                title="A temporary only feeds the next call",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "async def store(objects, path, audio):\n"
                        "    payload = encode(audio)\n"
                        "    await objects.upload(path=path, data=payload)\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="inlined-expression",
                title="The expression is written at its single use",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "async def store(objects, path, audio):\n"
                        "    await objects.upload(path=path, data=encode(audio))\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="value-reused-later",
                title="A value that later statements read keeps its name",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "async def store(objects, path, audio):\n"
                        "    payload = encode(audio)\n"
                        "    await objects.upload(path=path, data=payload)\n"
                        "    return len(payload)\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.path.suffix == ".pyi" or context.generated or is_test_path(context.path):
            return []
        tree = context.tree
        if tree is None:
            return []
        comments = comment_line_numbers(context.source)
        diagnostics: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            for finding in _function_findings(function, context.source_lines, comments):
                assignment = finding.assignment
                if context.suppressions.is_suppressed(assignment.lineno, self.code):
                    continue
                message = (
                    f"`{finding.name}` is only read by the next call; bind it at its first argument as "
                    f"`({finding.name} := {finding.value})` instead of a separate statement."
                    if finding.walrus
                    else f"`{finding.name}` only feeds the next statement; inline `{finding.value}` at its use."
                )
                diagnostics.append(
                    Diagnostic(
                        context.path,
                        assignment.lineno,
                        assignment.col_offset + 1,
                        self.code,
                        message,
                        severity=Severity.WARNING,
                    )
                )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _function_findings(
    function: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str], comments: frozenset[int]
) -> Iterator[_Finding]:
    usage = _ScopeUsage.of(function)
    for body in _blocks(function.body):
        for assignment, consumer in pairwise(body):
            if (finding := _finding(assignment, consumer, usage, lines, comments)) is not None:
                yield finding


def _finding(
    assignment: ast.stmt, consumer: ast.stmt, usage: _ScopeUsage, lines: list[str], comments: frozenset[int]
) -> _Finding | None:
    match assignment:
        case ast.Assign(targets=[ast.Name(id=name)], value=value, type_comment=None):
            pass
        case _:
            return None
    if (
        consumer.lineno != (assignment.end_lineno or 0) + 1
        or comments.intersection(range(assignment.lineno, consumer.lineno))
        or name in usage.excluded
        or usage.stores.get(name, 0) != 1
    ):
        return None
    segment = _single_line_segment(value, lines)
    reads = usage.loads.get(name, [])
    if segment is None or not _compact_value(value, segment) or not reads:
        return None
    if (first := _first_safe_read(consumer, reads)) is None:
        return None
    walrus = len(reads) > 1
    replacement = f"({name} := {segment})" if walrus else segment
    if not _fits(first, name, replacement, lines) or _awkward_position(first, value, consumer):
        return None
    if _variant_blocked(consumer, name, first, reads, walrus=walrus):
        return None
    return _Finding(assignment, name, segment, walrus=walrus)


def _first_safe_read(consumer: ast.stmt, reads: list[ast.Name]) -> ast.Name | None:
    if (headers := _headers(consumer)) is None:
        return None
    ordered = [node for header in headers for node in _evaluation(header)]
    positions = {id(node): index for index, node in enumerate(ordered)}
    if any(id(read) not in positions for read in reads):
        return None
    first = min(reads, key=lambda read: positions[id(read)])
    before = ordered[: positions[id(first)]]
    if any(isinstance(node, _EFFECTS) for node in before) or _unsafe_before(before, headers):
        return None
    return first


def _variant_blocked(consumer: ast.stmt, name: str, first: ast.Name, reads: list[ast.Name], *, walrus: bool) -> bool:
    if walrus:
        return len(reads) > _MAX_WALRUS_READS or not _direct_argument_of_top_call(consumer, first, reads)
    return _returns_name(consumer, name) or _raise_argument(consumer, first)


def _compact_value(value: ast.expr, segment: str) -> bool:
    return (
        value.lineno == value.end_lineno
        and len(segment) <= _MAX_VALUE_LENGTH
        and not isinstance(value, _EXPLANATORY_VALUES)
        and not _literal(value)
        and not any(isinstance(inner, _OPAQUE_SCOPES) for inner in ast.walk(value))
    )


def _single_line_segment(value: ast.expr, lines: list[str]) -> str | None:
    if value.lineno != value.end_lineno or value.end_col_offset is None or value.lineno > len(lines):
        return None
    encoded = lines[value.lineno - 1].encode()
    return encoded[value.col_offset : value.end_col_offset].decode(errors="replace")


def _fits(read: ast.Name, name: str, replacement: str, lines: list[str]) -> bool:
    line = lines[read.lineno - 1]
    return len(line) - len(name) + len(replacement) <= _MAX_LINE_LENGTH


def _awkward_position(read: ast.Name, value: ast.expr, consumer: ast.stmt) -> bool:
    for node in ast.walk(consumer):
        match node:
            case ast.Attribute(value=target) | ast.Subscript(value=target) | ast.Call(func=target) if target is read:
                return not isinstance(value, _POSTFIX_VALUES)
            case ast.NamedExpr(value=bound) if _contains(bound, read):
                return True
            case ast.JoinedStr() if _contains(node, read):
                return not _plain_lookup(value)
            case _:
                pass
    return False


def _contains(node: ast.AST, read: ast.Name) -> bool:
    return any(inner is read for inner in ast.walk(node))


def _plain_lookup(value: ast.expr) -> bool:
    match value:
        case ast.Attribute() | ast.Subscript() | ast.Call(args=[], keywords=[]):
            return True
        case _:
            return False


@dataclass(frozen=True)
class _ScopeUsage:
    loads: dict[str, list[ast.Name]]
    stores: dict[str, int]
    excluded: frozenset[str]

    @classmethod
    def of(cls, function: ast.FunctionDef | ast.AsyncFunctionDef) -> _ScopeUsage:
        loads: dict[str, list[ast.Name]] = {}
        stores: dict[str, int] = {}
        excluded: set[str] = {argument.arg for argument in _arguments(function.args)}
        for node, nested in _walk_scope(function):
            match node:
                case ast.Name(id=name, ctx=ast.Load()):
                    if nested:
                        excluded.add(name)
                    else:
                        loads.setdefault(name, []).append(node)
                case ast.Name(id=name):
                    if nested:
                        excluded.add(name)
                    stores[name] = stores.get(name, 0) + 1
                case ast.Global(names=names) | ast.Nonlocal(names=names):
                    excluded.update(names)
                case ast.ExceptHandler(name=str(name)) | ast.MatchAs(name=str(name)) | ast.MatchStar(name=str(name)):
                    excluded.add(name)
                case ast.MatchMapping(rest=str(name)):
                    excluded.add(name)
                case ast.alias(name=module, asname=asname):
                    excluded.add(asname or module.split(".")[0])
                case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                    excluded.add(name)
                case _:
                    pass
        return cls(loads, stores, frozenset(excluded))


def _arguments(arguments: ast.arguments) -> Iterator[ast.arg]:
    yield from arguments.posonlyargs
    yield from arguments.args
    yield from arguments.kwonlyargs
    if arguments.vararg is not None:
        yield arguments.vararg
    if arguments.kwarg is not None:
        yield arguments.kwarg


def _walk_scope(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[tuple[ast.AST, bool]]:
    pending: list[tuple[ast.AST, bool]] = [(statement, False) for statement in function.body]
    while pending:
        node, nested = pending.pop()
        yield node, nested
        inner = nested or isinstance(node, (*_NESTED_DEFINITIONS, *_OPAQUE_SCOPES))
        pending.extend((child, inner) for child in ast.iter_child_nodes(node))


def _blocks(body: list[ast.stmt]) -> Iterator[list[ast.stmt]]:
    yield body
    for statement in body:
        for nested in _child_blocks(statement):
            yield from _blocks(nested)


def _child_blocks(statement: ast.stmt) -> list[list[ast.stmt]]:
    match statement:
        case (
            ast.If(body=body, orelse=orelse)
            | ast.For(body=body, orelse=orelse)
            | ast.AsyncFor(body=body, orelse=orelse)
            | ast.While(body=body, orelse=orelse)
        ):
            return [body, orelse]
        case ast.With(body=body) | ast.AsyncWith(body=body):
            return [body]
        case (
            ast.Try(body=body, handlers=handlers, orelse=orelse, finalbody=final)
            | ast.TryStar(body=body, handlers=handlers, orelse=orelse, finalbody=final)
        ):
            return [
                body,
                *(handler.body for handler in handlers),
                orelse,
                final,
            ]
        case ast.Match(cases=cases):
            return [case.body for case in cases]
        case _:
            return []


def _headers(statement: ast.stmt) -> list[ast.AST] | None:
    match statement:
        case ast.If(test=test):
            return [test]
        case ast.For(iter=iterable) | ast.AsyncFor(iter=iterable):
            return [iterable]
        case ast.With(items=items) | ast.AsyncWith(items=items):
            return [item.context_expr for item in items]
        case ast.Match(subject=subject):
            return [subject]
        case ast.Expr() | ast.Assign() | ast.AnnAssign() | ast.Return() | ast.Raise():
            return [statement]
        case _:
            return None


def _evaluation(node: ast.AST) -> Iterator[ast.AST]:
    match node:
        case ast.Assign(targets=targets, value=value):
            children: Sequence[ast.AST] = [value, *targets]
        case ast.AnnAssign(target=target, value=value):
            children = [target] if value is None else [value, target]
        case ast.Dict(keys=keys, values=values):
            children = [
                part for key, item in zip(keys, values, strict=True) for part in (key, item) if part is not None
            ]
        case ast.Call(func=func, args=args, keywords=keywords):
            children = [func, *args, *(keyword.value for keyword in keywords)]
        case ast.BoolOp(values=values):
            children = values[:1]
        case ast.IfExp(test=test):
            children = [test]
        case _ if isinstance(node, (*_OPAQUE_SCOPES, *_NESTED_DEFINITIONS)):
            children = []
        case _:
            children = list(ast.iter_child_nodes(node))
    for child in children:
        yield from _evaluation(child)
    yield node


def _unsafe_before(before: list[ast.AST], headers: list[ast.AST]) -> bool:
    callees = {
        id(part)
        for header in headers
        for call in ast.walk(header)
        if isinstance(call, ast.Call)
        for part in ast.walk(call.func)
    }
    return any(
        isinstance(node, ast.Subscript) or (isinstance(node, ast.Attribute) and id(node) not in callees)
        for node in before
    )


def _literal(node: ast.expr) -> bool:
    match node:
        case ast.Constant() | ast.UnaryOp(operand=ast.Constant()):
            return True
        case _:
            return False


def _returns_name(statement: ast.stmt, name: str) -> bool:
    return isinstance(statement, ast.Return) and isinstance(statement.value, ast.Name) and statement.value.id == name


def _raise_argument(statement: ast.stmt, read: ast.Name) -> bool:
    if not isinstance(statement, ast.Raise) or statement.exc is None:
        return False
    return any(
        isinstance(call, ast.Call)
        and any(node is read for argument in _call_arguments(call) for node in ast.walk(argument))
        for call in ast.walk(statement.exc)
    )


def _call_arguments(call: ast.Call) -> list[ast.expr]:
    return [*call.args, *(keyword.value for keyword in call.keywords)]


def _direct_argument_of_top_call(statement: ast.stmt, first: ast.Name, reads: list[ast.Name]) -> bool:
    match statement:
        case ast.Expr(value=value) | ast.Assign(value=value) | ast.Return(value=value) | ast.AnnAssign(value=value):
            pass
        case _:
            return False
    if isinstance(value, ast.Await):
        value = value.value
    if not isinstance(value, ast.Call):
        return False
    arguments = _call_arguments(value)
    if not any(argument is first for argument in arguments):
        return False
    inside = {id(node) for argument in arguments for node in ast.walk(argument)}
    return all(id(read) in inside for read in reads)
