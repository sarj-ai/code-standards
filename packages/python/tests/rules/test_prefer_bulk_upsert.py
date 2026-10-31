from pathlib import Path
from textwrap import dedent, indent
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rules.prefer_bulk_upsert import PreferBulkUpsert


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


CONTRACT = """
class UserStore:
    async def upsert(self, user: UserInput) -> User:
        ...
    async def upsert_many(self, users: list[UserInput]) -> list[User]:
        ...
"""


def _check(body: str, contract: str = CONTRACT) -> list[Diagnostic]:
    return PreferBulkUpsert().check(Path("app/service.py"), dedent(contract) + "\n" + dedent(body))


@pytest.mark.parametrize("argument", ["user", "UserInput(name=user.name)"])
def test_flags_discarded_serial_upserts_with_proven_bulk_contract(argument: str) -> None:
    findings = _check(f"""
    async def save(store: UserStore, users: list[UserInput]):
        for user in users:
            await store.upsert({argument})
    """)
    assert len(findings) == 1
    assert findings[0].code == "SARJ516"
    assert "upsert_many" in findings[0].message


@pytest.mark.parametrize("member", ["upsert", "upsert_many"])
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
    ],
)
def test_pair_markers_use_class_evaluation_binding(member: str, before: str, after: str, expected: int) -> None:
    contract = CONTRACT.replace("class UserStore:", "class UserStore:\n" + indent(before, "    "))
    contract = contract.replace(f"    async def {member}(", f"    @marker\n    async def {member}(")
    contract += indent(after, "    ") + "\n"
    source = "from typing import override as marker\n" + contract
    caller = "async def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)\n"
    assert len(_check(caller, source)) == expected


@pytest.mark.parametrize("module", ["typing", "typing_extensions", "abc"])
@pytest.mark.parametrize("shadow", ["", "    markers = replacement\n", "    markers.MARKER = rewrite\n"])
def test_pair_namespace_markers_require_original_binding(module: str, shadow: str) -> None:
    marker = "abstractmethod" if module == "abc" else "override"
    contract = CONTRACT.replace("class UserStore:", "class UserStore:\n" + shadow.replace("MARKER", marker))
    contract = contract.replace("    async def upsert(", f"    @markers.{marker}\n    async def upsert(")
    caller = "async def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)\n"
    assert len(_check(caller, f"import {module} as markers\n" + contract)) == (0 if shadow else 1)


@pytest.mark.parametrize("marker", ["final", "property", "staticmethod", "classmethod"])
def test_unproven_or_descriptor_pair_markers_remain_excluded(marker: str) -> None:
    contract = "from typing import final\n" + CONTRACT.replace(
        "    async def upsert(", f"    @{marker}\n    async def upsert("
    )
    assert (
        _check(
            "async def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)\n",
            contract,
        )
        == []
    )


@pytest.mark.parametrize(
    "body",
    [
        "await store.upsert_many(users)",
        "for user in users:\n        saved = await store.upsert(user)",
        "for user in users:\n        await store.upsert(user)\n        notify(user)",
        "for user in users:\n        if allowed(user):\n            await store.upsert(user)",
        "for user in users:\n        try:\n            await store.upsert(user)\n        except Conflict:\n            continue",
        "for user in users:\n        await store.upsert(user)\n        break",
        "async for user in users:\n        await store.upsert(user)",
        "for user in users:\n        await another.upsert(user)",
        "for user in users:\n        await store.upsert(user, strict=True)",
        "for user in users:\n        await store.upsert(*user)",
        "for user in users:\n        await store.upsert(**user)",
        "for user in users:\n        await store.upsert(user)\n    else:\n        notify()",
        "for user in users:\n        await store.upsert(fixed)",
        "for user in users:\n        def deferred():\n            return store.upsert(user)",
    ],
)
def test_preserves_dependent_results_control_flow_and_unknown_receivers(body: str) -> None:
    assert _check(f"async def save(store: UserStore, users):\n    {body}\n") == []


@pytest.mark.parametrize(
    "replacement",
    [
        ("users: list[UserInput]", "users: list[OtherInput]"),
        ("list[User]:", "list[Other]:"),
        ("upsert_many", "save_many"),
        ("users: list[UserInput]", "users: UserInput"),
        ("users: list[UserInput]", "users: list[UserInput], tenant: str"),
        ("async def upsert_many", "def upsert_many"),
    ],
    ids=[
        "different-input",
        "different-output",
        "no-bulk-api",
        "scalar-bulk-argument",
        "extra-context",
        "sync-mismatch",
    ],
)
def test_requires_compatible_declared_bulk_signature(replacement: tuple[str, str]) -> None:
    contract = CONTRACT.replace(*replacement)
    assert (
        _check(
            "async def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)",
            contract,
        )
        == []
    )


def test_follows_constructor_injected_store() -> None:
    assert (
        len(
            _check("""
    class Service:
        def __init__(self, store: UserStore):
            self.store = store
        async def save(self, users):
            for user in users:
                await self.store.upsert(user)
    """)
        )
        == 1
    )


