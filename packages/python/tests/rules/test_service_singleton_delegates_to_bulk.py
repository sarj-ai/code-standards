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
    "body", ["return await anext(self.get_many([key]), None)", "return await self.get_many([key])"]
)
def test_async_generator_bulk_defers_adapter_consumption_proof(body: str) -> None:
    source = _service(body, bulk_body="for key in keys:\n    yield key").replace("    def ", "    async def ")
    assert _check(source) == []


def test_async_generator_bulk_preserves_known_reverse_call_error() -> None:
    source = _service(
        "return await anext(self.get_many([key]), None)", bulk_body="for key in keys:\n    yield await self.get(key)"
    ).replace("    def ", "    async def ")
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert "calls back through the singleton" in diagnostics[0].message


@pytest.mark.parametrize("awaited", [True, False])
def test_nested_yield_does_not_defer_bulk_coroutine_await_check(awaited: bool) -> None:
    body = f"return {'await ' if awaited else ''}self.get_many([key])"
    source = _service(body, bulk_body="def stream():\n    yield keys\nreturn keys").replace(
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


@pytest.mark.parametrize("callback_override", [False, True], ids=["primitive-override", "callback-override"])
def test_diamond_bulk_uses_c3_override_order(callback_override: bool) -> None:
    primitive = "return self.backend.fetch_many(keys)"
    callback = "return [self.get(key) for key in keys]"
    original, override = (primitive, callback) if callback_override else (callback, primitive)
    source = f"class A:\n    def get_many(self, keys):\n        {original}\nclass B(A):\n    pass\nclass C(A):\n    def get_many(self, keys):\n        {override}\nclass UserService(B, C):\n    def get(self, key):\n        return self.get_many([key])[0]\n"
    assert len(_check(source)) == int(callback_override)


@pytest.mark.parametrize("callback_first", [False, True], ids=["primitive-first", "callback-first"])
@pytest.mark.parametrize("neutral", ["", ", ABC"], ids=["plain", "neutral-abc"])
def test_independent_bases_keep_left_to_right_precedence(callback_first: bool, neutral: str) -> None:
    primitive = "return self.backend.fetch_many(keys)"
    callback = "return [self.get(key) for key in keys]"
    first, second = (callback, primitive) if callback_first else (primitive, callback)
    source = f"from abc import ABC\nclass Left(object):\n    def get_many(self, keys):\n        {first}\nclass Right:\n    def get_many(self, keys):\n        {second}\nclass UserService(Left, Right{neutral}):\n    def get(self, key):\n        return self.get_many([key])[0]\n"
    assert len(_check(source)) == int(callback_first)


@pytest.mark.parametrize(
    ("member", "expected"),
    [
        ("get_many = None", 1),
        ("get_many = provider", 0),
        ("@property\ndef get_many(self):\n    return provider", 0),
        ("def __init__(self):\n    self.get_many = provider", 0),
    ],
    ids=["literal-mask", "callable-mask", "descriptor-mask", "instance-mask"],
)
def test_diamond_masks_apply_at_the_c3_owner(member: str, expected: int) -> None:
    source = f"class A:\n    def get_many(self, keys):\n        return [self.get(key) for key in keys]\nclass B(A):\n    pass\nclass C(A):\n{indent(member, '    ')}\nclass UserService(B, C):\n    def get(self, key):\n        return self.get_many([key])[0]\n"
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    "bases",
    [
        "from external import Base\nclass A(Base):\n    pass\nclass B:\n    pass\n",
        "class X:\n    pass\nclass Y:\n    pass\nclass A(X, Y):\n    pass\nclass B(Y, X):\n    pass\n",
    ],
    ids=["imported-ancestor", "inconsistent-c3"],
)
@pytest.mark.parametrize("own_bulk", [False, True], ids=["inherited-uncertain", "own-evidence"])
def test_uncertain_mro_defers_inheritance_but_retains_own_evidence(bases: str, own_bulk: bool) -> None:
    source = bases + _service("return self.backend.get(key)", bulk_body=None).replace(
        "class UserService:", "class UserService(A, B):"
    )
    if own_bulk:
        source += "    def get_many(self, keys):\n        return self.backend.fetch_many(keys)\n"
    assert len(_check(source)) == int(own_bulk)


def test_known_simple_inheritance_still_checks_the_own_singleton() -> None:
    source = "class Base:\n    def get_many(self, keys):\n        return self.backend.fetch_many(keys)\n"
    source += _service("return self.backend.get(key)", bulk_body=None).replace(
        "class UserService:", "class UserService(Base):"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(("classes", "expected"), [(64, 1), (65, 0)], ids=["at-bound", "over-bound"])
def test_role_ancestry_has_an_explicit_class_bound(classes: int, expected: int) -> None:
    parts = ["class RootService:\n    pass\n"]
    parent = "RootService"
    for index in range(classes - 1):
        name = f"Child{index}"
        body = (
            "    def get(self, key):\n        return self.backend.get(key)\n" if index == classes - 2 else "    pass\n"
        )
        parts.append(f"class {name}({parent}):\n{body}")
        parent = name
    assert len(_check("".join(parts))) == expected


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


@pytest.mark.parametrize("marker", ["final", "override"])
@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("marker = rewrite", "", 0),
        ("if enabled:\n    marker = rewrite", "", 0),
        ("", "marker = rewrite", 1),
        ("def nested(marker):\n    marker = rewrite", "", 1),
        ("class Nested:\n    marker = rewrite", "", 1),
        ("deferred = lambda marker: marker", "", 1),
        ("values = [marker for marker in values]", "", 1),
        ("marker: object", "", 1),
    ],
)
def test_neutral_marker_uses_class_evaluation_binding(marker: str, before: str, after: str, expected: int) -> None:
    source = f"from typing import {marker} as marker\nclass UserService:\n"
    source += (
        indent(before, "    ")
        + "\n    @marker\n    def get(self, key, marker=None):\n        return self.backend.get(key)\n"
    )
    source += indent(after, "    ") + "\n"
    assert len(_check(source)) == expected


