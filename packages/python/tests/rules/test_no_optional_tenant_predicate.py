from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_optional_tenant_predicate import (
    NoOptionalTenantPredicate,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = NoOptionalTenantPredicate.public_examples()


def _check(source: str, name: str = "call_store.py") -> list[Diagnostic]:
    return NoOptionalTenantPredicate().check(Path(name), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = NoOptionalTenantPredicate().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


def _count(source: str) -> int:
    return len(_check(source))


# Positive: the tenant predicate is reachable only through a conditional.


def test_flags_conditional_tenant_predicate_with_tautology_fallback():
    src = (
        "def _build_filter_conditions(args):\n"
        "    where_conditions = []\n"
        "    params = []\n"
        "    if args.organization_ids:\n"
        '        where_conditions.append(SQL("organization_id = ANY(%s::uuid[])"))\n'
        "        params.append(list(args.organization_ids))\n"
        "    if args.status:\n"
        '        where_conditions.append(SQL("status = ANY(%s)"))\n'
        "        params.append(args.status)\n"
        '    where_clause = SQL(" AND ").join(where_conditions) if where_conditions else SQL("1=1")\n'
        "    return where_clause, params\n"
    )
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ056"
    assert "_build_filter_conditions" in diags[0].message


def test_flags_tautology_seeded_list():
    src = (
        "def as_sql_query(self):\n"
        '    clauses = [SQL("TRUE")]\n'
        "    if self.organization_id:\n"
        '        clauses.append(SQL("organization_id = {}").format(self.organization_id))\n'
        "    if self.provider:\n"
        '        clauses.append(SQL("provider = {}").format(self.provider))\n'
        '    return SQL(" AND ").join(clauses)\n'
    )
    assert _count(src) == 1


def test_flags_when_seed_is_a_non_tenant_predicate():
    src = (
        "def list_scenarios(args):\n"
        '    where_conditions = [SQL("s.deleted_at IS NULL")]\n'
        "    if args.organization_ids:\n"
        '        where_conditions.append(SQL("s.organization_id = ANY(%s::uuid[])"))\n'
        '    return SQL(" AND ").join(where_conditions)\n'
    )
    assert _count(src) == 1


def test_flags_qualified_column_and_alias():
    src = (
        "def build_where(filters):\n"
        "    conditions = []\n"
        "    if filters.organization_ids:\n"
        '        conditions.append(SQL("cf.organization_id = ANY(%s::uuid[])"))\n'
        '    return SQL(" AND ").join(conditions) if conditions else SQL("1=1")\n'
    )
    assert _count(src) == 1


def test_flags_ternary_guarded_tenant_predicate():
    src = (
        "def build(args):\n"
        "    conditions = []\n"
        '    conditions.append(SQL("organization_id = %s") if args.org else SQL("TRUE"))\n'
        '    return SQL(" AND ").join(conditions)\n'
    )
    assert _count(src) == 1


def test_flags_conditional_extend():
    src = (
        "def build(args):\n"
        "    conditions = []\n"
        "    if args.organization_id:\n"
        '        conditions.extend([SQL("organization_id = %s")])\n'
        "    return conditions\n"
    )
    assert _count(src) == 1


@pytest.mark.parametrize("operator", ["IN (%s)", "IS NOT NULL", "<> %s", "!= %s"])
def test_recognises_documented_predicate_operators(operator: str):
    src = (
        "def build(args):\n"
        "    conditions = []\n"
        "    if args.organization_id:\n"
        f'        conditions.append(SQL("organization_id {operator}"))\n'
        "    return conditions\n"
    )
    assert _count(src) == 1, operator


def test_flags_each_offending_function_separately():
    src = (
        "def first(args):\n"
        "    c = []\n"
        "    if args.organization_id:\n"
        '        c.append(SQL("organization_id = %s"))\n'
        "    return c\n"
        "\n"
        "def second(args):\n"
        "    c = []\n"
        "    if args.tenant_id:\n"
        '        c.append(SQL("tenant_id = %s"))\n'
        "    return c\n"
    )
    assert _count(src) == 2


def test_flags_async_method():
    src = (
        "class Store:\n"
        "    async def list_batches(self, args):\n"
        "        conds = []\n"
        "        if args.organization_ids:\n"
        '            conds.append(SQL("organization_id = ANY(%s::uuid[])"))\n'
        '        return SQL(" AND ").join(conds) if conds else SQL("1=1")\n'
    )
    assert _count(src) == 1


@pytest.mark.parametrize("column", ["org_id", "tenant_id", "account_id", "workspace_id"])
def test_recognises_alternate_tenant_column_names(column: str):
    src = (
        "def build(args):\n"
        "    c = []\n"
        "    if args.scope:\n"
        f'        c.append(SQL("{column} = %s"))\n'
        '    return SQL(" AND ").join(c)\n'
    )
    assert _count(src) == 1, column


# Negative: scoping that always applies, or code that is not scoping at all.


def test_ignores_unconditional_seed():
    src = (
        "def list_profiles(args):\n"
        '    conditions = [SQL("organization_id = %s")]\n'
        "    params = [args.organization_id]\n"
        "    if args.language:\n"
        '        conditions.append(SQL("language = %s"))\n'
        "        params.append(args.language)\n"
        '    return SQL(" AND ").join(conditions), params\n'
    )
    assert _count(src) == 0


def test_ignores_unconditional_append():
    src = (
        "def build(args):\n"
        "    c = []\n"
        '    c.append(SQL("organization_id = %s"))\n'
        "    if args.status:\n"
        '        c.append(SQL("status = %s"))\n'
        '    return SQL(" AND ").join(c)\n'
    )
    assert _count(src) == 0


def test_ignores_unconditional_extend():
    src = (
        "def build(args):\n"
        "    conditions = []\n"
        '    conditions.extend([SQL("organization_id = %s")])\n'
        "    return conditions\n"
    )
    assert _count(src) == 0


def test_ignores_query_with_no_tenant_predicate_at_all():
    src = (
        "def list_all_assignments(direction):\n"
        '    clauses = [SQL("TRUE")]\n'
        "    if direction:\n"
        '        clauses.append(SQL("direction = %s"))\n'
        '    return SQL(" AND ").join(clauses)\n'
    )
    assert _count(src) == 0


def test_ignores_mixed_function_with_one_unconditional_predicate():
    src = (
        "def build(args):\n"
        '    c = [SQL("organization_id = %s")]\n'
        "    if args.extra_orgs:\n"
        '        c.append(SQL("organization_id = ANY(%s::uuid[])"))\n'
        '    return SQL(" AND ").join(c)\n'
    )
    assert _count(src) == 0


def test_ignores_inline_sql_not_composed_into_a_list():
    src = (
        "async def get(self, org_id, provider):\n"
        "    await conn.execute(\n"
        '        "SELECT id FROM credential WHERE organization_id = %s AND provider = %s",\n'
        "        (org_id, provider),\n"
        "    )\n"
    )
    assert _count(src) == 0


def test_inline_sql_does_not_mask_an_optional_composed_predicate():
    src = (
        "def build(args):\n"
        '    execute("SELECT 1 WHERE organization_id = %s", args.organization_id)\n'
        "    conditions = []\n"
        "    if args.organization_id:\n"
        '        conditions.append(SQL("organization_id = %s"))\n'
        "    return conditions\n"
    )
    assert _count(src) == 1


def test_nested_function_predicate_does_not_mask_outer_scope():
    src = (
        "def outer(args):\n"
        "    conditions = []\n"
        "    if args.organization_id:\n"
        '        conditions.append(SQL("organization_id = %s"))\n'
        "    def inner():\n"
        '        return [SQL("tenant_id = %s")]\n'
        "    return conditions, inner()\n"
    )
    diags = _check(src)
    assert len(diags) == 1
    assert "`outer`" in diags[0].message


def test_ignores_tenant_column_in_a_select_list():
    src = (
        "def build(args):\n"
        "    fields = []\n"
        "    if args.include_org:\n"
        '        fields.append(SQL("id, organization_id, created_at"))\n'
        '    return SQL(", ").join(fields)\n'
    )
    assert _count(src) == 0


def test_ignores_test_files():
    src = (
        "def build(args):\n"
        "    c = []\n"
        "    if args.organization_ids:\n"
        '        c.append(SQL("organization_id = %s"))\n'
        "    return c\n"
    )
    assert len(_check(src, "tests/test_call_store.py")) == 0


def test_ignores_syntax_error():
    assert len(_check("def broken(:\n")) == 0


def test_ignores_empty_source():
    assert _count("") == 0


def test_recognises_uppercase_tenant_column() -> None:
    src = """
def build(args):
    conditions = []
    if args.organization_id:
        conditions.append(SQL("ORGANIZATION_ID = %s"))
    return conditions
"""
    assert _count(src) == 1


@pytest.mark.parametrize(
    "fragment",
    [
        'errors.append("account_id is required")',
        'updates.append("organization_id = replacement")',
        'notes.append("tenant_id in request metadata")',
    ],
)
def test_ignores_tenant_words_that_are_not_sql_predicates(fragment: str) -> None:
    src = f"def build(args):\n    if args.scope:\n        {fragment}\n"
    assert _count(src) == 0


def test_ignores_conditional_tenant_clause_when_else_raises():
    src = """
def build(tenant_id):
    conditions = []
    if tenant_id:
        conditions.append(SQL("tenant_id = %s"))
    else:
        raise ValueError("tenant required")
    return SQL(" AND ").join(conditions)
"""
    assert _count(src) == 0


def test_still_flags_when_else_only_conditionally_raises():
    src = """
def build(tenant_id, strict):
    conditions = []
    if tenant_id:
        conditions.append(SQL("tenant_id = %s"))
    elif strict:
        raise ValueError("tenant required")
    return SQL(" AND ").join(conditions)
"""
    assert _count(src) == 1