def test_receiver_rebinding_invalidates_annotation() -> None:
    assert (
        _check("""
    async def save(store: UserStore, users):
        store = other
        for user in users:
            await store.upsert(user)
    """)
        == []
    )


def test_loop_target_does_not_prove_store_receiver() -> None:
    assert (
        _check("""
    async def save(store: UserStore, users):
        for store in users:
            await store.upsert(store)
    """)
        == []
    )


def test_keyword_input_is_supported() -> None:
    assert (
        len(
            _check("""
    async def save(store: UserStore, users):
        for user in users:
            await store.upsert(user=user)
    """)
        )
        == 1
    )


def test_sync_contract_and_call_are_supported() -> None:
    assert (
        len(
            _check(
                """
    def save(store: UserStore, users):
        for user in users:
            store.upsert(user)
    """,
                CONTRACT.replace("async def", "def"),
            )
        )
        == 1
    )


@pytest.mark.parametrize("header", ["# Generated file. Do not edit.\n", "# @generated\n"])
def test_generated_sources_are_excluded(header: str) -> None:
    assert (
        PreferBulkUpsert().check(
            Path("app/service.py"),
            header
            + CONTRACT
            + "\nasync def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)\n",
        )
        == []
    )


@pytest.mark.parametrize(
    "example",
    PreferBulkUpsert.public_examples(),
    ids=tuple(example.example_id for example in PreferBulkUpsert.public_examples()),
)
def test_public_examples(example: RuleExample) -> None:
    assert (
        len(PreferBulkUpsert().check(Path(example.focus_file.path), example.focus_file.source))
        == example.expected_count
    )


def test_native_examples() -> None:
    verify_native_rule(PreferBulkUpsert, analyze)


def _case_id(case: EvaluationCase) -> str:
    return case.case_id


@pytest.mark.parametrize(
    "case",
    [
        EvaluationCase("malformed-source", Language.PYTHON, "def save(:"),
        EvaluationCase(
            "unknown-store-contract",
            Language.PYTHON,
            "async def save(store, users):\n    for user in users:\n        await store.upsert(user)\n",
        ),
        EvaluationCase(
            "proven-store-contract",
            Language.PYTHON,
            CONTRACT
            + "async def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)\n",
            ExpectedOutcome.MATCH,
        ),
    ],
    ids=_case_id,
)
def test_labeled_boundaries(case: EvaluationCase) -> None:
    assert bool(PreferBulkUpsert().check(Path("app/service.py"), case.source)) is (
        case.expected is ExpectedOutcome.MATCH
    )


@pytest.mark.parametrize(
    ("tail", "expected"),
    [
        ("raise RuntimeError('must never import application')\n", 1),
        ("UserStore = OtherStore\n", 0),
        ("UserStore.upsert_many = replacement\n", 0),
    ],
    ids=["source-only-resolution", "rebound-owner", "mutated-owner"],
)
def test_imported_contract_is_resolved_without_importing_application(tmp_path: Path, tail: str, expected: int) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"\nversion="0.0.0"\n', encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "store.py").write_text(CONTRACT + tail, encoding="utf-8")
    consumer = package / "service.py"
    consumer.write_text(
        "from app.store import UserStore as Store\nasync def save(store: Store, users):\n    for user in users:\n        await store.upsert(user)\n",
        encoding="utf-8",
    )
    findings = analyze([PreferBulkUpsert.id], [consumer])
    assert [(finding.code, finding.line) for finding in findings] == [("SARJ516", 4)] * expected


@pytest.mark.parametrize(
    ("before_module", "before_class", "expected"),
    [
        ("", "", 1),
        ("", "marker = rewrite", 0),
        ("", "if enabled:\n    marker = rewrite", 0),
        ("", "markers.override = rewrite", 0),
        ("markers.override = rewrite\n", "", 0),
    ],
)
def test_imported_pair_preserves_owner_decorator_bindings(
    tmp_path: Path, before_module: str, before_class: str, expected: int
) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"\nversion="0.0.0"\n', encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    expression = "markers.override" if "markers" in before_class + before_module else "marker"
    contract = CONTRACT.replace("class UserStore:", "class UserStore:\n" + indent(before_class, "    "))
    contract = contract.replace("    async def upsert(", f"    @{expression}\n    async def upsert(")
    (package / "store.py").write_text(
        "import typing as markers\nfrom typing import override as marker\n" + before_module + contract,
        encoding="utf-8",
    )
    consumer = package / "service.py"
    consumer.write_text(
        "from app.store import UserStore\nasync def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)\n",
        encoding="utf-8",
    )
    assert len(analyze([PreferBulkUpsert.id], [consumer])) == expected


def test_exact_suppression_and_warning_cli(tmp_path: Path) -> None:
    path = tmp_path / "service.py"
    source = (
        CONTRACT
        + "async def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)\n"
    )
    path.write_text(source, encoding="utf-8")
    assert main(["check", "--rule", PreferBulkUpsert.id, str(path)]) == 0
    path.write_text(
        source.replace(
            "await store.upsert(user)",
            "await store.upsert(user)  # sarj-noqa: SARJ516 -- each write must commit before the next",
        ),
        encoding="utf-8",
    )
    assert analyze([PreferBulkUpsert.id], [path]) == []


