#!/usr/bin/env python3
"""Extract Python and JavaScript-family comments as JSONL or a sentence-band summary."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import io
import json
import os
from pathlib import Path
import re
import tokenize
from typing import TYPE_CHECKING, TypedDict


if TYPE_CHECKING:
    from collections.abc import Iterator


SUFFIXES = {".py": "python", ".js": "typescript", ".jsx": "typescript", ".ts": "typescript", ".tsx": "typescript"}
SKIP_PARTS = {".git", ".venv", ".worktrees", "node_modules", "dist", "build", "coverage", "vendor", "vendored"}
BOUNDARY_RE = re.compile(r"(?<=[.!?])[\"'`)\]]*\s+(?=[A-Z0-9`])")
WARNING_SENTENCES = 2


class Record(TypedDict):
    repository: str
    path: str
    line: int
    language: str
    kind: str
    sentences: int
    text: str


def sentence_units(text: str) -> int:
    cleaned = re.sub(r"https?://\S+", "URL", text)
    cleaned = re.sub(r"`[^`\n]+`", "CODE", cleaned)
    cleaned = re.sub(r"\b\d+\.\d+\b", "NUMBER", cleaned)
    cleaned = re.sub(r"\b(?:e\.g\.|i\.e\.|vs\.|etc\.)", "ABBREVIATION", cleaned, flags=re.IGNORECASE)
    lines = [line.strip().lstrip("*").strip() for line in cleaned.splitlines()]
    bullets = sum(bool(re.match(r"^(?:[-*+] |\d+[.)] )", line)) for line in lines)
    prose = " ".join(line for line in lines if line and not re.match(r"^(?:[-*+] |\d+[.)] )", line))
    return bullets + (len(BOUNDARY_RE.split(prose)) if prose else 0)


def python_comments(source: str) -> list[tuple[int, str, str]]:
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
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.append((first.lineno, "docstring", first.value.value))
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        found.extend(
            (token.start[0], "comment", token.string.removeprefix("#").strip())
            for token in tokens
            if token.type == tokenize.COMMENT
        )
    except (tokenize.TokenError, IndentationError):
        return found
    return found


def javascript_comments(source: str) -> list[tuple[int, str, str]]:
    found: list[tuple[int, str, str]] = []
    index = 0
    line = 1
    quote: str | None = None
    while index < len(source):
        char = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""
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
        if char == "/" and nxt == "/":
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
            found.append((line, "comment", source[index + 2 : end].strip()))
            index = end
            continue
        if char == "/" and nxt == "*":
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


def records(roots: list[Path]) -> Iterator[Record]:
    for root in roots:
        for directory, names, filenames in os.walk(root):
            names[:] = [name for name in names if name not in SKIP_PARTS and not name.startswith(".")]
            for filename in filenames:
                path = Path(directory, filename)
                language = SUFFIXES.get(path.suffix.lower())
                if language is None:
                    continue
                try:
                    source = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                extracted = python_comments(source) if language == "python" else javascript_comments(source)
                for line, kind, text in extracted:
                    yield {
                        "repository": root.name,
                        "path": str(path.relative_to(root)),
                        "line": line,
                        "language": language,
                        "kind": kind,
                        "sentences": sentence_units(text),
                        "text": text,
                    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    extracted = records(args.roots)
    if not args.summary:
        for record in extracted:
            print(json.dumps(record, ensure_ascii=False))
        return 0
    counts: Counter[tuple[str, str]] = Counter()
    for record in extracted:
        sentences = int(record["sentences"])
        band = "0-1" if sentences <= 1 else "2" if sentences == WARNING_SENTENCES else "3+"
        counts[str(record["repository"]), band] += 1
    print("repository\t0-1\t2\t3+")
    for repository in sorted({key[0] for key in counts}):
        values = (counts[repository, "0-1"], counts[repository, "2"], counts[repository, "3+"])
        print(repository, *values, sep="\t")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