@pytest.mark.parametrize("marker", ["final", "override", "abstractmethod", "overload"])
@pytest.mark.parametrize("namespace", [False, True])
def test_shadowed_bulk_decorators_do_not_prove_bulk_behavior(marker: str, namespace: bool) -> None:
    module = "abc" if marker == "abstractmethod" else "typing"
    imports = f"import {module} as markers\n" if namespace else f"from {module} import {marker} as marker\n"
    expression = f"markers.{marker}" if namespace else "marker"
    source = imports + "class UserService:\n"
    source += f"    {expression} = rewrite\n    def get(self, key):\n        return self.get_many([key])[0]\n"
    source += f"    @{expression}\n    def get_many(self, keys):\n        return [self.get(key) for key in keys]\n"
    assert _check(source) == []


@pytest.mark.parametrize("target", ["singleton", "class"])
def test_mutated_module_marker_namespace_is_not_neutral(target: str) -> None:
    source = "import typing as markers\nmarkers.final = rewrite\n"
    service = _service("return self.backend.get(key)", bulk_body=None)
    source += (
        "@markers.final\n" + service
        if target == "class"
        else service.replace("    def get", "    @markers.final\n    def get")
    )
    assert _check(source) == []


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


@pytest.mark.parametrize("right", ["[key]", "(key,)", "{key}", "[*left]", "(*left,)", "{*left}"])
@pytest.mark.parametrize("via_helper", [False, True])
def test_distinct_collection_allocations_retain_the_original_item(right: str, via_helper: bool) -> None:
    call = "self._one(right)" if via_helper else "self.get_many(right)"
    source = _service(f"left = [key]\nright = {right}\nleft.clear()\nreturn {call}")
    source += "    def _one(self, values):\n        return self.get_many(values)[0]\n"
    assert _check(source) == []


@pytest.mark.parametrize("mutation", ["left.clear()", "left[0] = 'other'", "right.append('other')"])
@pytest.mark.parametrize("via_helper", [False, True])
def test_shared_collection_aliases_are_invalidated(mutation: str, via_helper: bool) -> None:
    body = f"left = [key]\nright = left\n{mutation}\nreturn self.get_many(right)"
    if via_helper:
        source = _service("return self._one([key])")
        source += f"    def _one(self, left):\n{indent(body.replace('left = [key]\n', ''), '        ')}\n"
    else:
        source = _service(body)
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("scalar", "validation"),
    [
        ("str", "isascii"),
        ("bytes", "isascii"),
        ("int", "bit_length"),
        ("bool", "bit_length"),
        ("float", "is_integer"),
        ("complex", "conjugate"),
    ],
)
@pytest.mark.parametrize("quoted", [False, True])
@pytest.mark.parametrize("via_helper", [False, True])
def test_immutable_scalar_validation_preserves_input_aliases(
    scalar: str, validation: str, quoted: bool, via_helper: bool
) -> None:
    annotation = repr(scalar) if quoted else scalar
    body = f"alias = key\nalias.{validation}()\nreturn self.get_many([key])"
    source = _service("return self._one(key)" if via_helper else body).replace("key: str", f"key: {annotation}")
    if via_helper:
        source += f"    def _one(self, key):\n{indent(body, '        ')}\n"
    assert _check(source) == []


@pytest.mark.parametrize("scalar", ["bytes", "int", "bool", "float", "complex"])
@pytest.mark.parametrize(
    ("prefix", "generic", "qualified"),
    [
        ("{scalar} = MutableKey\n", "", False),
        ("", "[{scalar}]", False),
        ("import builtins\nbuiltins.{scalar} = MutableKey\n", "", False),
        ("import builtins\nbuiltins.{scalar} = MutableKey\n", "", True),
    ],
)
def test_shadowed_scalar_annotations_do_not_prove_immutability(
    scalar: str, prefix: str, generic: str, qualified: bool
) -> None:
    annotation = f"builtins.{scalar}" if qualified else scalar
    source = _service("alias = key\nalias.validate()\nreturn self.get_many([key])")
    source = source.replace("key: str", f"key: {annotation}")
    source = source.replace("def get(", f"def get{generic.format(scalar=scalar)}(")
    assert len(_check(prefix.format(scalar=scalar) + source)) == 1


@pytest.mark.parametrize("annotation", ["bytearray", "list[int]", "tuple[list[int], ...]", "frozenset[int]"])
def test_mutable_and_composite_validation_remains_uncertain(annotation: str) -> None:
    source = _service("alias = key\nalias.validate()\nreturn self.get_many([key])")
    assert len(_check(source.replace("key: str", f"key: {annotation}"))) == 1


@pytest.mark.parametrize(
    ("prefix", "annotation", "generic"),
    [
        ("", "MutableKey", ""),
        ("", "", ""),
        ("str = MutableKey\n", "str", ""),
        ("", "str", "[str]"),
        ("import builtins\nbuiltins.str = MutableKey\n", "str", ""),
        ("import builtins\nbuiltins.str = MutableKey\n", "builtins.str", ""),
    ],
    ids=["mutable", "untyped", "shadowed-builtin", "generic-shadow", "mutated-builtin", "mutated-builtin-member"],
)
def test_method_spelling_does_not_prove_immutable_input(prefix: str, annotation: str, generic: str) -> None:
    source = _service("alias = key\nalias.isascii()\nreturn self.get_many([key])")
    source = source.replace("key: str", f"key{': ' + annotation if annotation else ''}")
    source = source.replace("def get(", f"def get{generic}(")
    assert len(_check(prefix + source)) == 1


