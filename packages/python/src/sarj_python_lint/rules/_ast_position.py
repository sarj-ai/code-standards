from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import ast


@dataclass(frozen=True, order=True, slots=True)
class AstPosition:
    line: int
    column: int


def ast_position(node: ast.AST, *, missing: int) -> AstPosition:
    return AstPosition(
        line=getattr(node, "lineno", missing),
        column=getattr(node, "col_offset", missing),
    )
