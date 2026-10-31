from __future__ import annotations

import ast
from bisect import bisect_left, insort
from dataclasses import dataclass
from functools import cached_property
from hashlib import sha256
from io import StringIO
from itertools import pairwise
import re
import tokenize
from typing import TYPE_CHECKING, Final, Literal, NamedTuple
from unicodedata import normalize

from sarj_rule_contracts import TextEdit, apply_edits
from sarj_rule_contracts.files import fix_file

from sarj_python_lint._autofix_aliases import AliasFixes
from sarj_python_lint._autofix_annotations import AnnotationFixes
from sarj_python_lint._autofix_comments import CommentFixes
from sarj_python_lint._autofix_declared_contracts import DeclaredContractFixes
from sarj_python_lint._autofix_declared_tests import fixes as declared_test_fixes
from sarj_python_lint._autofix_docs import DocstringFixes
from sarj_python_lint._autofix_enums import EnumFixes
from sarj_python_lint._autofix_exhaustiveness import ExhaustivenessFixes
from sarj_python_lint._autofix_parameters import ParameterFixes
from sarj_python_lint._autofix_repeated import RepeatedLiteralFixes
from sarj_python_lint._autofix_security import fixes as security_fixes
from sarj_python_lint._autofix_sql_projection import alias_fixes as sql_alias_fixes, fixes as sql_projection_fixes
from sarj_python_lint._autofix_tests import fixes as testing_fixes
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint._fixes import apply_fixes as apply_native_fixes
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules import (
    REGISTRY,
    duplicate_adjacent_exception_handler as exception_rule,
    no_comment_cruft as comment_cruft_rule,
    prefer_collection_comprehension as collection_rule,
    prefer_or_pattern as pattern_rule,
)
from sarj_python_lint.rules._ast_index import object_list
from sarj_python_lint.rules._closed_helpers import dynamic_namespace
from sarj_python_lint.rules._resource_provenance import ResourceProvenance
from sarj_python_lint.rules.prefer_match_type_dispatch import body_terminates


if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    from sarj_python_lint.rule_base import Diagnostic


type _Located = ast.expr | ast.stmt | ast.pattern | ast.ExceptHandler | ast.keyword | ast.arg


def _last_line(node: _Located) -> int:
    return node.end_lineno or node.lineno


def _type_parameter_names(node: ast.AST, context: PythonFileContext) -> frozenset[str]:
    names: set[str] = set()
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.TypeAlias)):
            names.update(
                parameter.name
                for parameter in current.type_params
                if isinstance(parameter, (ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple))
            )
        current = context.parents.get(current)
    return frozenset(names)


def _type_parameter_reference(node: ast.AST, context: PythonFileContext) -> bool:
    names = _type_parameter_names(node, context)
    return bool(names) and any(isinstance(child, ast.Name) and child.id in names for child in ast.walk(node))


_COMMENT_CODES = frozenset({"SARJ016", "SARJ089"})
_WALRUS_CODES = frozenset({"SARJ081", "SARJ432"})
_JWT_POSITIONAL_PREFIX_ARGUMENTS = 3
_STREAM_MIN_BODY_LENGTH = 3
_CONSTANT_TRUE_DEPTH_LIMIT = 32
# Bound accepted revisions; each rule still owns its work and replacement size.
_MAX_FIX_PASSES: Final = 256
_PURE_STRING_TRANSFORMS: Final[dict[str, str]] = {
    "strip": "stripped_value",
    "lower": "lowered_value",
    "upper": "uppered_value",
    "lstrip": "left_stripped_value",
    "rstrip": "right_stripped_value",
    "casefold": "casefolded_value",
    "capitalize": "capitalized_value",
    "title": "titled_value",
    "swapcase": "swapped_case_value",
    "expandtabs": "expanded_value",
}
_SEPARATOR = re.compile(r"[-=#*~_+.\s─-╿]{4,}\Z")
_SIMPLE_VALIDATION_PATTERN = re.compile(r"\^\[[A-Za-z0-9 -]+\](?:[+*?]|\{[0-9]+(?:,[0-9]*)?\})?\$\Z")


class _Span(NamedTuple):
    start: int
    end: int


class _Source:
    def __init__(self, context: PythonFileContext, diagnostics: Sequence[Diagnostic]) -> None:
        self.context = context
        self.text = context.source
        self.lines = StringIO(self.text, newline="").readlines()
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))
        self.comments = (
            {
                token.start[0]: token
                for token in tokenize.generate_tokens(StringIO(self.text, newline="").readline)
                if token.type == tokenize.COMMENT
            }
            if context.tree is not None
            else {}
        )
        self.comment_lines = sorted(self.comments)
        self.export_locations = frozenset(
            (diagnostic.line, diagnostic.col) for diagnostic in diagnostics if diagnostic.code == "SARJ098"
        )
        self.test_comment_locations = frozenset(
            (diagnostic.line, diagnostic.col) for diagnostic in diagnostics if diagnostic.code == "SARJ551"
        )

    @cached_property
    def enums(self) -> EnumFixes:
        return EnumFixes(self.context)

    @cached_property
    def annotations(self) -> AnnotationFixes:
        return AnnotationFixes(self.context)

    @cached_property
    def aliases(self) -> AliasFixes:
        return AliasFixes(self.context)

    @cached_property
    def commentary(self) -> CommentFixes:
        return CommentFixes(self.context, test_comment_locations=self.test_comment_locations)

    @cached_property
    def declared_contracts(self) -> DeclaredContractFixes:
        return DeclaredContractFixes(self.context)

    @cached_property
    def exhaustiveness(self) -> ExhaustivenessFixes:
        return ExhaustivenessFixes(self.context)

    @cached_property
    def repeated(self) -> RepeatedLiteralFixes:
        return RepeatedLiteralFixes(self.context)

    @cached_property
    def docstrings(self) -> DocstringFixes:
        return DocstringFixes(self.context)

    @cached_property
    def parameters(self) -> ParameterFixes:
        return ParameterFixes(self.context)

    def offset(self, line: int, column: int) -> int:
        prefix = self.lines[line - 1].encode("utf-8")[:column].decode("utf-8")
        return self.starts[line - 1] + len(prefix)

    def span(self, node: _Located) -> _Span:
        if node.end_lineno is None or node.end_col_offset is None:
            msg = "autofix requires a complete parsed source range"
            raise ValueError(msg)
        return _Span(
            self.offset(node.lineno, node.col_offset),
            self.offset(node.end_lineno, node.end_col_offset),
        )

    def segment(self, node: _Located) -> str:
        start, end = self.span(node)
        return self.text[start:end]

    def replace(self, node: _Located, replacement: str) -> TextEdit:
        start, end = self.span(node)
        return TextEdit(start, end, replacement)

    def full_statement(self, node: ast.stmt) -> _Span | None:
        start, end = self.span(node)
        line_start = self.starts[node.lineno - 1]
        line_end = self.starts[_last_line(node)]
        if self.text[line_start:start].strip() or self.text[end:line_end].strip():
            return None
        return _Span(line_start, line_end)

    def comments_between(self, start: int, end: int) -> bool:
        index = bisect_left(self.comment_lines, start)
        return index < len(self.comment_lines) and self.comment_lines[index] <= end


