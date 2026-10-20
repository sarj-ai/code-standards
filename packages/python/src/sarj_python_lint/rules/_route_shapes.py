from __future__ import annotations

import ast
from dataclasses import dataclass
from http import HTTPStatus
import re
from typing import TYPE_CHECKING, Final

from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_STATUS_OWNERS: Final = frozenset({"HTTPStatus", "status"})
_STARLETTE_STATUS: Final = re.compile(r"HTTP_(?P<code>[1-5][0-9]{2})_[A-Z_]+")
_SEGMENT_WORD: Final = re.compile(r"[-_.]")


@dataclass(frozen=True, slots=True)
class RouteDecorator:
    decorator: ast.Call
    methods: frozenset[str]
    path: str | None
    prefix: ast.expr | None


def route_decorators(context: PythonFileContext) -> Iterator[RouteDecorator]:
    if context.tree is None or context.generated or is_test_path(context.path):
        return
    if "APIRouter" not in context.symbol_source and "FastAPI" not in context.symbol_source:
        return
    index = context.fastapi
    for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
        grouped: dict[int, list[str]] = {}
        first: dict[int, RouteDecorator] = {}
        for route in index.routes(function):
            if route.has_unpack:
                continue
            grouped.setdefault(id(route.decorator), []).append(route.method)
            first.setdefault(
                id(route.decorator), RouteDecorator(route.decorator, frozenset(), route.path, route.inherited_prefix)
            )
        for key, methods in grouped.items():
            shape = first[key]
            yield RouteDecorator(shape.decorator, frozenset(methods), shape.path, shape.prefix)


def final_segment_word(path: str) -> str | None:
    segment = path.rstrip("/").rsplit("/", 1)[-1]
    if not segment or segment.startswith("{"):
        return None
    return _SEGMENT_WORD.split(segment.lower(), maxsplit=1)[0]


def final_segment_words(path: str) -> list[str]:
    segment = path.rstrip("/").rsplit("/", 1)[-1]
    if not segment or segment.startswith("{"):
        return []
    return [word for word in _SEGMENT_WORD.split(segment.lower()) if word]


def http_status(node: ast.expr | None) -> int | None:
    match node:
        case ast.Constant(value=int() as value) if not isinstance(value, bool):
            return value
        case ast.Attribute(value=ast.Name(id=owner), attr=name) if owner in _STATUS_OWNERS:
            if (match := _STARLETTE_STATUS.fullmatch(name)) is not None:
                return int(match.group("code"))
            member = HTTPStatus.__members__.get(name)
            return None if member is None else member.value
        case _:
            return None
