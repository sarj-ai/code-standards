"""Exhaustive suite for SARJ019 / no-query-with-many-joins.

Verified against the implementation:
  * threshold `_MAX_JOINS = 2` -> a query is flagged only when it contains
    **3 or more** `JOIN` keywords. The boundary is exact: 2 JOINs is clean,
    3 JOINs fires (`test_join_count_boundary`).
  * every qualified form (`LEFT/RIGHT/INNER/FULL/CROSS ... JOIN`) contributes
    exactly one to the count — only the bare word `JOIN` is matched.
  * `--` and `/* */` SQL comments are stripped before counting and before the
    query-shape check.
  * a string is only considered when it *looks* like a query: `SELECT ... FROM`,
    `UPDATE ... SET`, or `DELETE FROM`.
  * `str.join(...)`, prose, and substrings like `adjoining` never fire.

Known limitation exercised below (not a bug — deterministic by design): an
f-string only fires when the whole `SELECT ... FROM ... JOIN ...` shape lives in
a single literal segment. An interpolation placed *between* the `FROM` and the
`JOIN`s splits the literal so no single segment has both the shape and the joins
(`test_fstring_interpolation_between_from_and_joins_not_flagged`).
"""

from pathlib import Path

import pytest

from sarj_python_lint.rule_base import Diagnostic, is_suppressed
from sarj_python_lint.rules.no_query_with_many_joins import NoQueryWithManyJoins


def _check(source: str) -> list[Diagnostic]:
    return NoQueryWithManyJoins().check(Path("foo_store.py"), source)


def _sql_with_joins(n: int, join_kw: str = "JOIN") -> str:
    """Build a one-line assignment whose query has exactly `n` `join_kw` clauses.

    Returns:
        The assignment source.

    """
    clauses = " ".join(f"{join_kw} t{i} ON t{i}.id = base.id" for i in range(n))
    return 'q = "SELECT * FROM base ' + clauses + '"'  # ruff:ignore[hardcoded-sql-expression] — synthetic lint-rule fixture, not a real query


# --------------------------------------------------------------------------- #
# Boundary: the whole point of the rule.                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("n", "expected_diags"),
    [(0, 0), (1, 0), (2, 0), (3, 1), (4, 1), (5, 1), (6, 1), (10, 1)],
)
def test_join_count_boundary(n: int, expected_diags: int) -> None:
    diags = _check(_sql_with_joins(n))
    assert len(diags) == expected_diags


def test_exactly_threshold_minus_one_is_clean() -> None:
    assert _check(_sql_with_joins(2)) == []


def test_exactly_threshold_fires() -> None:
    assert len(_check(_sql_with_joins(3))) == 1


@pytest.mark.parametrize("n", [3, 4, 5, 7, 12])
def test_message_reports_actual_count(n: int) -> None:
    diags = _check(_sql_with_joins(n))
    assert len(diags) == 1
    assert f"Query has {n} JOINs (max 2)" in diags[0].message


# --------------------------------------------------------------------------- #
# Positive: qualified JOIN variants each count once.                          #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "join_kw",
    [
        "JOIN",
        "INNER JOIN",
        "LEFT JOIN",
        "RIGHT JOIN",
        "FULL JOIN",
        "CROSS JOIN",
        "LEFT OUTER JOIN",
        "RIGHT OUTER JOIN",
        "FULL OUTER JOIN",
    ],
)
def test_each_join_variant_counts_once(join_kw: str) -> None:
    diags = _check(_sql_with_joins(3, join_kw))
    assert len(diags) == 1
    assert "3 JOINs" in diags[0].message


def test_mixed_join_variants_all_counted() -> None:
    src = '''q = """
    SELECT *
    FROM a
    LEFT JOIN b ON TRUE
    RIGHT JOIN c ON TRUE
    INNER JOIN d ON TRUE
    FULL OUTER JOIN e ON TRUE
    CROSS JOIN f ON TRUE
    """'''
    diags = _check(src)
    assert len(diags) == 1
    assert "5 JOINs" in diags[0].message


def test_two_qualified_joins_stays_clean() -> None:
    src = '''q = """
    SELECT * FROM a
    LEFT JOIN b ON TRUE
    CROSS JOIN c ON TRUE
    """'''
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Positive: case-insensitivity.                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "src",
    [
        'q = "select * from a join b on 1 join c on 1 join d on 1"',
        'q = "SELECT * FROM A JOIN B ON 1 JOIN C ON 1 JOIN D ON 1"',
        'q = "SeLeCt * FrOm a JoIn b on 1 jOiN c on 1 JOin d on 1"',
    ],
)
def test_case_insensitive_keywords(src: str) -> None:
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Positive: multiline, concatenation, query shapes.                           #
# --------------------------------------------------------------------------- #


