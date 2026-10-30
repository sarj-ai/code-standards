import ast
from pathlib import Path
from textwrap import indent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.service_singleton_delegates_to_bulk import ServiceSingletonDelegatesToBulk


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


PATH = Path("app/users.py")
OPERATIONS = ("get", "create", "insert", "upsert", "update", "delete")


def _check(source: str, path: Path = PATH) -> list[Diagnostic]:
    return ServiceSingletonDelegatesToBulk().check(path, source)


def _service(
    body: str, *, operation: str = "get", bulk_body: str | None = "return self.backend.fetch_many(keys)"
) -> str:
    source = f"class UserService:\n    def {operation}(self, key: str):\n{indent(body, '        ')}\n"
    if bulk_body is not None:
        source += f"    def {operation}_many(self, keys: list[str]):\n{indent(bulk_body, '        ')}\n"
    return source


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("owner", ["UserService", "UserStore", "UserRepository"])
def test_rejects_singleton_only_crud(operation: str, owner: str) -> None:
    source = _service("return self.backend.execute(key)", operation=operation, bulk_body=None).replace(
        "UserService", owner
    )
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.ERROR
    assert diagnostics[0].line == 2
    assert f"{operation}_many" in diagnostics[0].message


@pytest.mark.parametrize("operation", OPERATIONS)
def test_rejects_parallel_singleton_implementation(operation: str) -> None:
    assert len(_check(_service("return self.backend.execute(key)", operation=operation))) == 1


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("argument", ["[key]", "(key,)", "{key}", "keys=[key]"])
def test_accepts_singleton_bulk_adapter(operation: str, argument: str) -> None:
    source = _service(
        f"rows = self.{operation}_many({argument})\nreturn rows[0] if rows else None", operation=operation
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "body",
    [
        "keys = [key]\nrows = self.get_many(keys)\nreturn rows[0]",
        "value = key\nkeys = (value,)\nreturn self.get_many(keys)[0]",
        "keys: list[str] = [key]\nreturn self.get_many(keys)[0]",
        "return self._get_one(key)",
    ],
)
def test_accepts_aliases_and_private_adapter(body: str) -> None:
    source = _service(body) + "    def _get_one(self, value):\n        return self.get_many([value])[0]\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    "body",
    [
        "return self.get_many([])",
        "return self.get_many([key, key])",
        "return self.get_many(key)",
        "return self.get_many(['other'])",
        "return self.backend.get_many([key])",
        "return other.get_many([key])",
        "return self.get_many",
        "key = 'other'\nreturn self.get_many([key])",
        "keys = [key]\nkeys.append('other')\nreturn self.get_many(keys)",
        "keys = [key]\nkeys[0] = 'other'\nreturn self.get_many(keys)",
        "def unused():\n    return self.get_many([key])\nreturn self.backend.get(key)",
        "unused = lambda: self.get_many([key])\nreturn self.backend.get(key)",
        "return self.backend.get(key)\nself.get_many([key])",
        "if False:\n    self.get_many([key])\nreturn self.backend.get(key)",
        "return self._get_one('other')",
    ],
)
def test_rejects_calls_that_do_not_delegate_the_original_item(body: str) -> None:
    source = _service(body) + "    def _get_one(self, value):\n        return self.get_many([value])[0]\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "bulk_body",
    [
        "return [self.get(key) for key in keys]",
        "for key in keys:\n    self.get(key)",
        "return self._read_each(keys)",
    ],
)
@pytest.mark.parametrize("body", ["return self.backend.get(key)", "return self.get_many([key])[0]"])
def test_rejects_inverted_bulk_and_recursion(body: str, bulk_body: str) -> None:
    source = (
        _service(body, bulk_body=bulk_body)
        + "    def _read_each(self, keys):\n        return [self.get(key) for key in keys]\n"
    )
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert "bulk" in diagnostics[0].message


