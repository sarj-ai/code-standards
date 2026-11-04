from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from io import StringIO
from itertools import islice
import re
from string import Formatter
import tokenize
from typing import TYPE_CHECKING, Final

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules.no_psycopg_execution_outside_injected_owner import psycopg_execution_calls


if TYPE_CHECKING:
    from pathlib import Path


_LITERAL_HEADER: Final = re.compile(r'''(?i:[ru]?)(?:"""|\x27\x27\x27|"|\x27)''')
_MAX_BINDING_DEPTH: Final = 16
_MAX_QUERY_CHARS: Final = 1_000_000
_MAX_RENDER_NODES: Final = 4096
_FORMAT_PART: Final = re.compile(r"{{|}}|{([^{}]*)}")


@dataclass(frozen=True, slots=True)
class SQLSourcePoint:
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int
    point: SQLSourcePoint
    linear: bool = True


@dataclass(frozen=True, slots=True)
class SQLLiteral:
    text: str
    line: int
    column: int
    spans: tuple[_Span, ...] = ()

    def source_point(self, *, line: int, column: int) -> SQLSourcePoint:
        lines = self.text.split("\n")
        if line < 1 or line > len(lines) or column < 1 or column > len(lines[line - 1]) + 1:
            msg = "SQL diagnostic is outside the extracted literal"
            raise ValueError(msg)
        offset = sum(len(part) + 1 for part in lines[: line - 1]) + column - 1
        if self.spans:
            span = next((part for part in self.spans if part.start <= offset < part.end), None)
            if span is None:
                if offset != len(self.text):
                    msg = "SQL diagnostic has no source span"
                    raise ValueError(msg)
                span = self.spans[-1]
            if not span.linear:
                return span.point
            return _advance(span.point, self.text[span.start : offset])
        return _advance(SQLSourcePoint(self.line, self.column), self.text[:offset])


@dataclass(frozen=True, slots=True)
class SQLExtractionGap:
    line: int
    column: int
    reason: str


@dataclass(frozen=True, slots=True)
class SQLExtraction:
    literals: tuple[SQLLiteral, ...]
    gaps: tuple[SQLExtractionGap, ...]


def extract_sql_literals(path: Path, source: str) -> SQLExtraction:
    context = PythonFileContext(path, source)
    if context.tree is None:
        msg = "cannot extract SQL from invalid Python source"
        raise ValueError(msg)
    literals: dict[SQLLiteral, None] = {}
    gaps: list[SQLExtractionGap] = []
    renderer: _Renderer | None = None
    for call in psycopg_execution_calls(context, include_injected=True, include_probes=True):
        argument = (
            call.args[0]
            if call.args
            else next((keyword.value for keyword in call.keywords if keyword.arg == "query"), None)
        )
        if argument is None:
            gaps.append(SQLExtractionGap(call.lineno, _source_column(call, source), "query argument is not explicit"))
            continue
        if renderer is None:
            renderer = _Renderer(context)
        rendered = renderer.render(argument)
        literal = rendered.literal if rendered is not None else None
        if literal is None:
            gaps.append(
                SQLExtractionGap(argument.lineno, _source_column(argument, source), "dynamic or unmappable SQL")
            )
        else:
            literals[literal] = None
    return SQLExtraction(tuple(literals), tuple(gaps))


class _Kind(StrEnum):
    TEXT = "text"
    SQL = "sql"
    IDENTIFIER = "identifier"
    COMPOSED = "composed"


@dataclass(frozen=True, slots=True)
class _Rendered:
    literal: SQLLiteral
    kind: _Kind


class _FormatBindings:
    def __init__(self, arguments: tuple[_Rendered | None, ...], keywords: dict[str | None, _Rendered | None]) -> None:
        self.arguments = arguments
        self.keywords = keywords
        self.automatic = 0
        self.numbering: str | None = None

    def resolve(self, key: str) -> _Rendered | None:
        if key and not key.isdecimal():
            return self.keywords.get(key) if key.isidentifier() else None
        mode = "automatic" if not key else "manual"
        if self.numbering is not None and self.numbering != mode:
            return None
        self.numbering = mode
        try:
            index = self.automatic if not key else int(key)
        except ValueError:
            return None
        if not key:
            self.automatic += 1
        return self.arguments[index] if index < len(self.arguments) else None


