"""Extract Python and JavaScript-family comments for rule calibration."""

from __future__ import annotations

import ast
from collections import Counter
from contextlib import suppress
import io
import json
import os
from pathlib import Path
import re
import tokenize
from typing import TYPE_CHECKING, TypedDict


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from typing import TextIO


_SUFFIXES = {".py": "python", ".js": "typescript", ".jsx": "typescript", ".ts": "typescript", ".tsx": "typescript"}
_SKIP_PARTS = {".git", ".venv", ".worktrees", "node_modules", "dist", "build", "coverage", "vendor", "vendored"}
_BOUNDARY_RE = re.compile(r"(?<=[.!?])[\"'`)\]]*\s+(?=[A-Z0-9`])")
_BULLET_RE = re.compile(r"^\s*(?:[-*+] |\d+[.)] )")
_SECOND_SENTENCE = 2


class Record(TypedDict):
    repository: str
    path: str
    line: int
    language: str
    kind: str
    sentences: int
    text: str


def records(roots: Sequence[Path]) -> Iterator[Record]:
    for root in roots:
        resolved_root = root.resolve(strict=True)
        for directory, names, filenames in os.walk(resolved_root, followlinks=False):
            names[:] = [name for name in names if name not in _SKIP_PARTS and not name.startswith(".")]
            for filename in filenames:
                path = Path(directory, filename)
                language = _SUFFIXES.get(path.suffix.lower())
                if language is None or path.is_symlink():
                    continue
                try:
                    resolved = path.resolve(strict=True)
                    if not resolved.is_relative_to(resolved_root):
                        continue
                    source = resolved.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                comments = _python_comments(source) if language == "python" else _javascript_comments(source)
                for line, kind, value in comments:
                    yield {
                        "repository": resolved_root.name,
                        "path": str(path.relative_to(resolved_root)),
                        "line": line,
                        "language": language,
                        "kind": kind,
                        "sentences": _sentence_units(value),
                        "text": value,
                    }


def emit_summary(roots: Sequence[Path], output: TextIO) -> int:
    counts: Counter[tuple[str, str]] = Counter()
    for index, root in enumerate(roots, start=1):
        repository = f"repository-{index}"
        for record in records([root]):
            sentences = record["sentences"]
            band = "0-1" if sentences <= 1 else "2" if sentences == _SECOND_SENTENCE else "3+"
            counts[repository, band] += 1
    output.write("repository\t0-1\t2\t3+\n")
    output.writelines(
        f"{repository}\t{counts[repository, '0-1']}\t{counts[repository, '2']}\t{counts[repository, '3+']}\n"
        for repository in sorted({key[0] for key in counts})
    )
    return 0


def write_records(roots: Sequence[Path], destination: Path) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(destination, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.writelines(json.dumps(record, ensure_ascii=False) + "\n" for record in records(roots))
    return 0


def _python_comments(source: str) -> list[tuple[int, str, str]]:
    found: list[tuple[int, str, str]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) or not node.body:
                continue
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.append((first.lineno, "docstring", first.value.value))
    with suppress(tokenize.TokenError, IndentationError):
        found.extend(
            (token.start[0], "comment", token.string.removeprefix("#").strip())
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type == tokenize.COMMENT
        )
    return found


def _sentence_units(text: str) -> int:
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
    return units + (len(_BOUNDARY_RE.split(paragraph)) if paragraph else 0)


def _javascript_comments(source: str) -> list[tuple[int, str, str]]:
    found: list[tuple[int, str, str]] = []
    index = 0
    line = 1
    quote: str | None = None
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            line += char == "\n"
            index += 1
            continue
        if char in {'"', "'", "`"}:
            quote = char
            index += 1
            continue
        if char == "/" and following == "/":
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
            found.append((line, "comment", source[index + 2 : end].strip()))
            index = end
            continue
        if char == "/" and following == "*":
            end = source.find("*/", index + 2)
            end = len(source) - 2 if end < 0 else end
            value = source[index + 2 : end]
            found.append((line, "jsdoc" if value.startswith("*") else "comment", value.strip("* \n")))
            line += value.count("\n")
            index = end + 2
            continue
        line += char == "\n"
        index += 1
    return found
