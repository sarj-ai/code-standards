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
    if "RETURNING" in sql:
        source = source.replace('name = EXCLUDED.name"', 'name = EXCLUDED.name RETURNING id, name"')
    if "updated_at" in sql:
        source = source.replace('name = EXCLUDED.name"', 'name = EXCLUDED.name, updated_at = NOW()"')
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


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("(id, name) VALUES (%s, %s)", "(id) VALUES (%s)"),
        ("VALUES (%s, %s)", "SELECT %s, %s"),
        ("VALUES (%s, %s)", "VALUES (%s, upper(%s))"),
        ("VALUES (%s, %s)", "VALUES (%s, DEFAULT)"),
        ("(data.id, data.name)", "(data.id, 'constant')"),
        ("(data.id, data.name)", "(data.id, data.name.upper())"),
        ("(data.id, data.name)", "(data.name, data.id)"),
        ("(data.id, data.name)", "data.model_dump()"),
        ("(data.id, data.name)", "(data.id, other.name)"),
        ("(data.id, data.name)", "(data.id, data.name, data.id)"),
    ],
)
def test_requires_command_fields_to_supply_inserted_values_directly(before: str, after: str) -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace(before, after)
    assert _check(source) == []


@pytest.mark.parametrize(
    ("placeholders", "bindings", "expected"),
    [
        pytest.param("VALUES (%(key)s, %(value)s)", "{'value': data.name, 'key': data.id}", 1, id="lowercase-names"),
        pytest.param("VALUES (%(Key)s, %(Value)s)", "{'Value': data.name, 'Key': data.id}", 1, id="uppercase-names"),
        pytest.param(
            "VALUES (%(key)s, %(value)s)", "{'Value': data.name, 'Key': data.id}", 0, id="uppercase-keys-mismatch"
        ),
        pytest.param(
            "VALUES (%(Key)s, %(Value)s)", "{'value': data.name, 'key': data.id}", 0, id="lowercase-keys-mismatch"
        ),
    ],
)
def test_named_parameters_prove_command_to_column_bindings(placeholders: str, bindings: str, expected: int) -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace("VALUES (%s, %s)", placeholders)
    source = source.replace("(data.id, data.name)", bindings)
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    "bindings",
    [
        "{'key': data.id, 'value': data.name.upper()}",
        "{'key': data.id, 'value': data.id}",
        "{'key': data.id, 'missing': data.name}",
        "{'key': data.id, 'value': data.name, 'value': other.name}",
        "{**data.model_dump()}",
    ],
)
def test_ambiguous_named_command_bindings_are_excluded(bindings: str) -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace(
        "VALUES (%s, %s)", "VALUES (%(key)s, %(value)s)"
    )
    assert _check(source.replace("(data.id, data.name)", bindings)) == []


def test_keyword_params_and_list_bindings_are_supported() -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace(
        ", (data.id, data.name))", ", params=[data.id, data.name])"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize("method", ["upsert", "set_name"])
@pytest.mark.parametrize("guard", ["if allowed():", "try:", "for attempt in attempts:", "while allowed():"])
def test_python_guarded_writes_have_distinct_contracts(method: str, guard: str) -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s")
    lines = source.splitlines()
    start = next(index for index, line in enumerate(lines) if f"async def {method}(" in line)
    lines[start + 1] = "        " + guard + "\n    " + lines[start + 1]
    if guard == "try:":
        lines[start + 1] += "\n        except MissingRow:\n            return None"
    assert _check("\n".join(lines)) == []


@pytest.mark.parametrize("method", ["upsert", "set_name"])
def test_decorated_writes_preserve_distinct_contracts(method: str) -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace(
        f"    async def {method}(", f"    @authorize\n    async def {method}("
    )
    assert _check(source) == []


def test_known_override_decorator_does_not_hide_duplicate_write() -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace(
        "    async def ", "    @override\n    async def "
    )
    source = "from typing import override\n" + source
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "conflict", ["name = EXCLUDED.name, revision = users.revision + 1", "name = EXCLUDED.name, other = %s"]
)
def test_upsert_with_additional_write_policy_is_excluded(conflict: str) -> None:
    assert _check(_source("UPDATE users SET name = %s WHERE id = %s", conflict=conflict)) == []