@pytest.mark.parametrize("change", ["UserStore = OtherStore\n", "UserStore.upsert_many = replacement\n"])
def test_rebound_or_mutated_class_is_not_an_available_bulk_contract(change: str) -> None:
    assert (
        _check(
            f"{change}async def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)\n"
        )
        == []
    )


@pytest.mark.parametrize("iterable", ["[]", "[only]", "()", "(only,)", "{}", "{only: value}", "''", "'x'", "b'x'"])
def test_known_zero_or_one_iteration_is_not_a_batch_problem(iterable: str) -> None:
    assert (
        _check(
            f"async def save(store: UserStore, only):\n    for user in {iterable}:\n        await store.upsert(user)\n"
        )
        == []
    )


def test_rebound_self_does_not_resolve_an_injected_store() -> None:
    assert (
        _check("""
    class Service:
        def __init__(self, store: UserStore):
            self.store = store
        async def save(self, users):
            self = other
            for user in users:
                await self.store.upsert(user)
    """)
        == []
    )


@pytest.mark.parametrize(
    "change",
    [
        "    upsert_many = None\n",
        "    if enabled:\n        upsert_many = None\n",
        "    if enabled:\n        async def upsert_many(self, users):\n            ...\n",
        "    def __init__(self):\n        self.upsert_many = None\n",
    ],
    ids=["class-assignment", "conditional-assignment", "conditional-definition", "instance-method-shadow"],
)
def test_declared_bulk_method_must_not_be_shadowed(change: str) -> None:
    assert (
        _check(
            "async def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)",
            CONTRACT + change,
        )
        == []
    )


def test_explicit_metaclass_can_replace_the_declared_bulk_method() -> None:
    contract = (
        "class Meta(type):\n"
        "    def __new__(cls, name, bases, namespace):\n"
        "        namespace['upsert_many'] = None\n"
        "        return super().__new__(cls, name, bases, namespace)\n"
        + CONTRACT.replace("class UserStore:", "class UserStore(metaclass=Meta):")
    )
    assert (
        _check(
            "async def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)",
            contract,
        )
        == []
    )


@pytest.mark.parametrize("member", ["upsert", "upsert_many", "__class__"])
def test_receiver_method_replacement_invalidates_the_contract(member: str) -> None:
    assert (
        _check(f"""
        async def save(store: UserStore, users):
            store.{member} = replacement
            for user in users:
                await store.upsert(user)
        """)
        == []
    )


@pytest.mark.parametrize("mutation", ["setattr(store, 'upsert_many', None)", "delattr(store, 'upsert_many')"])
def test_explicit_builtin_method_replacement_invalidates_the_receiver(mutation: str) -> None:
    assert (
        _check(f"""
        async def save(store: UserStore, users):
            {mutation}
            for user in users:
                await store.upsert(user)
        """)
        == []
    )


def test_annotation_only_class_field_does_not_intercept_constructor_injection() -> None:
    assert (
        len(
            _check("""
        class Service:
            store: UserStore
            def __init__(self, store: UserStore):
                self.store = store
            async def save(self, users):
                for user in users:
                    await self.store.upsert(user)
        """)
        )
        == 1
    )


def test_mutation_of_an_unrelated_parameter_binding_does_not_invalidate_the_receiver() -> None:
    assert (
        len(
            _check("""
        def customize(store):
            store.upsert_many = replacement
        async def save(store: UserStore, users):
            for user in users:
                await store.upsert(user)
        """)
        )
        == 1
    )


@pytest.mark.parametrize("change", ['globals()["UserStore"] = OtherStore\n', "from adapter import *\n"])
def test_dynamic_owner_namespace_is_not_a_proven_bulk_contract(change: str) -> None:
    assert (
        _check(
            f"{change}async def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)",
        )
        == []
    )


@pytest.mark.parametrize(
    ("argument", "expected"),
    [
        ("[user for user in fixed]", 0),
        ("{user for user in fixed}", 0),
        ("{user: user for user in fixed}", 0),
        ("(user for user in fixed)", 0),
        ("[part for part in user]", 1),
        ("[user for part in fixed]", 1),
        ("[user for user in user]", 1),
    ],
)
def test_comprehension_locals_do_not_prove_outer_loop_dependence(argument: str, expected: int) -> None:
    assert (
        len(
            _check(f"""
        async def save(store: UserStore, users):
            for user in users:
                await store.upsert(UserInput(parts={argument}))
        """)
        )
        == expected
    )


def test_matching_quoted_scalar_annotations_are_equivalent() -> None:
    contract = CONTRACT.replace("user: UserInput", 'user: "UserInput"').replace(" -> User:", ' -> "User":')
    assert (
        len(
            _check(
                "async def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)",
                contract,
            )
        )
        == 1
    )


def test_annotated_constructor_assignment_preserves_injection_provenance() -> None:
    assert (
        len(
            _check("""
        class Service:
            def __init__(self, store: UserStore):
                self.store: UserStore = store
            async def save(self, users, optional=None):
                for user in users:
                    await self.store.upsert(user)
        """)
        )
        == 1
    )


