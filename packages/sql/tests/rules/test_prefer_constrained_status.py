from itertools import pairwise, product
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rule_base import DefaultLevel
from sarj_sql_lint.rules.prefer_constrained_status import PreferConstrainedStatus


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


_PATH = Path("supabase/migrations/001_job.sql")


def _check(source: str, path: Path = _PATH) -> list[Diagnostic]:
    return PreferConstrainedStatus().check(path, source)


@pytest.mark.parametrize(
    "example",
    PreferConstrainedStatus.public_examples(),
    ids=tuple(item.example_id for item in PreferConstrainedStatus.public_examples()),
)
def test_documented_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, Path(example.focus_file.path))) == example.expected_count


@pytest.mark.parametrize(
    "check",
    [
        "NOT confirmed OR requested",
        "NOT (confirmed AND requested)",
        "confirmed <> requested",
        "confirmed = requested",
        "confirmed IS TRUE AND requested IS FALSE OR confirmed IS FALSE",
    ],
)
def test_flags_proven_restrictions_between_required_flags(check: str) -> None:
    source = f"CREATE TABLE job (requested BOOLEAN NOT NULL, confirmed BOOLEAN NOT NULL, CHECK ({check}));"
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ129"
    assert findings[0].severity is DefaultLevel.WARNING
    assert "confirmed, requested" in findings[0].message


@pytest.mark.parametrize(
    "check",
    [
        "confirmed OR NOT confirmed OR requested",
        "confirmed AND NOT confirmed AND requested",
        "confirmed AND requested",
        "confirmed OR (requested AND NOT requested)",
        "confirmed IS NULL OR requested",
        "custom(confirmed, requested)",
        "requested = 1 OR confirmed",
    ],
)
def test_abstains_for_independent_tautological_impossible_or_unknown_checks(check: str) -> None:
    assert _check(f"CREATE TABLE job (requested BOOLEAN NOT NULL, confirmed BOOLEAN NOT NULL, CHECK ({check}));") == []


@pytest.mark.parametrize("nullable", ["requested BOOLEAN", "requested BOOLEAN NULL", "requested INTEGER NOT NULL"])
def test_unproven_boolean_domain_is_not_guessed(nullable: str) -> None:
    assert (
        _check(f"CREATE TABLE job ({nullable}, confirmed BOOLEAN NOT NULL, CHECK (NOT confirmed OR requested));") == []
    )


def test_explicitly_nullable_flags_are_not_treated_as_not_null() -> None:
    assert _check("CREATE TABLE t (a BOOLEAN NULL, b BOOLEAN NULL, CHECK (NOT a OR b));") == []


def test_quoted_columns_have_exact_case_and_diagnostics_have_source_offsets() -> None:
    source = '-- migrate:up\nSELECT 1;\nCREATE TABLE job (\n  "Request" BOOLEAN NOT NULL,\n  "confirm)ed" BOOLEAN NOT NULL,\n  CHECK (NOT "confirm)ed" OR "Request")\n);'
    (finding,) = _check(source)
    assert (finding.line, finding.col) == (4, 3)
    assert '"Request"' in finding.message


def test_interacting_checks_can_eliminate_dependence() -> None:
    assert _check("CREATE TABLE job (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b), CHECK (a));") == []