def test_private_helper_cycle_terminates() -> None:
    source = (
        _service("return self._a(key)")
        + "    def _a(self, key):\n        return self._b(key)\n    def _b(self, key):\n        return self._a(key)\n"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize("awaited", [True, False])
def test_async_delegation_requires_await(awaited: bool) -> None:
    body = f"rows = {'await ' if awaited else ''}self.get_many([key])\nreturn rows[0]"
    source = _service(body, bulk_body="return await self.backend.fetch_many(keys)").replace(
        "    def ", "    async def "
    )
    assert len(_check(source)) == (0 if awaited else 1)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("return self.get_many([key], tenant=tenant)[0]", 0),
        ("return self.get_many(keys=[key], tenant=tenant)[0]", 0),
        ("return self.get_many([key], tenant='other')[0]", 1),
        ("return self.get_many([key])[0]", 1),
    ],
)
def test_context_must_be_forwarded(body: str, expected: int) -> None:
    source = f"class UserService:\n    def get(self, key: str, *, tenant: str):\n{indent(body, '        ')}\n    def get_many(self, keys: list[str], *, tenant: str):\n        return self.backend.fetch_many(keys, tenant)\n"
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    "path", ["tests/test_users.py", "app/fakes/users.py", "app/generated/users.py", "vendor/users.py", "app/users.pyi"]
)
def test_excludes_unmaintained_and_test_sources(path: str) -> None:
    assert _check(_service("return self.backend.get(key)", bulk_body=None), Path(path)) == []


@pytest.mark.parametrize(
    "source",
    [
        "class UserService:\n    def get(",
        "# Code generated by protoc. DO NOT EDIT.\n" + _service("return self.backend.get(key)", bulk_body=None),
        "class Mapping:\n    def get(self, key):\n        return self.values[key]\n",
        "def get(key):\n    return backend.get(key)\n",
        "class UserService:\n    def get(self):\n        return self.value\n",
        "class UserService:\n    @property\n    def get(self):\n        return self.value\n",
        "class UserService:\n    @staticmethod\n    def get(key):\n        return backend.get(key)\n",
        "class UserService:\n    @classmethod\n    def get(cls, key):\n        return cls.backend.get(key)\n",
        "from abc import ABC, abstractmethod\nclass UserService(ABC):\n    @abstractmethod\n    def get(self, key): ...\n",
        "from typing import Protocol\nclass UserService(Protocol):\n    def get(self, key): ...\n",
        "class UserService:\n    def get(self, key):\n        raise NotImplementedError\n",
        "class UserService:\n    def get(self, key): ...\n",
        "class UserService:\n    def get_many(self, keys):\n        return self.backend.fetch_many(keys)\n",
    ],
)
def test_negative_and_near_miss_cases(source: str) -> None:
    assert _check(source) == []


def test_accepts_local_inherited_bulk() -> None:
    source = "class Base:\n    def get_many(self, keys):\n        return self.backend.fetch_many(keys)\nclass UserService(Base):\n    def get(self, key):\n        return self.get_many([key])[0]\n"
    assert _check(source) == []


def test_unknown_base_does_not_prove_missing_bulk() -> None:
    source = "from external import Base\nclass UserService(Base):\n    def get(self, key):\n        return super().get(key)\n"
    assert _check(source) == []


def test_multiple_operations_have_distinct_locations() -> None:
    source = "class UserService:\n    def get(self, key):\n        return self.backend.get(key)\n    def delete(self, key):\n        self.backend.delete(key)\n"
    diagnostics = _check(source)
    assert [(d.line, d.col) for d in diagnostics] == [(2, 5), (4, 5)]


@pytest.mark.parametrize("suppression", ["", "  # sarj-noqa: SARJ556 -- remote API exposes only singleton reads"])
def test_runner_enforces_error_and_exact_suppression(tmp_path: Path, suppression: str) -> None:
    path = tmp_path / "users.py"
    path.write_text(
        _service("return self.backend.get(key)", bulk_body=None).replace("key: str):", f"key: str):{suppression}")
    )
    diagnostics = analyze([ServiceSingletonDelegatesToBulk.id], [path])
    assert len(diagnostics) == (0 if suppression else 1)
    if diagnostics:
        assert diagnostics[0].severity is Severity.ERROR


@pytest.mark.parametrize(
    "example",
    ServiceSingletonDelegatesToBulk.public_examples(),
    ids=tuple(example.example_id for example in ServiceSingletonDelegatesToBulk.public_examples()),
)
def test_public_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, Path(example.focus_path))) == example.expected_count