def test_multiline_triple_quoted() -> None:
    src = '''q = """
SELECT *
FROM call c
JOIN user u ON u.id = c.user_id
JOIN organization o ON o.id = c.org_id
JOIN scenario s ON s.id = c.scenario_id
"""'''
    diags = _check(src)
    assert len(diags) == 1
    assert "3 JOINs" in diags[0].message


def test_plus_concatenated_query() -> None:
    src = 'q = ("SELECT * FROM a "\n     + "JOIN b ON 1 "\n     + "JOIN c ON 1 "\n     + "JOIN d ON 1")'
    assert len(_check(src)) == 1


def test_implicit_adjacent_concatenation() -> None:
    src = """q = (
    "SELECT * FROM a "
    "JOIN b ON TRUE "
    "JOIN c ON TRUE "
    "JOIN d ON TRUE"
)"""
    assert len(_check(src)) == 1


def test_plus_concatenation_below_threshold_is_clean() -> None:
    src = 'q = "SELECT * FROM a " + "JOIN b ON 1 " + "JOIN c ON 1"'
    assert _check(src) == []


def test_update_set_query_shape() -> None:
    src = 'q = "UPDATE a SET x = 1 FROM b JOIN c ON 1 JOIN d ON 1 JOIN e ON 1"'
    diags = _check(src)
    assert len(diags) == 1
    assert "3 JOINs" in diags[0].message


def test_delete_from_query_shape() -> None:
    src = 'q = "DELETE FROM a USING b JOIN c ON 1 JOIN d ON 1 JOIN e ON 1"'
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Positive: f-strings (when the shape lives in one literal segment).          #
# --------------------------------------------------------------------------- #


def test_fstring_without_interpolation_fires() -> None:
    src = 'q = f"SELECT * FROM a JOIN b ON 1 JOIN c ON 1 JOIN d ON 1"'
    assert len(_check(src)) == 1


def test_fstring_interpolation_after_joins_fires() -> None:
    src = 'q = f"SELECT * FROM a JOIN b ON 1 JOIN c ON 1 JOIN d ON 1 WHERE x = {y}"'
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Positive: multiple queries in one file -> sorted diagnostics.               #
# --------------------------------------------------------------------------- #


def test_multiple_queries_each_flagged_and_sorted() -> None:
    src = (
        'a = "SELECT * FROM t1 JOIN x ON 1 JOIN y ON 1 JOIN z ON 1"\n'
        'clean = "SELECT * FROM t2 JOIN x ON 1"\n'
        'b = "SELECT * FROM t3 JOIN x ON 1 JOIN y ON 1 JOIN z ON 1"'
    )
    diags = _check(src)
    assert [(d.line, d.col) for d in diags] == [(1, 5), (3, 5)]
    assert all(d.code == "SARJ019" for d in diags)


# --------------------------------------------------------------------------- #
# Line / column reporting.                                                    #
# --------------------------------------------------------------------------- #


def test_single_line_position() -> None:
    src = 'q = "SELECT * FROM a JOIN b ON 1 JOIN c ON 1 JOIN d ON 1"'
    (diag,) = _check(src)
    assert (diag.line, diag.col) == (1, 5)


def test_multiline_position_is_opening_quote_line() -> None:
    src = 'x = 1\ny = 2\nq = """\nSELECT * FROM a\nJOIN b ON 1\nJOIN c ON 1\nJOIN d ON 1\n"""'
    (diag,) = _check(src)
    assert (diag.line, diag.col) == (3, 5)


def test_diagnostic_field_integrity() -> None:
    src = 'q = "SELECT * FROM a JOIN b ON 1 JOIN c ON 1 JOIN d ON 1"'
    (diag,) = _check(src)
    assert diag.path == Path("foo_store.py")
    assert diag.code == "SARJ019"
    assert diag.line == 1
    assert diag.col == 5
    assert "split it" in diag.message


# --------------------------------------------------------------------------- #
# Negative: JOINs hidden in SQL comments never push over the threshold.       #
# --------------------------------------------------------------------------- #