def _at(node: _Located, diagnostic: Diagnostic) -> bool:
    return node.lineno == diagnostic.line and node.col_offset + 1 == diagnostic.col


def _comment_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    token = source.comments.get(diagnostic.line)
    if token is None:
        return []
    body = token.string.removeprefix("#").strip()
    if (
        diagnostic.code == "SARJ016"
        and _SEPARATOR.fullmatch(body) is None
        and not comment_cruft_rule.is_section_label(body)
    ):
        return []
    start = source.starts[token.start[0] - 1]
    if source.text[start : start + token.start[1]].strip():
        return []
    newline = "\r\n" if source.lines[token.start[0] - 1].endswith("\r\n") else "\n"
    return [TextEdit(start, source.starts[token.end[0]], newline)]


def _comprehension_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    for node in source.context.nodes(ast.ListComp):
        generator = _literal_string_generator(node, diagnostic)
        if generator is None or not isinstance(generator.target, ast.Name):
            continue
        call = generator.ifs[0]
        if not isinstance(call, ast.Call) or ast.dump(node.elt) != ast.dump(call):
            continue
        stem = _cache_binding_name(call, generator.target, source)
        if stem is None or not _closed_comprehension_return(node, source):
            continue
        name = _fresh_comprehension_name(stem, source.text)
        return [source.replace(node.elt, name), source.replace(call, f"({name} := {source.segment(call)})")]
    return []


def _cache_binding_name(call: ast.Call, target: ast.Name, source: _Source) -> str | None:
    if call.keywords:
        return None
    match call:
        case ast.Call(func=ast.Attribute(value=ast.Name(id=name), attr=method), args=[]):
            return _PURE_STRING_TRANSFORMS.get(method) if name == target.id else None
        case ast.Call(func=ast.Name(id="len"), args=[ast.Name(id=name)]) if name == target.id:
            if (
                source.context.imports.builtin_is_unshadowed("len")
                and source.parameters.provenance.binding("len", call) is None
                and source.parameters.provenance.builtin_namespace_untouched
            ):
                return "value_length"
        case _:
            return None
    return None


def _literal_string_generator(node: ast.ListComp, diagnostic: Diagnostic) -> ast.comprehension | None:
    if len(node.generators) != 1:
        return None
    generator = node.generators[0]
    if generator.is_async or len(generator.ifs) != 1 or not _at(generator.ifs[0], diagnostic):
        return None
    if not isinstance(generator.iter, (ast.List, ast.Tuple)):
        return None
    return (
        generator
        if all(isinstance(value, ast.Constant) and isinstance(value.value, str) for value in generator.iter.elts)
        else None
    )


def _closed_comprehension_return(node: ast.ListComp, source: _Source) -> bool:
    statement = source.context.parents.get(node)
    owner = source.context.parents.get(statement) if statement is not None else None
    if not isinstance(statement, ast.Return) or not isinstance(owner, ast.FunctionDef):
        return False
    return (
        owner.body == [statement]
        and bool(source.parameters.closed_calls(owner))
        and not source.comments_between(node.lineno, _last_line(node))
    )


def _fresh_comprehension_name(stem: str, text: str) -> str:
    occupied = {
        normalize("NFKC", token.string)
        for token in tokenize.generate_tokens(StringIO(text, newline="").readline)
        if token.type == tokenize.NAME
    }
    name = stem
    suffix = 2
    while name in occupied:
        name = f"{stem}_{suffix}"
        suffix += 1
    return name


def _literal_loop_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    for function in source.context.nodes(ast.FunctionDef):
        if not source.parameters.closed_calls(function):
            continue
        match function.body:
            case [
                ast.Assign(targets=[ast.Name(id=accumulator)], value=ast.Constant(value="")) as initial,
                ast.For(
                    target=ast.Name(id=item),
                    iter=iterable,
                    body=[ast.AugAssign(target=ast.Name(id=target), op=ast.Add(), value=ast.Name(id=value)) as growth],
                    orelse=[],
                ),
                ast.Return(value=ast.Name(id=result) as returned_value),
            ]:
                if target != accumulator or value != item or item == accumulator or result != accumulator:
                    continue
                if not _nonempty_literal_fragments(iterable) or not _at(growth, diagnostic):
                    continue
                if source.comments_between(function.lineno, _last_line(function)):
                    continue
                return [
                    source.replace(initial.value, "[]"),
                    source.replace(growth, f"{accumulator}.append({item})"),
                    source.replace(returned_value, f"''.join({accumulator})"),
                ]
            case _:
                continue
    return []


def _nonempty_literal_fragments(iterable: ast.expr) -> bool:
    if not isinstance(iterable, (ast.List, ast.Tuple)) or len(iterable.elts) <= 1:
        return False
    return all(
        isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value for value in iterable.elts
    )


def _complexity_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    for function in source.context.nodes(ast.FunctionDef):
        arguments = function.args
        if not _at(function, diagnostic) or len(function.body) != 1:
            continue
        if arguments.posonlyargs or arguments.args or arguments.kwonlyargs or arguments.vararg or arguments.kwarg:
            continue
        root = function.body[0]
        leaf = _constant_true_return(root)
        if (
            leaf is None
            or leaf.lineno != leaf.end_lineno
            or source.full_statement(leaf) is None
            or source.comments_between(function.lineno, _last_line(function))
            or not source.parameters.closed_calls(function)
        ):
            continue
        if (span := source.full_statement(root)) is None:
            continue
        prefix = source.text[span.start : source.starts[leaf.lineno - 1]]
        blanks = "".join(character for character in prefix if character in "\r\n")
        indent = source.text[span.start : source.span(root).start]
        suffix = source.text[source.span(leaf).end : span.end]
        return [TextEdit(*span, blanks + indent + source.segment(leaf) + suffix)]
    return []


def _constant_true_return(statement: ast.stmt) -> ast.Return | None:
    depth = 0
    while isinstance(statement, ast.If):
        if (
            depth >= _CONSTANT_TRUE_DEPTH_LIMIT
            or not isinstance(statement.test, ast.Constant)
            or statement.test.value is not True
            or statement.orelse
            or len(statement.body) != 1
        ):
            return None
        depth += 1
        statement = statement.body[0]
    return (
        statement if depth and isinstance(statement, ast.Return) and isinstance(statement.value, ast.Constant) else None
    )