def test_update_only_table_scope_is_preserved() -> None:
    assert _check(_source("UPDATE ONLY users SET name = %s WHERE id = %s")) == []


def test_distinct_async_contract_is_preserved() -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace("async def set_name", "def set_name")
    source = source.replace("        await self.cursor.execute('UPDATE", "        self.cursor.execute('UPDATE")
    assert _check(source) == []


def test_python_transformed_setter_value_has_distinct_policy() -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace("(name, id_)", "(name.upper(), id_)")
    assert _check(source) == []


def test_composite_tenant_conflict_key_is_supported_without_dropping_scope() -> None:
    source = _source(
        "UPDATE users SET name = %s WHERE tenant_id = %s AND id = %s",
        fields="id: str\n    name: str\n    tenant_id: str",
    )
    source = source.replace("(id, name) VALUES (%s, %s)", "(tenant_id, id, name) VALUES (%s, %s, %s)")
    source = source.replace("ON CONFLICT (id)", "ON CONFLICT (tenant_id, id)")
    source = source.replace("(data.id, data.name)", "(data.tenant_id, data.id, data.name)")
    source = source.replace("id_: str, name: str", "id_: str, name: str, tenant_id: str")
    source = source.replace("(name, id_)", "(name, tenant_id, id_)")
    assert len(_check(source)) == 1


@pytest.mark.parametrize("annotation", ["ClassVar[str]", "'ClassVar[str]'"])
def test_class_variables_do_not_prove_writable_command_fields(annotation: str) -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s", fields=f"id: str\n    name: {annotation}")
    source = "from typing import ClassVar\n" + source
    assert _check(source) == []


@pytest.mark.parametrize("mutation", ["data = other", "data.name = 'constant'"])
def test_command_rebinding_or_mutation_is_not_direct_input(mutation: str) -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace(
        '        await self.cursor.execute("INSERT', f'        {mutation}\n        await self.cursor.execute("INSERT'
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    ("update", "conflict"),
    [
        ("UPDATE users SET name = %s, updated_at = NOW() WHERE id = %s", "name = EXCLUDED.name"),
        ("UPDATE users SET name = %s WHERE id = %s", "name = EXCLUDED.name, updated_at = NOW()"),
    ],
)
def test_distinct_timestamp_policy_is_preserved(update: str, conflict: str) -> None:
    assert _check(_source(update, conflict=conflict)) == []


@pytest.mark.parametrize("returning", ["id", "name, id", "name AS value", "*"])
def test_distinct_returning_projection_is_preserved(returning: str) -> None:
    source = _source(f"UPDATE users SET name = %s WHERE id = %s RETURNING {returning}")  # ruff: ignore[hardcoded-sql-expression] -- synthetic SQL input is parsed by the rule, never executed.
    source = source.replace('name = EXCLUDED.name"', 'name = EXCLUDED.name RETURNING id, name"')
    assert _check(source) == []