@pytest.mark.parametrize(
    "extra",
    [
        "    @property\n    def store(self):\n        return OtherStore()\n",
        "    def customize(self):\n        self.store.upsert_many = replacement\n",
    ],
    ids=["descriptor-receiver", "replaced-injected-method"],
)
def test_injected_receiver_descriptor_or_method_replacement_is_excluded(extra: str) -> None:
    assert (
        _check(
            "class Service:\n"
            "    def __init__(self, store: UserStore):\n        self.store = store\n"
            + extra
            + "    async def save(self, users):\n        for user in users:\n            await self.store.upsert(user)\n"
        )
        == []
    )


def test_nested_unrelated_self_parameter_is_not_the_service_instance() -> None:
    assert (
        _check("""
        class Service:
            def __init__(self, store: UserStore):
                self.store = store
            async def save(self, users):
                async def nested(self):
                    for user in users:
                        await self.store.upsert(user)
        """)
        == []
    )


@pytest.mark.parametrize("operation", ["create", "insert", "update", "delete"])
def test_flags_compatible_discarded_crud_writes(operation: str) -> None:
    contract = CONTRACT.replace("upsert", operation)
    findings = _check(
        f"async def save(store: UserStore, users):\n    for user in users:\n        await store.{operation}(user)",
        contract,
    )
    assert len(findings) == 1
    assert f"{operation}_many" in findings[0].message


@pytest.mark.parametrize("operation", ["create", "insert", "update", "delete"])
@pytest.mark.parametrize(
    "replacement",
    [
        (" -> User:", " -> User | None:"),
        ("list[User]:", "int:"),
        ("users: list[UserInput]", "users: list[OtherInput]"),
        ("user: UserInput", "user: UserInput, tenant: str = 'default'"),
    ],
    ids=["optional-write-result", "aggregate-result", "different-input-model", "optional-context"],
)
def test_crud_pairs_keep_strict_input_and_result_compatibility(operation: str, replacement: tuple[str, str]) -> None:
    assert (
        _check(
            f"async def save(store: UserStore, users):\n    for user in users:\n        await store.{operation}(user)",
            CONTRACT.replace("upsert", operation).replace(*replacement),
        )
        == []
    )


READ_CONTRACT = """
class UserStore:
    async def get(self, user_id: str) -> User | None:
        ...
    async def get_many(self, user_ids: list[str]) -> list[User]:
        ...
"""


@pytest.mark.parametrize("bulk_name", ["get_many", "get_by_ids"])
@pytest.mark.parametrize(
    "value", ["[await store.get(user_id) for user_id in ids]", "{user_id: await store.get(user_id) for user_id in ids}"]
)
@pytest.mark.parametrize(
    ("imports", "scalar", "result"),
    [
        ("", "User", "list[User]"),
        ("", "User | None", "list[User]"),
        ("", "None | User", "dict[str, User]"),
        ("from typing import Optional, Sequence\n", "Optional[User]", "Sequence[User]"),
        ("from collections.abc import Mapping\n", '"User | None"', "Mapping[str, User]"),
    ],
)
def test_flags_source_proven_read_comprehensions(
    bulk_name: str, value: str, imports: str, scalar: str, result: str
) -> None:
    contract = imports + READ_CONTRACT.replace("get_many", bulk_name).replace("User | None", scalar).replace(
        "list[User]", result
    )
    findings = _check(f"async def load(store: UserStore, ids):\n    return {value}", contract)
    assert len(findings) == 1
    assert findings[0].severity.value == "warning"
    assert bulk_name in findings[0].message


def test_sync_read_and_keyword_key_are_supported() -> None:
    assert (
        len(
            _check(
                "def load(store: UserStore, ids):\n    return [store.get(user_id=user_id) for user_id in ids]",
                READ_CONTRACT.replace("async def", "def"),
            )
        )
        == 1
    )


@pytest.mark.parametrize(
    "value",
    [
        "[store.get(user_id) for user_id in ids]",
        "[await store.get(user_id) async for user_id in ids]",
        "[await store.get(user_id) for user_id in ids if allowed(user_id)]",
        "[await store.get(user_id) for group in groups for user_id in group]",
        "[wrap(await store.get(user_id)) for user_id in ids]",
        "[await store.get(transform(user_id)) for user_id in ids]",
        "[await store.get(user_id) for user_id in load_ids()]",
        "{touch(user_id): await store.get(user_id) for user_id in ids}",
        "[await store.get(user_id) for user_id in ids if (saved := user_id)]",
        "[await store.get(user_id) for user_id in [only]]",
        "[await store.get(fixed) for user_id in ids]",
        "[await store.get(user_id, tenant=tenant) for user_id in ids]",
        "[await store.get(*user_id) for user_id in ids]",
        "[await store.get(user_id) for store in stores]",
        "[await other.get(user_id) for user_id in ids]",
        "(await store.get(user_id) for user_id in ids)",
    ],
)
def test_read_comprehension_boundaries(value: str) -> None:
    assert _check(f"async def load(store: UserStore, ids):\n    return {value}", READ_CONTRACT) == []