@pytest.mark.parametrize("annotation", ["str", "bytes", "int", "bool", "float", "complex"])
@pytest.mark.parametrize("argument", ["{key, key}", "{*[key], key}", "{key, *(key,)}", "[*{key, key}]"])
def test_repeated_immutable_set_elements_are_one_item(annotation: str, argument: str) -> None:
    source = _service(f"return self.get_many({argument})").replace("key: str", f"key: {annotation}")
    assert _check(source) == []


@pytest.mark.parametrize("annotation", ["str", "bytes", "int", "bool", "float", "complex"])
@pytest.mark.parametrize("argument", ["[key, key]", "(key, key)", "[*[key], key]", "(*[key], key)"])
def test_sequence_duplicates_keep_their_cardinality(annotation: str, argument: str) -> None:
    source = _service(f"return self.get_many({argument})").replace("key: str", f"key: {annotation}")
    assert len(_check(source)) == 1


@pytest.mark.parametrize("annotation", ["MutableKey", "", "str | MutableKey"])
def test_set_cardinality_does_not_infer_unknown_hashing(annotation: str) -> None:
    source = _service("return self.get_many({key, key})")
    source = source.replace("key: str", f"key{': ' + annotation if annotation else ''}")
    assert len(_check(source)) == 1


@pytest.mark.parametrize("context_first", [False, True])
@pytest.mark.parametrize("via_helper", [False, True])
@pytest.mark.parametrize("wrap_context", [False, True])
def test_typed_bulk_collection_slot_receives_the_wrapper(
    context_first: bool, via_helper: bool, wrap_context: bool
) -> None:
    parameters = "tenant: str, key: str" if context_first else "key: str, tenant: str"
    arguments = "scope=[tenant], keys=key" if wrap_context else "scope=tenant, keys=[key]"
    delegation = f"return self.get_many({arguments})"
    body = "return self._one(key, tenant)" if via_helper else delegation
    source = f"class UserService:\n    def get(self, {parameters}):\n{indent(body, '        ')}\n    def get_many(self, scope: str, keys: list[str]):\n        return self.backend.fetch_many(keys, scope)\n"
    if via_helper:
        source += f"    def _one(self, key, tenant):\n{indent(delegation, '        ')}\n"
    assert len(_check(source)) == (1 if wrap_context else 0)


@pytest.mark.parametrize(
    ("prefix", "annotation"),
    [
        ("", "tuple[str, ...]"),
        ("", "set[str]"),
        ("from collections.abc import Sequence as Batch\n", "Batch[str]"),
        ("from typing import Collection\n", "Collection[str]"),
        ("", "'list[str]'"),
    ],
    ids=["tuple", "set", "imported-sequence", "imported-collection", "quoted-list"],
)
def test_proven_collection_annotation_controls_bulk_argument(prefix: str, annotation: str) -> None:
    source = "class UserService:\n    def get(self, key: str, tenant: str):\n        return self.get_many(key, scope=[tenant])\n    def get_many(self, keys: list[str], *, scope: str):\n        return self.backend.fetch_many(keys, scope)\n"
    assert len(_check(prefix + source.replace("keys: list[str]", f"keys: {annotation}"))) == 1


@pytest.mark.parametrize(
    ("prefix", "parameters", "generic"),
    [
        ("", "keys, *, scope", ""),
        ("", "keys: Unknown, *, scope: str", ""),
        ("", "keys: list[str], *, scope: list[str]", ""),
        ("list = CustomCollection\n", "keys: list[str], *, scope: str", ""),
        ("", "keys: list[str], *, scope: str", "[list]"),
    ],
    ids=["untyped", "unknown", "two-collections", "shadowed-list", "generic-list"],
)
def test_uncertain_collection_slots_do_not_infer_argument_roles(prefix: str, parameters: str, generic: str) -> None:
    source = f"class UserService:\n    def get(self, key: str, tenant: str):\n        return self.get_many(key, scope=[tenant])\n    def get_many{generic}(self, {parameters}):\n        return self.backend.fetch_many(keys, scope)\n"
    assert _check(prefix + source) == []


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


@pytest.mark.parametrize("module", ["typing", "typing_extensions"])
def test_concrete_protocol_implementations_keep_the_bulk_requirement(module: str) -> None:
    source = f"from {module} import Protocol\nclass UserService(Protocol):\n    def get(self, key): ...\nclass Child(UserService):\n    def get(self, key):\n        return self.backend.get(key)\n"
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 5


@pytest.mark.parametrize("base", ["BaseModel", "RootModel", "Exception", "TypedDict"])
@pytest.mark.parametrize("child", ["Child", "ChildService"])
def test_known_data_model_ancestry_does_not_leak_service_roles(base: str, child: str) -> None:
    source = f"class UserService({base}):\n    def get_many(self, keys):\n        return keys\nclass Middle(UserService):\n    pass\nclass {child}(Middle):\n    def get(self, key):\n        return self.backend.get(key)\n"
    assert _check(source) == []


def test_inherited_abstract_declaration_remains_excluded() -> None:
    source = "from abc import ABC, abstractmethod\nclass UserService(ABC):\n    @abstractmethod\n    def get(self, key):\n        return self.backend.get(key)\nclass Child(UserService):\n    @abstractmethod\n    def get(self, key):\n        return self.backend.get(key)\n"
    assert _check(source) == []