@pytest.mark.parametrize(
    ("checks", "expected"),
    [
        ("CHECK (NOT b OR a), CHECK (NOT c OR b)", {frozenset({"a", "b", "c"})}),
        ("CHECK (NOT b OR a), CHECK (NOT b OR a)", {frozenset({"a", "b"})}),
        ("CHECK (NOT b OR a), CHECK (NOT a OR b)", {frozenset({"a", "b"})}),
        ("CHECK (NOT b OR a), CHECK (NOT a OR b), CHECK (a)", set[frozenset[str]]()),
        ("CHECK ((NOT b OR a) AND (c OR NOT c))", {frozenset({"a", "b"})}),
        ("CHECK ((NOT b OR a) AND c)", {frozenset({"a", "b"})}),
        ("CHECK ((a AND b) OR (NOT a AND c))", {frozenset({"a", "b", "c"})}),
        ("CHECK ((a = b) AND (c = d))", {frozenset({"a", "b"}), frozenset({"c", "d"})}),
        ("CHECK ((a = b) AND (c <> d))", {frozenset({"a", "b"}), frozenset({"c", "d"})}),
        (
            "CHECK ((a = b) AND (c <> d) AND (a OR NOT a OR c))",
            {frozenset({"a", "b"}), frozenset({"c", "d"})},
        ),
        ("CHECK ((a <> b) <> c)", {frozenset({"a", "b", "c"})}),
        ("CHECK (NOT b OR a), CHECK (TRUE)", {frozenset({"a", "b"})}),
        ("CHECK (NOT b OR a), CHECK (FALSE)", set[frozenset[str]]()),
        ("CHECK (NOT b OR a), CHECK (c), CHECK (NOT c)", set[frozenset[str]]()),
        ("CHECK (NOT b OR a), CHECK (custom(a))", set[frozenset[str]]()),
        ("CHECK (NOT b OR a), CHECK (custom(c))", {frozenset({"a", "b"})}),
        ("CHECK (NOT b OR a), CHECK (custom())", set[frozenset[str]]()),
        ("CHECK (NOT b OR a), CHECK (job.a)", set[frozenset[str]]()),
    ],
)
def test_reports_only_jointly_dependent_factors(checks: str, expected: set[frozenset[str]]) -> None:
    columns = ", ".join(f"{name} BOOLEAN NOT NULL" for name in "abcd")
    findings = _check(f"CREATE TABLE job ({columns}, {checks});")
    actual = {_fields(finding) for finding in findings}
    assert actual == expected
    assert len(findings) == len(actual)


def _fields(finding: Diagnostic) -> frozenset[str]:
    return frozenset(finding.message.split("booleans ", 1)[1].split(". Review", 1)[0].split(", "))


@pytest.mark.parametrize("flags", range(2, 7))
def test_joint_state_relations_remain_bounded_to_six_fields(flags: int) -> None:
    names = "abcdef"[:flags]
    columns = ", ".join(f"{name} BOOLEAN NOT NULL" for name in names)
    checks = ", ".join(f"CHECK (NOT {right} OR {left})" for left, right in pairwise(names))
    (finding,) = _check(f"CREATE TABLE job ({columns}, {checks});")
    assert _fields(finding) == frozenset(names)


def test_excessive_connected_state_relations_abstain_without_partial_groups() -> None:
    names = "abcdefg"
    columns = ", ".join(f"{name} BOOLEAN NOT NULL" for name in names)
    checks = ", ".join(f"CHECK (NOT {right} OR {left})" for left, right in pairwise(names))
    assert _check(f"CREATE TABLE job ({columns}, {checks});") == []


def test_six_axes_keep_three_way_dependence_separate_from_a_pair_and_an_independent_flag() -> None:
    columns = ", ".join(f"{name} BOOLEAN NOT NULL" for name in "abcdef")
    findings = _check(f"CREATE TABLE job ({columns}, CHECK (((a <> b) <> c) AND (d = e) AND (f OR NOT f)));")
    assert {_fields(finding) for finding in findings} == {frozenset({"a", "b", "c"}), frozenset({"d", "e"})}


@pytest.mark.parametrize("extra", ["CHECK (a = c)", "CHECK (NOT c OR a)", "CHECK (NOT c OR b)"])
def test_unproven_flag_domains_poison_every_connected_check(extra: str) -> None:
    assert (
        _check(
            f"CREATE TABLE job (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, c BOOLEAN, CHECK (NOT b OR a), {extra}, CHECK (c));"
        )
        == []
    )