@pytest.mark.parametrize(
    "replacement",
    [
        ("get_many", "fetch_many"),
        ("user_ids: list[str]", "user_ids: list[int]"),
        ("list[User]", "dict[int, User]"),
        ("list[User]", "list[Other]"),
        ("list[User]", "set[User]"),
        ("user_id: str", "user_id: str, tenant: str"),
        ("async def get_many", "def get_many"),
        ("User | None", "User | Other | None"),
    ],
    ids=[
        "missing-canonical-bulk",
        "different-key-type",
        "different-mapping-key",
        "different-result-model",
        "unordered-result",
        "required-context",
        "different-await-mode",
        "ambiguous-result-union",
    ],
)
def test_read_pairs_require_compatible_source_contracts(replacement: tuple[str, str]) -> None:
    assert (
        _check(
            "async def load(store: UserStore, ids):\n    return [await store.get(user_id) for user_id in ids]",
            READ_CONTRACT.replace(*replacement),
        )
        == []
    )


def test_injected_backend_exposes_a_fake_bulk_read_implementation() -> None:
    findings = _check(
        """
    class UserService:
        def __init__(self, backend: UserStore):
            self.backend = backend
        async def get_many(self, ids):
            return [await self.backend.get(user_id) for user_id in ids]
    """,
        READ_CONTRACT,
    )
    assert len(findings) == 1


@pytest.mark.parametrize("annotation", ["", ": UnknownBackend", ": dict[str, User]"])
def test_unproven_backend_or_dictionary_does_not_establish_a_bulk_pair(annotation: str) -> None:
    assert (
        _check(
            f"def load(backend{annotation}, ids):\n    return [backend.get(user_id) for user_id in ids]",
            READ_CONTRACT,
        )
        == []
    )


def test_batched_read_then_dictionary_join_remains_clean() -> None:
    assert (
        _check(
            """
    async def load(store: UserStore, ids):
        users = await store.get_many(ids)
        users_by_id = {user.id: user for user in users}
        return [users_by_id.get(user_id) for user_id in ids]
    """,
            READ_CONTRACT,
        )
        == []
    )


@pytest.mark.parametrize(
    "member",
    [
        "create",
        "create_many",
        "insert",
        "insert_many",
        "update",
        "update_many",
        "delete",
        "delete_many",
        "get",
        "get_many",
        "get_by_ids",
    ],
)
@pytest.mark.parametrize(
    "mutation",
    [
        "store.{member} = replacement",
        "del store.{member}",
        "setattr(store, '{member}', replacement)",
        "delattr(store, '{member}')",
    ],
)
def test_new_receiver_members_invalidate_existing_upsert_proof(member: str, mutation: str) -> None:
    assert (
        _check(
            f"async def save(store: UserStore, users):\n    {mutation.format(member=member)}\n    for user in users:\n        await store.upsert(user)"
        )
        == []
    )


@pytest.mark.parametrize("member", ["get", "get_many", "get_by_ids"])
def test_injected_read_receiver_method_replacement_is_excluded(member: str) -> None:
    assert (
        _check(
            f"""
    class UserService:
        def __init__(self, backend: UserStore):
            self.backend = backend
        def customize(self):
            setattr(self.backend, '{member}', replacement)
        async def get_many(self, ids):
            return [await self.backend.get(user_id) for user_id in ids]
    """,
            READ_CONTRACT,
        )
        == []
    )


@pytest.mark.parametrize("operation", ["upsert", "create", "insert", "update", "delete"])
@pytest.mark.parametrize(
    "expression",
    ["[await store.{operation}(user) for user in users]", "{user.id: await store.{operation}(user) for user in users}"],
    ids=["list-results", "dict-results"],
)
@pytest.mark.parametrize("statement", ["return ", ""], ids=["collected", "discarded"])
def test_flags_strict_compatible_write_comprehensions(operation: str, expression: str, statement: str) -> None:
    findings = _check(
        f"async def save(store: UserStore, users):\n    {statement}{expression.replace('{operation}', operation)}",
        CONTRACT.replace("upsert", operation),
    )
    assert len(findings) == 1
    assert f"{operation}_many" in findings[0].message
    assert "serial" in findings[0].message


def test_sync_write_comprehension_binds_exact_keyword() -> None:
    findings = _check(
        "def save(store: UserStore, users):\n    return [store.upsert(user=user) for user in users]",
        CONTRACT.replace("async def", "def"),
    )
    assert len(findings) == 1


@pytest.mark.parametrize(
    "expression",
    [
        "[await store.upsert(user) for user in users if allowed(user)]",
        "[wrap(await store.upsert(user)) for user in users]",
        "[(await store.upsert(user)).id for user in users]",
        "{audit(user): await store.upsert(user) for user in users}",
        "[await store.upsert(UserInput(user)) for user in users]",
        "[store.upsert(user) for user in users]",
        "[await store.upsert(fixed) for user in users]",
        "[await store.upsert(user) for user in [only]]",
        "[await store.upsert(user) for user, store.member in users]",
    ],
    ids=[
        "filter-effects",
        "result-wrapper",
        "result-projection",
        "dict-key-effects",
        "argument-effects",
        "unawaited-coroutines",
        "no-target-dependency",
        "one-iteration",
        "target-mutation",
    ],
)
def test_write_comprehensions_preserve_effect_and_shape_boundaries(expression: str) -> None:
    assert _check(f"async def save(store: UserStore, users):\n    return {expression}") == []