def test_join_in_line_comment_ignored() -> None:
    src = '''q = """
SELECT * FROM a
JOIN b ON TRUE
JOIN c ON TRUE
-- JOIN d ON TRUE  (removed)
"""'''
    assert _check(src) == []


def test_join_in_block_comment_ignored() -> None:
    src = '''q = """
SELECT * FROM a
JOIN b ON TRUE
JOIN c ON TRUE
/* JOIN d ON TRUE */
"""'''
    assert _check(src) == []


def test_two_real_joins_plus_comment_join_is_clean() -> None:
    src = 'q = """SELECT * FROM a JOIN b ON 1 JOIN c ON 1 -- JOIN d ON 1\n"""'
    assert _check(src) == []


def test_three_real_plus_comment_still_fires() -> None:
    src = 'q = """SELECT * FROM a JOIN b ON 1 JOIN c ON 1 JOIN d ON 1 /* JOIN e ON 1 */\n"""'
    assert len(_check(src)) == 1


def test_query_entirely_inside_comment_is_clean() -> None:
    src = 'q = """\n-- SELECT * FROM a JOIN b JOIN c JOIN d\nSELECT 1\n"""'
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: no query shape -> never considered.                               #
# --------------------------------------------------------------------------- #


def test_prose_with_join_words_not_flagged() -> None:
    src = 'msg = "please JOIN the call. JOIN now. JOIN us. JOIN in."'
    assert _check(src) == []


def test_select_without_from_not_flagged() -> None:
    src = 'q = "SELECT 1 JOIN JOIN JOIN JOIN"'
    assert _check(src) == []


def test_from_without_select_not_flagged() -> None:
    src = 'note = "notes FROM the team JOIN x JOIN y JOIN z"'
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: false-positive guards for the Python str.join method.             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "src",
    [
        'x = ",".join(parts)',
        'x = "\\n".join(clauses)',
        'x = " JOIN ".join(tables)',
        'sql = " AND ".join(["a JOIN b", "c JOIN d", "e JOIN f"])',
    ],
)
def test_str_join_method_not_flagged(src: str) -> None:
    assert _check(src) == []


def test_join_separator_building_a_query_without_shape_is_clean() -> None:
    # The separator literal " JOIN " has no SELECT/FROM shape, so even though
    # it reads like a join it is never considered.
    src = 'clause = " JOIN ".join(rels)'
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: substrings that merely contain "join".                           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "word",
    ["adjoining", "enjoying", "rejoining", "disjoint", "conjoined"],
)
def test_join_substrings_do_not_match(word: str) -> None:
    src = 'q = "SELECT ' + word + ' FROM a WHERE b = 1 AND c = 2 AND d = 3"'  # ruff:ignore[hardcoded-sql-expression] — synthetic lint-rule fixture, not a real query
    assert _check(src) == []


def test_join_substrings_do_not_inflate_real_count() -> None:
    # Two real JOINs plus three "join" substrings must stay clean (count == 2).
    src = 'q = "SELECT * FROM a JOIN b ON 1 JOIN c ON 1 WHERE note = %s AND adjoining AND enjoying AND rejoined"'
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: f-string interpolation splits the shape from the joins.           #
# --------------------------------------------------------------------------- #


def test_fstring_interpolation_between_from_and_joins_not_flagged() -> None:
    src = 'q = f"SELECT * FROM {table} JOIN b ON 1 JOIN c ON 1 JOIN d ON 1"'
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: non-string / non-query constants.                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "src",
    [
        "n = 3",
        "flag = True",
        "vals = [1, 2, 3]",
        "ratio = 3.14",
        'empty = ""',
    ],
)
def test_non_query_constants_not_flagged(src: str) -> None:
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Edge: empty / whitespace / broken sources.                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("src", ["", "   ", "\n\n", "# just a comment\n"])
def test_empty_or_trivial_source(src: str) -> None:
    assert _check(src) == []


def test_syntax_error_returns_empty() -> None:
    assert _check("def (:::") == []


def test_syntax_error_with_query_text_returns_empty() -> None:
    src = 'q = "SELECT * FROM a JOIN b JOIN c JOIN d"\ndef (:::'
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Suppression via `# sarj-noqa: SARJ019`.                                     #
# --------------------------------------------------------------------------- #


def test_rule_still_emits_under_suppression_comment() -> None:
    # The rule itself does not consume the noqa; is_suppressed does.
    src = (
        'q = "SELECT * FROM a JOIN b ON 1 JOIN c ON 1 JOIN d ON 1"  # sarj-noqa: SARJ019 — reporting view, intentional'
    )
    diags = _check(src)
    assert len(diags) == 1
    assert is_suppressed(src.splitlines(), diags[0].line, diags[0].code)


