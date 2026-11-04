from __future__ import annotations

import ast
from dataclasses import dataclass
from io import StringIO
import re
import tokenize
from typing import TYPE_CHECKING, Final

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules.no_psycopg_execution_outside_injected_owner import psycopg_execution_calls


if TYPE_CHECKING:
    from pathlib import Path


_LITERAL_HEADER: Final = re.compile(r'''(?i:[ru]?)(?:"""|\x27\x27\x27|"|\x27)''')
_MAX_BINDING_DEPTH: Final = 16


@dataclass(frozen=True, slots=True)
class SQLSourcePoint:
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class SQLLiteral:
    text: str
    line: int
    column: int

    def source_point(self, *, line: int, column: int) -> SQLSourcePoint:
        lines = self.text.split("\n")
        if line < 1 or line > len(lines) or column < 1 or column > len(lines[line - 1]) + 1:
            msg = "SQL diagnostic is outside the extracted literal"
            raise ValueError(msg)
        return SQLSourcePoint(self.line + line - 1, column + (self.column - 1 if line == 1 else 0))


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
    for call in psycopg_execution_calls(context, include_injected=True, include_probes=True):
        argument = (
            call.args[0]
            if call.args
            else next((keyword.value for keyword in call.keywords if keyword.arg == "query"), None)
        )
        if argument is None:
            gaps.append(SQLExtractionGap(call.lineno, _source_column(call, source), "query argument is not explicit"))
            continue
        origin = _literal_origin(argument, context)
        literal = _mapped_literal(origin, source) if origin is not None else None
        if literal is None:
            gaps.append(
                SQLExtractionGap(argument.lineno, _source_column(argument, source), "dynamic or unmappable SQL")
            )
        else:
            literals[literal] = None
    return SQLExtraction(tuple(literals), tuple(gaps))


def _literal_origin(expression: ast.expr, context: PythonFileContext) -> ast.Constant | None:
    seen: set[int] = set()
    for _ in range(_MAX_BINDING_DEPTH):
        if isinstance(expression, ast.Constant):
            return expression if isinstance(expression.value, str) else None
        if not isinstance(expression, ast.Name) or id(expression) in seen:
            return None
        seen.add(id(expression))
        provenance = context.static_resource_provenance
        if provenance.dynamic_namespace or provenance.wildcard:
            return None
        binding = provenance.runtime_binding(expression.id, expression)
        value = provenance.assignment_value(binding, expression) if isinstance(binding, ast.Name) else None
        if value is None:
            return None
        expression = value
    return None


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
