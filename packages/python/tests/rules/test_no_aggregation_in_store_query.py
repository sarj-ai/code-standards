"""Exhaustive suite for SARJ020 (no-aggregation-in-store-query).

The rule flags exactly three surfaces inside a SQL-shaped string literal in a
`.py` file: `COUNT(`, `GROUP BY`, and `DISTINCT`. Everything else — SUM/AVG/
MIN/MAX/HAVING, prose, non-query strings, ClickHouse files/queries — is out of
scope by design (see the rule module docstring: "no DISTINCT / GROUP BY /
COUNT"). These tests pin the *actual* behavior of the implementation, not a
broader intuition of what "aggregation" might mean.
"""

from pathlib import Path

import pytest

from sarj_python_lint.rule_base import Diagnostic, is_suppressed
from sarj_python_lint.rules.no_aggregation_in_store_query import (
    NoAggregationInStoreQuery,
)


def _check(source: str, filename: str = "call_store.py") -> list[Diagnostic]:
    return NoAggregationInStoreQuery().check(Path(filename), source)


def _labels(diags: list[Diagnostic]) -> list[str]:
    return [d.message.split(" —")[0] for d in diags]


# --------------------------------------------------------------------------- #
# Positive: each flagged keyword, on its own, in a store query.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("source", "expected_label"),
    [
        ('q = "SELECT COUNT(*) FROM call"\n', "COUNT("),
        ('q = "SELECT COUNT(id) FROM call"\n', "COUNT("),
        ('q = "SELECT COUNT (*) FROM call"\n', "COUNT("),
        ('q = "SELECT status, x FROM call GROUP BY status"\n', "GROUP BY"),
        ('q = "SELECT DISTINCT org_id FROM call"\n', "DISTINCT"),
    ],
)
def test_flags_single_aggregation(source: str, expected_label: str) -> None:
    diags = _check(source)
    assert len(diags) == 1
    assert expected_label in diags[0].message


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('q = "select count(*) from call"\n', id="all-lower"),
        pytest.param('q = "SELECT COUNT(*) FROM CALL"\n', id="all-upper"),
        pytest.param('q = "sElEcT CoUnT(*) fRoM call"\n', id="mixed-case"),
        pytest.param('q = "select distinct org_id from call"\n', id="distinct-lower"),
        pytest.param('q = "SELECT s FROM call GROUP    BY s"\n', id="group-many-spaces"),
        pytest.param('q = "SELECT s FROM call\\nGROUP\\nBY s"\n', id="group-newline-split"),
    ],
)
def test_case_and_whitespace_insensitive(source: str) -> None:
    assert len(_check(source)) == 1


# --------------------------------------------------------------------------- #
# Positive: query shapes beyond plain SELECT ... FROM.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('q = "UPDATE call SET n = (SELECT COUNT(*) FROM x)"\n', id="update-set"),
        pytest.param(
            'q = "DELETE FROM call WHERE id IN (SELECT DISTINCT id FROM x)"\n',
            id="delete-from",
        ),
        pytest.param(
            'q = "SELECT s FROM call GROUP BY s HAVING COUNT(*) > 1"\n',
            id="count-in-having",
        ),
    ],
)
def test_flags_various_query_shapes(source: str) -> None:
    assert len(_check(source)) == 1


# --------------------------------------------------------------------------- #
# Positive: how the SQL string is spelled — concatenation, f-string, format,
# execute/fetch call arguments. The rule walks every str Constant (and
# +-concatenated / adjacent-literal Constants), so all of these are caught.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('q = (\n  "SELECT COUNT(*) "\n  "FROM call"\n)\n', id="adjacent-literals"),
        pytest.param('q = "SELECT COUNT(*) " + "FROM call"\n', id="plus-concatenation"),
        pytest.param('q = f"SELECT COUNT(*) FROM call"\n', id="fstring-no-interp"),
        pytest.param('q = f"SELECT COUNT(*) FROM {table} WHERE id = 1"\n', id="fstring-interp"),
        pytest.param('q = "SELECT COUNT(*) FROM call".format()\n', id="dot-format"),
        pytest.param('cur.execute("SELECT COUNT(*) FROM call")\n', id="execute-arg"),
        pytest.param('await conn.fetch("SELECT DISTINCT id FROM call")\n', id="fetch-arg"),
    ],
)
def test_flags_regardless_of_string_spelling(source: str) -> None:
    assert len(_check(source)) == 1


