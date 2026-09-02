from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity, is_suppressed
from sarj_python_lint.rules.store_get_delegates_to_bulk_read import StoreGetDelegatesToBulkRead


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


PATH = Path("app/user_store.py")


def _check(source: str, path: Path = PATH) -> list[Diagnostic]:
    return StoreGetDelegatesToBulkRead().check(path, source)


@pytest.mark.parametrize(
    "example",
    StoreGetDelegatesToBulkRead.public_examples(),
    ids=tuple(example.example_id for example in StoreGetDelegatesToBulkRead.public_examples()),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, Path(focus.path))) == example.expected_count


def test_flags_compatible_async_get_and_get_many() -> None:
    source = """class UserStore:
    async def get(self, user_id: UserId) -> User | None:
        return await self.query_one(user_id)

    async def get_many(self, user_ids: list[UserId]) -> list[User]:
        return await self.query_many(user_ids)
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].line == 2
    assert diagnostics[0].severity is Severity.WARNING
    assert "signatures suggest" in diagnostics[0].message


def test_flags_compatible_get_by_ids_mapping() -> None:
    source = """class UserStore:
    async def get(self, user_id: UserId) -> User | None:
        return await self.query_one(user_id)

    async def get_by_ids(self, user_ids: list[UserId]) -> dict[UserId, User]:
        return await self.query_many(user_ids)
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "and `get_by_ids` expose the same keyed read" in diagnostics[0].message


@pytest.mark.parametrize(
    "projection",
    [
        "rows = await self.get_many([user_id])\n        return rows[0] if rows else None",
        "rows = await self.get_by_ids([user_id])\n        return rows.get(user_id)",
    ],
)
def test_allows_singleton_delegation(projection: str) -> None:
    bulk_name = "get_by_ids" if "get_by_ids" in projection else "get_many"
    bulk_result = "dict[UserId, User]" if bulk_name == "get_by_ids" else "list[User]"
    source = f"""class UserStore:
    async def get(self, user_id: UserId) -> User | None:
        {projection}

    async def {bulk_name}(self, user_ids: list[UserId]) -> {bulk_result}:
        return await self.query_many(user_ids)
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    "delegation",
    [
        "await self.get_many([user_id])",
        "await self.get_many(user_ids=[user_id])",
        "await self.get_many((user_id,))",
        "await self.get_many(keys)",
        "await cls.get_many([user_id])",
    ],
)
def test_allows_any_direct_call_to_the_bulk_sibling(delegation: str) -> None:
    receiver = "cls" if delegation.startswith("await cls") else "self"
    decorator = "    @classmethod\n" if receiver == "cls" else ""
    source = f"""class UserStore:
{decorator}    async def get({receiver}, user_id: UserId) -> User | None:
        keys = [user_id]
        rows = {delegation}
        return rows[0] if rows else None

{decorator}    async def get_many({receiver}, user_ids: list[UserId]) -> list[User]:
        return await {receiver}.query_many(user_ids)
"""

    assert _check(source) == []


def test_ignores_singleton_contract_with_cache_specific_access() -> None:
    source = """class UserStore:
    async def get(self, user_id: UserId) -> User | None:
        if user_id in self.cache:
            return self.cache[user_id]
        return await self.query_one(user_id)

    async def get_many(self, user_ids: list[UserId]) -> list[User]:
        return await self.query_many(user_ids)
"""

    assert _check(source) == []


def test_ignores_conditional_expression_singleton_contract() -> None:
    source = """class UserStore:
    async def get(self, user_id: UserId) -> User | None:
        return self.cache[user_id] if user_id in self.cache else await self.query_one(user_id)

    async def get_many(self, user_ids: list[UserId]) -> list[User]:
        return await self.query_many(user_ids)
"""

    assert _check(source) == []


def test_flags_missing_row_branch_when_contracts_are_otherwise_compatible() -> None:
    source = """class UserStore:
    async def get(self, tenant: TenantId, user_id: UserId) -> User | None:
        row = await self.query_one(tenant, user_id)
        if row is None:
            return None
        return row

    async def get_many(self, tenant: TenantId, user_ids: list[UserId]) -> dict[UserId, User]:
        rows = await self.query_many(tenant, user_ids)
        return {row.id: row for row in rows}
"""

    assert len(_check(source)) == 1


def test_ignores_mismatched_shared_context_parameters() -> None:
    source = """class UserStore:
    async def get(self, tenant: TenantId, user_id: UserId) -> User | None:
        return await self.query_one(tenant, user_id)

    async def get_many(self, account: TenantId, user_ids: list[UserId]) -> dict[UserId, User]:
        return await self.query_many(account, user_ids)