@pytest.mark.parametrize(
    "replacement",
    [
        (" -> User:", " -> User | None:"),
        ("list[User]:", "dict[str, User]:"),
        ("list[User]:", "list[Other]:"),
        ("async def upsert_many", "def upsert_many"),
    ],
    ids=["optional-write-result", "mapping-write-result", "different-write-result", "async-bulk-parity"],
)
@pytest.mark.parametrize(
    "expression",
    ["[await store.upsert(user) for user in users]", "await asyncio.gather(*(store.upsert(user) for user in users))"],
    ids=["serial-comprehension", "eager-gather"],
)
def test_new_write_shapes_keep_strict_result_contracts(replacement: tuple[str, str], expression: str) -> None:
    assert (
        _check(
            f"async def save(store: UserStore, users):\n    return {expression}",
            "import asyncio\n" + CONTRACT.replace(*replacement),
        )
        == []
    )


@pytest.mark.parametrize(
    ("imports", "callee"),
    [
        ("import asyncio\n", "asyncio.gather"),
        ("import asyncio as aio\n", "aio.gather"),
        ("from asyncio import gather\n", "gather"),
        ("from asyncio import gather as collect\n", "collect"),
    ],
    ids=["stdlib-module", "module-alias", "stdlib-member", "member-alias"],
)
@pytest.mark.parametrize(
    "expression",
    ["(store.get(user_id) for user_id in ids)", "[store.get(user_id=user_id) for user_id in ids]"],
    ids=["generator", "list-keyword"],
)
def test_flags_import_proven_eager_read_gather_once(imports: str, callee: str, expression: str) -> None:
    findings = _check(
        f"async def load(store: UserStore, ids):\n    return await {callee}(*{expression})", imports + READ_CONTRACT
    )
    assert len(findings) == 1
    assert findings[0].severity.value == "warning"
    assert "fan-out" in findings[0].message
    assert "serial" not in findings[0].message
    assert "cancellation" in findings[0].message


@pytest.mark.parametrize("operation", ["upsert", "create", "insert", "update", "delete"])
def test_flags_eager_write_gather_once(operation: str) -> None:
    findings = _check(
        f"async def save(store: UserStore, users):\n    await asyncio.gather(*[store.{operation}(user) for user in users])",
        "import asyncio\n" + CONTRACT.replace("upsert", operation),
    )
    assert len(findings) == 1
    assert f"{operation}_many" in findings[0].message


@pytest.mark.parametrize(
    "contract",
    [
        READ_CONTRACT.replace("async def", "def"),
        READ_CONTRACT.replace("        ...", "        yield user", 1),
        READ_CONTRACT.replace("        ...", "        yield user"),
    ],
    ids=["sync-pair", "async-generator-singleton", "async-generator-pair"],
)
def test_gather_requires_coroutine_methods(contract: str) -> None:
    assert (
        _check(
            "async def load(store: UserStore, ids):\n    return await asyncio.gather(*(store.get(user_id) for user_id in ids))",
            "import asyncio\n" + contract,
        )
        == []
    )


@pytest.mark.parametrize(
    "expression",
    [
        "asyncio.gather(*(store.get(user_id) for user_id in ids))",
        "await custom.gather(*(store.get(user_id) for user_id in ids))",
        "await asyncio.gather(*[store.get(user_id) for user_id in ids], return_exceptions=True)",
        "await asyncio.gather(store.get(fixed), *[store.get(user_id) for user_id in ids])",
        "await asyncio.gather(*[store.get(user_id) for user_id in ids], *others)",
        "await asyncio.gather([store.get(user_id) for user_id in ids])",
        "await asyncio.gather(*(store.get(user_id) for user_id in ids if user_id))",
        "await asyncio.gather(*(store.get(user_id) async for user_id in ids))",
        "await asyncio.gather(*(store.get(user_id) for group in groups for user_id in group))",
        "await asyncio.gather(*(asyncio.create_task(store.get(user_id)) for user_id in ids))",
        "await asyncio.gather(*(store.get(transform(user_id)) for user_id in ids))",
        "await asyncio.gather(*(store.get(user_id) for user_id in load_ids()))",
        "await asyncio.gather(*(store.get(await user_id) for user_id in ids))",
        "await asyncio.gather(*(store.get(fixed) for user_id in ids))",
        "await asyncio.gather(*(store.get(*user_id) for user_id in ids))",
        "await asyncio.gather(*(store.get(user_id) for user_id in [only]))",
        "await asyncio.gather(*(store.get(user_id) for store in stores))",
        "await asyncio.gather(*(store.get((saved := user_id)) for user_id in ids))",
        "await asyncio.gather(*(other.get(user_id) for user_id in ids))",
    ],
    ids=[
        "unawaited-gather",
        "custom-gather",
        "per-row-exceptions",
        "extra-call",
        "extra-expansion",
        "unexpanded-list",
        "filtered",
        "async-stream",
        "nested-generators",
        "task-factory",
        "argument-effects",
        "iterable-call",
        "argument-await-effect",
        "constant-input",
        "starred-input",
        "one-iteration",
        "receiver-shadow",
        "assignment-effect",
        "unknown-receiver",
    ],
)
def test_eager_gather_requires_exact_shape_and_execution_proof(expression: str) -> None:
    assert (
        _check(f"async def load(store: UserStore, ids):\n    return {expression}", "import asyncio\n" + READ_CONTRACT)
        == []
    )