# --------------------------------------------------------------------------- #
# Positive: multiple labels in one query, and multiple violations across a file.
# --------------------------------------------------------------------------- #


def test_multiple_labels_in_one_query_listed_in_rule_order() -> None:
    diags = _check('q = "SELECT DISTINCT s, COUNT(*) FROM call GROUP BY s"\n')
    assert len(diags) == 1
    assert _labels(diags) == ["Store query uses COUNT(, GROUP BY, DISTINCT"]


def test_count_distinct_lists_both() -> None:
    diags = _check('q = "SELECT COUNT(DISTINCT org_id) FROM call"\n')
    assert len(diags) == 1
    assert "COUNT(" in diags[0].message
    assert "DISTINCT" in diags[0].message


def test_multiple_violations_sorted_by_line_then_col() -> None:
    src = 'a = "SELECT DISTINCT x FROM y"\nb = "SELECT COUNT(*) FROM call"\nc = "SELECT s FROM call GROUP BY s"\n'
    diags = _check(src)
    assert [(d.line, d.col) for d in diags] == [(1, 5), (2, 5), (3, 5)]
    assert [d.code for d in diags] == ["SARJ020"] * 3


# --------------------------------------------------------------------------- #
# Positive: exact line/col reporting (x2, per brief).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("source", "line", "col"),
    [
        pytest.param('q = "SELECT COUNT(*) FROM call"\n', 1, 5, id="simple-assign"),
        pytest.param('x = 1\ny = 2\nq = "SELECT COUNT(*) FROM call"\n', 3, 5, id="third-line"),
        pytest.param('cur.execute("SELECT COUNT(*) FROM call")\n', 1, 13, id="execute-arg-col"),
        pytest.param(
            'q = (\n  "SELECT COUNT(*) "\n  "FROM call"\n)\n',
            2,
            3,
            id="adjacent-literal-col",
        ),
    ],
)
def test_line_and_col(source: str, line: int, col: int) -> None:
    diags = _check(source)
    assert len(diags) == 1
    assert (diags[0].line, diags[0].col) == (line, col)


# --------------------------------------------------------------------------- #
# Negative: legitimate bounded/point reads and non-query strings.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('q = "SELECT id, status FROM call WHERE id = %s"\n', id="point"),
        pytest.param('q = "SELECT id FROM call ORDER BY created_at LIMIT 50"\n', id="bounded"),
        pytest.param('label = "GROUP BY clause"\n', id="no-query-shape"),
        pytest.param('msg = "distinct count of group members"\n', id="prose"),
        pytest.param(
            'msg = "This failure is distinct from the others reported."\n',
            id="distinct-from-prose",
        ),
    ],
)
def test_allows_non_aggregating_or_non_query(source: str) -> None:
    assert _check(source) == []


# --------------------------------------------------------------------------- #
# Negative: OUT-OF-SCOPE aggregate surfaces. The rule name says "aggregation"
# but the implementation deliberately covers only COUNT(/GROUP BY/DISTINCT.
# SUM/AVG/MIN/MAX/HAVING in a Postgres store query are NOT flagged. Pinned here
# so a future scope change is a conscious, visible edit (see report).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('q = "SELECT SUM(amount) FROM invoice"\n', id="sum"),
        pytest.param('q = "SELECT AVG(x) FROM call"\n', id="avg"),
        pytest.param('q = "SELECT MIN(x) FROM call"\n', id="min"),
        pytest.param('q = "SELECT MAX(x) FROM call"\n', id="max"),
        pytest.param('q = "SELECT org FROM call HAVING x > 1"\n', id="having-only"),
    ],
)
def test_out_of_scope_aggregates_not_flagged(source: str) -> None:
    assert _check(source) == []


