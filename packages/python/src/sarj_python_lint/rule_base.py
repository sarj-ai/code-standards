"""Base types for sarj-python-lint rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
import ast
from dataclasses import dataclass
from pathlib import Path
import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Sequence


# Suppression syntax. Two forms supported:
#   # sarj-noqa: SARJ001 — reason
#   # sarj-noqa: SARJ001, SARJ002 — reason
# We deliberately do NOT reuse ruff's own suppression comment because ruff
# aggressively cleans unrecognized codes (RUF100/RUF102) even with `external`
# set, which silently breaks suppressions across runs. A distinct prefix
# (sarj-noqa) shares no syntax with ruff, so the two never collide.
_SARJ_NOQA_RE = re.compile(
    r"#\s*sarj-noqa(?::\s*([A-Za-z0-9_, ]+))?",
    re.IGNORECASE,
)


def is_suppressed(source_lines: Sequence[str], line: int, code: str) -> bool:
    """Report whether the diagnostic's line carries a `# sarj-noqa[: CODE]` comment.

    `line` is 1-based to match Diagnostic.line.

    Returns:
        True when the line is suppressed for `code`.

    """
    if line < 1 or line > len(source_lines):
        return False
    text = source_lines[line - 1]
    m = _SARJ_NOQA_RE.search(text)
    if not m:
        return False
    codes_str = m.group(1)
    if not codes_str:
        # Bare `# sarj-noqa` suppresses every SARJ code on the line
        return True
    codes = {c.strip().upper() for c in codes_str.split(",") if c.strip()}
    return code.upper() in codes


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A single lint finding."""

    path: Path
    line: int
    col: int
    code: str
    message: str

    def format(self) -> str:
        """Render the finding ruff-compatibly as `path:line:col: CODE message`.

        Returns:
            The formatted single-line diagnostic string.

        """
        return f"{self.path}:{self.line}:{self.col}: {self.code} {self.message}"


class Rule(ABC):
    """Base class for a single lint rule.

    Subclasses set `id` (kebab-case) and `code` (e.g. SARJ001) as class
    attributes and implement `check(path, source) -> list[Diagnostic]`.
    """

    id: str
    code: str
    description: str

    @abstractmethod
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Inspect the given source. Return zero or more diagnostics."""
        raise NotImplementedError


_last_parse: tuple[str, str, ast.Module | None] | None = None


def parse_or_none(path: Path, source: str) -> ast.Module | None:
    """Parse `source`, memoizing the most recent file so N rules share one parse.

    Returns:
        The parsed module, or None when `source` has a syntax error.

    """
    global _last_parse  # ruff:ignore[global-statement] — single-slot memo; the CLI runs rules per file sequentially
    path_key = str(path)
    if _last_parse is not None and _last_parse[0] == path_key and _last_parse[1] is source:
        return _last_parse[2]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        tree = None
    _last_parse = (path_key, source, tree)
    return tree
