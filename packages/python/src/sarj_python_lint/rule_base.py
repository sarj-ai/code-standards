"""Base types for sarj-python-lint rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
import ast
from dataclasses import dataclass
from pathlib import Path
import re
from typing import TYPE_CHECKING, Final


if TYPE_CHECKING:
    from collections.abc import Sequence


# The two locations a rule's documentation lives in, and the base of the links
# that point at them. Named once here because `Rule.examples_path` /
# `Rule.evidence_path` DERIVE every rule's links from these plus the rule's own
# module name and code — no rule module writes a URL by hand, so a rename cannot
# leave a dead link behind. `test_rule_meta.py` asserts every derived path
# resolves on disk.
REPO_BLOB: Final = "https://github.com/sarj-ai/standards/blob/main"
TESTS_DIR: Final = "packages/python/tests/rules"
EVIDENCE_DIR: Final = "docs/rules"


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
    codes = {val.upper() for c in codes_str.split(",") if (val := c.strip())}
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
        """Render the finding ruff-compatibly as `path:line:col: CODE message`."""
        return f"{self.path}:{self.line}:{self.col}: {self.code} {self.message}"


class Rule(ABC):
    """Base class for a single lint rule.

    Subclasses set `id` (kebab-case) and `code` (e.g. SARJ001) as class
    attributes and implement `check(path, source) -> list[Diagnostic]`.

    A rule documents itself with a one-line summary plus two DERIVED links —
    `examples_url()` (the examples) and `evidence_url()` (the measurements). Both
    are computed from `__module__` and `code`, never written by hand, and
    `test_rule_meta.py` asserts each resolves to a file that exists. A rename
    therefore fails the suite instead of leaving a dead link in a docstring.
    """

    id: str
    code: str
    description: str

    # True when `docs/rules/<code>.md` holds this rule's measured evidence — the
    # corpus census, the threshold sweeps and the false-positive families each
    # guard was built to stop. Declared rather than probed so the link still
    # prints from an installed wheel, where `docs/` is not shipped;
    # `test_evidence_flag_matches_the_filesystem` keeps the two honest.
    has_evidence: bool = False

    @abstractmethod
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Inspect the given source. Return zero or more diagnostics."""
        raise NotImplementedError

    @classmethod
    def examples_path(cls) -> str:
        return f"{TESTS_DIR}/test_{cls.__module__.rpartition('.')[2]}.py"

    @classmethod
    def evidence_path(cls) -> str:
        return f"{EVIDENCE_DIR}/{cls.code}.md"

    @classmethod
    def examples_url(cls) -> str:
        return f"{REPO_BLOB}/{cls.examples_path()}"

    @classmethod
    def evidence_url(cls) -> str:
        return f"{REPO_BLOB}/{cls.evidence_path()}"


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