# --------------------------------------------------------------------------- #
# Negative: false-positive guards — substrings, column names, and Python
# identifiers that merely contain "count"/"distinct"/"sum" must not trip.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('q = "SELECT account FROM ledger WHERE id = %s"\n', id="account-substring"),
        pytest.param('q = "SELECT amount FROM invoice WHERE id = %s"\n', id="amount-substring"),
        pytest.param('q = "SELECT discount FROM item WHERE id = %s"\n', id="discount-substring"),
        pytest.param('q = "SELECT distinct_id FROM call WHERE id = %s"\n', id="distinct-id-col"),
        pytest.param('q = "SELECT row_count FROM call WHERE id = %s"\n', id="count-col-no-paren"),
        pytest.param('q = "SELECT count FROM call WHERE id = %s"\n', id="count-word-no-paren"),
        pytest.param('sum = "SELECT amount FROM invoice WHERE id = %s"\n', id="sum-py-identifier"),
        pytest.param('count = "SELECT id FROM call WHERE id = %s"\n', id="count-py-identifier"),
        pytest.param("total = sum(values)\n", id="sum-builtin-call"),
        pytest.param("lo = min(a, b)\nhi = max(a, b)\n", id="min-max-builtins"),
    ],
)
def test_false_positive_guards(source: str) -> None:
    assert _check(source) == []


def test_docstring_mentioning_count_prose_is_not_a_query() -> None:
    src = '"""Returns the COUNT of active rows, grouped by org, for reporting."""\n'
    assert _check(src) == []


def test_docstring_containing_actual_query_is_flagged() -> None:
    # A docstring that literally embeds SELECT ... COUNT( ... FROM is
    # indistinguishable from a query string and IS flagged (col 1).
    src = '"""Run SELECT COUNT(*) FROM call to get the total."""\n'
    diags = _check(src)
    assert len(diags) == 1
    assert (diags[0].line, diags[0].col) == (1, 1)


# --------------------------------------------------------------------------- #
# Negative: SQL comments are stripped before matching.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'q = "SELECT id FROM call -- COUNT here is prose\\n WHERE id = %s"\n',
            id="line-comment",
        ),
        pytest.param(
            'q = "SELECT id FROM call /* COUNT(*) */ WHERE id = %s"\n',
            id="block-comment",
        ),
        pytest.param(
            'q = "SELECT id FROM call /* GROUP BY s */ WHERE id = %s"\n',
            id="block-comment-group-by",
        ),
    ],
)
def test_aggregation_only_in_sql_comment_ignored(source: str) -> None:
    assert _check(source) == []


def test_comment_stripped_but_real_aggregation_still_flagged() -> None:
    src = 'q = "SELECT COUNT(*) FROM call -- point read note"\n'
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Exempt: ClickHouse files and ClickHouse-flavored queries — aggregation there
# is the whole point of the columnar mirror.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "from clickhouse_connect.driver import AsyncClient\n"
            'q = "SELECT status, COUNT(*) FROM call GROUP BY status"\n',
            id="connect",
        ),
        pytest.param(
            'import clickhouse_driver\nq = "SELECT status, COUNT(*) FROM call GROUP BY status"\n',
            id="driver",
        ),
        pytest.param(
            'import clickhouse\nq = "SELECT status, COUNT(*) FROM call GROUP BY status"\n',
            id="bare-import",
        ),
    ],
)
def test_clickhouse_file_is_exempt(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'q = "SELECT argMax(status, _peerdb_version), COUNT(*) FROM call GROUP BY org"\n',
            id="argMax-peerdb",
        ),
        pytest.param('q = "SELECT argMin(x, v), COUNT(*) FROM call"\n', id="argMin"),
        pytest.param('q = "SELECT uniqExact(id), COUNT(*) FROM call GROUP BY x"\n', id="uniqExact"),
        pytest.param('q = "SELECT groupArray(x), COUNT(*) FROM call"\n', id="groupArray"),
        pytest.param('q = "SELECT arrayJoin(x), COUNT(*) FROM call"\n', id="arrayJoin"),
        pytest.param("q = \"SELECT JSONExtract(x, 'a'), COUNT(*) FROM call\"\n", id="JSONExtract"),
        pytest.param('q = "SELECT quantile(0.5)(x), COUNT(*) FROM call"\n', id="quantile"),
    ],
)
def test_clickhouse_flavored_query_is_exempt(source: str) -> None:
    assert _check(source) == []