def test_nested_helper_guards_do_not_change_the_executed_write() -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace(
        "    async def set_name(self, id_: str, name: str) -> User:\n",
        "    async def set_name(self, id_: str, name: str) -> User:\n        def unused_helper():\n            if ignored():\n                return None\n",
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "guarded_execute",
    [
        "allowed() and await self.cursor.execute('UPDATE users SET name = %s WHERE id = %s', (name, id_))",
        "allowed() or await self.cursor.execute('UPDATE users SET name = %s WHERE id = %s', (name, id_))",
        "[await self.cursor.execute('UPDATE users SET name = %s WHERE id = %s', (name, id_)) for allowed in permissions if allowed]",
    ],
)
def test_short_circuit_and_comprehension_guards_are_preserved(guarded_execute: str) -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s")
    source = source[: source.index("    async def set_name")] + (
        "    async def set_name(self, id_: str, name: str) -> User:\n        " + guarded_execute + "\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "extra",
    [
        "    @property\n    def name(self):\n        return 'fixed'\n",
        "    name = property(lambda self: 'fixed')\n",
        "    name: str = property(lambda self: 'fixed')\n",
        "    name = 'fixed'\n",
        "    if enabled:\n        name = property(lambda self: 'fixed')\n",
        "    name: int\n",
    ],
)
def test_annotation_shadowed_by_class_scope_does_not_prove_a_writable_field(extra: str) -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s").replace(
        "class UserInput(BaseModel):", "class UserInput:"
    )
    source = source.replace("class UserStore:", f"{extra}class UserStore:")
    assert _check(source) == []


@pytest.mark.parametrize("owner", ["UserInput(BaseModel)", "UserStore"])
def test_explicit_class_keywords_cannot_prove_the_write_contract(owner: str) -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s")
    target = (
        "UserInput(BaseModel, metaclass=ChangingMeta)" if "BaseModel" in owner else "UserStore(metaclass=ChangingMeta)"
    )
    source = source.replace(f"class {owner}:", f"class {target}:")
    metaclass = (
        "class ChangingMeta(type):\n"
        "    def __new__(cls, name, bases, namespace):\n"
        "        namespace['name'] = property(lambda self: 'fixed')\n"
        "        return super().__new__(cls, name, bases, namespace)\n"
    )
    source = f"{metaclass}{source}"
    assert _check(source) == []


def test_literal_field_default_is_still_a_command_field() -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s", fields="id: str\n    name: str = 'initial'")
    assert len(_check(source)) == 1


def test_annotated_descriptor_value_is_not_a_writable_field() -> None:
    source = _source(
        "UPDATE users SET name = %s WHERE id = %s", fields="id: str\n    name: str = property(lambda self: 'fixed')"
    )
    assert _check(source) == []


@pytest.mark.parametrize("descriptor", ["property", "classmethod", "staticmethod"])
@pytest.mark.parametrize(
    ("declaration_template", "factory_template"),
    [
        pytest.param("import builtins", "builtins.{descriptor}", id="qualified"),
        pytest.param("import builtins as runtime", "runtime.{descriptor}", id="module-alias"),
        pytest.param("from builtins import {descriptor} as readonly", "readonly", id="member-alias"),
    ],
)
def test_import_proven_builtin_descriptor_defaults_are_not_writable_fields(
    descriptor: str, declaration_template: str, factory_template: str
) -> None:
    declaration = declaration_template.replace("{descriptor}", descriptor)
    factory = factory_template.replace("{descriptor}", descriptor)
    source = _source(
        "UPDATE users SET name = %s WHERE id = %s", fields=f"id: str\n    name: str = {factory}(lambda self: 'fixed')"
    ).replace("class UserInput(BaseModel):", "class UserInput:")
    source = f"{declaration}\n{source}"
    assert _check(source) == []


def test_unrelated_default_factory_name_does_not_prove_a_builtin_descriptor() -> None:
    source = _source("UPDATE users SET name = %s WHERE id = %s", fields="id: str\n    name: str = readonly()")
    source = f"from app.fields import property as readonly\n{source}"
    assert len(_check(source)) == 1


def test_timestamp_precision_is_part_of_the_write_policy() -> None:
    source = _source(
        "UPDATE users SET name = %s, updated_at = CURRENT_TIMESTAMP(0) WHERE id = %s",
        conflict="name = EXCLUDED.name, updated_at = NOW()",
    )
    assert _check(source) == []
    assert len(_check(source.replace("updated_at = NOW()", "updated_at = CURRENT_TIMESTAMP(0)"))) == 1