def _deletion_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    for function in source.context.nodes(ast.FunctionDef):
        arguments = function.args
        if arguments.posonlyargs or arguments.args or arguments.kwonlyargs or arguments.vararg or arguments.kwarg:
            continue
        match function.body:
            case [
                ast.Assign(targets=[ast.Name(id=name)], value=ast.Constant(value=None)),
                ast.Delete(targets=[ast.Name(id=target)]) as deletion,
                ast.Return(value=ast.Constant()),
            ] if name == target:
                pass
            case _:
                continue
        if (
            not _at(deletion, diagnostic)
            or deletion.lineno != deletion.end_lineno
            or source.comments_between(function.lineno, _last_line(function))
            or not source.parameters.closed_calls(function)
            or (span := source.full_statement(deletion)) is None
        ):
            continue
        newline = "".join(character for character in source.text[span.start : span.end] if character in "\r\n")
        return [TextEdit(*span, newline)]
    return []


def _regex_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    provenance = source.parameters.provenance
    if dynamic_namespace(source.context) or provenance.mock_namespace_patching or provenance.imported_namespace_hazards:
        return []
    for call in source.context.nodes(ast.Call):
        if not _regex_call_owned(call, source, diagnostic):
            continue
        pattern, subject = call.args
        if not isinstance(pattern, ast.Constant) or not isinstance(pattern.value, str):
            continue
        if _SIMPLE_VALIDATION_PATTERN.fullmatch(pattern.value) is None or not _literal_without_newline(subject):
            continue
        replacement = _strict_end_literal(source.segment(pattern))
        if replacement is not None:
            return [source.replace(pattern, replacement)]
    return []


def _regex_call_owned(call: ast.Call, source: _Source, diagnostic: Diagnostic) -> bool:
    match call:
        case ast.Call(func=ast.Attribute(value=ast.Name()), args=[_, _], keywords=[]):
            return (
                _at(call, diagnostic)
                and source.parameters.provenance.imported(call.func, "re.match")
                and not _type_parameter_reference(call.func, source.context)
                and not source.comments_between(call.lineno, _last_line(call))
            )
        case _:
            return False


def _literal_without_newline(subject: ast.expr) -> bool:
    return isinstance(subject, ast.Constant) and isinstance(subject.value, str) and "\n" not in subject.value


def _strict_end_literal(literal: str) -> str | None:
    tokens = list(tokenize.generate_tokens(StringIO(literal, newline="").readline))
    strings = [token for token in tokens if token.type == tokenize.STRING]
    if len(strings) != 1 or strings[0].string != literal:
        return None
    prefix = literal[: len(literal) - len(literal.lstrip("rRuU"))]
    quote = literal[len(prefix) : len(prefix) + 1]
    if quote not in {"'", '"'} or literal[len(prefix) :].startswith(quote * 3):
        return None
    ending = "\\Z" if "r" in prefix.lower() else "\\\\Z"
    return literal[:-2] + ending + quote


def _security_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return security_fixes(source.context, diagnostic)


def _sql_projection_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return sql_projection_fixes(source.context, diagnostic)


def _sql_alias_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return sql_alias_fixes(source.context, diagnostic)


def _alias_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    if not diagnostic.fixes:
        return source.aliases.fixes(diagnostic)
    validated = apply_native_fixes(source.text, diagnostic.fixes)
    edits = [
        TextEdit(
            source.offset(edit.start_line, edit.start_col - 1),
            source.offset(edit.end_line, edit.end_col - 1),
            edit.replacement,
        )
        for fix in diagnostic.fixes
        for edit in fix.edits
    ]
    if apply_edits(source.text, edits) != validated:
        msg = "native alias fix coordinates differ from contract edits"
        raise ValueError(msg)
    return edits


def _annotation_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return source.annotations.fixes(diagnostic)


def _enum_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return source.enums.fixes(diagnostic)


def _declared_contract_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return source.declared_contracts.fixes(diagnostic)


def _declared_testing_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return declared_test_fixes(source.context, diagnostic)


def _testing_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return testing_fixes(source.context, diagnostic)


def _commentary_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return source.commentary.fixes(diagnostic)


def _exhaustiveness_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return source.exhaustiveness.fixes(diagnostic)


def _repeated_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return source.repeated.fixes(diagnostic)


def _statement_pairs(context: PythonFileContext) -> Iterator[tuple[ast.stmt, ast.stmt]]:
    for owner in context.nodes(ast.AST):
        for field in ("body", "orelse", "finalbody"):
            value: object = getattr(  # sarj-noqa: SARJ557 -- Inspect optional statement-list fields across heterogeneous AST node types.
                owner, field, None
            )
            if object_list(value):
                statements = [item for item in value if isinstance(item, ast.stmt)]
                yield from pairwise(statements)


def _walrus_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    for assignment, condition in _statement_pairs(source.context):
        match assignment, condition:
            case ast.Assign(targets=[ast.Name() as target]), ast.If():
                pass
            case _:
                continue
        if not _at(assignment, diagnostic) or source.comments_between(assignment.lineno, condition.lineno):
            continue
        references = [node for node in ast.walk(condition.test) if isinstance(node, ast.Name) and node.id == target.id]
        if len(references) != 1 or (statement_span := source.full_statement(assignment)) is None:
            continue
        binding = f"({source.segment(target)} := {source.segment(assignment.value)})"
        return [TextEdit(*statement_span, ""), source.replace(references[0], binding)]
    return []


def _stream_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    for loop in source.context.nodes(ast.While):
        if len(loop.body) < _STREAM_MIN_BODY_LENGTH or not _at(loop.body[0], diagnostic):
            continue
        assignment, guard = loop.body[:2]
        if not isinstance(assignment, ast.Assign) or not isinstance(guard, ast.If):
            continue
        assignment_span = source.full_statement(assignment)
        guard_span = source.full_statement(guard)
        if assignment_span is None or guard_span is None or source.comments_between(loop.lineno, _last_line(guard)):
            continue
        suffix = " is not None" if isinstance(guard.test, ast.Compare) else ""
        condition = f"({source.segment(assignment.targets[0])} := {source.segment(assignment.value)}){suffix}"
        return [source.replace(loop.test, condition), TextEdit(assignment_span[0], guard_span[1], "")]
    return []


def _pattern_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    for run, replacement in pattern_rule.autofix_pattern_runs(source.context):
        first, last = run[0], run[-1]
        if not _at(first.pattern, diagnostic) or source.comments_between(
            first.pattern.lineno, _last_line(last.body[-1])
        ):
            continue
        first_end = source.starts[_last_line(first.body[-1])]
        last_end = source.starts[_last_line(last.body[-1])]
        return [source.replace(first.pattern, replacement), TextEdit(first_end, last_end, "")]
    return []


def _exception_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    provenance = ResourceProvenance(source.context)
    for statement in source.context.nodes(ast.Try):
        for first, second in zip(statement.handlers, statement.handlers[1:], strict=False):
            if not _at(second, diagnostic) or first.type is None:
                continue
            first_types = _exception_types(first.type, source.context, provenance)
            second_types = _exception_types(second.type, source.context, provenance)
            if not first_types or not second_types:
                continue
            names = [*first_types, *second_types]
            if source.comments_between(first.lineno, _last_line(second)):
                continue
            types = ", ".join(source.segment(name) for name in names)
            return [
                source.replace(first.type, f"({types})"),
                TextEdit(source.starts[second.lineno - 1], source.starts[_last_line(second)], ""),
            ]
    return []