# --------------------------------------------------------------------------- #
# Exempt: BigQuery analytics files and BigQuery-flavored queries — analytics and
# reporting reads against the columnar mirror LEGITIMATELY aggregate. Mirrors the
# ClickHouse exemption above. (FP class found on one first-party repo's inline
# analytics services, e.g. `SELECT id AS session_id FROM \`{source_table}\``.)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'from google.cloud import bigquery\nq = "SELECT status, COUNT(*) FROM call GROUP BY status"\n',
            id="from-import",
        ),
        pytest.param(
            'from google.cloud.bigquery import Client\nq = "SELECT status, COUNT(*) FROM call GROUP BY status"\n',
            id="from-submodule",
        ),
        pytest.param(
            'import google.cloud.bigquery\nq = "SELECT DISTINCT org_id FROM call"\n',
            id="import-dotted",
        ),
    ],
)
def test_bigquery_file_is_exempt(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'q = f"SELECT id AS session_id, COUNT(*) FROM `{source_table}` GROUP BY id"\n',
            id="backtick-braced-table",
        ),
        pytest.param(
            'q = "SELECT status, COUNT(*) FROM `proj.ds.call` GROUP BY status"\n',
            id="backtick-qualified-table",
        ),
        pytest.param(
            'q = "SELECT DISTINCT id FROM `proj.ds.call` cs JOIN `proj.ds.x` x ON cs.id = x.id"\n',
            id="backtick-join",
        ),
        pytest.param(
            'q = "SELECT APPROX_COUNT_DISTINCT(id), COUNT(*) FROM call GROUP BY org"\n',
            id="approx-count-distinct",
        ),
        pytest.param(
            'q = "SELECT COUNTIF(ok), COUNT(*) FROM call GROUP BY org"\n',
            id="countif",
        ),
        pytest.param(
            'q = "SELECT SAFE_CAST(x AS INT64), COUNT(*) FROM call GROUP BY x"\n',
            id="safe-cast",
        ),
        pytest.param(
            "q = \"SELECT PARSE_TIMESTAMP('%Y', y), COUNT(*) FROM call GROUP BY y\"\n",
            id="parse-timestamp",
        ),
        pytest.param(
            'q = "SELECT STRUCT(a, b), COUNT(*) FROM call GROUP BY a"\n',
            id="struct-constructor",
        ),
    ],
)
def test_bigquery_flavored_query_is_exempt(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'q = "SELECT COUNT(*) FROM users WHERE org_id = %s GROUP BY status"\n',
            id="plain-postgres-count-group-by",
        ),
        pytest.param('q = "SELECT DISTINCT org_id FROM account"\n', id="plain-distinct"),
        pytest.param('q = "SELECT s FROM account GROUP BY s"\n', id="plain-group-by"),
        pytest.param(
            'q = "SELECT ARRAY_AGG(id), COUNT(*) FROM account GROUP BY org"\n',
            id="array-agg-is-postgres-too",
        ),
        pytest.param(
            'q = "SELECT UNNEST(ids), COUNT(*) FROM account GROUP BY org"\n',
            id="unnest-is-postgres-too",
        ),
    ],
)
def test_plain_postgres_aggregation_still_fires(source: str) -> None:
    assert len(_check(source)) == 1


# --------------------------------------------------------------------------- #
# Path gate: the rule fires only on store-layer modules (`*_store.py` basename
# or a file under a `stores/` directory). A non-store file (a Flask view, a
# Django ORM SQL generator) with aggregating SQL is out of scope.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("filename", ["call_store.py", "stores/call.py"])
def test_store_file_flagged(filename: str) -> None:
    assert len(_check('q = "SELECT COUNT(*) FROM call"\n', filename=filename)) == 1


@pytest.mark.parametrize("filename", ["service.py", "routes.py", "app/views.py", "random_module.py"])
def test_nonstore_file_not_flagged(filename: str) -> None:
    assert _check('q = "SELECT COUNT(*) FROM call"\n', filename=filename) == []


# --------------------------------------------------------------------------- #
# Suppression.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        'q = "SELECT COUNT(*) FROM call"  # sarj-noqa: SARJ020\n',
        'q = "SELECT COUNT(*) FROM call"  # sarj-noqa: SARJ020 — bounded admin count\n',
        'q = "SELECT COUNT(*) FROM call"  # sarj-noqa\n',
        'q = "SELECT COUNT(*) FROM call"  # sarj-noqa: SARJ019, SARJ020\n',
    ],
)
def test_respects_noqa(source: str) -> None:
    diags = _check(source)
    lines = source.splitlines()
    kept = [d for d in diags if not is_suppressed(lines, d.line, d.code)]
    assert kept == []


