from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity, is_suppressed
from sarj_python_lint.rules.prefer_non_nullable_collection import (
    PreferNonNullableCollection,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


PATH = Path("app/models.py")


def _check(source: str, path: Path = PATH) -> list[Diagnostic]:
    return PreferNonNullableCollection().check(path, source)


_PUBLIC_EXAMPLES = PreferNonNullableCollection.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferNonNullableCollection().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    "annotation",
    [
        "list[OrganizationId] | None",
        "None | list[OrganizationId]",
        "typing.Optional[list[OrganizationId]]",
        "Optional[List[OrganizationId]]",
        "Union[list[OrganizationId], None]",
        "list[One] | list[Two] | None",
    ],
)
@pytest.mark.parametrize("default", [" = None", "", " = Field(default=None)"])
def test_allows_nullable_list_fields_without_behavioral_proof(annotation: str, default: str) -> None:
    source = f"class AnyModel:\n    organization_ids: {annotation}{default}\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    "declaration",
    [
        "class Response(BaseModel):",
        "class UpdateInput(BaseModel):",
        "@dataclass\nclass Settings:",
        "@define\nclass DomainState:",
        "class PlainTypedClass:",
    ],
)
def test_nullable_fields_may_encode_framework_or_patch_semantics(declaration: str) -> None:
    source = f"{declaration}\n    items: list[str] | None = None\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "class Model:\n    items: list[str] = field(default_factory=list)\n",
        "class Model:\n    items: list[str] = Field(default_factory=list)\n",
        "class Model:\n    items: list[str]\n",
        "class Model:\n    item: str | None = None\n",
        "class Model:\n    value: str | list[str] | None = None\n",
        "items: list[str] | None = None\n",
    ],
)
def test_ignores_non_target_shapes(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "annotation",
    [
        "list[Beneficiary] | None",
        "None | list[Beneficiary]",
        "Optional[List[Beneficiary]]",
        "typing.Optional[list[Beneficiary]]",
        "Union[list[Beneficiary], None]",
    ],
)
def test_flags_none_default_used_only_as_an_empty_list(annotation: str) -> None:
    source = (
        "class BeneficiaryNotFoundError(ValueError):\n"
        f"    def __init__(self, available: {annotation} = None):\n"
        "        self.available = available or []\n"
    )

    diagnostics = _check(source, Path("app/errors.py"))

    assert len(diagnostics) == 1
    assert diagnostics[0].line == 2
    assert diagnostics[0].severity is Severity.WARNING
    assert "Sequence" in diagnostics[0].message
    assert "required" in diagnostics[0].message


def test_flags_keyword_only_parameter_normalized_with_list_constructor() -> None:
    source = (
        "def resolve(*, candidates: list[str] | None = None):\n"
        "    normalized = candidates or list()\n"
        "    return normalized\n"
    )

    assert len(_check(source, Path("app/resolver.py"))) == 1


@pytest.mark.parametrize("empty", ["[]", "list()"])
def test_flags_first_statement_none_guard_that_only_normalizes_empty(empty: str) -> None:
    source = (
        "def resolve(candidates: list[str] | None = None):\n"
        "    if candidates is None:\n"
        f"        candidates = {empty}\n"
        "    return sorted(candidates)\n"
    )

    assert len(_check(source, Path("app/resolver.py"))) == 1


def test_flags_first_statement_self_normalization() -> None:
    source = (
        "def resolve(candidates: list[str] | None = None):\n"
        "    candidates = candidates or []\n"
        "    return sorted(candidates)\n"
    )

    assert len(_check(source, Path("app/resolver.py"))) == 1


@pytest.mark.parametrize(
    "normalization",
    [
        "candidates = [] if candidates is None else candidates",
        "candidates = list() if candidates is None else candidates",
        "candidates = candidates if candidates is not None else []",
        "candidates = candidates if candidates is not None else list()",
    ],
)
def test_flags_first_statement_conditional_expression_normalization(normalization: str) -> None:
    source = f"def resolve(candidates: list[str] | None = None):\n    {normalization}\n    return sorted(candidates)\n"

    assert len(_check(source, Path("app/resolver.py"))) == 1


@pytest.mark.parametrize(
    "normalization",
    [
        "candidates = [] if other is None else candidates",
        "candidates = [] if candidates is not None else candidates",
        "candidates = candidates if candidates is None else []",
        "candidates = [default] if candidates is None else candidates",
        "normalized = [] if candidates is None else candidates",
        "candidates = [] if candidates is None else list(candidates)",
    ],
)
def test_ignores_conditional_expressions_that_do_not_only_normalize_none(normalization: str) -> None:
    source = (
        "def resolve(candidates: list[str] | None = None, other: object = None):\n"
        f"    {normalization}\n"
        "    return candidates\n"
    )

    assert _check(source, Path("app/resolver.py")) == []