def _exception_types(
    node: ast.expr | None, context: PythonFileContext, provenance: ResourceProvenance
) -> list[ast.Name]:
    if (
        isinstance(node, ast.Name)
        and not _type_parameter_reference(node, context)
        and exception_rule.is_builtin_exception_type(node, context, provenance)
    ):
        return [node]
    if isinstance(node, ast.Tuple):
        members = [_exception_types(element, context, provenance) for element in node.elts]
        return [name for member in members for name in member] if all(members) else []
    return []


def _exact_primitive(node: ast.expr, context: PythonFileContext) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (str, bytes, int, float, complex, bool, type(None)))
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"int", "float", "bool", "len", "ord", "hash", "id"}
        and context.imports.builtin_is_unshadowed(node.func.id)
        and not _type_parameter_reference(node.func, context)
    )


def _fstring_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    if source.context.dynamic_namespace or not ResourceProvenance(source.context).builtin_namespace_untouched:
        return []
    for expression in source.context.nodes(ast.BinOp):
        if not _at(expression, diagnostic) or source.comments_between(expression.lineno, _last_line(expression)):
            continue
        parts: list[ast.expr] = []
        for part in _concat_parts(expression):
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part)
            elif (converted := _primitive_conversion(part, source.context)) is not None:
                parts.append(converted)
            else:
                break
        else:
            return [source.replace(expression, ast.unparse(ast.JoinedStr(values=parts)))]
    return []


def _concat_parts(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [*_concat_parts(node.left), *_concat_parts(node.right)]
    return [node]


def _primitive_conversion(expression: ast.expr, context: PythonFileContext) -> ast.FormattedValue | None:
    match expression:
        case ast.Call(func=ast.Name(id=name), args=[value], keywords=[]) if name in {"str", "repr", "ascii"}:
            if (
                context.imports.builtin_is_unshadowed(name)
                and not _type_parameter_reference(expression.func, context)
                and _exact_primitive(value, context)
            ):
                return ast.FormattedValue(value=value, conversion=ord({"str": "s", "repr": "r", "ascii": "a"}[name]))
        case _:
            return None
    return None


def _export_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    if any(_is_export_insert(call) for call in source.context.nodes(ast.Call)):
        return []
    for sequence in source.context.nodes(ast.List, ast.Tuple):
        if not any(_at(element, diagnostic) for element in sequence.elts):
            continue
        if source.comments_between(sequence.lineno, _last_line(sequence)):
            continue
        remaining = [
            element
            for element in sequence.elts
            if (element.lineno, element.col_offset + 1) not in source.export_locations
        ]
        return [source.replace(sequence, _export_sequence(source, sequence, remaining))]
    return _export_append_fix(source, diagnostic)


def _is_export_insert(call: ast.Call) -> bool:
    match call.func:
        case ast.Attribute(value=ast.Name(id="__all__"), attr="insert"):
            return True
        case _:
            return False


def _export_sequence(source: _Source, sequence: ast.List | ast.Tuple, remaining: list[ast.expr]) -> str:
    contents = ", ".join(source.segment(element) for element in remaining)
    if isinstance(sequence, ast.Tuple):
        suffix = "," if len(remaining) == 1 else ""
        return f"({contents}{suffix})"
    return f"[{contents}]"


def _export_append_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    for statement in source.context.nodes(ast.Expr):
        match statement.value:
            case ast.Call(func=ast.Attribute(attr="append"), args=[*_, literal]):
                if _at(literal, diagnostic) and (span := source.full_statement(statement)) is not None:
                    return [TextEdit(*span, "")]
            case _:
                continue
    return []


def _mock_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    for assignment in source.context.nodes(ast.Assign, ast.AnnAssign):
        if not _at(assignment, diagnostic):
            continue
        call_edits = _mock_constructor_fix(source, assignment, diagnostic)
        if call_edits:
            return call_edits
        match assignment:
            case ast.Assign(targets=[ast.Attribute(attr="return_value" | "side_effect")]):
                if (span := source.full_statement(assignment)) is not None:
                    return [TextEdit(*span, "")]
            case _:
                continue
    return []


def _mock_constructor_fix(
    source: _Source, assignment: ast.Assign | ast.AnnAssign, diagnostic: Diagnostic
) -> list[TextEdit]:
    call = assignment.value
    if not isinstance(call, ast.Call) or source.comments_between(assignment.lineno, _last_line(assignment)):
        return []
    if _type_parameter_reference(call.func, source.context):
        return []
    dead_target = re.match(r"`[^`]+\.(return_value|side_effect)`", diagnostic.message)
    if dead_target is None:
        return []
    replacement = ast.Call(
        func=call.func,
        args=call.args,
        keywords=[keyword for keyword in call.keywords if keyword.arg != dead_target[1]],
    )
    return [source.replace(call, ast.unparse(replacement))]


def _disjoint_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    for expression in source.context.nodes(ast.BinOp, ast.Call):
        if not _at(expression, diagnostic) or source.comments_between(expression.lineno, _last_line(expression)):
            continue
        if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.BitAnd):
            left, right = expression.left, expression.right
        elif (
            isinstance(expression, ast.Call)
            and isinstance(expression.func, ast.Attribute)
            and expression.func.attr == "intersection"
            and len(expression.args) == 1
            and not expression.keywords
        ):
            left, right = expression.func.value, expression.args[0]
        else:
            continue
        if _primitive_set(left) and _primitive_set(right):
            return [source.replace(expression, f"(not ({source.segment(left)}).isdisjoint({source.segment(right)}))")]
    return []


def _primitive_set(node: ast.expr) -> bool:
    return isinstance(node, ast.Set) and all(
        isinstance(element, ast.Constant) and isinstance(element.value, (str, bytes, int, float, bool, type(None)))
        for element in node.elts
    )


def _dispatch_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    if diagnostic.code == "SARJ080" and diagnostic.severity is not Severity.ERROR:
        return []
    for root in source.context.nodes(ast.If):
        if not _at(root, diagnostic):
            continue
        type_dispatch = diagnostic.code == "SARJ080"
        roots = _dispatch_roots(root, source.context) if type_dispatch else [root]
        if source.comments_between(root.lineno, _last_line(roots[-1])) or (
            len(roots) > 1 and any(source.full_statement(branch) is None for branch in roots)
        ):
            continue
        matched = _dispatch_match(roots, source.context, type_dispatch=type_dispatch)
        if matched is None or not isinstance(matched.subject, ast.Name):
            continue
        if not _dispatch_parameter(root, matched.subject, source):
            continue
        rendered = ast.unparse(matched)
        indent = source.lines[root.lineno - 1][: root.col_offset]
        newline = "\r\n" if "\r\n" in source.text else "\n"
        return [
            TextEdit(
                source.span(root).start, source.span(roots[-1]).end, (newline + indent).join(rendered.splitlines())
            )
        ]
    return []