@pytest.mark.parametrize(
    "body",
    [
        "return self.get_many([key]) if False else self.backend.get(key)",
        "return False and self.get_many([key])",
        "return (self.get_many([key]) for _ in [])",
        "return [self.get_many([key]) for _ in []]",
        "return self.get_many(*args)",
        "return self.get_many(**kwargs)",
        "return self.get_many([key], keys=[key])",
    ],
)
def test_lazy_or_dynamic_calls_do_not_prove_delegation(body: str) -> None:
    assert len(_check(_service(body))) == 1


@pytest.mark.parametrize(
    "bulk",
    [
        "def get_many(self, keys): ...",
        "def get_many(self):\n    return []",
        "def get_many(self, keys, required):\n    return self.backend.get_many(keys)",
    ],
)
def test_bulk_must_be_an_implemented_callable_contract(bulk: str) -> None:
    source = _service("return self.get_many([key])[0]", bulk_body=None) + indent(bulk, "    ") + "\n"
    ast.parse(source)
    assert len(_check(source)) == 1


def test_accepts_abstract_bulk_contract_with_concrete_adapter() -> None:
    source = "from abc import ABC, abstractmethod\nclass UserService(ABC):\n    def get(self, key):\n        return self.get_many([key])[0]\n    @abstractmethod\n    def get_many(self, keys): ...\n"
    assert _check(source) == []


@pytest.mark.parametrize("decorator", ["override", "final"])
def test_imported_neutral_decorators_preserve_detection(decorator: str) -> None:
    source = f"from typing import {decorator} as marker\n" + _service(
        "return self.backend.get(key)", bulk_body=None
    ).replace("    def get", "    @marker\n    def get")
    assert len(_check(source)) == 1


def test_prefers_error_over_existing_store_advisory(tmp_path: Path) -> None:
    path = tmp_path / "user_store.py"
    path.write_text(
        "class UserStore:\n    def get(self, user_id: str) -> User | None:\n        return self.query_one(user_id)\n    def get_many(self, user_ids: list[str]) -> list[User]:\n        return self.query_many(user_ids)\n"
    )
    diagnostics = analyze([ServiceSingletonDelegatesToBulk.id, "store-get-delegates-to-bulk-read"], [path])
    assert [(diagnostic.code, diagnostic.line) for diagnostic in diagnostics] == [("SARJ556", 2)]


@pytest.mark.parametrize("argument", ["[*[key]]", "[*(key,)]", "[*[], key]", "[*{key}]"])
def test_closed_starred_singleton_collections_are_valid(argument: str) -> None:
    assert _check(_service(f"return self.get_many({argument})[0]")) == []


@pytest.mark.parametrize("body", ["return self.backend.get(key)", "return self.get_many([key])[0]"])
def test_final_class_preserves_policy(body: str) -> None:
    source = "from typing import final as closed\n@closed\n" + _service(body)
    assert len(_check(source)) == (0 if "self.get_many" in body else 1)


def test_rebound_receiver_does_not_prove_own_bulk_delegation() -> None:
    assert len(_check(_service("self = other\nreturn self.get_many([key])[0]"))) == 1


@pytest.mark.parametrize("body", ["return self.backend.get(key)", "return self.get_many([key])[0]"])
def test_cli_exit_status_is_blocking(tmp_path: Path, body: str) -> None:
    path = tmp_path / "users.py"
    path.write_text(_service(body))
    assert main(["check", "--rule", ServiceSingletonDelegatesToBulk.id, str(path)]) == (
        0 if "self.get_many" in body else 1
    )


@pytest.mark.parametrize("bulk_name", ["get_many", "get_by_ids"])
@pytest.mark.parametrize("delegates", [True, False])
def test_existing_bulk_read_names_are_equivalent(bulk_name: str, delegates: bool) -> None:
    body = "return self.get_many([key])[0]" if delegates else "return self.backend.get(key)"
    assert len(_check(_service(body).replace("get_many", bulk_name))) == (0 if delegates else 1)


def test_either_declared_read_primitive_can_own_the_adapter() -> None:
    source = (
        _service("return self.get_by_ids([key])[0]")
        + "    def get_by_ids(self, keys):\n        return self.backend.fetch_many(keys)\n"
    )
    assert _check(source) == []