def test_ignores_conditional_normalization_when_none_is_observed_again() -> None:
    source = (
        "def resolve(candidates: list[str] | None = None):\n"
        "    candidates = [] if candidates is None else candidates\n"
        "    if candidates is None:\n"
        "        record_omission()\n"
        "    return candidates\n"
    )

    assert _check(source, Path("app/resolver.py")) == []


def test_ignores_conditional_normalization_captured_by_nested_scope() -> None:
    source = (
        "def resolve(candidates: list[str] | None = None):\n"
        "    candidates = candidates if candidates is not None else []\n"
        "    def current():\n"
        "        return candidates\n"
        "    return current\n"
    )

    assert _check(source, Path("app/resolver.py")) == []


def test_skips_none_guard_that_performs_additional_behavior() -> None:
    source = (
        "def resolve(candidates: list[str] | None = None):\n"
        "    if candidates is None:\n"
        "        record_omission()\n"
        "        candidates = []\n"
        "    return sorted(candidates)\n"
    )

    assert _check(source, Path("app/resolver.py")) == []


def test_skips_normalized_parameter_observed_as_none_again() -> None:
    source = (
        "def resolve(candidates: list[str] | None = None):\n"
        "    candidates = candidates or []\n"
        "    if candidates is None:\n"
        "        record_omission()\n"
        "    return candidates\n"
    )

    assert _check(source, Path("app/resolver.py")) == []


@pytest.mark.parametrize(
    "source",
    [
        # The parameter remains nullable when the function observes the distinction.
        (
            "def resolve(candidates: list[str] | None = None):\n"
            "    if candidates is None:\n"
            "        record_omission()\n"
            "    return candidates or []\n"
        ),
        # Forwarding None can be part of an external contract.
        ("def resolve(candidates: list[str] | None = None):\n    return downstream(candidates)\n"),
        # A non-empty fallback is not an empty-state normalization.
        ("def resolve(candidates: list[str] | None = None):\n    return candidates or [default_candidate]\n"),
        # A required nullable parameter may use None as an explicit state.
        ("def resolve(candidates: list[str] | None):\n    return candidates or []\n"),
        # Other nullable collection kinds are outside this list-specific rule.
        ("def resolve(candidates: set[str] | None = None):\n    return candidates or []\n"),
        # Multiple reads prevent proving that None and [] are equivalent.
        ("def resolve(candidates: list[str] | None = None):\n    audit(candidates)\n    return candidates or []\n"),
        # An inherited API contract cannot be changed locally.
        ("@override\ndef resolve(candidates: list[str] | None = None):\n    return candidates or []\n"),
        # An undecorated method may still implement a third-party base contract.
        (
            "class Adapter(FrameworkAdapter):\n"
            "    def resolve(self, candidates: list[str] | None = None):\n"
            "        return candidates or []\n"
        ),
    ],
)
def test_ignores_parameter_cases_without_proven_equivalent_empty_states(source: str) -> None:
    assert _check(source, Path("app/resolver.py")) == []


def test_ignores_constructor_parameter_forwarded_to_external_base() -> None:
    source = (
        "class Adapter(FrameworkAdapter):\n"
        "    def __init__(self, tools: list[Tool] | None = None):\n"
        "        super().__init__(tools=tools or [])\n"
    )

    assert _check(source) == []


def test_object_base_does_not_create_an_external_constructor_contract() -> None:
    source = (
        "class Adapter(object):\n"
        "    def __init__(self, tools: list[Tool] | None = None):\n"
        "        tools = tools or []\n"
        "        self.tools = tools\n"
    )

    assert len(_check(source)) == 1


def test_ignores_tests_and_generated_files() -> None:
    source = "def resolve(items: list[str] | None = None):\n    return items or []\n"
    assert _check(source, Path("tests/test_models.py")) == []
    assert _check(source, Path("src/generated/models.py")) == []
    assert _check(source, Path("src/vendor/models.py")) == []
    assert _check(f"# Generated by tool\n{source}") == []


def test_ignores_shared_test_support_modules() -> None:
    source = "def resolve(items: list[str] | None = None):\n    return items or []\n"

    assert _check(source, Path("python/common/testing/builders.py")) == []


def test_parameter_captured_by_nested_closure_is_not_locally_proven_equivalent() -> None:
    source = (
        "def resolve(items: list[str] | None = None):\n"
        "    normalized = items or []\n"
        "    def omitted():\n"
        "        return items is None\n"
        "    return normalized, omitted\n"
    )

    assert _check(source, Path("app/resolver.py")) == []


def test_meaningful_none_state_can_be_suppressed_inline() -> None:
    source = (
        "def resolve(allowed_schemes: list[str] | None = None):  "
        "# sarj-noqa: SARJ082 — None means inherit defaults\n"
        "    return allowed_schemes or []\n"
    )
    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert is_suppressed(source.splitlines(), diagnostics[0].line, diagnostics[0].code)