def _dispatch_roots(root: ast.If, context: PythonFileContext) -> list[ast.If]:
    if root.orelse:
        return [root]
    parent = context.parents.get(root)
    for field in ("body", "orelse", "finalbody"):
        value: object = getattr(  # sarj-noqa: SARJ557 -- Inspect optional statement-list fields across heterogeneous AST node types.
            parent, field, None
        )
        if not object_list(value) or root not in value:
            continue
        branches: list[ast.If] = []
        for statement in value[value.index(root) :]:
            if isinstance(statement, ast.If) and statement.orelse:
                return [root]
            if not isinstance(statement, ast.If) or not body_terminates(statement.body):
                break
            branches.append(statement)
        return branches or [root]
    return [root]


def _dispatch_match(roots: Sequence[ast.If], context: PythonFileContext, *, type_dispatch: bool) -> ast.Match | None:
    cases: list[ast.match_case] = []
    pending = list(reversed(roots))
    subject: ast.Name | None = None
    while pending:
        branch = pending.pop()
        if type_dispatch and _type_parameter_reference(branch.test, context):
            return None
        pattern = _dispatch_pattern(branch.test, type_dispatch=type_dispatch)
        if pattern is None or (subject is not None and subject.id != pattern[0].id):
            return None
        subject = pattern[0]
        cases.append(ast.match_case(pattern=pattern[1], guard=None, body=branch.body))
        if len(branch.orelse) == 1 and isinstance(branch.orelse[0], ast.If):
            pending.append(branch.orelse[0])
        elif branch.orelse:
            cases.append(ast.match_case(pattern=ast.MatchAs(), guard=None, body=branch.orelse))
    if subject is None or (type_dispatch and len(cases) == 1):
        return None
    return ast.Match(subject=subject, cases=cases)


def _dispatch_pattern(test: ast.expr, *, type_dispatch: bool) -> tuple[ast.Name, ast.pattern] | None:
    if type_dispatch:
        match test:
            case ast.Call(
                func=ast.Name(id="isinstance"), args=[ast.Name() as subject, ast.Name() as kind], keywords=[]
            ):
                if kind.id in {"str", "bytes", "int", "float", "bool", "dict", "list", "set", "tuple", "frozenset"}:
                    return subject, ast.MatchClass(cls=kind, patterns=[], kwd_attrs=[], kwd_patterns=[])
            case _:
                return None
        return None
    match test:
        case ast.Compare(left=ast.Name() as subject, ops=[ast.Eq()], comparators=[ast.Constant() as literal]):
            if isinstance(literal.value, (str, bytes, int, float)) and not isinstance(literal.value, bool):
                return subject, ast.MatchValue(value=literal)
        case _:
            return None
    return None


def _dispatch_parameter(root: ast.If, subject: ast.Name, source: _Source) -> bool:
    context = source.context
    owner: ast.AST | None = context.parents.get(root)
    while owner is not None and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        owner = context.parents.get(owner)
    if not isinstance(owner, ast.FunctionDef) or not source.parameters.closed_calls(owner):
        return False
    parameters = (*owner.args.posonlyargs, *owner.args.args, *owner.args.kwonlyargs)
    return subject.id in {argument.arg for argument in parameters} and not any(
        isinstance(node, (ast.Global, ast.Nonlocal)) and subject.id in node.names for node in ast.walk(owner)
    )


def _marker_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    if source.context.dynamic_namespace:
        return []
    for assignment in source.context.nodes(ast.Assign):
        if not _at(assignment, diagnostic) or len(assignment.targets) != 1:
            continue
        if not isinstance(assignment.value, ast.Constant) or not isinstance(
            assignment.value.value, (str, bytes, int, float, complex, bool, type(None))
        ):
            continue
        owner = source.context.parents.get(assignment)
        if (
            not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef))
            or (span := source.full_statement(assignment)) is None
        ):
            continue
        only_markers = all(_literal_marker(statement, source.context) for statement in owner.body)
        return (
            [source.replace(assignment, "pass")]
            if only_markers and owner.body[0] is assignment
            else [TextEdit(*span, "")]
        )
    return []


def _literal_marker(statement: ast.stmt, context: PythonFileContext) -> bool:
    match statement:
        case ast.Assign(targets=[ast.Name(id="_")], value=ast.Constant() as value):
            return _exact_primitive(value, context)
        case _:
            return False


def _replace_call_keywords(source: _Source, call: ast.Call, keywords: list[ast.keyword]) -> list[TextEdit]:
    if source.comments_between(call.lineno, _last_line(call)):
        return []
    replacement = ast.Call(func=call.func, args=call.args, keywords=keywords)
    return [source.replace(call, ast.unparse(replacement))]


def _xfail_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    for call in source.context.nodes(ast.Call):
        if (
            not _at(call, diagnostic)
            or any(keyword.arg in {None, "strict"} for keyword in call.keywords)
            or _type_parameter_reference(call.func, source.context)
        ):
            continue
        owner = source.context.parents.get(call)
        if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)) or call not in owner.decorator_list:
            continue
        if any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "parametrize"
            for decorator in owner.decorator_list
        ):
            continue
        return _replace_call_keywords(
            source, call, [*call.keywords, ast.keyword(arg="strict", value=ast.Constant(value=True))]
        )
    return []


def _description_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    if diagnostic.severity is not Severity.ERROR:
        return []
    for description in source.context.nodes(ast.Constant):
        if not _at(description, diagnostic):
            continue
        keyword = source.context.parents.get(description)
        call = source.context.parents.get(keyword) if keyword is not None else None
        if isinstance(keyword, ast.keyword) and keyword.arg == "description" and isinstance(call, ast.Call):
            if _type_parameter_reference(call.func, source.context):
                continue
            return _replace_call_keywords(source, call, [item for item in call.keywords if item is not keyword])
    return []


def _self_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    if diagnostic.severity is not Severity.ERROR:
        return []
    aliases = [
        name
        for name, target in source.context.imports.bindings.items()
        if target.module in {"typing", "typing_extensions"} and target.symbol == "Self"
    ]
    if not aliases:
        return []
    for method in source.context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
        annotation = method.returns
        if annotation is None or not _at(annotation, diagnostic):
            continue
        if source.comments_between(annotation.lineno, _last_line(annotation)):
            continue
        shadowed = _type_parameter_names(method, source.context)
        alias = next((name for name in aliases if name not in shadowed), None)
        if alias is not None:
            return [source.replace(annotation, alias)]
    return []