def test_unrelated_protocol_name_does_not_exclude_real_service() -> None:
    source = "class Protocol:\n    pass\n" + _service("return self.backend.get(key)", bulk_body=None).replace(
        "class UserService:", "class UserService(Protocol):"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize("role", ["Service", "Store", "Repository"])
@pytest.mark.parametrize("implementation", ["Implementation", "Worker", "UserServiceImpl"])
def test_same_file_role_contract_applies_to_concrete_implementations(role: str, implementation: str) -> None:
    source = f"from abc import ABC, abstractmethod\nclass User{role}(ABC):\n    @abstractmethod\n    def get(self, key): ...\nclass {implementation}(User{role}):\n    def get(self, key):\n        return self.backend.get(key)\n"
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 6


@pytest.mark.parametrize(
    "base",
    [
        "class Base:\n    pass\nBase = external_base()\n",
        "@rewrite\nclass Base:\n    pass\n",
        "class Base(metaclass=Meta):\n    pass\n",
    ],
)
def test_unstable_base_cannot_prove_missing_bulk(base: str) -> None:
    source = base + _service("return self.backend.get(key)", bulk_body=None).replace(
        "class UserService:", "class UserService(Base):"
    )
    assert _check(source) == []


def test_later_base_redefinition_cannot_erase_the_original_bulk() -> None:
    source = (
        "class Base:\n    def get_many(self, keys):\n        return keys\n"
        + _service("return self.get_many([key])[0]", bulk_body=None).replace(
            "class UserService:", "class UserService(Base):"
        )
        + "class Base:\n    pass\n"
    )
    assert _check(source) == []


def test_explicit_metaclass_can_replace_the_service_api() -> None:
    source = _service("return self.backend.get(key)", bulk_body=None).replace(
        "class UserService:", "class UserService(metaclass=Meta):"
    )
    assert _check(source) == []


@pytest.mark.parametrize("aliased", [False, True], ids=["direct", "stable-local-bound-alias"])
@pytest.mark.parametrize(
    ("bulk_name", "asynchronous", "via_helper"),
    [
        ("get_many", False, False),
        ("get_by_ids", True, False),
        ("get_many", False, True),
        ("get_by_ids", True, True),
    ],
    ids=["sync-many-context", "awaited-ids-context", "private-helper-context", "awaited-private-helper-context"],
)
def test_stable_local_bound_adapters_match_direct_calls(
    aliased: bool, bulk_name: str, asynchronous: bool, via_helper: bool
) -> None:
    prefix = "async " if asynchronous else ""
    awaited = "await " if asynchronous else ""
    member = "_one" if via_helper else bulk_name
    arguments = "key, tenant" if via_helper else "[key], scope=tenant"
    body = (
        f"fetch = self.{member}\nreturn {awaited}fetch({arguments})"
        if aliased
        else f"return {awaited}self.{member}({arguments})"
    )
    source = f"class UserService:\n    {prefix}def get(self, key, tenant):\n{indent(body, '        ')}\n    {prefix}def {bulk_name}(self, keys, *, scope):\n        return self.backend.fetch_many(keys, scope)\n"
    if via_helper:
        source += f"    {prefix}def _one(self, key, tenant):\n        fetch = self.{bulk_name}\n        return {awaited}fetch([key], scope=tenant)\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    "body",
    [
        "fetch = self.get_many\nfetch = self.backend.get_many\nreturn fetch([key])",
        "fetch = self.backend.get_many\nreturn fetch([key])",
        "fetch = self.get_many\nreturn self.backend.get(key)",
        "return fetch([key])\nfetch = self.get_many",
        "fetch = getattr(self, 'get_many')\nreturn fetch([key])",
        "fetch = self.get_many if enabled else self.backend.get_many\nreturn fetch([key])",
        "fetch = self.get_many\nregister(fetch)\nreturn fetch([key])",
        "fetch = self.get_many\ndef nested():\n    return fetch([key])\nreturn nested()",
        "fetch = self.get_many\nother_fetch = fetch\nreturn other_fetch([key])",
        "self = other\nfetch = self.get_many\nreturn fetch([key])",
        "fetch = self.get_many\nself = other\nreturn fetch([key])",
        "fetch = self.get_many\nreturn fetch(['other'])",
        "fetch = self.get_many\nreturn fetch(keys=[key], extra=True)",
        "receiver = self\nfetch = receiver.get_many\nreturn fetch([key])",
    ],
    ids=[
        "rebound-alias",
        "wrong-receiver",
        "unused-alias",
        "before-assignment",
        "dynamic-getattr",
        "ambiguous-conditional",
        "escaped-callback",
        "closure-call",
        "alias-chain",
        "rebound-receiver-before",
        "rebound-receiver-after",
        "changed-item",
        "bad-signature",
        "object-receiver-alias-deferred",
    ],
)
def test_unproven_local_callables_do_not_establish_delegation(body: str) -> None:
    assert len(_check(_service(body))) == 1


@pytest.mark.parametrize("awaited", [False, True], ids=["unawaited", "awaited"])
def test_local_async_bound_alias_requires_await(awaited: bool) -> None:
    body = f"fetch = self.get_many\nreturn {'await ' if awaited else ''}fetch([key])"
    source = _service(body).replace("    def ", "    async def ")
    assert len(_check(source)) == (0 if awaited else 1)


@pytest.mark.parametrize(
    "bulk_body",
    [
        "fetch = self.get\nreturn [fetch(key) for key in keys]",
        "fetch = self.get\nfor key in keys:\n    fetch(key)",
        "fetch = self.get\nregister(fetch)\nreturn [fetch(key) for key in keys]",
        "fetch = self._read_each\nreturn fetch(keys)",
    ],
    ids=[
        "singleton-alias-comprehension",
        "singleton-alias-loop",
        "escaped-alias-explicit-reverse-call",
        "private-helper-alias-cycle",
    ],
)
def test_local_bound_alias_cannot_hide_reverse_singleton_calls(bulk_body: str) -> None:
    source = _service("fetch = self.get_many\nreturn fetch([key])", bulk_body=bulk_body)
    source += "    def _read_each(self, keys):\n        fetch = self.get\n        return [fetch(key) for key in keys]\n"
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert "calls back through the singleton" in diagnostics[0].message