"""

    assert _check(source) == []


def test_ignores_bulk_implementation_that_calls_get() -> None:
    source = """class UserStore:
    async def get(self, user_id: UserId) -> User | None:
        return await self.query_one(user_id)

    async def get_many(self, user_ids: list[UserId]) -> list[User]:
        return [user for user_id in user_ids if (user := await self.get(user_id))]
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    ("singleton_key", "bulk_key", "singleton_result", "bulk_result"),
    [
        ("UserId", "str", "User | None", "list[User]"),
        ("UserId", "UserId", "Admin | None", "list[User]"),
        ("UserId", "UserId", "User", "list[User]"),
        ("UserId", "UserId", "User | None", "Sequence[User]"),
    ],
)
def test_ignores_incompatible_signatures(
    singleton_key: str,
    bulk_key: str,
    singleton_result: str,
    bulk_result: str,
) -> None:
    source = f"""class UserStore:
    async def get(self, user_id: {singleton_key}) -> {singleton_result}:
        return await self.query_one(user_id)

    async def get_many(self, user_ids: list[{bulk_key}]) -> {bulk_result}:
        return await self.query_many(user_ids)
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "class UserStore:\n    async def get(self, user_id: UserId) -> User | None: ...\n",
        "class UserStore:\n    @abstractmethod\n    async def get(self, user_id: UserId) -> User | None: ...\n\n    async def get_many(self, user_ids: list[UserId]) -> list[User]: ...\n",
        "class UserStore:\n    async def get(self, user_id: UserId) -> User | None: return None\n\n    def get_many(self, user_ids: list[UserId]) -> list[User]: return []\n",
        "def get(user_id: UserId) -> User | None: return None\ndef get_many(user_ids: list[UserId]) -> list[User]: return []\n",
    ],
)
def test_ignores_non_concrete_or_non_owned_pairs(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        Path("tests/test_user_store.py"),
        Path("app/user_service.py"),
        Path("generated/user_store.py"),
    ],
    ids=("test", "non-store", "generated"),
)
def test_ignores_excluded_paths(path: Path) -> None:
    source = """class UserStore:
    async def get(self, user_id: UserId) -> User | None:
        return await self.query_one(user_id)
    async def get_many(self, user_ids: list[UserId]) -> list[User]:
        return await self.query_many(user_ids)
"""

    assert _check(source, path) == []


def test_exact_suppression_applies_on_reported_method_line() -> None:
    source = """class UserStore:
    async def get(self, user_id: UserId) -> User | None:  # sarj-noqa: SARJ421 — singleton uses a locking read
        return await self.query_one(user_id)
    async def get_many(self, user_ids: list[UserId]) -> list[User]:
        return await self.query_many(user_ids)
"""

    diagnostic = _check(source)[0]

    assert is_suppressed(source.splitlines(), diagnostic.line, diagnostic.code)


def test_malformed_source_is_ignored() -> None:
    assert _check("class UserStore:\n  async def get(") == []


def test_common_private_read_helper_is_already_one_canonical_path() -> None:
    source = """class UserStore:
    async def get(self, user_id: UserId) -> User | None:
        rows = await self._read([user_id])
        return rows.get(user_id)

    async def get_many(self, user_ids: list[UserId]) -> dict[UserId, User]:
        return await self._read(user_ids)
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "singleton_body",
    [
        "return await self.query_one(user_id, for_update=True)",
        "return await self.query_one('SELECT * FROM users FOR UPDATE', user_id)",
        "async with self.db.transaction():\n            return await self.query_one(user_id)",
        "return await self.query_one(user_id, prepare=False)",
    ],
)
def test_distinct_singleton_access_semantics_are_not_assumed_equivalent(singleton_body: str) -> None:
    source = f"""class UserStore:
    async def get(self, user_id: UserId) -> User | None:
        {singleton_body}

    async def get_many(self, user_ids: list[UserId]) -> list[User]:
        return await self.query_many(user_ids)
"""
    assert _check(source) == []


def test_operational_decorator_mismatch_is_not_assumed_equivalent() -> None:
    source = """class UserStore:
    @read_your_writes
    async def get(self, user_id: UserId) -> User | None:
        return await self.query_one(user_id)

    async def get_many(self, user_ids: list[UserId]) -> list[User]:
        return await self.query_many(user_ids)
"""
    assert _check(source) == []


def test_multi_statement_not_implemented_stub_is_not_concrete() -> None:
    source = """class UserStore:
    async def get(self, user_id: UserId) -> User | None:
        message = "not implemented"
        raise NotImplementedError(message)

    async def get_many(self, user_ids: list[UserId]) -> list[User]:
        return await self.query_many(user_ids)
"""
    assert _check(source) == []


def test_same_python_type_with_different_key_domains_is_not_compatible() -> None:
    source = """class UserStore:
    async def get(self, email: str) -> User | None:
        return await self.query_by_email(email)

    async def get_many(self, user_ids: list[str]) -> list[User]:
        return await self.query_by_ids(user_ids)
"""
    assert _check(source) == []


def test_non_store_class_in_store_module_is_not_owned() -> None:
    source = """class UserRepository:
    async def get(self, user_id: UserId) -> User | None:
        return await self.query_one(user_id)

    async def get_many(self, user_ids: list[UserId]) -> list[User]:
        return await self.query_many(user_ids)
"""
    assert _check(source) == []
