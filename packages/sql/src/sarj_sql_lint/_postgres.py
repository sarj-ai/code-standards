from __future__ import annotations

from typing import override

from sqlglot import exp, parse
from sqlglot.dialects.postgres import Postgres


def parse_postgres(source: str) -> list[exp.Expr | None]:
    return parse(source, read=PostgresForLint)


class PostgresForLint(Postgres):
    class Parser(Postgres.Parser):
        @override
        def _warn_unsupported(self) -> None:
            """Unsupported input must not copy SQL source into dependency logs."""