def test_duplicate_columns_do_not_establish_a_state_contract() -> None:
    assert (
        _check("CREATE TABLE job (a BOOLEAN NOT NULL, a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT b OR a));")
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        'CREATE TABLE job ("" BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT b OR ""));',
        'CREATE TABLE "" (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT b OR a));',
        'CREATE TABLE "".job (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT b OR a));',
        'CREATE TABLE job (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CONSTRAINT "" CHECK (NOT b OR a));',
    ],
    ids=["empty-column", "empty-table", "empty-schema", "empty-constraint"],
)
def test_empty_delimited_identifiers_do_not_establish_a_postgres_contract(source: str) -> None:
    assert _check(source) == []


def test_nonempty_quoted_space_identifiers_are_preserved() -> None:
    (finding,) = _check('CREATE TABLE " " (" " BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT b OR " "));')
    assert _fields(finding) == frozenset({'" "', "b"})


@pytest.mark.parametrize(
    "source",
    [
        "CREATE DOMAIN flag AS BOOLEAN; CREATE TABLE job (a flag NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT b OR a));",
        "CREATE TABLE job (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT b OR a::BOOLEAN));",
        "CREATE TABLE job (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT b OR a)) INHERITS (parent);",
        "CREATE TABLE job (a BOOLEAN GENERATED ALWAYS AS (TRUE) STORED NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT b OR a));",
        "CREATE TABLE job (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT b OR a OR NULL));",
        "CREATE TABLE job (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT b OR a), CHECK (NULL));",
        "ALTER TABLE job ADD CONSTRAINT lifecycle CHECK (NOT b OR a);",
        "UPDATE job SET a = TRUE, b = FALSE;",
    ],
)
def test_unsupported_types_writers_and_unknown_truth_values_do_not_prove_a_state_group(source: str) -> None:
    assert _check(source) == []


def test_required_bool_aliases_keep_postgres_identifier_normalization() -> None:
    (finding,) = _check(
        "CREATE TABLE job (REQUESTED BOOL NOT NULL, CONFIRMED BOOL NOT NULL, CHECK (NOT CONFIRMED OR REQUESTED));"
    )
    assert _fields(finding) == frozenset({"requested", "confirmed"})


def test_repeated_checks_within_the_budget_still_have_one_owner() -> None:
    checks = ", ".join("CHECK (NOT b OR a)" for _ in range(32))
    (finding,) = _check(f"CREATE TABLE job (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, {checks});")
    assert _fields(finding) == frozenset({"a", "b"})


def test_six_field_parity_at_both_check_and_node_limits_reports_once() -> None:
    predicate = "((((a <> b) <> c) <> d) <> e) <> f"
    columns = ", ".join(f"{name} BOOLEAN NOT NULL" for name in "abcdef")
    checks = ", ".join([f"CHECK ({predicate})"] * 24 + ["CHECK (TRUE)"] * 8)
    (finding,) = _check(f"CREATE TABLE job ({columns}, {checks});")
    assert _fields(finding) == frozenset("abcdef")


def test_inline_and_named_checks_share_the_same_column_relation() -> None:
    source = "CREATE TABLE job (a BOOLEAN NOT NULL CHECK (NOT b OR a), b BOOLEAN NOT NULL, CONSTRAINT together CHECK (NOT a OR b));"
    (finding,) = _check(source)
    assert _fields(finding) == frozenset({"a", "b"})


def test_factors_are_reported_at_their_own_first_column_in_source_order() -> None:
    source = "CREATE TABLE job (z BOOLEAN NOT NULL, a BOOLEAN NOT NULL, y BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK ((z = y) AND (a = b)));"
    findings = _check(source)
    assert [_fields(finding) for finding in findings] == [frozenset({"z", "y"}), frozenset({"a", "b"})]
    assert [finding.col for finding in findings] == [source.index("z BOOLEAN") + 1, source.index("a BOOLEAN") + 1]


