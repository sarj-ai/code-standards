from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.psycopg_sql_format_field_mismatch import PsycopgSqlFormatFieldMismatch


_REPORT_QUERY = '''from psycopg.sql import SQL


async def page(cursor, cursor_id):
    where_clause = SQL("WHERE b.batch_id = %s")
    if cursor_id is not None:
        where_clause += SQL(" AND b.id > %s")
    await cursor.execute(
        SQL("""
        SELECT
            b.id,
            COALESCE(b.payload, '{}') AS payload
        FROM batch_item b
        {where}
        ORDER BY b.id
        """).format(where=where_clause),
    )
'''


def _sql(body: str) -> str:
    return "from psycopg.sql import SQL, Identifier\n" + body


def _sql_module(body: str) -> str:
    return "from psycopg import sql\n" + body


def _findings(source: str, path: str = "app/store.py") -> list[str]:
    return [finding.message for finding in PsycopgSqlFormatFieldMismatch().check(Path(path), source)]


@pytest.mark.parametrize(
    ("source", "error", "field"),
    [
        pytest.param(_REPORT_QUERY, "IndexError", "{}", id="sql-empty-object-beside-named-field"),
        pytest.param(
            _sql("SQL('SELECT {0}, {1}').format(Identifier('a'))"), "IndexError", "{1}", id="index-past-arguments"
        ),
        pytest.param(
            _sql("SQL('SELECT {}, {}').format(a=Identifier('a'))"), "IndexError", "{}", id="automatic-with-keywords"
        ),
        pytest.param(
            _sql("SQL('SELECT {} FROM {}').format(Identifier('a'))"), "IndexError", "{}", id="second-automatic"
        ),
        pytest.param(
            _sql("SQL('SELECT * FROM {table}').format(name=Identifier('a'))"),
            "KeyError",
            "{table}",
            id="missing-keyword",
        ),
        pytest.param(
            _sql("SQL('SELECT {field.name}').format(field=Identifier('a'))"),
            "KeyError",
            "{field.name}",
            id="attribute-lookup",
        ),
        pytest.param(_sql("SQL('SELECT {0[0]}').format(Identifier('a'))"), "KeyError", "{0[0]}", id="item-lookup"),
        pytest.param(
            _sql("SQL('SELECT {}, {0}').format(Identifier('a'))"), "ValueError", "{0}", id="automatic-then-manual"
        ),
        pytest.param(
            _sql("SQL('SELECT {0}, {}').format(Identifier('a'))"), "ValueError", "{}", id="manual-then-automatic"
        ),
        pytest.param(
            _sql("SQL('SELECT {name!r}').format(name=Identifier('a'))"), "ValueError", "{name!r}", id="conversion"
        ),
        pytest.param(
            _sql("SQL('SELECT {name:>10}').format(name=Identifier('a'))"), "ValueError", "{name:>10}", id="format-spec"
        ),
        pytest.param(
            _sql("SQL('SELECT {x:{{}}}').format(x=Identifier('a'))"), "ValueError", "{x:{{}}}", id="nested-spec"
        ),
        pytest.param(
            _sql('SQL("SELECT \'{\\"a\\": 1}\'::jsonb").format()'), "ValueError", '{"a": 1}', id="json-object"
        ),
        pytest.param(_sql("SQL('SELECT {0} {').format(Identifier('a'))"), "ValueError", "", id="unmatched-open-brace"),
        pytest.param(_sql("SQL('SELECT {1} }').format(Identifier('a'))"), "IndexError", "{1}", id="first-failure-wins"),
        pytest.param(_sql_module("sql.SQL('SELECT {}').format()"), "IndexError", "{}", id="module-alias"),
        pytest.param(
            "from psycopg.sql import SQL as Q\nQ('SELECT {where}').format()", "KeyError", "{where}", id="renamed-import"
        ),
        pytest.param(
            _sql("SQL('SELECT {} '\n    'FROM {table}').format(table=Identifier('t'))"),
            "IndexError",
            "{}",
            id="implicit-concatenation",
        ),
        pytest.param(_sql("SQL('SELECT {} ' + 'FROM t').format()"), "IndexError", "{}", id="added-literals"),
        pytest.param(_sql("QUERY = 'SELECT {}'\nSQL(QUERY).format()"), "IndexError", "{}", id="constant-template"),
        pytest.param(_sql("query = SQL('SELECT {x}')\nquery.format()"), "KeyError", "{x}", id="bound-receiver"),
        pytest.param(
            _sql("SQL('SELECT {}').format(SQL('{x}').format(y=Identifier('a')))"), "KeyError", "{x}", id="nested-format"
        ),
    ],
)
def test_reports_fields_psycopg_cannot_fill(source: str, error: str, field: str) -> None:
    [message] = _findings(source)

    assert message.startswith(f"psycopg SQL.format raises {error}:")
    assert f"field {field} " in message or (not field and "unmatched brace" in message)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(_REPORT_QUERY.replace("'{}'", "'{{}}'"), id="escaped-empty-object"),
        pytest.param(_sql("SQL('SELECT {{literal}}, {}').format(Identifier('a'))"), id="escaped-field"),
        pytest.param(_sql("SQL('SELECT {0}, {1}, {0}').format(Identifier('a'), Identifier('b'))"), id="reused-index"),
        pytest.param(_sql("SQL('SELECT {a}').format(a=Identifier('a'), unused=Identifier('b'))"), id="extra-keyword"),
        pytest.param(_sql("SQL('SELECT {}').format(Identifier('a'), Identifier('b'))"), id="extra-positional"),
        pytest.param(_sql("SQL('SELECT {a:}').format(a=Identifier('a'))"), id="empty-spec"),
        pytest.param(_sql("SQL('SELECT {}').format(SQL(\"'{}'\"))"), id="unformatted-nested-sql"),
        pytest.param(_sql("SQL('SELECT {a}').format(**fields)"), id="keyword-unpacking"),
        pytest.param(_sql("SQL('SELECT {}, {}').format(*fields)"), id="positional-unpacking"),
        pytest.param(_sql("def build(template):\n    return SQL(template).format()"), id="parameter-template"),
        pytest.param(_sql("SQL(f'SELECT {{}} {suffix}').format()"), id="f-string-template"),
        pytest.param(_sql("SQL(template_for(kind)).format()"), id="computed-template"),
        pytest.param(_sql_module("sql.Composed([sql.SQL('{}'), sql.Identifier('a')])"), id="composed"),
        pytest.param(_sql_module("sql.SQL(', ').join([sql.SQL('{}')])"), id="joined"),
        pytest.param("client.query('SELECT {id:UInt64}', parameters={'id': 1})", id="clickhouse-parameter"),
        pytest.param("'SELECT {id:UInt64}'.format(id=1)", id="plain-string-format"),
        pytest.param("def SQL(text):\n    return text\nSQL('SELECT {}').format()", id="local-sql"),
        pytest.param(_sql("def build(SQL):\n    return SQL('SELECT {}').format()"), id="shadowed-sql"),
        pytest.param("from sqlalchemy import text as SQL\nSQL('SELECT {}').format()", id="other-library"),
        pytest.param(_sql("SQL('SELECT {}').format(\n"), id="malformed-python"),
    ],
)
def test_accepts_fillable_or_unproven_templates(source: str) -> None:
    assert _findings(source) == []


def test_reports_each_failing_call_at_its_start() -> None:
    source = _sql(
        "query = (\n    SQL('SELECT {a}')\n    .format()\n)\nSQL('{}').format(); SQL('{}').format(SQL('a'))\n"
    )

    findings = PsycopgSqlFormatFieldMismatch().check(Path("app/store.py"), source)

    assert [(finding.code, finding.severity, finding.line, finding.col) for finding in findings] == [
        ("SARJ576", Severity.WARNING, 3, 5),
        ("SARJ576", Severity.WARNING, 6, 1),
    ]


def test_suppression_and_generated_sources() -> None:
    source = _sql("SQL('SELECT {}').format()")
    suppressed = f"{source}  # sarj-noqa: SARJ576 -- exercise the psycopg failure\n"

    assert len(_findings(source)) == 1
    assert _findings(suppressed) == []
    assert _findings(source, "generated/store.py") == []


def test_documented_examples() -> None:
    verify_native_rule(PsycopgSqlFormatFieldMismatch, analyze)