def test_inverted_read_alias_cannot_hide_behind_another_bulk_primitive() -> None:
    source = (
        _service("return self.get_many([key])[0]")
        + "    def get_by_ids(self, keys):\n        return [self.get(key) for key in keys]\n"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize("context_name", ["scope", "tenant_context"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("via_helper", [False, True])
def test_renamed_bulk_context_preserves_original_value(context_name: str, asynchronous: bool, via_helper: bool) -> None:
    prefix = "async " if asynchronous else ""
    awaited = "await " if asynchronous else ""
    delegation = f"rows = {awaited}self.get_many([key], {context_name}=tenant)\nreturn rows[0]"
    body = f"return {awaited}self._get_one(key, tenant)" if via_helper else delegation
    source = f"class UserService:\n    {prefix}def get(self, key: str, tenant: str):\n{indent(body, '        ')}\n    {prefix}def get_many(self, keys: list[str], *, {context_name}: str):\n        return {awaited}self.backend.fetch_many(keys, {context_name})\n"
    if via_helper:
        source += f"    {prefix}def _get_one(self, key: str, tenant: str):\n{indent(delegation, '        ')}\n"
    ast.parse(source)
    assert _check(source) == []


def test_same_named_context_parameters_cannot_swap_values() -> None:
    source = "class UserService:\n    def get(self, key, tenant, actor):\n        return self.get_many([key], tenant=actor, actor=tenant)[0]\n    def get_many(self, keys, *, tenant, actor):\n        return self.backend.fetch_many(keys, tenant, actor)\n"
    assert len(_check(source)) == 1


def test_renamed_context_cannot_drop_the_original_value() -> None:
    source = "class UserService:\n    def get(self, key, tenant):\n        return self.get_many([key], scope='other')[0]\n    def get_many(self, keys, *, scope):\n        return self.backend.fetch_many(keys, scope)\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize("inherited", [False, True])
@pytest.mark.parametrize(
    "bulk",
    [
        "@staticmethod\ndef get_many(keys):\n    return keys",
        "@classmethod\ndef get_many(cls, keys):\n    return keys",
        "@property\ndef get_many(self):\n    return lambda keys: keys",
        "def read_many(self, keys):\n    return keys\nget_many = read_many",
        "@retain\ndef get_many(self, keys):\n    return keys",
        "@overload\ndef get_many(self, keys: list[str]) -> list[str]: ...\n@overload\ndef get_many(self, keys: list[int]) -> list[int]: ...\ndef get_many(self, keys):\n    return keys",
        "def get_many(self, *keys):\n    return keys[0]",
        "def __init__(self):\n    self.get_many = lambda keys: keys",
    ],
)
def test_callable_bulk_declarations_are_not_reported_missing(bulk: str, inherited: bool) -> None:
    source = "from typing import overload\ndef retain(function):\n    return function\n"
    adapter = "def get(self, key):\n    return self.get_many([key])[0]\n"
    if inherited:
        source += f"class Base:\n{indent(bulk, '    ')}\nclass UserService(Base):\n{indent(adapter, '    ')}"
    else:
        source += f"class UserService:\n{indent(adapter + bulk, '    ')}\n"
    ast.parse(source)
    assert _check(source) == []


@pytest.mark.parametrize("literal", ["None", "False", "[]", "{}", "()", "42"])
@pytest.mark.parametrize("shadows_inherited", [False, True])
def test_noncallable_bulk_members_do_not_satisfy_contract(literal: str, shadows_inherited: bool) -> None:
    source = "class Base:\n    def get_many(self, keys):\n        return keys\n" if shadows_inherited else ""
    source += _service("return self.get_many([key])[0]", bulk_body=None).replace(
        "class UserService:", "class UserService(Base):" if shadows_inherited else "class UserService:"
    )
    source += f"    get_many = {literal}\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize("module", ["typing", "typing_extensions"])
def test_protocol_default_adapter_is_not_an_unimplemented_service(module: str) -> None:
    source = f"from {module} import Protocol as Contract\n" + _service(
        "return self.get_many([key])[0]", bulk_body="..."
    ).replace("class UserService:", "class UserService(Contract):")
    assert _check(source) == []


def test_unrelated_protocol_name_does_not_exclude_real_service() -> None:
    source = "class Protocol:\n    pass\n" + _service("return self.backend.get(key)", bulk_body=None).replace(
        "class UserService:", "class UserService(Protocol):"
    )
    assert len(_check(source)) == 1