def test_noqa_for_other_code_does_not_suppress() -> None:
    src = 'q = "SELECT COUNT(*) FROM call"  # sarj-noqa: SARJ019\n'
    diags = _check(src)
    lines = src.splitlines()
    kept = [d for d in diags if not is_suppressed(lines, d.line, d.code)]
    assert len(kept) == 1


# --------------------------------------------------------------------------- #
# Edge cases: empty, blank, and unparsable sources.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("", id="empty"),
        pytest.param("\n\n\n", id="blank-lines"),
        pytest.param("# just a comment\n", id="comment-only"),
        pytest.param("def (:\n", id="syntax-error"),
        pytest.param('q = "SELECT COUNT(*) FROM call"\ndef (:\n', id="syntax-error-with-query"),
        pytest.param("x = 1\n", id="no-strings"),
    ],
)
def test_edge_sources_return_no_diagnostics(source: str) -> None:
    assert _check(source) == []


# --------------------------------------------------------------------------- #
# Diagnostic metadata sanity.
# --------------------------------------------------------------------------- #


def test_diagnostic_metadata() -> None:
    diags = _check('q = "SELECT COUNT(*) FROM call"\n')
    assert len(diags) == 1
    d = diags[0]
    assert d.code == "SARJ020"
    assert d.path == Path("call_store.py")
    assert "ClickHouse" in d.message
    assert "sarj-noqa: SARJ020" in d.message


# --------------------------------------------------------------------------- #
# Adversarial: Postgres-flavored SQL that overlaps with BigQuery vocabulary but
# is NOT a BQ signal (DATE_TRUNC excluded by docstring; DISTINCT ON is a
# Postgres-only extension) must STILL fire.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "q = \"SELECT DATE_TRUNC('day', ts), COUNT(*) FROM call GROUP BY 1\"\n",
            id="date-trunc-excluded-from-bq-signals",
        ),
        pytest.param(
            'q = "SELECT DISTINCT ON (org_id) * FROM call ORDER BY org_id, ts"\n',
            id="distinct-on-is-postgres-only",
        ),
    ],
)
def test_postgres_overlapping_vocab_still_fires(source: str) -> None:
    assert len(_check(source)) == 1


# --------------------------------------------------------------------------- #
# Adversarial: an aggregation keyword split across a `+` concatenation boundary
# (so neither literal half is a full keyword) must still fire once the BinOp is
# reconstructed. Also tab-separated GROUP/BY.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('q = "SELECT COUNT" + "(*) FROM call"\n', id="count-split-across-concat"),
        pytest.param('q = "SELECT s FROM call GROUP" + " BY s"\n', id="group-by-split-across-concat"),
        pytest.param('q = "SELECT s FROM call GROUP\\tBY s"\n', id="group-by-tab-separated"),
    ],
)
def test_keyword_split_or_tabbed_still_fires(source: str) -> None:
    assert len(_check(source)) == 1


# --------------------------------------------------------------------------- #
# Adversarial: BigQuery signals live only inside a stripped SQL comment. Comment
# stripping runs BEFORE the BQ-exemption check, so a comment-embedded backtick or
# BQ-only function must NOT smuggle a real Postgres aggregation past the rule.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'q = "SELECT COUNT(*) FROM call /* APPROX_COUNT_DISTINCT(x) */ WHERE org = 1"\n',
            id="bq-func-only-in-block-comment",
        ),
        pytest.param(
            'q = "SELECT COUNT(*) FROM call /* join `proj.ds` here */ WHERE org = 1"\n',
            id="backtick-only-in-block-comment",
        ),
    ],
)
def test_bq_signal_only_in_comment_does_not_exempt(source: str) -> None:
    assert len(_check(source)) == 1


# --------------------------------------------------------------------------- #
# BigQuery exemption, tightened: a backtick inside a Postgres string VALUE is    #
# masked (not read as a table quote), and a file-level BigQuery import no longer #
# exempts a query carrying a Postgres `%s` placeholder.                          #
# --------------------------------------------------------------------------- #


