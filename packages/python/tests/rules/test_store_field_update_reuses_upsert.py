from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.store_field_update_reuses_upsert import StoreFieldUpdateReusesUpsert


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _source(update: str, *, conflict: str = "name = EXCLUDED.name", fields: str = "id: str\n    name: str") -> str:
    return f"""from pydantic import BaseModel
class UserInput(BaseModel):
    {fields}
class UserStore:
    async def upsert(self, data: UserInput) -> User:
        await self.cursor.execute("INSERT INTO users (id, name) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET {conflict}", (data.id, data.name))
    async def set_name(self, id_: str, name: str) -> User:
        await self.cursor.execute({update!r}, (name, id_))
"""  # ruff: ignore[hardcoded-sql-expression] -- constructs synthetic linter input; no SQL is executed.


def _check(source: str) -> list[Diagnostic]:
    return StoreFieldUpdateReusesUpsert().check(Path("app/user_store.py"), source)


def test_flags_redundant_plain_field_assignment() -> None:
    findings = _check(_source("UPDATE users SET name = %s WHERE id = %s"))
    assert len(findings) == 1
    assert findings[0].code == "SARJ517"
    assert "missing-row" in findings[0].message


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE users SET name = %s WHERE id = %s RETURNING id, name",
        "UPDATE public.users SET name = %s WHERE id = %s",
        "UPDATE users SET name = %s, updated_at = NOW() WHERE id = %s",
        'UPDATE "users" SET "name" = %s WHERE "id" = %s',
    ],
)
def test_static_equivalent_assignment_shapes(sql: str) -> None:
    source = _source(sql)
    if "public.users" in sql:
        source = source.replace("INTO users", "INTO public.users")
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE other SET name = %s WHERE id = %s",
        "UPDATE private.users SET name = %s WHERE id = %s",
        "UPDATE users SET name = %s WHERE id = %s AND version = %s",
        "UPDATE users SET name = %s WHERE id = %s AND tenant_id = %s",
        "UPDATE users SET name = %s WHERE id = %s AND name IS DISTINCT FROM %s",
        "UPDATE users SET name = name || %s WHERE id = %s",
        "UPDATE users SET revision = revision + 1 WHERE id = %s",
        "UPDATE users SET name = COALESCE(%s, name) WHERE id = %s",
        "UPDATE users SET name = %s WHERE email = %s",
        "UPDATE users SET name = %s",
        "UPDATE users SET name = %s FROM audit WHERE users.id = audit.id",
        "WITH selected AS (SELECT id FROM users) UPDATE users SET name = %s WHERE id = %s",
        "UPDATE users SET name = %s WHERE id = %s; DELETE FROM audit",
        "SELECT 'UPDATE users SET name = %s WHERE id = %s'",
        "UPDATE users SET name = %s WHERE id = ANY(%s)",
        "UPDATE users SET name = %s WHERE id = %s OR admin = true",
    ],
)
def test_preserves_domain_operations_and_ambiguous_sql(sql: str) -> None:
    assert _check(_source(sql)) == []


@pytest.mark.parametrize(
    "conflict",
    [
        "name = COALESCE(EXCLUDED.name, users.name)",
        "name = upper(EXCLUDED.name)",
        "name = EXCLUDED.other",
        "other = EXCLUDED.other",
    ],
)
def test_requires_existing_upsert_to_update_the_same_field_directly(conflict: str) -> None:
    assert _check(_source("UPDATE users SET name = %s WHERE id = %s", conflict=conflict)) == []


def test_requires_field_in_existing_command() -> None:
    assert _check(_source("UPDATE users SET name = %s WHERE id = %s", fields="id: str")) == []


def test_does_not_diagnose_existing_delegation() -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s")
    source = (
        source[: source.index("    async def set_name")]
        + "    async def set_name(self, id_: str, name: str) -> User:\n        return await self.upsert(UserInput(id=id_, name=name))\n"
    )
    assert _check(source) == []


def test_generated_and_test_modules_are_excluded() -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s")
    assert _check("# @generated\n" + source) == []
    assert StoreFieldUpdateReusesUpsert().check(Path("tests/test_user_store.py"), source) == []


def test_native_examples() -> None:
    verify_native_rule(StoreFieldUpdateReusesUpsert, analyze)


def test_quoted_case_sensitive_tables_do_not_collapse() -> None:
    source = _source('UPDATE "Users" SET name = %s WHERE id = %s').replace("INTO users", "INTO Users")
    assert _check(source) == []


def test_quoted_case_sensitive_columns_do_not_collapse() -> None:
    assert _check(_source('UPDATE users SET "Name" = %s WHERE id = %s')) == []


def test_exact_suppression_preserves_intentional_update_only_contract() -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace(
        "async def set_name(self, id_: str, name: str) -> User:",
        "async def set_name(self, id_: str, name: str) -> User:  # sarj-noqa: SARJ517 -- missing rows must fail instead of inserting",
    )
    assert _check(source) == []


def test_definition_time_sql_is_not_a_method_body_write() -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s")
    definition = """    async def set_name(
        self,
        id_: str,
        name: str = load_default(cursor.execute('UPDATE users SET name = %s WHERE id = %s', ('initial', 'target'))),
    ) -> User:
        return User(id=id_, name=name)
"""
    source = source[: source.index("    async def set_name")] + definition
    assert _check(source) == []


def test_malformed_source_does_not_crash() -> None:
    assert _check("class UserStore(:") == []


def test_distinct_result_contract_is_preserved() -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace(
        "set_name(self, id_: str, name: str) -> User", "set_name(self, id_: str, name: str) -> User | None"
    )
    assert _check(source) == []


def test_conditional_upsert_has_distinct_write_semantics() -> None:
    source = _source(
        "UPDATE users SET name = %s WHERE id = %s",
        conflict="name = EXCLUDED.name WHERE users.version = EXCLUDED.version",
    )
    assert _check(source) == []
