"""Shared extraction and sentence counting for SARJ090-092."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import io
import re
import tokenize
from typing import TYPE_CHECKING, Final

from sarj_python_lint.rule_base import ColumnEncoding, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._docstrings import PROMPT_DECORATOR_MARKERS, decorator_markers, sections
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_DIRECTIVE_RE: Final = re.compile(
    r"^(?:!|noqa|sarj-noqa|type:|pragma|pyright|mypy|fmt:|isort|ruff|pylint|flake8|"
    r"nosec|nosemgrep|todo|fixme|hack\b|xxx|coding[:=])",
    re.IGNORECASE,
)
_LICENSE_RE: Final = re.compile(r"\b(?:copyright|spdx-license-identifier|licensed under)\b", re.IGNORECASE)
_BOUNDARY_RE: Final = re.compile(r"(?<=[.!?])[\"'`)\]]*\s+(?=[A-Z0-9`])")
_BULLET_RE: Final = re.compile(r"^\s*(?:[-*+] |\d+[.)] )")
_TYPED_SECTIONS: Final = frozenset(
    {
        "Args",
        "Arguments",
        "Parameters",
        "Params",
        "Keyword Args",
        "Keyword Arguments",
        "Returns",
        "Return",
        "Yields",
        "Yield",
    }
)
_SCHEMA_BASES: Final = frozenset({"BaseModel", "BaseSettings", "RootModel", "TypedDict", "Enum", "IntEnum", "StrEnum"})
_SCHEMA_DECORATORS: Final = frozenset({"pydantic", "strawberry", "graphene", "msgspec"})


@dataclass(frozen=True, slots=True)
class ProseGroup:
    line: int
    col: int
    text: str
    kind: str
    typed_sections: frozenset[str] = frozenset()

    @property
    def column_encoding(self) -> ColumnEncoding:
        """Return the coordinate convention of the parser that found this prose."""
        return ColumnEncoding.CODEPOINTS if self.kind == "comment" else ColumnEncoding.UTF8_BYTES


_last_groups: tuple[str, str, tuple[ProseGroup, ...]] | None = None


def sentence_units(text: str) -> int:
    """Count prose sentences and unpunctuated list items deterministically."""
    text = _without_examples_metadata(text)
    cleaned = re.sub(r"https?://\S+", "URL", text)
    cleaned = re.sub(r"`[^`\n]+`", "CODE", cleaned)
    cleaned = re.sub(r"\b\d+\.\d+\b", "NUMBER", cleaned)
    cleaned = re.sub(r"\b(?:e\.g\.|i\.e\.|vs\.|etc\.)", "ABBREVIATION", cleaned, flags=re.IGNORECASE)
    units = 0
    prose: list[str] = []
    for raw in cleaned.splitlines():
        line = raw.strip().lstrip("*").strip()
        if not line or re.fullmatch(r"[A-Za-z][A-Za-z ]+:", line):
            continue
        if _BULLET_RE.match(line):
            units += 1
        else:
            prose.append(line)
    paragraph = " ".join(prose).strip()
    if paragraph:
        units += len(_BOUNDARY_RE.split(paragraph))
    return units


def _without_examples_metadata(text: str) -> str:
    """Remove standardized rule-example links from the prose budget."""
    kept: list[str] = []
    expect_url = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.casefold() == "examples:":
            expect_url = True
            continue
        if re.fullmatch(r"examples:\s+https?://\S+", line, re.IGNORECASE):
            expect_url = False
            continue
        if expect_url and re.fullmatch(r"https?://\S+", line):
            expect_url = False
            continue
        expect_url = False
        kept.append(raw)
    return "\n".join(kept)


def groups(path: Path, source: str) -> list[ProseGroup]:
    """Extract docstrings and contiguous own-line comment runs from one file."""
    global _last_groups  # ruff: ignore[global-statement] -- rules run sequentially per file.
    path_key = str(path)
    if _last_groups is not None and _last_groups[0] == path_key and _last_groups[1] is source:
        return list(_last_groups[2])
    extracted = _extract_groups(path, source)
    _last_groups = (path_key, source, tuple(extracted))
    return extracted


def _extract_groups(path: Path, source: str) -> list[ProseGroup]:
    """Perform the shared parse and tokenization once for adjacent prose rules."""
    if is_generated(path, source):
        return []
    tree = parse_or_none(path, source)
    if tree is None:
        return []
    out = _docstring_groups(tree)
    lines = source.splitlines()
    try:
        comments = [
            token for token in tokenize.generate_tokens(io.StringIO(source).readline) if token.type == tokenize.COMMENT
        ]
    except tokenize.TokenError, IndentationError, SyntaxError:
        return out
    run: list[tokenize.TokenInfo] = []
    for comment in comments:
        body = comment.string.removeprefix("#").strip()
        own_line = not lines[comment.start[0] - 1][: comment.start[1]].strip()
        if not own_line or _DIRECTIVE_RE.match(body) or _LICENSE_RE.search(body):
            if run:
                out.append(_comment_run(run))
                run = []
            continue
        if run and (comment.start[0] != run[-1].end[0] + 1 or comment.start[1] != run[-1].start[1]):
            out.append(_comment_run(run))
            run = []
        run.append(comment)
    if run:
        out.append(_comment_run(run))
    return out


def _comment_run(run: list[tokenize.TokenInfo]) -> ProseGroup:
    return ProseGroup(
        line=run[0].start[0],
        col=run[0].start[1] + 1,
        text="\n".join(token.string.removeprefix("#").strip() for token in run),
        kind="comment",
    )


def _docstring_groups(tree: ast.Module) -> list[ProseGroup]:
    out: list[ProseGroup] = []
    for node in nodes(tree, ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef):
        if not node.body:
            continue
        first = node.body[0]
        if not (
            isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)
        ):
            continue
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and (
            decorator_markers(node) & PROMPT_DECORATOR_MARKERS
        ):
            continue
        if isinstance(node, ast.ClassDef) and _is_schema_class(node):
            continue
        doc = first.value.value
        found = frozenset(
            name
            for name in sections(doc)
            if name in _TYPED_SECTIONS
            and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _fully_typed(node)
        )
        out.append(ProseGroup(first.lineno, first.col_offset + 1, doc, "docstring", found))
    return out


def _is_schema_class(node: ast.ClassDef) -> bool:
    bases = {
        target.attr if isinstance(target, ast.Attribute) else target.id
        for base in node.bases
        if isinstance((target := base.value if isinstance(base, ast.Subscript) else base), (ast.Attribute, ast.Name))
    }
    return bool(bases & _SCHEMA_BASES or decorator_markers(node) & _SCHEMA_DECORATORS)


def _fully_typed(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    args = node.args
    parameters = (*args.posonlyargs, *args.args, *args.kwonlyargs)
    return (
        node.returns is not None
        and all(arg.arg in {"self", "cls"} or arg.annotation is not None for arg in parameters)
        and (args.vararg is None or args.vararg.annotation is not None)
        and (args.kwarg is None or args.kwarg.annotation is not None)
    )
