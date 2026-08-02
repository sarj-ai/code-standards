"""SARJ053 — `gen_random_uuid()` in SQL embedded in Python — use `uuidv7()`.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_gen_random_uuid_in_sql.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._sql import strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


_GEN_RANDOM_UUID_RE = re.compile(r"\bgen_random_uuid\s*\(", re.IGNORECASE)

# Require SQL structure so prose that merely names the function stays valid.
_SQL_SHAPE_RE = re.compile(
    r"\b(?:CREATE|ALTER|INSERT|UPDATE|SELECT|DEFAULT|VALUES)\b",
    re.IGNORECASE,
)

_BUILDS_UUIDV7_RE = re.compile(
    r"\buuid_?(?:generate_)?v7\b|\buuid7\b|"
    r"\b(?:uuid_send|gen_random_bytes|set_byte|get_byte|int8send)\s*\(|"
    r"\b(?:substring|encode|overlay)\s*\(\s*(?:uuid_send\s*\()?\s*gen_random_uuid",
    re.IGNORECASE,
)

_MESSAGE = (
    "`gen_random_uuid()` generates a random UUIDv4 — use `uuidv7()` (Postgres 18) "
    "so keys are time-ordered and inserts append to the index's right edge "
    "instead of scattering across every leaf page."
)


@final
class NoGenRandomUuidInSql(Rule):
    id: str = "no-gen-random-uuid-in-sql"
    code: str = "SARJ053"
    description: str = (
        "`gen_random_uuid()` in SQL embedded in Python emits a random UUIDv4 — "
        "use `uuidv7()` so primary keys are time-ordered."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Report every embedded SQL literal defaulting to `gen_random_uuid()`."""
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=_MESSAGE,
            )
            for node in nodes(tree, ast.Constant)
            if isinstance(node.value, str) and _is_offending_sql(node.value)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_offending_sql(value: str) -> bool:
    """Report whether a string literal is SQL that calls `gen_random_uuid()`."""
    masked = strip_sql_noise(value)
    if not (_GEN_RANDOM_UUID_RE.search(masked) and _SQL_SHAPE_RE.search(masked)):
        return False
    return not _BUILDS_UUIDV7_RE.search(masked)