def test_bare_sarj_noqa_suppresses() -> None:
    src = 'q = "SELECT * FROM a JOIN b ON 1 JOIN c ON 1 JOIN d ON 1"  # sarj-noqa'
    (diag,) = _check(src)
    assert is_suppressed(src.splitlines(), diag.line, diag.code)


def test_unrelated_noqa_code_does_not_suppress() -> None:
    src = 'q = "SELECT * FROM a JOIN b ON 1 JOIN c ON 1 JOIN d ON 1"  # sarj-noqa: SARJ001 — different code'
    (diag,) = _check(src)
    assert not is_suppressed(src.splitlines(), diag.line, diag.code)


# --------------------------------------------------------------------------- #
# Adversarial: further qualified JOIN variants each count exactly once.        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "join_kw",
    ["NATURAL JOIN", "NATURAL LEFT JOIN", "LEFT JOIN LATERAL", "CROSS JOIN LATERAL"],
)
def test_natural_and_lateral_join_variants_count_once(join_kw: str) -> None:
    diags = _check(_sql_with_joins(3, join_kw))
    assert len(diags) == 1
    assert "3 JOINs" in diags[0].message


def test_qualified_join_split_across_newline_counts_once() -> None:
    src = '''q = """
    SELECT * FROM a
    LEFT
    JOIN b ON 1
    RIGHT
    JOIN c ON 1
    INNER
    JOIN d ON 1
    """'''
    diags = _check(src)
    assert len(diags) == 1
    assert "3 JOINs" in diags[0].message


# --------------------------------------------------------------------------- #
# Adversarial: implicit comma joins are intentionally NOT counted.            #
# --------------------------------------------------------------------------- #


def test_implicit_comma_join_not_counted() -> None:
    src = 'q = "SELECT * FROM a, b, c, d, e WHERE a.id = b.id AND c.id = d.id"'
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Adversarial: `.format()` template literal still carries shape + joins.       #
# --------------------------------------------------------------------------- #


def test_format_template_literal_still_fires() -> None:
    src = 'q = "SELECT * FROM {} JOIN b ON 1 JOIN c ON 1 JOIN d ON 1".format(t)'
    assert len(_check(src)) == 1


def test_str_join_receiver_with_query_shape_still_fires() -> None:
    src = 'x = "SELECT * FROM a JOIN b ON 1 JOIN c ON 1 JOIN d ON 1".join(parts)'
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Adversarial: the word JOIN split across `+` chunks is reconstructed.         #
# --------------------------------------------------------------------------- #


def test_join_word_split_across_plus_concat_is_reconstructed() -> None:
    src = 'q = "SELECT * FROM a JO" + "IN b JO" + "IN c JO" + "IN d ON 1"'
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Adversarial: underscore-prefixed identifiers containing "join" don't count.  #
# --------------------------------------------------------------------------- #


def test_underscore_prefixed_join_identifier_not_counted() -> None:
    src = 'q = "SELECT a.cross_join, b.left_join FROM a JOIN b ON 1 JOIN c ON 1"'
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Adversarial cases: string-literal `'join'` values and a `--` inside a quoted  #
# value no longer fool the JOIN count (masked before scanning). The remaining   #
# `+`-concatenated-variable split stays xfail — masking a single literal cannot #
# rejoin keywords spread across separate Constant segments.                     #
# --------------------------------------------------------------------------- #


def test_string_literal_join_values_false_positive() -> None:
    src = "q = \"SELECT x FROM a WHERE p = 'join' AND q = 'join' AND r = 'join'\""
    assert _check(src) == []


@pytest.mark.xfail(
    strict=True,
    reason="SARJ019 FN: a `+`-concatenated variable placed between the JOINs splits the literal so no single segment holds shape + 3 joins.",
)
def test_plus_concat_variable_between_joins_false_negative() -> None:
    src = 'q = "SELECT * FROM a JOIN b ON 1 " + mid + " JOIN c ON 1 JOIN d ON 1"'
    assert len(_check(src)) == 1


def test_double_dash_in_string_value_truncates_joins_false_negative() -> None:
    src = "q = \"SELECT * FROM a JOIN b ON x = '--' JOIN c ON 1 JOIN d ON 1\""
    assert len(_check(src)) == 1