@pytest.mark.parametrize(
    ("bulk_body", "expected"),
    [
        ("self = other\nreturn [self.get(key) for key in keys]", 0),
        ("self = other\nfetch = self.get\nreturn [fetch(key) for key in keys]", 0),
        ("fetch = self.get\nself = other\nreturn [fetch(key) for key in keys]", 0),
        ("return self._read_each(keys)", 0),
    ],
    ids=["rebound-direct", "rebound-before-alias", "uncertain-rebound-alias", "rebound-helper"],
)
def test_reverse_edges_require_the_original_receiver(bulk_body: str, expected: int) -> None:
    source = _service("return self.get_many([key])", bulk_body=bulk_body)
    source += "    def _read_each(self, keys):\n        self = other\n        return [self.get(key) for key in keys]\n"
    assert len(_check(source)) == expected


def test_forward_receiver_identity_alias_remains_a_valid_adapter() -> None:
    assert _check(_service("self = self\nreturn self.get_many([key])")) == []


@pytest.mark.parametrize(
    "bulk_body",
    [
        "fetch = self.get\nfetch = self.backend.get\nreturn [fetch(key) for key in keys]",
        "fetch = self.backend.get\nreturn [fetch(key) for key in keys]",
        "fetch = self.get\nreturn self.backend.fetch_many(keys)",
    ],
    ids=["rebound-singleton-alias", "wrong-singleton-receiver", "unused-singleton-alias"],
)
def test_unproven_or_unused_aliases_do_not_invent_reverse_calls(bulk_body: str) -> None:
    assert _check(_service("fetch = self.get_many\nreturn fetch([key])", bulk_body=bulk_body)) == []


@pytest.mark.parametrize(
    "body",
    [
        "fetch = self.get_many\nreturn fetch([key], scope='other')",
        "fetch = self.get_many\nreturn fetch([key])",
    ],
    ids=["changed-context", "missing-context"],
)
def test_local_bound_alias_must_forward_original_context(body: str) -> None:
    source = f"class UserService:\n    def get(self, key, tenant):\n{indent(body, '        ')}\n    def get_many(self, keys, *, scope):\n        return self.backend.fetch_many(keys, scope)\n"
    assert len(_check(source)) == 1


def test_annotated_local_bound_alias_preserves_callable_identity() -> None:
    assert _check(_service("fetch: object = self.get_many\nreturn fetch([key])")) == []


@pytest.mark.parametrize("aliased", [False, True], ids=["direct", "stable-bound-alias"])
@pytest.mark.parametrize("helpers", [1, 2, 63, 64])
def test_awaited_sync_helper_returns_bulk_coroutine(aliased: bool, helpers: int) -> None:
    body = (
        "fetch = self._relay0\nreturn await fetch(key, tenant)" if aliased else "return await self._relay0(key, tenant)"
    )
    source = f"class UserService:\n    async def get(self, key: str, tenant: str):\n{indent(body, '        ')}\n    async def get_many(self, keys: list[str], *, scope: str):\n        return keys\n"
    helper_sources: list[str] = []
    for index in range(helpers):
        member = f"_relay{index + 1}" if index + 1 < helpers else "get_many"
        arguments = "value, tenant" if index + 1 < helpers else "[value], scope=tenant"
        body = f"fetch = self.{member}\nreturn fetch({arguments})" if aliased else f"return self.{member}({arguments})"
        helper_sources.append(f"    def _relay{index}(self, value, tenant):\n{indent(body, '        ')}\n")
    source += "".join(helper_sources)
    assert len(_check(source)) == (1 if helpers == 64 else 0)


@pytest.mark.parametrize(
    ("caller", "helper", "extra"),
    [
        ("return self._one(key, tenant)", "return self.get_many([key], scope=tenant)", ""),
        ("return await self._one(key, tenant)", "self.get_many([key], scope=tenant)\nreturn other", ""),
        ("return await self._one(key, tenant)", "return self.get_many([key], scope=tenant)[0]", ""),
        ("return await self._one(key, tenant)", "return wrap(self.get_many([key], scope=tenant))", ""),
        ("return await self._one(key, tenant)", "return self.get_many([key], scope=tenant) if enabled else other", ""),
        ("return await self._one(key, tenant)", "return lambda: self.get_many([key], scope=tenant)", ""),
        ("return await self._one(key, tenant)", "return (self.get_many([key], scope=tenant) for _ in items)", ""),
        (
            "return await self._one(key, tenant)",
            "def nested():\n    return self.get_many([key], scope=tenant)\nreturn nested()",
            "",
        ),
        ("return await self._one(key, tenant)", "yield other\nreturn self.get_many([key], scope=tenant)", ""),
        ("return await self._one(key, tenant)", "return other.get_many([key], scope=tenant)", ""),
        ("return await self._one(key, tenant)", "self = other\nreturn self.get_many([key], scope=tenant)", ""),
        (
            "return await self._one(key, tenant)",
            "fetch = self.get_many\nregister(fetch)\nreturn fetch([key], scope=tenant)",
            "",
        ),
        (
            "return await self._one(key, tenant)",
            "fetch = self.get_many\nfetch = other.get_many\nreturn fetch([key], scope=tenant)",
            "",
        ),
        ("return await self._one(key, tenant)", "return self.get_many(['other'], scope=tenant)", ""),
        ("return await self._one(key, tenant)", "return self.get_many([key], scope='other')", ""),
        (
            "return await self._one(key, tenant)",
            "return self._two(key, tenant)",
            "    async def _two(self, key, tenant):\n        return self.get_many([key], scope=tenant)\n",
        ),
        (
            "return await self._one(key, tenant)",
            "return self._two(key, tenant)",
            "    def _two(self, key, tenant):\n        return self._one(key, tenant)\n",
        ),
    ],
    ids=[
        "unawaited-caller",
        "discarded-coroutine",
        "result-projection",
        "wrapped-call",
        "conditional-return",
        "lambda",
        "generator-expression",
        "nested-function",
        "generator-helper",
        "another-receiver",
        "rebound-receiver",
        "escaped-callable",
        "rebound-callable",
        "changed-item",
        "changed-context",
        "async-helper-returns-inner-coroutine",
        "sync-helper-cycle",
    ],
)
def test_sync_coroutine_relay_requires_exact_eager_return(caller: str, helper: str, extra: str) -> None:
    source = f"class UserService:\n    async def get(self, key: str, tenant: str):\n{indent(caller, '        ')}\n    async def get_many(self, keys: list[str], *, scope: str):\n        return keys\n    def _one(self, key, tenant):\n{indent(helper, '        ')}\n{extra}"
    assert len(_check(source)) == 1


