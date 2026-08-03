"""Base types for sarj-python-lint rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
import ast
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import re
from typing import TYPE_CHECKING, Final


if TYPE_CHECKING:
    from collections.abc import Sequence


# Each rule points directly to its executable examples.
REPO_BLOB: Final = "https://github.com/sarj-ai/standards/blob/main"
TESTS_DIR: Final = "packages/python/tests/rules"


# Suppression syntax.
_SARJ_NOQA_RE = re.compile(
    r"#\s*sarj-noqa(?::\s*([A-Za-z0-9_, ]+))?",
    re.IGNORECASE,
)


def is_suppressed(source_lines: Sequence[str], line: int, code: str) -> bool:
    """Report whether the diagnostic's line carries a `# sarj-noqa[: CODE]` comment."""
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
    codes = {val.upper() for c in codes_str.split(",") if (val := c.strip())}
    return code.upper() in codes


class Severity(StrEnum):
    """Whether a diagnostic blocks the lint command."""

    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A single lint finding."""

    path: Path
    line: int
    col: int
    code: str
    message: str
    severity: Severity = Severity.ERROR

    def format(self) -> str:
        """Render the finding ruff-compatibly as `path:line:col: CODE message`."""
        label = "warning: " if self.severity is Severity.WARNING else ""
        return f"{self.path}:{self.line}:{self.col}: {self.code} {label}{self.message}"


class Rule(ABC):
    """Base class for a single lint rule."""

    id: str
    code: str
    description: str

    @abstractmethod
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Inspect the given source."""
        raise NotImplementedError

    @classmethod
    def examples_path(cls) -> str:
        return f"{TESTS_DIR}/test_{cls.__module__.rpartition('.')[2]}.py"

    @classmethod
    def examples_url(cls) -> str:
        return f"{REPO_BLOB}/{cls.examples_path()}"


_last_parse: tuple[str, str, ast.Module | None] | None = None


def parse_or_none(path: Path, source: str) -> ast.Module | None:
    """Parse `source`, memoizing the most recent file so N rules share one parse."""
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