@pytest.mark.parametrize(
    "checks",
    [", ".join("CHECK (NOT b OR a)" for _ in range(33)), "CHECK (" + " OR ".join("a = b" for _ in range(130)) + ")"],
    ids=["too-many-checks", "predicate-node-budget"],
)
def test_oversized_predicates_abstain_without_partial_findings(checks: str) -> None:
    assert _check(f"CREATE TABLE job (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, {checks});") == []


def _oracle_factors(states: set[tuple[bool, ...]], names: tuple[str, ...]) -> set[frozenset[str]]:
    if not states:
        return set()
    best: tuple[tuple[int, ...], ...] = ()
    for groups in _oracle_partitions(tuple(range(len(names)))):
        if len(groups) > len(best) and _oracle_reconstruction(states, groups, len(names)) == states:
            best = groups
    return {frozenset(names[index] for index in group) for group in best if len(group) > 1}


def _oracle_partitions(indices: tuple[int, ...]) -> Iterator[tuple[tuple[int, ...], ...]]:
    if not indices:
        yield ()
        return
    first, *rest = indices
    for groups in _oracle_partitions(tuple(rest)):
        yield ((first,), *groups)
        for index, group in enumerate(groups):
            yield (*groups[:index], (first, *group), *groups[index + 1 :])


def _oracle_reconstruction(
    states: set[tuple[bool, ...]], groups: tuple[tuple[int, ...], ...], width: int
) -> set[tuple[bool, ...]]:
    projections = [{tuple(row[index] for index in group) for row in states} for group in groups]
    reconstructed: set[tuple[bool, ...]] = set()
    for pieces in product(*projections):
        values = dict(
            pair for group, piece in zip(groups, pieces, strict=True) for pair in zip(group, piece, strict=True)
        )
        reconstructed.add(tuple(values[index] for index in range(width)))
    return reconstructed


def _relation_sql(states: set[tuple[bool, ...]], names: tuple[str, ...]) -> str:
    columns = ", ".join(f"{name} BOOLEAN NOT NULL" for name in names)
    clauses = [
        "(" + " AND ".join(name if value else f"NOT {name}" for name, value in zip(names, row, strict=True)) + ")"
        for row in sorted(states)
    ]
    predicate = " OR ".join(clauses) or "FALSE"
    return f"CREATE TABLE job ({columns}, CHECK ({predicate}));"


@pytest.mark.parametrize("width", [2, 3])
def test_every_small_boolean_relation_matches_an_independent_partition_oracle(width: int) -> None:
    names = tuple("abc"[:width])
    rows = tuple(product((False, True), repeat=width))
    for mask in range(1 << len(rows)):
        states = {row for index, row in enumerate(rows) if mask & (1 << index)}
        findings = _check(_relation_sql(states, names))
        assert {_fields(finding) for finding in findings} == _oracle_factors(states, names), mask
        assert len(findings) == len({_fields(finding) for finding in findings}), mask


@pytest.mark.parametrize(
    "source",
    [
        "-- CREATE TABLE t (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b));",
        "SELECT $$CREATE TABLE t (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b));$$;",
        "DO $$ BEGIN CREATE TABLE t (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b)); END $$;",
        "CREATE TABLE t (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b);",
    ],
)
def test_comments_literals_routines_and_malformed_input_are_inert(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path", ["queries/job.sql", "postgres/tests/migrations/job.sql", "mysql/migrations/job.sql", "supabase/schema.sql"]
)
def test_scope_exclusions(path: str) -> None:
    assert _check("CREATE TABLE t (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b));", Path(path)) == []


def test_unrelated_tables_and_string_predicates_do_not_prove_flag_dependence() -> None:
    source = "CREATE TABLE a (flag BOOLEAN NOT NULL); CREATE TABLE b (other BOOLEAN NOT NULL, CHECK (flag OR other));"
    assert _check(source) == []


def test_copy_input_cannot_manufacture_a_schema_contract() -> None:
    assert (
        _check(
            "COPY docs FROM STDIN;\nCREATE TABLE t (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b));\n\\.\n"
        )
        == []
    )