def test_awaiting_async_helper_does_not_await_returned_coroutine() -> None:
    source = "class UserService:\n    async def get(self, key: str):\n        return await self._one(key)\n    async def get_many(self, keys: list[str]):\n        return keys\n    async def _one(self, key):\n        return self.get_many([key])\n"
    assert len(_check(source)) == 1


def test_sync_relay_can_return_async_helper_that_awaits_bulk() -> None:
    source = "class UserService:\n    async def get(self, key: str):\n        return await self._one(key)\n    async def get_many(self, keys: list[str]):\n        return keys\n    def _one(self, key):\n        return self._two(key)\n    async def _two(self, key):\n        return await self.get_many([key])\n"
    assert _check(source) == []


def test_sync_helper_await_state_is_distinct_for_identical_bindings() -> None:
    source = "class UserService:\n    async def get(self, key: str):\n        await self._one(key)\n        return self._one(key)\n    async def get_many(self, keys: list[str]):\n        return keys\n    def _one(self, key):\n        return self.get_many([key])\n"
    assert _check(source) == []


def test_sync_coroutine_relay_preserves_reverse_call_detection() -> None:
    source = "class UserService:\n    async def get(self, key: str):\n        return await self._one(key)\n    async def get_many(self, keys: list[str]):\n        fetch = self.get\n        return [fetch(key) for key in keys]\n    def _one(self, key):\n        return self.get_many([key])\n"
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert "calls back through the singleton" in diagnostics[0].message


@pytest.mark.parametrize(
    "bulk_body",
    [
        "return self.backend.fetch_many(keys)\nself.get(keys[0])",
        "raise RuntimeError('stop')\nself.get(keys[0])",
        "if False:\n    self.get(keys[0])\nreturn self.backend.fetch_many(keys)",
        "if True:\n    pass\nelse:\n    self.get(keys[0])\nreturn self.backend.fetch_many(keys)",
        "False and self.get(keys[0])\nreturn self.backend.fetch_many(keys)",
        "True or self.get(keys[0])\nreturn self.backend.fetch_many(keys)",
        "enabled and False and self.get(keys[0])\nreturn self.backend.fetch_many(keys)",
        "enabled or True or self.get(keys[0])\nreturn self.backend.fetch_many(keys)",
        "return self.get(keys[0]) if False else self.backend.fetch_many(keys)",
        "return self.backend.fetch_many(keys) if True else self.get(keys[0])",
        "if enabled:\n    return keys\n    self.get(keys[0])\nreturn self.backend.fetch_many(keys)",
    ],
    ids=[
        "after-return",
        "after-raise",
        "false-body",
        "true-else",
        "false-and",
        "true-or",
        "unknown-before-false-and",
        "unknown-before-true-or",
        "false-conditional-expression",
        "true-conditional-expression",
        "nested-after-return",
    ],
)
def test_provably_dead_reverse_calls_do_not_reject_bulk_primitives(bulk_body: str) -> None:
    assert _check(_service("return self.get_many([key])", bulk_body=bulk_body)) == []


@pytest.mark.parametrize(
    "bulk_body",
    [
        "if enabled:\n    self.get(keys[0])\nreturn self.backend.fetch_many(keys)",
        "if False:\n    pass\nelse:\n    self.get(keys[0])\nreturn self.backend.fetch_many(keys)",
        "enabled and self.get(keys[0])\nreturn self.backend.fetch_many(keys)",
        "False or self.get(keys[0])\nreturn self.backend.fetch_many(keys)",
        "True and self.get(keys[0])\nreturn self.backend.fetch_many(keys)",
        "for key in keys:\n    self.get(key)\nreturn keys",
        "return [self.get(key) for key in keys]",
        "return {self.get(key) for key in keys}",
        "return {key: self.get(key) for key in keys}",
        "return (self.get(key) for key in keys)",
        "unused = (self.get(key) for key in keys)\nreturn self.backend.fetch_many(keys)",
        "try:\n    return self.backend.fetch_many(keys)\nfinally:\n    self.get(keys[0])",
        "fetch = self.get\nif enabled:\n    fetch(keys[0])\nreturn self.backend.fetch_many(keys)",
    ],
    ids=[
        "unknown-branch",
        "active-else",
        "unknown-and",
        "false-or",
        "true-and",
        "loop",
        "list-comprehension",
        "set-comprehension",
        "dict-comprehension",
        "returned-generator",
        "potential-generator-consumption",
        "finally-after-return",
        "bound-alias-unknown-branch",
    ],
)
def test_potential_reverse_calls_remain_errors(bulk_body: str) -> None:
    diagnostics = _check(_service("return self.get_many([key])", bulk_body=bulk_body))
    assert len(diagnostics) == 1
    assert "calls back through the singleton" in diagnostics[0].message


@pytest.mark.parametrize("used_bulk", ["get_many", "get_by_ids"])
@pytest.mark.parametrize("reverse_bulk", [None, "get_many", "get_by_ids"])
def test_multiple_bulk_names_accept_any_adapter_but_reject_each_reverse_edge(
    used_bulk: str, reverse_bulk: str | None
) -> None:
    source = _service(f"fetch = self.{used_bulk}\nreturn fetch([key])", bulk_body=None)
    for name in ("get_many", "get_by_ids"):
        body = (
            "return [self.get(key) for key in keys]" if name == reverse_bulk else "return self.backend.fetch_many(keys)"
        )
        source += f"    def {name}(self, keys):\n        {body}\n"
    diagnostics = _check(source)
    assert len(diagnostics) == int(reverse_bulk is not None)
    if diagnostics:
        assert "calls back through the singleton" in diagnostics[0].message