def _jwt_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    provenance = ResourceProvenance(source.context, require_static_namespace=True)
    for call in source.context.nodes(ast.Call):
        if not _jwt_call_owned(call, source, diagnostic):
            continue
        qualified = source.context.imports.resolved_qualified_name(call.func)
        if qualified is None or not provenance.imported(call.func, qualified):
            continue
        option = next((keyword for keyword in call.keywords if keyword.arg == "options"), None)
        if option is None:
            added = ast.keyword(
                arg="options",
                value=ast.Dict(
                    keys=[ast.Constant(value="require")],
                    values=[ast.List(elts=[ast.Constant(value="exp")], ctx=ast.Load())],
                ),
            )
            return _replace_call_keywords(source, call, [*call.keywords, added])
        updated = _jwt_options(option.value)
        if updated is None or source.comments_between(option.value.lineno, _last_line(option.value)):
            continue
        return [source.replace(option.value, ast.unparse(updated))]
    return []


def _jwt_call_owned(call: ast.Call, source: _Source, diagnostic: Diagnostic) -> bool:
    return (
        _at(call, diagnostic)
        and len(call.args) <= _JWT_POSITIONAL_PREFIX_ARGUMENTS
        and not any(isinstance(arg, ast.Starred) for arg in call.args)
        and not _type_parameter_reference(call.func, source.context)
    )


def _jwt_options(options: ast.expr) -> ast.Dict | None:
    if not isinstance(options, ast.Dict):
        return None
    names: list[str] = []
    for key in options.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        names.append(key.value)
    if len(names) != len(set(names)):
        return None
    required_index = next((index for index, name in enumerate(names) if name == "require"), None)
    if required_index is None:
        return ast.Dict(
            keys=[*options.keys, ast.Constant(value="require")],
            values=[*options.values, ast.List(elts=[ast.Constant(value="exp")], ctx=ast.Load())],
        )
    sequence = _jwt_required_sequence(options.values[required_index])
    if sequence is None:
        return None
    values = list(options.values)
    values[required_index] = sequence
    return ast.Dict(keys=options.keys, values=values)


def _jwt_required_sequence(required: ast.expr) -> ast.expr | None:
    if not isinstance(required, (ast.List, ast.Tuple, ast.Set)) or not all(
        isinstance(item, ast.Constant) and isinstance(item.value, str) for item in required.elts
    ):
        return None
    elements = [*required.elts, ast.Constant(value="exp")]
    match required:
        case ast.List():
            return ast.List(elts=elements, ctx=ast.Load())
        case ast.Tuple():
            return ast.Tuple(elts=elements, ctx=ast.Load())
        case _:
            pass
    return ast.Set(elts=elements)


def _loguru_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    provenance = ResourceProvenance(source.context, require_static_namespace=True)
    for call in source.context.nodes(ast.Call):
        if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
            continue
        exc_info = _loguru_exception_keyword(call, diagnostic)
        if exc_info is None or _type_parameter_reference(call.func, source.context):
            continue
        if not provenance.imported(call.func.value, "loguru.logger") or not _literal_call_values(call):
            continue
        if source.comments_between(call.lineno, _last_line(call)):
            continue
        receiver = ast.Call(
            func=ast.Attribute(value=call.func.value, attr="opt", ctx=ast.Load()),
            args=[],
            keywords=[ast.keyword(arg="exception", value=ast.Constant(value=True))],
        )
        replacement = ast.Call(
            func=ast.Attribute(value=receiver, attr=call.func.attr, ctx=ast.Load()),
            args=call.args,
            keywords=[keyword for keyword in call.keywords if keyword is not exc_info],
        )
        return [source.replace(call, ast.unparse(replacement))]
    return []


def _loguru_exception_keyword(call: ast.Call, diagnostic: Diagnostic) -> ast.keyword | None:
    return next((keyword for keyword in call.keywords if keyword.arg == "exc_info" and _at(keyword, diagnostic)), None)


def _literal_call_values(call: ast.Call) -> bool:
    return all(isinstance(arg, ast.Constant) for arg in call.args) and all(
        keyword.arg is not None and isinstance(keyword.value, ast.Constant) for keyword in call.keywords
    )


def _printf_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    provenance = ResourceProvenance(source.context, require_static_namespace=True)
    for call in source.context.nodes(ast.Call):
        if (
            not _at(call, diagnostic)
            or not isinstance(call.func, ast.Attribute)
            or not isinstance(call.func.value, ast.Name)
            or _type_parameter_reference(call.func, source.context)
        ):
            continue
        if not provenance.imported(call.func.value, "loguru.logger") or not provenance.builtin_namespace_untouched:
            continue
        index = int(call.func.attr == "log")
        message = call.args[index]
        if not isinstance(message, ast.Constant) or not isinstance(message.value, str):
            continue
        if source.comments_between(message.lineno, _last_line(message)):
            continue
        template = _printf_template(message.value, call.args[index + 1 :], source.context)
        if template is not None:
            return [source.replace(message, repr(template))]
    return []


def _printf_template(template: str, values: list[ast.expr], context: PythonFileContext) -> str | None:
    if "{" in template or "}" in template or not all(_exact_primitive(value, context) for value in values):
        return None
    pieces: list[str] = []
    position = 0
    index = 0
    for token in re.finditer(r"%(?:%|[sradi])", template):
        pieces.append(template[position : token.start()])
        conversion = token[0]
        if conversion == "%%":
            pieces.append("%")
        elif index < len(values):
            if conversion in {"%d", "%i"}:
                value = values[index]
                if not isinstance(value, ast.Constant) or not isinstance(value.value, int):
                    return None
                pieces.append("{:d}")
            elif conversion in {"%s", "%r", "%a"}:
                pieces.append("{!" + conversion[1] + "}")
            else:
                return None
            index += 1
        else:
            return None
        position = token.end()
    pieces.append(template[position:])
    rendered = "".join(pieces)
    if index != len(values) or "%" in re.sub(r"%%|%[sradi]", "", template):
        return None
    return rendered


def _collection_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    if diagnostic.severity is not Severity.ERROR or source.context.dynamic_namespace:
        return []
    for init, loop in _statement_pairs(source.context):
        if (
            not isinstance(loop, ast.For)
            or not _at(loop, diagnostic)
            or not isinstance(init, (ast.Assign, ast.AnnAssign))
        ):
            continue
        owner = _collection_owner(init, source.context)
        if owner is None or not _literal_collection_scope(owner, init, loop, source):
            continue
        replacement = collection_rule.autofix_comprehension_replacement(source.context, owner, init, loop)
        span = source.full_statement(loop)
        if (
            replacement is None
            or span is None
            or init.value is None
            or _type_parameter_reference(init.value, source.context)
        ):
            continue
        return [source.replace(init.value, replacement), TextEdit(*span, "")]
    return []