def test_backtick_inside_string_value_wrongly_exempts_postgres_query() -> None:
    src = "q = \"SELECT COUNT(*) FROM call WHERE note = 'imported from `legacy`'\"\n"
    assert len(_check(src)) == 1


def test_bigquery_import_file_with_real_postgres_query_is_over_broad() -> None:
    src = 'from google.cloud import bigquery\nq = "SELECT COUNT(*) FROM call WHERE org_id = %s GROUP BY status"\n'
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# First-party review regressions.                                               #
#                                                                               #
# `IS [NOT] DISTINCT FROM` is Postgres' null-safe comparison OPERATOR, and a     #
# `test_<x>_store.py` is a test, not a store module. Both classes were 100%      #
# suppressed at review head with no defect behind any of them.                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'q = "UPDATE t SET a = 1 WHERE org_id IS NOT DISTINCT FROM %s"\n',
            id="is-not-distinct-from",
        ),
        pytest.param(
            'q = "SELECT id FROM call WHERE org_id IS DISTINCT FROM %s"\n',
            id="is-distinct-from",
        ),
        pytest.param(
            'q = "SELECT id FROM call WHERE a IS   NOT\\n  DISTINCT   FROM b"\n',
            id="is-not-distinct-from-whitespace-split",
        ),
        pytest.param(
            'q = "select id from call where a is not distinct from b"\n',
            id="is-not-distinct-from-lowercase",
        ),
    ],
)
def test_null_safe_comparison_operator_is_not_aggregation(source: str) -> None:
    """`IS [NOT] DISTINCT FROM` is a per-row predicate that merely shares a keyword with `SELECT DISTINCT`.

    Evidence: one first-party store module that uses it as an upsert guard.
    """
    assert _check(source) == []


def test_provisioned_number_upsert_shape_is_clean() -> None:
    """The exact regression site: an ON CONFLICT upsert guarded by a null-safe comparison."""
    src = (
        'q = """\n'
        "    INSERT INTO provisioned_number (phone_number_id, organization_id)\n"
        "    VALUES (%s, %s)\n"
        "    ON CONFLICT (phone_number_id) DO UPDATE\n"
        "        SET updated_at = NOW()\n"
        "        WHERE provisioned_number.organization_id\n"
        "                IS NOT DISTINCT FROM EXCLUDED.organization_id\n"
        '"""\n'
    )
    assert _check(src) == []


def test_real_distinct_still_fires_alongside_a_null_safe_comparison() -> None:
    """Blanking the operator must not blind the rule to a genuine `SELECT DISTINCT` in the same query."""
    src = 'q = "SELECT DISTINCT org_id FROM call WHERE a IS NOT DISTINCT FROM b"\n'
    diags = _check(src)
    assert _labels(diags) == ["Store query uses DISTINCT"]


def test_count_still_fires_alongside_a_null_safe_comparison() -> None:
    src = 'q = "SELECT COUNT(*) FROM call WHERE org_id IS NOT DISTINCT FROM %s"\n'
    assert _labels(_check(src)) == ["Store query uses COUNT("]


@pytest.mark.parametrize(
    "filename",
    [
        pytest.param("tests/store/test_batch_order_store.py", id="test-prefixed-store-name"),
        pytest.param("tests/store/test_global_config_store.py", id="test-prefixed-store-name-2"),
        pytest.param("call_store_test.py", id="test-suffixed-store-name"),
        pytest.param("tests/helpers.py", id="under-tests-dir"),
        pytest.param("stores/conftest.py", id="conftest-under-stores"),
    ],
)
def test_test_files_are_not_store_modules(filename: str) -> None:
    """A COUNT(*) asserting over per-test fixture rows never runs on the OLTP primary.

    Evidence: three first-party sites — two in one store test module and one in
    another.
    """
    src = 'q = "SELECT COUNT(*) FROM batch_call WHERE batch_id = %s::uuid"\n'
    assert _check(src, filename=filename) == []


@pytest.mark.parametrize(
    "filename",
    [
        pytest.param("call_store.py", id="store-module"),
        pytest.param("stores/call_history_store.py", id="under-stores-dir"),
    ],
)
def test_production_store_modules_still_fire(filename: str) -> None:
    src = 'q = "SELECT COUNT(*) FROM batch_call WHERE batch_id = %s::uuid"\n'
    assert len(_check(src, filename=filename)) == 1