class _Renderer:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = context.static_resource_provenance
        self.remaining = _MAX_RENDER_NODES

    @cached_property
    def written_attributes(self) -> frozenset[str]:
        return frozenset(
            node.attr for node in self.context.nodes(ast.Attribute) if isinstance(node.ctx, ast.Store | ast.Del)
        )

    @cached_property
    def dynamic_attributes(self) -> bool:
        return any(
            (isinstance(node.func, ast.Name) and node.func.id in {"setattr", "delattr"})
            or (isinstance(node.func, ast.Attribute) and node.func.attr in {"__setattr__", "__delattr__"})
            for node in self.context.nodes(ast.Call)
        )

    def render(self, expression: ast.expr, seen: frozenset[int] = frozenset()) -> _Rendered | None:
        if not seen:
            self.remaining = _MAX_RENDER_NODES
        self.remaining -= 1
        if self.remaining < 0 or id(expression) in seen or len(seen) >= _MAX_BINDING_DEPTH:
            return None
        seen |= {id(expression)}
        match expression:
            case ast.Constant():
                literal = _mapped_literal(expression, self.context.source)
                return (
                    _Rendered(literal, _Kind.TEXT)
                    if literal is not None and len(literal.text) <= _MAX_QUERY_CHARS
                    else None
                )
            case ast.Name() | ast.Attribute():
                value = self._bound_value(expression)
                return self.render(value, seen) if value is not None else None
            case ast.BinOp(op=ast.Add()):
                return self._addition(expression, seen)
            case ast.Call():
                return self._call(expression, seen)
            case _:
                return None

    def _bound_value(self, expression: ast.Name | ast.Attribute) -> ast.expr | None:
        if self.provenance.dynamic_namespace or self.provenance.wildcard:
            return None
        if isinstance(expression, ast.Attribute):
            return self._class_value(expression)
        if expression.id in self.provenance.mutated:
            return None
        binding = self.provenance.runtime_binding(expression.id, expression)
        if not isinstance(binding, ast.Name):
            return None
        value = self.provenance.assignment_value(binding, expression)
        if not isinstance(value, ast.Constant) and self.provenance.binding_reads(expression.id, binding) != [
            expression
        ]:
            return None
        return value

    def _class_value(self, expression: ast.Attribute) -> ast.expr | None:
        if expression.attr in self.written_attributes or not isinstance(expression.value, ast.Name):
            return None
        if self.provenance.mock_namespace_patching or self.dynamic_attributes:
            return None
        owner = self._class_owner(expression.value)
        if owner is None or owner.keywords or owner.bases:
            return None
        if any(self.provenance.runtime_import_name(node) != "typing.final" for node in owner.decorator_list):
            return None
        bindings = self.provenance.bindings.get(owner, {}).get(expression.attr, ())
        if len(bindings) != 1 or not isinstance(bindings[0], ast.Name):
            return None
        statement = self.context.parents.get(bindings[0])
        if statement is None or self.context.parents.get(statement) is not owner:
            return None
        if not isinstance(statement, ast.Assign | ast.AnnAssign):
            return None
        if isinstance(statement, ast.Assign) and len(statement.targets) != 1:
            return None
        return statement.value if isinstance(statement.value, ast.Constant) else None

    def _class_owner(self, receiver: ast.Name) -> ast.ClassDef | None:
        binding = self.provenance.runtime_binding(receiver.id, receiver)
        match binding:
            case ast.ClassDef():
                if any(
                    not isinstance(parent := self.context.parents.get(read), ast.Attribute)
                    or parent.attr.startswith("__")
                    for read in self.provenance.binding_reads(receiver.id, binding)
                ):
                    return None
                return binding
            case ast.arg():
                arguments_node = self.context.parents.get(binding)
                method = self.context.parents.get(arguments_node) if arguments_node is not None else None
                owner = self.context.parents.get(method) if method is not None else None
                if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef) or not isinstance(
                    owner, ast.ClassDef
                ):
                    return None
                arguments = (*method.args.posonlyargs, *method.args.args)
                if not arguments or arguments[0] is not binding or method.decorator_list:
                    return None
                return owner if self._closed_receiver(owner) else None
            case _:
                return None

    def _closed_receiver(self, owner: ast.ClassDef) -> bool:
        if not owner.decorator_list:
            return False
        if any(name in self.provenance.bindings.get(owner, {}) for name in ("__getattr__", "__getattribute__")):
            return False
        for method in owner.body:
            if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            arguments = (*method.args.posonlyargs, *method.args.args)
            if arguments and any(
                not isinstance(parent := self.context.parents.get(read), ast.Attribute) or parent.attr.startswith("__")
                for read in self.provenance.binding_reads(arguments[0].arg, arguments[0])
            ):
                return False
        return True

    def _addition(self, expression: ast.BinOp, seen: frozenset[int]) -> _Rendered | None:
        left, right = self.render(expression.left, seen), self.render(expression.right, seen)
        if left is None or right is None or (left.kind == _Kind.TEXT) != (right.kind == _Kind.TEXT):
            return None
        literal = _combine((left.literal, right.literal))
        return (
            _Rendered(literal, _Kind.TEXT if left.kind == _Kind.TEXT else _Kind.COMPOSED)
            if literal is not None
            else None
        )

    def _call(self, call: ast.Call, seen: frozenset[int]) -> _Rendered | None:
        native = self.provenance.runtime_import_name(call.func)
        if native == "psycopg.sql.SQL" and len(call.args) == 1 and not call.keywords:
            value = self.render(call.args[0], seen)
            return _Rendered(value.literal, _Kind.SQL) if value is not None and value.kind == _Kind.TEXT else None
        if native == "psycopg.sql.Identifier" and call.args and not call.keywords:
            return self._identifier(call, seen)
        if not isinstance(call.func, ast.Attribute):
            return None
        owner = self.render(call.func.value, seen)
        if owner is None or owner.kind != _Kind.SQL:
            return None
        if call.func.attr == "format":
            return self._format(owner.literal, call, seen)
        if call.func.attr == "join" and len(call.args) == 1 and not call.keywords:
            return self._join(owner.literal, call.args[0], seen)
        return None

    def _identifier(self, call: ast.Call, seen: frozenset[int]) -> _Rendered | None:
        parts: list[SQLLiteral] = []
        for argument in call.args:
            value = self.render(argument, seen)
            if value is None or value.kind != _Kind.TEXT or "\0" in value.literal.text:
                return None
            point = value.literal.source_point(line=1, column=1)
            text = '"' + value.literal.text.replace('"', '""') + '"'
            if parts:
                parts.append(SQLLiteral(".", point.line, point.column, (_Span(0, 1, point, linear=False),)))
            parts.append(SQLLiteral(text, point.line, point.column, (_Span(0, len(text), point, linear=False),)))
        literal = _combine(tuple(parts))
        return _Rendered(literal, _Kind.IDENTIFIER) if literal is not None else None

    def _format(self, template: SQLLiteral, call: ast.Call, seen: frozenset[int]) -> _Rendered | None:
        try:
            fields = tuple(islice(Formatter().parse(template.text), _MAX_RENDER_NODES + 1))
        except ValueError:
            return None
        if len(fields) > _MAX_RENDER_NODES:
            return None
        if any(spec or conversion for _, _, spec, conversion in fields):
            return None
        arguments = tuple(self.render(value, seen) for value in call.args)
        keywords = {item.arg: self.render(item.value, seen) for item in call.keywords}
        if None in keywords or any(
            value is None or value.kind == _Kind.TEXT for value in (*arguments, *keywords.values())
        ):
            return None
        bindings = _FormatBindings(arguments, keywords)
        pieces: list[SQLLiteral] = []
        cursor = 0
        for match in _FORMAT_PART.finditer(template.text):
            pieces.append(_slice(template, cursor, match.start()))
            if match[0] in {"{{", "}}"}:
                pieces.append(_slice(template, match.start(), match.start() + 1))
            else:
                value = bindings.resolve(match[1])
                if value is None:
                    return None
                pieces.append(value.literal)
            cursor = match.end()
        pieces.append(_slice(template, cursor, len(template.text)))
        literal = _combine(tuple(pieces))
        return _Rendered(literal, _Kind.COMPOSED) if literal is not None else None

    def _join(self, separator: SQLLiteral, expression: ast.expr, seen: frozenset[int]) -> _Rendered | None:
        if len(seen) >= _MAX_BINDING_DEPTH:
            return None
        if isinstance(expression, ast.Name):
            value = self._bound_value(expression)
            if value is None or id(expression) in seen:
                return None
            return self._join(separator, value, seen | {id(expression)})
        if not isinstance(expression, ast.List | ast.Tuple) or len(expression.elts) > _MAX_RENDER_NODES:
            return None
        pieces: list[SQLLiteral] = []
        for item in expression.elts:
            value = self.render(item, seen)
            if value is None or value.kind == _Kind.TEXT:
                return None
            if pieces:
                pieces.append(separator)
            pieces.append(value.literal)
        literal = _combine(tuple(pieces))
        return _Rendered(literal, _Kind.COMPOSED) if literal is not None else None