def _collection_owner(
    init: ast.Assign | ast.AnnAssign, context: PythonFileContext
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    owner = context.parents.get(init)
    while owner is not None:
        if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return owner
        owner = context.parents.get(owner)
    return None


def _literal_collection_scope(
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
    init: ast.Assign | ast.AnnAssign,
    loop: ast.For,
    source: _Source,
) -> bool:
    if not isinstance(owner, ast.FunctionDef) or source.context.parents.get(owner) is not source.context.tree:
        return False
    if owner.decorator_list or owner.type_params or not _empty_collection_parameters(owner.args):
        return False
    match owner.body, init:
        case [first, second, ast.Return(value=ast.Name(id=returned))], (
            ast.Assign(targets=[ast.Name(id=name)], value=value) | ast.AnnAssign(target=ast.Name(id=name), value=value)
        ):
            if first is not init or second is not loop or returned != name or value is None:
                return False
            if not isinstance(loop.iter, (ast.List, ast.Tuple)) or len(loop.body) != 1 or loop.orelse:
                return False
            names = _literal_iteration_names(loop.target, loop.iter.elts)
            if names is None:
                return False
            return _literal_collection_mutation(name, value, loop.body[0], names, source)
        case _:
            return False


def _empty_collection_parameters(arguments: ast.arguments) -> bool:
    return not (
        arguments.posonlyargs
        or arguments.args
        or arguments.kwonlyargs
        or arguments.vararg is not None
        or arguments.kwarg is not None
    )


def _literal_iteration_names(target: ast.expr, values: list[ast.expr]) -> frozenset[str] | None:
    if isinstance(target, ast.Name):
        return frozenset({target.id}) if all(isinstance(value, ast.Constant) for value in values) else None
    if not isinstance(target, (ast.Tuple, ast.List)):
        return None
    sequences: list[ast.Tuple | ast.List] = []
    for value in values:
        if not isinstance(value, (ast.Tuple, ast.List)) or len(value.elts) != len(target.elts):
            return None
        sequences.append(value)
    names: set[str] = set()
    for index, item in enumerate(target.elts):
        bound = _literal_iteration_names(item, [sequence.elts[index] for sequence in sequences])
        if bound is None:
            return None
        names.update(bound)
    return frozenset(names)


def _literal_collection_mutation(
    name: str,
    initialized: ast.expr,
    statement: ast.stmt,
    names: frozenset[str],
    source: _Source,
) -> bool:
    match initialized, statement:
        case ast.List(elts=[]), ast.Expr(
            value=ast.Call(func=ast.Attribute(value=ast.Name(id=receiver), attr="append"), args=[element], keywords=[])
        ):
            return receiver == name and _literal_collection_element(element, names)
        case ast.Call(func=ast.Name(id="set"), args=[], keywords=[]), ast.Expr(
            value=ast.Call(func=ast.Attribute(value=ast.Name(id=receiver), attr="add"), args=[element], keywords=[])
        ):
            return (
                receiver == name
                and _literal_collection_element(element, names)
                and source.context.imports.builtin_is_unshadowed("set")
                and source.parameters.provenance.builtin_namespace_untouched
            )
        case ast.Dict(keys=[], values=[]), ast.Assign(
            targets=[ast.Subscript(value=ast.Name(id=receiver), slice=key)], value=element
        ):
            return (
                receiver == name
                and _literal_collection_element(key, names)
                and _literal_collection_element(element, names)
            )
        case _:
            return False


def _literal_collection_element(element: ast.expr, names: frozenset[str]) -> bool:
    if isinstance(element, ast.Tuple):
        return all(_literal_collection_element(item, names) for item in element.elts)
    return isinstance(element, ast.Constant) or (isinstance(element, ast.Name) and element.id in names)


def _inert_definition(node: ast.FunctionDef | ast.AsyncFunctionDef, *, postponed_annotations: bool) -> bool:
    args = node.args
    if node.decorator_list or node.type_params:
        return False
    return not (
        any(not isinstance(value, ast.Constant) for value in args.defaults)
        or any(value is not None and not isinstance(value, ast.Constant) for value in args.kw_defaults)
        or (
            not postponed_annotations
            and (
                not _inert_annotation(node.returns)
                or any(
                    not _inert_annotation(argument.annotation)
                    for argument in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
                    if argument is not None
                )
            )
        )
    )


def _inert_annotation(annotation: ast.expr | None) -> bool:
    return annotation is None or (
        isinstance(annotation, ast.Constant) and (annotation.value is None or isinstance(annotation.value, str))
    )


def _stepdown_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    tree = source.context.tree
    if tree is None:
        return []
    postponed_annotations = _postponed_module_annotations(tree) or bool(source.context.nodes(ast.TemplateStr))
    for index, helper in enumerate(tree.body):
        if not isinstance(helper, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _at(helper, diagnostic):
            continue
        if not _inert_definition(helper, postponed_annotations=postponed_annotations):
            continue
        caller = _inert_stepdown_caller(helper, tree.body[index + 1 :], postponed_annotations=postponed_annotations)
        if caller is None or _stepdown_comments(helper, caller, source):
            continue
        span = source.full_statement(helper)
        if span is None:
            continue
        position = source.starts[_last_line(caller)]
        newline = "\r\n" if "\r\n" in source.text else "\n"
        return [TextEdit(*span, ""), TextEdit(position, position, newline + source.text[span[0] : span[1]] + newline)]
    return []


def _postponed_module_annotations(tree: ast.Module) -> bool:
    for index, statement in enumerate(tree.body):
        if (
            index == 0
            and isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        if not isinstance(statement, ast.ImportFrom) or statement.module != "__future__" or statement.level != 0:
            return False
        if any(alias.name == "annotations" for alias in statement.names):
            return True
    return False


def _inert_stepdown_caller(
    helper: ast.FunctionDef | ast.AsyncFunctionDef, later: list[ast.stmt], *, postponed_annotations: bool
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    callers = [
        node
        for node in later
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _calls_function(node, helper.name)
    ]
    if len(callers) != 1 or not _inert_definition(callers[0], postponed_annotations=postponed_annotations):
        return None
    caller = callers[0]
    for node in later:
        if node.lineno <= caller.lineno and (
            not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            or not _inert_definition(node, postponed_annotations=postponed_annotations)
        ):
            return None
    return caller


def _calls_function(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == name
        for call in ast.walk(node)
    )


def _stepdown_comments(
    helper: ast.FunctionDef | ast.AsyncFunctionDef, caller: ast.FunctionDef | ast.AsyncFunctionDef, source: _Source
) -> bool:
    start_line = helper.lineno
    while start_line > 1 and _blank_or_comment(source.lines[start_line - 2]):
        start_line -= 1
    end_line = _last_line(caller)
    while end_line < len(source.lines) and _blank_or_comment(source.lines[end_line]):
        end_line += 1
    return source.comments_between(start_line, end_line)


def _blank_or_comment(line: str) -> bool:
    return not line.strip() or line.lstrip().startswith("#")


def _docstring_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return source.docstrings.fixes(diagnostic)


def _parameter_fix(source: _Source, diagnostic: Diagnostic) -> list[TextEdit]:
    return source.parameters.fixes(diagnostic)


_BUILDERS: Final[dict[str, Callable[[_Source, Diagnostic], list[TextEdit]]]] = {
    "SARJ021": _sql_projection_fix,
    "SARJ543": _sql_alias_fix,
    "SARJ002": _literal_loop_fix,
    "SARJ006": _enum_fix,
    "SARJ011": _security_fix,
    **dict.fromkeys(_COMMENT_CODES, _comment_fix),
    **dict.fromkeys(_WALRUS_CODES, _walrus_fix),
    **dict.fromkeys({"SARJ050", "SARJ086", "SARJ087", "SARJ092", "SARJ099", "SARJ420"}, _docstring_fix),
    "SARJ023": _stepdown_fix,
    "SARJ024": _repeated_fix,
    "SARJ032": _exhaustiveness_fix,
    "SARJ046": _xfail_fix,
    **dict.fromkeys({"SARJ049", "SARJ051", "SARJ054", "SARJ434", "SARJ551"}, _commentary_fix),
    "SARJ067": _mock_fix,
    "SARJ068": _fstring_fix,
    "SARJ070": _pattern_fix,
    "SARJ077": _stream_fix,
    "SARJ078": _self_fix,
    "SARJ080": _dispatch_fix,
    "SARJ098": _export_fix,
    "SARJ423": _description_fix,
    "SARJ430": _collection_fix,
    "SARJ431": _disjoint_fix,
    "SARJ439": _dispatch_fix,
    "SARJ442": _deletion_fix,
    "SARJ443": _parameter_fix,
    "SARJ444": _complexity_fix,
    "SARJ452": _marker_fix,
    "SARJ475": _parameter_fix,
    "SARJ034": _parameter_fix,
    "SARJ076": _comprehension_fix,
    "SARJ460": _regex_fix,
    "SARJ447": _annotation_fix,
    "SARJ456": _testing_fix,
    "SARJ526": _declared_testing_fix,
    "SARJ528": _declared_contract_fix,
    "SARJ531": _alias_fix,
    "SARJ477": _parameter_fix,
    "SARJ488": _exception_fix,
    "SARJ504": _jwt_fix,
    "SARJ508": _loguru_fix,
    "SARJ509": _printf_fix,
}


@dataclass(frozen=True, slots=True)
class _FixCandidate:
    code: str
    edits: tuple[TextEdit, ...]


@dataclass(frozen=True, slots=True)
class _FixPass:
    edits: tuple[TextEdit, ...]
    codes: tuple[str, ...]


def fix_source(path: Path, source: str, *, rule_ids: Sequence[str] | None = None) -> str:
    from sarj_python_lint.__main__ import check_context  # ruff: ignore[import-outside-top-level] -- the CLI imports this entry point lazily.

    selected = list(REGISTRY) if rule_ids is None else list(rule_ids)
    rules = [REGISTRY[rule_id]() for rule_id in selected if REGISTRY[rule_id].code in _BUILDERS]
    if any(character in source for character in "\v\f\x1c\x1d\x1e\x85\u2028\u2029") or "\r" in source.replace(
        "\r\n", ""
    ):
        # Only the closed alias builder owns aligned physical-line buffers and token coordinates here.
        rules = [rule for rule in rules if rule.code == "SARJ531"]
    seen: set[bytes] = set()
    applied_codes: set[str] = set()
    passes = 0
    current = source
    while (fingerprint := sha256(current.encode("utf-8")).digest()) not in seen:
        seen.add(fingerprint)
        context = PythonFileContext(path, current)
        diagnostics = check_context(rules, context)
        candidates = _candidate_edits(context, diagnostics)
        if not candidates:
            return current
        # Batch independent candidates; overlapping candidates get fresh offsets on the next pass.
        selected_pass = _coherent_edits(candidates)
        updated = _apply_validated_edits(path, current, selected_pass.edits)
        if updated == current:
            return current
        if passes == _MAX_FIX_PASSES:
            raise _convergence_error(path, reason="pass budget exhausted", passes=passes, codes=applied_codes)
        passes += 1
        applied_codes.update(selected_pass.codes)
        current = updated
    raise _convergence_error(path, reason="source cycle", passes=passes, codes=applied_codes)


def _apply_validated_edits(path: Path, current: str, edits: Sequence[TextEdit]) -> str:
    updated = apply_edits(current, edits)
    try:
        compile(  # sarj-noqa: SARJ557 -- Compile proposed fixes to reject invalid scopes without executing them.
            updated, str(path), "exec", dont_inherit=True
        )
    except SyntaxError:
        try:
            compile(  # sarj-noqa: SARJ557 -- Distinguish pre-existing invalid scope from a broken generated fix without executing input.
                current, str(path), "exec", dont_inherit=True
            )
        except SyntaxError:
            return current
        raise
    return updated


def _convergence_error(
    path: Path, *, reason: Literal["pass budget exhausted", "source cycle"], passes: int, codes: set[str]
) -> ValueError:
    participants = ", ".join(sorted(codes)) or "none"
    msg = f"Python autofixes did not converge: {path} ({reason}; passes={passes}; rules={participants})"
    return ValueError(msg)


def _candidate_edits(context: PythonFileContext, diagnostics: Sequence[Diagnostic]) -> list[_FixCandidate]:
    if not diagnostics:
        return []
    view = _Source(context, diagnostics)
    return [
        _FixCandidate(diagnostic.code, tuple(edits))
        for diagnostic in diagnostics
        if (builder := _BUILDERS.get(diagnostic.code)) is not None
        if (edits := builder(view, diagnostic))
    ]


def _coherent_edits(candidates: list[_FixCandidate]) -> _FixPass:
    accepted: list[TextEdit] = []
    codes: list[str] = []
    known: set[TextEdit] = set()
    for candidate in candidates:
        additions = sorted(set(candidate.edits) - known)
        if any(map(_overlap, additions, additions[1:], strict=False)):
            continue
        for edit in additions:
            position = bisect_left(accepted, edit)
            if (position > 0 and _overlap(accepted[position - 1], edit)) or (
                position < len(accepted) and _overlap(edit, accepted[position])
            ):
                break
        else:
            for edit in additions:
                insort(accepted, edit)
            known.update(additions)
            if additions:
                codes.append(candidate.code)
    return _FixPass(tuple(accepted), tuple(dict.fromkeys(codes)))


def _overlap(first: TextEdit, second: TextEdit) -> bool:
    return second.start < first.end or second.start == first.start


def fix_paths(paths: Sequence[Path], *, rule_ids: Sequence[str] | None = None) -> int:
    from sarj_python_lint.__main__ import expand_paths  # ruff: ignore[import-outside-top-level] -- shares native CLI file selection.
    from sarj_python_lint._source import python_source_encoding  # ruff: ignore[import-outside-top-level] -- source-only transformations do not require file decoding.

    changed = 0
    for path in dict.fromkeys(expand_paths(list(paths))):
        if fix_file(
            path,
            lambda source, selected_path=path: fix_source(selected_path, source, rule_ids=rule_ids),
            source_encoding=python_source_encoding,
        ):
            changed += 1
    return changed