@pytest.mark.parametrize(
    ("imports", "parameters", "prefix", "callee"),
    [
        ("", "", "", "asyncio.gather"),
        ("from custom import gather\n", "", "", "gather"),
        ("import asyncio\n", ", asyncio", "", "asyncio.gather"),
        ("from asyncio import gather\n", ", gather", "", "gather"),
        ("import asyncio\n", "", "    asyncio = custom\n", "asyncio.gather"),
        ("from asyncio import gather\n", "", "    gather = custom\n", "gather"),
        ("import asyncio\nasyncio = custom\n", "", "", "asyncio.gather"),
        ("from asyncio import gather\ngather = custom\n", "", "", "gather"),
        ("import asyncio\n", "", "    global asyncio\n    asyncio = custom\n", "asyncio.gather"),
    ],
    ids=[
        "unimported-module",
        "custom-import",
        "module-parameter",
        "member-parameter",
        "local-module-rebind",
        "local-member-rebind",
        "global-module-rebind",
        "global-member-rebind",
        "explicit-global-write",
    ],
)
def test_gather_spelling_and_shadowed_bindings_do_not_prove_stdlib_execution(
    imports: str, parameters: str, prefix: str, callee: str
) -> None:
    assert (
        _check(
            f"async def load(store: UserStore, ids{parameters}):\n{prefix}    return await {callee}(*(store.get(user_id) for user_id in ids))",
            imports + READ_CONTRACT,
        )
        == []
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "asyncio.gather = replacement",
        "del asyncio.gather",
        "setattr(asyncio, 'gather', replacement)",
        "delattr(asyncio, 'gather')",
        "asyncio.__dict__['gather'] = replacement",
        "alias.gather = replacement",
        "asyncio.gather.__code__ = replacement",
        "patch_module(asyncio)",
        "patch_function(collect)",
    ],
    ids=[
        "member-assignment",
        "member-deletion",
        "setattr",
        "delattr",
        "module-dict-mutation",
        "other-module-alias",
        "function-mutation",
        "module-escape",
        "function-escape",
    ],
)
def test_visible_gather_namespace_mutation_invalidates_all_import_aliases(mutation: str) -> None:
    assert (
        _check(
            f"async def load(store: UserStore, ids):\n    {mutation}\n    return await collect(*(store.get(user_id) for user_id in ids))",
            "import asyncio\nimport asyncio as alias\nfrom asyncio import gather as collect\n" + READ_CONTRACT,
        )
        == []
    )


def test_unrelated_scope_shadow_and_mutation_preserve_real_gather_binding() -> None:
    findings = _check(
        """
        def customize(asyncio, gather):
            asyncio.gather = gather
        async def load(store: UserStore, ids):
            return await collect(*(store.get(user_id) for user_id in ids))
        """,
        "import asyncio\nfrom asyncio import gather as collect\n" + READ_CONTRACT,
    )
    assert len(findings) == 1


@pytest.mark.parametrize(
    "expression",
    ["[await store.upsert(user) for user in users]", "await asyncio.gather(*(store.upsert(user) for user in users))"],
    ids=["serial-write-comprehension", "eager-write-gather"],
)
def test_new_shapes_preserve_receiver_mutation_and_exact_suppression(expression: str) -> None:
    contract = "import asyncio\n" + CONTRACT
    assert (
        _check(
            f"async def save(store: UserStore, users):\n    store.upsert_many = replacement\n    {expression}", contract
        )
        == []
    )
    assert (
        _check(
            f"async def save(store: UserStore, users):\n    {expression}  # sarj-noqa: SARJ516 -- independent effects",
            contract,
        )
        == []
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("for user_id in ids:\n        await store.get(user_id)", 1),
        ("users = []\n    for user_id in ids:\n        users.append(await store.get(user_id))", 0),
        ("for user_id in ids:\n        user = await store.get(user_id)", 0),
        ("for user_id in ids:\n        await store.get(user_id)\n        audit(user_id)", 0),
        ("for user_id in ids:\n        await store.get(transform(user_id))", 0),
        ("for user_id, store.member in ids:\n        await store.get(user_id)", 0),
    ],
    ids=[
        "discarded-read",
        "append-collector",
        "assigned-result",
        "per-row-effect",
        "argument-effect",
        "target-mutation",
    ],
)
def test_serial_read_loop_scope_is_limited_to_discarded_calls(body: str, expected: int) -> None:
    findings = _check(f"async def load(store: UserStore, ids):\n    {body}", READ_CONTRACT)
    assert len(findings) == expected