@pytest.mark.parametrize("inherited_write", [False, True], ids=["own-write", "inherited-write"])
@pytest.mark.parametrize("inherited_bulk", [False, True], ids=["own-method", "inherited-method"])
@pytest.mark.parametrize(
    "write",
    [
        "self.get_many = primitive",
        "del self.get_many",
        "setattr(self, 'get_many', primitive)",
        "delattr(self, 'get_many')",
    ],
    ids=["assignment", "deletion", "builtin-assignment", "builtin-deletion"],
)
def test_instance_bulk_masks_survive_method_overrides(inherited_write: bool, inherited_bulk: bool, write: str) -> None:
    initializer = f"    def __init__(self, primitive):\n        {write}\n"
    bulk = "    def get_many(self, keys):\n        return [self.get(key) for key in keys]\n"
    source = "class Base:\n    pass\n"
    if inherited_write:
        source += initializer
    if inherited_bulk:
        source += bulk
    source += "class UserService(Base):\n    def get(self, key):\n        return self.backend.fetch(key)\n"
    if not inherited_write:
        source += initializer
    if not inherited_bulk:
        source += bulk
    assert _check(source) == []


@pytest.mark.parametrize("member", ["get", "get_many", "__class__"])
def test_literal_builtin_member_masks_defer_the_original_method_body(member: str) -> None:
    source = _service("return self.backend.fetch(key)")
    source += f"    def __init__(self, primitive):\n        setattr(self, {member!r}, primitive)\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    "setup",
    [
        "setattr(other, 'get_many', primitive)",
        "self = other\nsetattr(self, 'get_many', primitive)",
        "setattr = primitive\nsetattr(self, 'get_many', primitive)",
        "if enabled:\n    setattr = primitive\nelse:\n    setattr = replacement\nsetattr(self, 'get_many', primitive)",
        "setattr(self, member, primitive)",
        "opaque(self, 'get_many', primitive)",
        "setattr(*(self, 'get_many', primitive))",
        "setattr(self, 'get_many', value=primitive)",
    ],
    ids=[
        "other-receiver",
        "rebound-self",
        "shadowed",
        "ambiguous-binding",
        "unknown-member",
        "opaque",
        "starred",
        "keyword",
    ],
)
def test_unproven_named_mutations_do_not_hide_a_declared_bulk_contract(setup: str) -> None:
    source = _service("return self.backend.fetch(key)")
    source += f"    def __init__(self, primitive):\n{indent(setup, '        ')}\n"
    assert len(_check(source)) == 1


def _bound_resource_service(
    *,
    getter: str = "def get(self) -> Document:\n    return self.backend.load()",
    update: str = "def update(self, value: Document) -> Document:\n    return self.backend.save(value)",
    extra: str = "",
    model: str = "from pydantic import BaseModel\nclass Document(BaseModel):\n    value: str\n",
) -> str:
    return model + "class RecordService:\n" + indent(f"{getter}\n{update}\n{extra}", "    ") + "\n"


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("quoted", [False, True], ids=["direct-type", "quoted-type"])
@pytest.mark.parametrize("positional_only", [False, True], ids=["ordinary-self", "positional-only-self"])
def test_bound_resource_update_defers_missing_bulk_ambiguity(
    asynchronous: bool, quoted: bool, positional_only: bool
) -> None:
    source = _bound_resource_service()
    if asynchronous:
        source = source.replace("def ", "async def ")
    if quoted:
        source = source.replace("-> Document:", "-> 'Document':")
    if positional_only:
        source = source.replace("get(self)", "get(self, /)")
    assert _check(source) == []


@pytest.mark.parametrize(
    "model",
    [
        "import pydantic as models\nclass Document(models.BaseModel):\n    value: str\n",
        "from pydantic import BaseModel as Model\nclass Document(Model):\n    value: str\n",
        "from pydantic import RootModel\nclass Document(RootModel[str]):\n    pass\n",
        "from typing import NamedTuple\nclass Document(NamedTuple):\n    value: str\n",
        "from typing import TypedDict\nclass Document(TypedDict):\n    value: str\n",
    ],
    ids=["namespace", "import-alias", "root-model", "named-tuple", "typed-dict"],
)
def test_bound_resource_model_requires_a_proven_data_model_import(model: str) -> None:
    assert _check(_bound_resource_service(model=model)) == []


