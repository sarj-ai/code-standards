"""Shared extraction and sentence counting for SARJ091-092."""

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
_STRUCTURED_LINE_RE: Final = re.compile(r"(?:^\s*(?:[-*+] |\d+[.)] ))|(?:^[A-Za-z][A-Za-z ]+:$)|(?:->|=>|\|)")
_MIN_STRUCTURED_PARAGRAPHS: Final = 2
_TECHNICAL_ANCHOR_RE: Final = re.compile(
    r"https?://|`[^`\n]+`|:[a-z][a-z0-9_-]*:`|(['\"])[^'\"\n]+\1|"
    r"\bv?\d+\.\d+(?:\.\d+)?\b|"
    r"\b\d+(?:\.\d+)?\s?(?:ns|us|ms|s|sec|secs|seconds?|mins?|minutes?|hours?|days?|"
    r"bytes?|kib|mib|gib|kb|mb|gb|hz|khz|mhz|px|%)\b|"
    r"\b[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*\b|\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|"
    r"(?:^|\s)(?:[\w.-]+/)+[\w.-]+|\b[\w.-]+\.(?:py|pyi|js|jsx|ts|tsx|json|ya?ml|toml|csv|parquet|md)\b|"
    r"->|=>|==|!=|<=|>=|\|",
    re.MULTILINE,
)
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
    owner_kind: str | None = None
    owner_name: str | None = None
    owner_fully_typed: bool = False
    typed_restatements: tuple[int, ...] = ()

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


def has_list_items(text: str) -> bool:
    """Report whether prose contains a Markdown-style list item."""
    return any(_BULLET_RE.match(line.strip().lstrip("*").strip()) for line in text.splitlines())


def has_documentation_structure(text: str) -> bool:
    """Return whether prose is deliberately structured rather than one narrative wall."""
    paragraphs = [part for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) >= _MIN_STRUCTURED_PARAGRAPHS:
        return True
    for raw in text.splitlines():
        line = raw.strip().lstrip("*").strip()
        if line and _STRUCTURED_LINE_RE.search(line):
            return True
    return False


def has_technical_anchor(text: str) -> bool:
    """Return whether prose carries a concrete code, path, literal, or numeric anchor."""
    return _TECHNICAL_ANCHOR_RE.search(text) is not None


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
        owner_kind = (
            "module" if isinstance(node, ast.Module) else "class" if isinstance(node, ast.ClassDef) else "function"
        )
        owner_name = None if isinstance(node, ast.Module) else node.name
        out.append(
            ProseGroup(
                first.lineno,
                first.col_offset + 1,
                doc,
                "docstring",
                found,
                owner_kind,
                owner_name,
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _fully_typed(node),
                (
                    _typed_restatement_lines(doc, node, first.lineno)
                    if found and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    else ()
                ),
            )
        )
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


_SECTION_HEADING_RE: Final = re.compile(
    r"^\s*(Args|Arguments|Parameters|Params|Keyword Args|Keyword Arguments|Returns|Return|Yields|Yield):\s*$"
)
_ANY_SECTION_HEADING_RE: Final = re.compile(r"^\s*[A-Za-z][A-Za-z ]+:\s*$")
_ARG_TYPE_ENTRY_RE: Final = re.compile(r"^\s*([*]{0,2}[A-Za-z_]\w*)\s*\(([^)]+)\)\s*:")
_NUMPY_ARG_TYPE_ENTRY_RE: Final = re.compile(r"^\s*([*]{0,2}[A-Za-z_]\w*)\s*:\s*([^:]+?)\s*$")
_RETURN_TYPE_ENTRY_RE: Final = re.compile(r"^\s*([^:]+?)\s*:")


def _typed_restatement_lines(
    doc: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    docstring_line: int,
) -> tuple[int, ...]:
    """Locate entries that explicitly repeat types already present in the signature."""
    annotations = {
        arg.arg: _normalise_type(ast.unparse(arg.annotation))
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        if arg.annotation is not None
    }
    if node.args.vararg is not None and node.args.vararg.annotation is not None:
        annotations[f"*{node.args.vararg.arg}"] = _normalise_type(ast.unparse(node.args.vararg.annotation))
    if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
        annotations[f"**{node.args.kwarg.arg}"] = _normalise_type(ast.unparse(node.args.kwarg.annotation))
    return_type = _normalise_type(ast.unparse(node.returns)) if node.returns is not None else ""
    body_line_counts = _section_body_line_counts(doc)

    active: str | None = None
    active_header: int | None = None
    result: list[int] = []
    for index, raw in enumerate(doc.splitlines()):
        if heading := _SECTION_HEADING_RE.match(raw):
            active = heading.group(1)
            active_header = index
            continue
        if _ANY_SECTION_HEADING_RE.match(raw):
            active = None
            active_header = None
            continue
        if not raw.strip() or active is None:
            continue
        if active in {"Args", "Arguments", "Parameters", "Params", "Keyword Args", "Keyword Arguments"}:
            match = _ARG_TYPE_ENTRY_RE.match(raw) or _NUMPY_ARG_TYPE_ENTRY_RE.match(raw)
            if match is not None and _normalise_type(match.group(2)) == annotations.get(match.group(1)):
                result.append(docstring_line + index)
        elif match := _RETURN_TYPE_ENTRY_RE.match(raw):
            if _normalise_type(match.group(1)) == return_type:
                result.append(docstring_line + index)
        elif (
            active_header is not None
            and body_line_counts.get(active_header) == 1
            and _normalise_type(raw.strip()) == return_type
        ):
            result.append(docstring_line + index)
    return tuple(result)


def _section_body_line_counts(doc: str) -> dict[int, int]:
    """Count non-blank body lines under each typed-section heading."""
    counts: dict[int, int] = {}
    active_header: int | None = None
    for index, raw in enumerate(doc.splitlines()):
        if _SECTION_HEADING_RE.match(raw):
            active_header = index
            counts[index] = 0
        elif _ANY_SECTION_HEADING_RE.match(raw):
            active_header = None
        elif active_header is not None and raw.strip():
            counts[active_header] += 1
    return counts


def _normalise_type(value: str) -> str:
    """Normalize insignificant spelling differences in a repeated annotation."""
    return re.sub(r"\s+", "", value).removeprefix("typing.").removesuffix(",optional").casefold()