def _advance(point: SQLSourcePoint, text: str) -> SQLSourcePoint:
    lines = text.split("\n")
    return SQLSourcePoint(point.line + len(lines) - 1, len(lines[-1]) + (point.column if len(lines) == 1 else 1))


def _spans(literal: SQLLiteral) -> tuple[_Span, ...]:
    return literal.spans or (_Span(0, len(literal.text), SQLSourcePoint(literal.line, literal.column)),)


def _slice(literal: SQLLiteral, start: int, end: int) -> SQLLiteral:
    spans: list[_Span] = []
    point = SQLSourcePoint(literal.line, literal.column)
    for span in _spans(literal):
        left, right = max(start, span.start), min(end, span.end)
        if left >= right:
            continue
        point = _advance(span.point, literal.text[span.start : left]) if span.linear else span.point
        spans.append(_Span(left - start, right - start, point, span.linear))
    first = spans[0].point if spans else point
    return SQLLiteral(literal.text[start:end], first.line, first.column, tuple(spans))


def _combine(pieces: tuple[SQLLiteral, ...]) -> SQLLiteral | None:
    if not pieces or sum(len(piece.text) for piece in pieces) > _MAX_QUERY_CHARS:
        return None
    spans: list[_Span] = []
    offset = 0
    for piece in pieces:
        spans.extend(
            _Span(part.start + offset, part.end + offset, part.point, part.linear)
            for part in _spans(piece)
            if part.start != part.end
        )
        if len(spans) > _MAX_RENDER_NODES:
            return None
        offset += len(piece.text)
    point = spans[0].point if spans else SQLSourcePoint(pieces[0].line, pieces[0].column)
    return SQLLiteral("".join(piece.text for piece in pieces), point.line, point.column, tuple(spans))


def _mapped_literal(node: ast.Constant, source: str) -> SQLLiteral | None:
    segment = ast.get_source_segment(source, node)
    if segment is None or not isinstance(node.value, str):
        return None
    tokens = [part for part in tokenize.generate_tokens(StringIO(segment).readline) if part.type == tokenize.STRING]
    header = _LITERAL_HEADER.match(segment)
    if len(tokens) != 1 or tokens[0].string != segment or header is None:
        return None
    opening = header[0]
    quote_length = 3 if opening.endswith(('"""', "'''")) else 1
    body = segment[len(opening) : -quote_length]
    if body.replace("\r\n", "\n").replace("\r", "\n") != node.value:
        return None
    return SQLLiteral(node.value, node.lineno, _source_column(node, source) + len(opening))


def _source_column(node: ast.expr, source: str) -> int:
    line = source.splitlines()[node.lineno - 1]
    return len(line.encode("utf-8")[: node.col_offset].decode("utf-8")) + 1