@pytest.mark.parametrize(
    "getter",
    [
        "def get(self, key: str) -> Document:\n    return self.backend.load(key)",
        "def get(self, key: str | None = None) -> Document:\n    return self.backend.load(key)",
        "def get(self, *, tenant: str) -> Document:\n    return self.backend.load(tenant)",
        "def get(self, *keys) -> Document:\n    return self.backend.load(keys)",
        "def get(self, **context) -> Document:\n    return self.backend.load(context)",
        "def get(self=None) -> Document:\n    return self.backend.load()",
        "def get(other) -> Document:\n    return other.backend.load()",
        "def get(self) -> Document:\n    yield self.backend.load()",
        "async def get(self) -> Document:\n    yield self.backend.load()",
        "def get(self) -> Document:\n    pass",
        "def get(self) -> Document:\n    ...",
        "def get(self) -> Document:\n    raise NotImplementedError",
        "@property\ndef get(self) -> Document:\n    return self.backend.load()",
        "@staticmethod\ndef get(self) -> Document:\n    return self.backend.load()",
        "@classmethod\ndef get(self) -> Document:\n    return self.backend.load()",
        "@rewrite\ndef get(self) -> Document:\n    return self.backend.load()",
        "def get[Document](self) -> Document:\n    return self.backend.load()",
    ],
    ids=[
        "keyed",
        "optional-key",
        "keyword-context",
        "varargs",
        "kwargs",
        "default-self",
        "other-receiver",
        "generator",
        "async-generator",
        "pass-stub",
        "ellipsis-stub",
        "raising-stub",
        "property",
        "static",
        "class",
        "rewriting-decorator",
        "method-type-parameter",
    ],
)
def test_bound_resource_deferral_requires_an_own_concrete_parameterless_getter(getter: str) -> None:
    diagnostics = _check(_bound_resource_service(getter=getter))
    assert any("RecordService.update" in diagnostic.message for diagnostic in diagnostics)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("get(self) -> Document", "get(self)"),
        ("value: Document) -> Document", "value: Document)"),
        ("get(self) -> Document", "get(self) -> list[Document]"),
        ("-> Document", "-> list[Document]"),
        ("-> Document", "-> None"),
        ("-> Document", "-> object"),
        ("-> Document", "-> Any"),
        ("-> Document", "-> Alias"),
        ("update(self, value: Document)", "update[Document](self, value: Document)"),
        ("class RecordService:", "class RecordService[Document]:"),
    ],
    ids=[
        "unannotated-get",
        "unannotated-update",
        "collection-get-single-item-update",
        "collection-returns",
        "none-returns",
        "object-returns",
        "unknown-any",
        "unresolved-alias",
        "update-type-parameter",
        "class-type-parameter",
    ],
)
def test_bound_resource_return_identity_must_name_the_same_local_model(before: str, after: str) -> None:
    source = _bound_resource_service().replace(before, after)
    assert any("RecordService.update" in diagnostic.message for diagnostic in _check(source))


@pytest.mark.parametrize(
    "model",
    [
        "class BaseModel:\n    pass\nclass Document(BaseModel):\n    value: str\n",
        "from third_party import BaseModel\nclass Document(BaseModel):\n    value: str\n",
        "from pydantic import BaseModel\nBaseModel = replacement\nclass Document(BaseModel):\n    value: str\n",
        "import pydantic\npydantic.BaseModel = replacement\nclass Document(pydantic.BaseModel):\n    value: str\n",
        "from pydantic import BaseModel\n@rewrite\nclass Document(BaseModel):\n    value: str\n",
        "from pydantic import BaseModel\nclass Document(BaseModel):\n    value: str\nDocument = replacement\n",
        "from pydantic import BaseModel\nclass Document(BaseModel):\n    value: str\ndef replace_model():\n    global Document\n    Document = replacement\n",
        "from pydantic import BaseModel\nclass Data(BaseModel):\n    value: str\nDocument = Data\n",
        "from external import Document\n",
    ],
    ids=[
        "local-base-spelling",
        "other-library-base",
        "rebound-base-import",
        "mutated-base-namespace",
        "rewritten-model",
        "rebound-model",
        "global-model-write",
        "model-alias",
        "imported-model",
    ],
)
def test_bound_resource_deferral_does_not_infer_unknown_or_rebound_models(model: str) -> None:
    assert any(
        "RecordService.update" in diagnostic.message for diagnostic in _check(_bound_resource_service(model=model))
    )


@pytest.mark.parametrize(
    "extra",
    [
        "get = replacement",
        "def get(self) -> Document:\n    return other.load()",
        "def __init__(self, replacement):\n    self.get = replacement",
        "def __init__(self, replacement):\n    setattr(self, 'get', replacement)",
        "Document = replacement",
    ],
    ids=["class-get-write", "duplicate-get", "instance-get-write", "builtin-get-write", "class-model-shadow"],
)
def test_bound_resource_getter_and_model_bindings_must_remain_stable(extra: str) -> None:
    assert any(
        "RecordService.update" in diagnostic.message for diagnostic in _check(_bound_resource_service(extra=extra))
    )


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("literal", [False, True], ids=["declared", "literal-member"])
def test_any_crud_bulk_peer_keeps_update_policy_enforced(operation: str, literal: bool) -> None:
    extra = f"{operation}_many = None" if literal else f"def {operation}_many(self, values):\n    return values"
    diagnostics = _check(_bound_resource_service(extra=extra))
    assert any("RecordService.update" in diagnostic.message for diagnostic in diagnostics)


@pytest.mark.parametrize(
    "extra",
    [
        "def get_by_ids(self, keys):\n    return keys",
        "def __init__(self, replacement):\n    self.get_many = replacement",
    ],
    ids=["alternate-read-peer", "uncertain-instance-peer"],
)
def test_bound_resource_deferral_requires_no_known_or_uncertain_bulk_peer(extra: str) -> None:
    assert any(
        "RecordService.update" in diagnostic.message for diagnostic in _check(_bound_resource_service(extra=extra))
    )


def test_bound_resource_shape_does_not_hide_reverse_update_calls() -> None:
    source = _bound_resource_service(
        extra="def update_many(self, values):\n    return [self.update(value) for value in values]"
    )
    assert any("calls back through the singleton" in diagnostic.message for diagnostic in _check(source))


@pytest.mark.parametrize("operation", ["create", "delete"])
def test_bound_resource_shape_does_not_exempt_other_crud(operation: str) -> None:
    source = _bound_resource_service(
        extra=f"def {operation}(self, value: Document) -> Document:\n    return self.backend.execute(value)"
    )
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert f"RecordService.{operation}" in diagnostics[0].message


def test_inherited_parameterless_getter_does_not_prove_bound_update() -> None:
    source = _bound_resource_service(getter="def get(self) -> Document:\n    return self.backend.load()", update="")
    source += "class Child(RecordService):\n    def update(self, value: Document) -> Document:\n        return self.backend.save(value)\n"
    assert any("Child.update" in diagnostic.message for diagnostic in _check(source))


def test_later_model_declaration_does_not_prove_bound_resource_identity() -> None:
    model = "from pydantic import BaseModel\nclass Document(BaseModel):\n    value: str\n"
    assert len(_check(_bound_resource_service(model="") + model)) == 1