_FANOUT_PATH = Path("app/item_store.py")
_FANOUT_BASE = """from psycopg import AsyncCursor
class ItemStore:
    def __init__(self, cursor: AsyncCursor):
        self.cursor = cursor
    async def upsert(self, item):
        await self.cursor.execute('INSERT INTO item(id, name) VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name', (item.id, item.name))
    async def set_name(self, key, name):
        await self.cursor.execute('UPDATE item SET name=%s WHERE id=%s AND started_at IS NULL', (name,key))
"""


def test_guarded_setter_requires_review_without_upsert_replacement() -> None:
    [finding] = StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, _FANOUT_BASE)
    assert finding.code == "SARJ517"
    assert finding.message.startswith("Review `set_name` beside the model upsert")
    assert "concurrency" in finding.message
    assert finding.severity.value == "warning"


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        pytest.param("UPDATE item", "UPDATE other", id="different-relation"),
        pytest.param("async def upsert", "async def create", id="no-model-command"),
        pytest.param("async def set_name", "async def transition", id="explicit-transition"),
        pytest.param("async def set_name", "async def update_name", id="guarded-update-name"),
        pytest.param("UPDATE item", "DELETE FROM item", id="different-operation"),
    ],
)
def test_other_owners_and_operations_are_preserved(original: str, replacement: str) -> None:
    assert StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, _FANOUT_BASE.replace(original, replacement)) == []


def test_upsert_can_delegate_to_direct_class_helper() -> None:
    source = _FANOUT_BASE.replace(
        "    async def upsert(self, item):",
        "    async def upsert(self, item):\n        return await self._insert(item)\n    async def _insert(self, item):",
    )
    assert len(StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, source)) == 1


def test_name_upsert_does_not_prove_its_duplicate_policy() -> None:
    source = _FANOUT_BASE.replace(" ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name", "")
    assert len(StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, source)) == 1


def test_abstract_setter_policy_uses_actual_abstract_decorator() -> None:
    source = """import abc
class ItemStore(abc.ABC):
    @abc.abstractmethod
    def upsert(self, item): pass
    @abc.abstractmethod
    def set_name_before_start(self, key, name): pass
"""
    assert len(StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, source)) == 1
    assert StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, source.replace("import abc", "import other as abc")) == []


def test_test_and_generated_sources_are_excluded() -> None:
    assert StoreFieldUpdateReusesUpsert().check(Path("tests/item_store.py"), _FANOUT_BASE) == []
    assert StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, "# Code generated. DO NOT EDIT.\n" + _FANOUT_BASE) == []


def test_repeated_updates_in_one_method_have_one_finding() -> None:
    line = "        await self.cursor.execute('UPDATE item SET name=%s WHERE id=%s AND started_at IS NULL', (name,key))"
    assert len(StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, _FANOUT_BASE.replace(line, line + "\n" + line))) == 1


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param("    set_name = other\n", id="class-shadow"),
        pytest.param("    async def set_name(self, key, name):\n        pass\n", id="duplicate-definition"),
        pytest.param("ItemStore.set_name = other\n", id="class-replacement"),
        pytest.param("del ItemStore.set_name\n", id="class-deletion"),
        pytest.param("ItemStore.upsert = other\n", id="command-replacement"),
    ],
)
def test_only_effective_declared_methods_are_reviewed(suffix: str) -> None:
    assert StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, _FANOUT_BASE + suffix) == []


def test_instance_replacement_is_not_a_declared_setter() -> None:
    source = _FANOUT_BASE.replace(
        "        self.cursor = cursor", "        self.cursor = cursor\n        self.set_name = other"
    )
    assert StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, source) == []


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param("        self = other\n        return await self._insert(item)", id="rebound-self"),
        pytest.param("        async def unused():\n            return await self._insert(item)", id="nested-call"),
    ],
)
def test_helper_delegation_requires_the_method_receiver(replacement: str) -> None:
    source = _FANOUT_BASE.replace(
        "    async def upsert(self, item):",
        "    async def upsert(self, item):\n" + replacement + "\n    async def _insert(self, item):",
    )
    assert StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, source) == []


