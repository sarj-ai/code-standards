from pathlib import Path
from textwrap import dedent
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