@pytest.mark.parametrize(
    "setup",
    [
        "backend = store\n    backend.get_many = None",
        "backend = store\n    backend = backend\n    backend.get_many = None",
        "backend = store\n    second = backend\n    second.get_many = None",
        "backend: UserStore = store\n    del backend.get_many",
        "backend = store\n    setattr(backend, 'get_many', None)",
        "backend = store\n    delattr(backend, 'get_many')",
        "backend = store\n    backend.get_many = None\n    backend = other",
        "backend = store\n    backend: UserStore\n    backend.get_many = None",
        "backend = other\n    if condition:\n        backend = store\n    backend.get_many = None",
    ],
    ids=[
        "parameter-alias-member-assignment",
        "self-assignment-preserves-alias-object",
        "parameter-alias-chain",
        "annotated-alias-member-delete",
        "parameter-alias-setattr",
        "parameter-alias-delattr",
        "mutation-precedes-alias-rebinding",
        "annotation-preserves-alias-object",
        "conditional-alias-may-replace-member",
    ],
)
def test_read_receiver_alias_member_mutation_invalidates_direct_proof(setup: str) -> None:
    assert (
        _check(
            f"async def load(store: UserStore, ids):\n    {setup}\n    return [await store.get(key) for key in ids]",
            READ_CONTRACT,
        )
        == []
    )


@pytest.mark.parametrize("aliases", [15, 16, 32], ids=["within-budget", "exhausted", "above-budget"])
@pytest.mark.parametrize("injected", [False, True], ids=["typed-parameter", "injected-attribute"])
@pytest.mark.parametrize("mutation", ["{target}.get = replacement", "setattr({target}, 'get_many', replacement)"])
def test_receiver_mutation_defers_when_alias_origin_budget_exhausts(
    aliases: int, injected: bool, mutation: str
) -> None:
    previous = "self.store" if injected else "store"
    lines: list[str] = []
    for index in range(aliases):
        current = f"alias{index}"
        lines.append(f"{current} = {previous}")
        previous = current
    lines.append(mutation.format(target=previous))
    receiver = "self.store" if injected else "store"
    lines.append(f"return [await {receiver}.get(key) for key in ids]")
    body = "\n".join(lines)
    caller = (
        "class Service:\n    def __init__(self, store: UserStore):\n        self.store = store\n    async def load(self, ids):\n"
        + indent(body, "        ")
        if injected
        else "async def load(store: UserStore, ids):\n" + indent(body, "    ")
    )
    assert _check(caller, READ_CONTRACT) == []


@pytest.mark.parametrize(
    "setup",
    [
        "backend = self.store\n        backend.update_many = None",
        "backend = self.store\n        second = backend\n        second.update_many = None",
        "backend = self.store\n        del backend.update_many",
        "backend = self.store\n        setattr(backend, 'update_many', None)",
        "backend = self.store\n        delattr(backend, 'update_many')",
    ],
    ids=[
        "injected-alias-member-assignment",
        "injected-alias-chain",
        "injected-alias-member-delete",
        "injected-alias-setattr",
        "injected-alias-delattr",
    ],
)
def test_injected_receiver_alias_member_mutation_invalidates_gather_proof(setup: str) -> None:
    assert (
        _check(
            f"""
    class Service:
        def __init__(self, store: UserStore):
            self.store = store
        async def save(self, users):
            {setup}
            await asyncio.gather(*(self.store.update(user) for user in users))
    """,
            "import asyncio\n" + CONTRACT.replace("upsert", "update"),
        )
        == []
    )


@pytest.mark.parametrize(
    "setup",
    [
        "backend = store\n    backend = other\n    backend.get_many = None",
        "backend = store\n    def backend():\n        pass\n    backend.get_many = None",
        "backend = store\n    import other as backend\n    backend.get_many = None",
        "backend = other\n    backend.get_many = None\n    backend = store",
        "def customize(store):\n        backend = store\n        backend.get_many = None",
        "def customize(backend):\n        backend.get_many = None\n    backend = store",
        "backend = store\n    def customize(backend):\n        backend.get_many = None",
    ],
    ids=[
        "definite-rebind-before-mutation",
        "function-definition-rebinds-alias",
        "import-rebinds-alias",
        "alias-assignment-follows-mutation",
        "distinct-parameter-binding",
        "unrelated-lexical-scope",
        "nested-parameter-shadows-alias",
    ],
)
def test_unrelated_alias_mutation_preserves_direct_read_proof(setup: str) -> None:
    assert (
        len(
            _check(
                f"async def load(store: UserStore, ids):\n    {setup}\n    return [await store.get(key) for key in ids]",
                READ_CONTRACT,
            )
        )
        == 1
    )


@pytest.mark.parametrize("mutation", ["setattr(self, 'cache', primitive)", "delattr(self, 'cache')"])
def test_unrelated_constructor_member_mutation_preserves_bulk_pair(mutation: str) -> None:
    contract = CONTRACT + f"    def __init__(self, primitive):\n        {mutation}\n"
    assert (
        len(
            _check(
                "async def save(store: UserStore, users):\n    for user in users:\n        await store.upsert(user)",
                contract,
            )
        )
        == 1
    )