@pytest.mark.parametrize(
    "definition",
    [
        pytest.param("    @staticmethod\n    async def upsert(self, item):", id="static-self-name"),
        pytest.param("    async def upsert(other, item):", id="nonreceiver-self-name"),
        pytest.param("    @other\n    async def upsert(self, item):", id="unknown-decorator"),
    ],
)
def test_helper_command_requires_an_instance_method(definition: str) -> None:
    source = _FANOUT_BASE.replace(
        "    async def upsert(self, item):",
        definition + "\n        return await self._insert(item)\n    async def _insert(self, item):",
    )
    assert StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, source) == []


def test_positional_only_receiver_can_delegate() -> None:
    source = _FANOUT_BASE.replace(
        "    async def upsert(self, item):",
        "    async def upsert(self, /, item):\n        return await self._insert(item)\n    async def _insert(self, item):",
    )
    assert len(StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "import abc\nclass ItemStore:\n    abc = other\n    @abc.abstractmethod\n    def upsert(self, item): pass\n    @abc.abstractmethod\n    def set_name(self, key, name): pass\n",
            id="class-shadows-module",
        ),
        pytest.param(
            "from abc import abstractmethod as abstract\nclass ItemStore:\n    abstract = other\n    @abstract\n    def upsert(self, item): pass\n    @abstract\n    def set_name(self, key, name): pass\n",
            id="class-shadows-alias",
        ),
        pytest.param(
            "import abc\nabc.abstractmethod = other\nclass ItemStore:\n    @abc.abstractmethod\n    def upsert(self, item): pass\n    @abc.abstractmethod\n    def set_name(self, key, name): pass\n",
            id="mutated-decorator",
        ),
        pytest.param(
            "import abc\nclass ItemStore:\n    @other\n    @abc.abstractmethod\n    def upsert(self, item): pass\n    @abc.abstractmethod\n    def set_name(self, key, name): pass\n",
            id="unknown-outer-wrapper",
        ),
    ],
)
def test_abstract_policy_requires_the_runtime_decorator_binding(source: str) -> None:
    assert StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, source) == []


@pytest.mark.parametrize(
    ("imports", "decorator"),
    [
        pytest.param("    import abc\n", "abc.abstractmethod", id="class-module-import"),
        pytest.param("    from abc import abstractmethod as abstract\n", "abstract", id="class-symbol-alias"),
    ],
)
def test_class_local_abstract_imports_are_recognized(imports: str, decorator: str) -> None:
    source = (
        "class ItemStore:\n"
        + imports
        + f"    @{decorator}\n    def upsert(self, item): pass\n"
        + f"    @{decorator}\n    def set_name(self, key, name): pass\n"
    )
    assert len(StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, source)) == 1


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param("@other\nclass ItemStore:", id="class-decorator"),
        pytest.param("class ItemStore(metaclass=Other):", id="metaclass"),
    ],
)
def test_unknown_class_transformations_abstain(replacement: str) -> None:
    assert (
        StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, _FANOUT_BASE.replace("class ItemStore:", replacement)) == []
    )


def test_known_final_class_decorator_preserves_direct_command() -> None:
    source = "from typing import final\n" + _FANOUT_BASE.replace("class ItemStore:", "@final\nclass ItemStore:")
    assert len(StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, source)) == 1


def test_precise_ordinary_field_owner_takes_precedence() -> None:
    source = (
        _FANOUT_BASE.replace("class ItemStore:", "class ItemInput:\n    id: str\n    name: str\nclass ItemStore:")
        .replace("upsert(self, item):", "upsert(self, item: ItemInput) -> Item:")
        .replace("set_name(self, key, name):", "set_name(self, key, name) -> Item:")
        .replace(" AND started_at IS NULL", "")
    )
    [finding] = StoreFieldUpdateReusesUpsert().check(_FANOUT_PATH, source)
    assert "repeats fields" in finding.message
