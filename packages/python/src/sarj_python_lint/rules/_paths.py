from __future__ import annotations

import ast
from io import StringIO
import re
import tokenize
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


_TEST_DIR_NAMES = frozenset({"integration_tests", "tests", "test"})
_TEST_SUPPORT_DIR_NAMES = frozenset(
    {"testing", "fakes", "mocks", "doubles", "test_fakes", "test_doubles", "test_utils"}
)
_TEST_SUPPORT_STEM_RE = re.compile(r"(?:^|_)(?:fakes?|mocks?|stubs?|doubles?|testing)(?:$|_)")

# A marker must claim ownership of the file/code, not merely describe a value.
_GENERATED_RE = re.compile(
    r"(?:^@generated\b|^auto(?:-|matically )?generated(?:[.!]?|\s+file\b.*|\s+by\b.*)$|"
    r"(?:this\s+)?file\s+(?:is|was|has been)\s+(?:auto(?:-|matically )?)?generated\b|"
    r"code\s+generated\s+by\b|^generated\s+(?:by|with)\b|"
    r"\bgenerated\b.*\bdo not edit\b|\bdo not edit\b.*\bgenerated\b|"
    r"\bwarning:\s+auto(?:-|matically )?generated\b.*\ball edits will be lost\b)",
    re.IGNORECASE,
)
_DO_NOT_EDIT_RE = re.compile(r"^do not edit[.!]?$", re.IGNORECASE)

# AI attribution is not evidence that a reproducible generator owns the file.
_AI_ATTRIBUTION_RE = re.compile(
    r"\b(?:@?generated|authored|written)(?:\s+\w+){0,2}\s+(?:by|with|using|via)\s+(?:an?\s+)?"
    r"(?:ai|llm|openai|anthropic|chatgpt|claude|codex|(?:github\s+)?copilot|gemini|"
    r"chat-gpt|gpt\s*-?\s*\d[\w.]*|cursor|amazon\s+q|language\s+model|assistant)\b",
    re.IGNORECASE,
)

_GENERATED_HEADER_LINES = 5

_GENERATED_DIR_NAMES = frozenset({".venv", "generated", "site-packages", "vendor", "vendored", "venv"})

# Marker files identify generator roots whose banner-less output cannot self-identify as generated.
_CODEGEN_MARKER_NAMES = (
    ".openapi-generator",
    ".openapi-generator-ignore",
    ".swagger-codegen-ignore",
    "openapi-python-client.yml",
    "openapi-python-client.yaml",
    "codegen.yml",
    "codegen.yaml",
    "codegen.config.yml",
    "codegen.config.yaml",
    "buf.gen.yaml",
    "buf.gen.yml",
)

# Ancestor walks stop at the repository root.
_REPO_ROOT_MARKERS = (".git",)

# Bound ancestor scans so pathological paths or symlink loops cannot stall linting.
_MAX_ANCESTOR_DEPTH = 40


def is_generated_source(source: str) -> bool:
    bodies = _leading_header_bodies(source)
    non_ai = [body for body in bodies if _AI_ATTRIBUTION_RE.search(body) is None]
    for body in non_ai:
        if _GENERATED_RE.search(body):
            return True
    return not any(_AI_ATTRIBUTION_RE.search(body) for body in bodies) and any(
        _DO_NOT_EDIT_RE.fullmatch(body) for body in bodies
    )


def _leading_header_bodies(source: str) -> list[str]:
    bodies: list[str] = []
    tokens = tokenize.generate_tokens(StringIO(source).readline)
    while True:
        try:
            token = next(tokens)
        except StopIteration:
            break
        except IndentationError, tokenize.TokenError:
            break
        if token.start[0] > _GENERATED_HEADER_LINES:
            break
        if token.type in {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}:
            continue
        if token.type == tokenize.COMMENT:
            bodies.append(token.string.lstrip("#").strip())
            continue
        if token.type == tokenize.STRING and not bodies:
            try:
                expression = ast.parse(token.string, mode="eval").body
            except SyntaxError, ValueError:
                break
            if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
                bodies.extend(line for raw_line in expression.value.splitlines() if (line := raw_line.strip()))
            break
        break
    return bodies


def is_generated_path(path: Path) -> bool:
    if any(part.lower() in _GENERATED_DIR_NAMES for part in path.parts):
        return True
    for depth, ancestor in enumerate(path.parents):
        if depth >= _MAX_ANCESTOR_DEPTH:
            break
        # `depth == 0` is the file's own directory: a generator config sitting
        # next to the file makes the file the generator, not its output.
        if _is_repo_root(ancestor):
            break
        if depth and _is_codegen_root(ancestor):
            return True
    return False


def _is_codegen_root(directory: Path) -> bool:
    return any((directory / name).exists() for name in _CODEGEN_MARKER_NAMES)


def _is_repo_root(directory: Path) -> bool:
    return any((directory / name).exists() for name in _REPO_ROOT_MARKERS)


def clear_path_caches() -> None:
    """Compatibility no-op; path topology is intentionally observed fresh."""


def is_generated(path: Path, source: str) -> bool:
    return is_generated_source(source) or is_generated_path(path)


def is_test_path(path: Path) -> bool:
    name = path.name
    if name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part in _TEST_DIR_NAMES for part in path.parts)


def is_test_support_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    stem = path.stem.lower()
    return bool(parts & _TEST_SUPPORT_DIR_NAMES or (not stem.endswith("_prod") and _TEST_SUPPORT_STEM_RE.search(stem)))
