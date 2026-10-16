from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, RootModel, ValidationError, model_validator
import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules.prefer_discriminated_model_union import PreferDiscriminatedModelUnion


_BASE = (
    "from typing import Literal, Self\n"
    "from pydantic import BaseModel, model_validator\n"
    "class Delivery(BaseModel):\n"
    "    kind: Literal['email', 'pickup']\n"
    "    address: str | None = None\n"
    "    @model_validator(mode='after')\n"
    "    def validate_address(self) -> Self:\n"
    "        if self.kind == 'email' and self.address is None:\n"
    "            raise ValueError('Email requires an address')\n"
    "        return self\n"
)

_PROBLEM = RuleProblem(
    key="literal-tag-dependent-required-payload",
    summary="A direct after validator proves a tag-dependent field requirement missing from the model type.",
    harm="Consumers must repeat None guards and static checking admits a payload state rejected by the model validator.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=(_BASE,),
    good_examples=(PreferDiscriminatedModelUnion.public_examples()[1].focus_file.source,),
    exclusions=(
        "Independent nullable fields, open or computed tags, inherited models and opaque validators remain excluded.",
        "Optional fields in other variants remain legal unless an explicit invariant excludes them.",
    ),
)


def _check(source: str, path: str = "app/models.py"):
    return PreferDiscriminatedModelUnion().check(Path(path), source)


_CASES = (
    ("dependent-payload", _BASE, True),
    (
        "optional-independent",
        _BASE.replace(
            "        if self.kind == 'email' and self.address is None:\n            raise ValueError('Email requires an address')\n",
            "",
        ),
        False,
    ),
    ("open-tag", _BASE.replace("Literal['email', 'pickup']", "str"), False),
    ("one-tag", _BASE.replace("Literal['email', 'pickup']", "Literal['email']"), False),
    ("duplicate-tags", _BASE.replace("Literal['email', 'pickup']", "Literal['email', 'email']"), False),
    ("non-string-tag", _BASE.replace("Literal['email', 'pickup']", "Literal['email', 1]"), False),
    ("unknown-literal", _BASE.replace("== 'email'", "== 'courier'"), False),
    ("computed-tag", _BASE.replace("self.kind == 'email'", "self.kind.lower() == 'email'"), False),
    ("computed-value", _BASE.replace("== 'email'", "== EMAIL"), False),
    ("computed-payload", _BASE.replace("self.address is None", "getattr(self, 'address') is None"), False),
    ("nonnull-payload", _BASE.replace("str | None = None", "str"), False),
    ("missing-payload", _BASE.replace("    address: str | None = None\n", ""), False),
    ("missing-tag", _BASE.replace("    kind: Literal['email', 'pickup']\n", ""), False),
    ("falsey-is-not-absent", _BASE.replace("self.address is None", "not self.address"), False),
    ("equals-none", _BASE.replace("self.address is None", "self.address == None"), False),
    ("disjunction", _BASE.replace("'email' and", "'email' or"), False),
    ("third-condition", _BASE.replace("self.address is None:", "self.address is None and self.enabled:"), False),
    (
        "helper-validator",
        _BASE.replace(
            "        if self.kind == 'email' and self.address is None:\n            raise ValueError('Email requires an address')",
            "        check_delivery(self)",
        ),
        False,
    ),
    (
        "nested-guard",
        _BASE.replace("        if self.kind", "        if enabled:\n            if self.kind").replace(
            "            raise", "                raise"
        ),
        False,
    ),
    (
        "caught-rejection",
        _BASE.replace("        if self.kind", "        try:\n            if self.kind")
        .replace("            raise", "                raise")
        .replace("        return self", "        except ValueError:\n            pass\n        return self"),
        False,
    ),
    (
        "mutating-validator",
        _BASE.replace("        return self", "        self.address = fallback\n        return self"),
        False,
    ),
    ("noninstance-return", _BASE.replace("return self", "return other"), False),
    ("before-validator", _BASE.replace("mode='after'", "mode='before'"), False),
    ("wrap-validator", _BASE.replace("mode='after'", "mode='wrap'"), False),
    ("unknown-mode", _BASE.replace("mode='after'", "mode=MODE"), False),
    (
        "another-validator",
        _BASE.replace(
            "        return self",
            "        return self\n    @model_validator(mode='before')\n    @classmethod\n    def normalize(cls, values):\n        return values",
        ),
        False,
    ),
    ("other-method", _BASE + "    def render(self):\n        return self.kind\n", False),
    ("property-tag", _BASE + "    @property\n    def kind(self):\n        return 'email'\n", False),
    ("repeated-field", _BASE.replace("    @model_validator", "    address: str\n    @model_validator"), False),
    (
        "inherited-model",
        _BASE.replace("class Delivery(BaseModel):", "class Parent(BaseModel): pass\nclass Delivery(Parent):"),
        False,
    ),
    (
        "non-pydantic-base",
        _BASE.replace(
            "from pydantic import BaseModel, model_validator",
            "from another_framework import BaseModel, model_validator",
        ),
        False,
    ),
    (
        "non-pydantic-validator",
        _BASE.replace(
            "from pydantic import BaseModel, model_validator",
            "from pydantic import BaseModel\nfrom another_framework import model_validator",
        ),
        False,
    ),
    (
        "non-typing-literal",
        _BASE.replace(
            "from typing import Literal, Self", "from typing import Self\nfrom another_framework import Literal"
        ),
        False,
    ),
    ("model-decorator", _BASE.replace("class Delivery", "@adapt\nclass Delivery"), False),
    ("validator-decorator", _BASE.replace("    @model_validator", "    @adapt\n    @model_validator"), False),
    ("validator-extra-parameter", _BASE.replace("validate_address(self)", "validate_address(self, info)"), False),
    ("validator-variadic", _BASE.replace("validate_address(self)", "validate_address(self, **kwargs)"), False),
    ("async-validator", _BASE.replace("    def validate_address", "    async def validate_address"), False),
    ("rebound-import", _BASE.replace("class Delivery", "model_validator = custom\nclass Delivery"), False),
    ("class-import-shadow", _BASE.replace("    kind:", "    Literal: ClassVar = custom\n    kind:"), False),
    ("exception-shadow", _BASE.replace("class Delivery", "ValueError = custom\nclass Delivery"), False),
    ("local-import-shadow", _BASE + "def helper(Literal): pass\n", False),
    ("wildcard", "from other import *\n" + _BASE, False),
    ("dynamic-namespace", _BASE + "globals()['Delivery'] = custom\n", False),
    ("generated", "# @generated\n" + _BASE, False),
    ("malformed", "class Broken(:", False),
    ("comment", "# " + _BASE.replace("\n", "\n# "), False),
    ("string", repr(_BASE), False),
    ("reversed-tag", _BASE.replace("self.kind == 'email'", "'email' == self.kind"), True),
    ("reversed-none", _BASE.replace("self.address is None", "None is self.address"), True),
    (
        "reversed-conjunction",
        _BASE.replace("self.kind == 'email' and self.address is None", "self.address is None and self.kind == 'email'"),
        True,
    ),
    ("other-instance-name", _BASE.replace("self", "record"), True),
    ("reverse-union", _BASE.replace("str | None", "None | str"), True),
    ("larger-union", _BASE.replace("str | None", "str | int | None"), True),
    (
        "optional-import",
        _BASE.replace("Literal, Self", "Literal, Optional, Self").replace("str | None", "Optional[str]"),
        True,
    ),
    (
        "import-aliases",
        _BASE.replace("Literal, Self", "Literal as Tag, Self")
        .replace("Literal[", "Tag[")
        .replace("BaseModel, model_validator", "BaseModel as Model, model_validator as validate")
        .replace("(BaseModel)", "(Model)")
        .replace("@model_validator", "@validate"),
        True,
    ),
    (
        "module-aliases",
        _BASE.replace("from typing import Literal, Self", "import typing as t")
        .replace("from pydantic import BaseModel, model_validator", "import pydantic as p")
        .replace("Literal[", "t.Literal[")
        .replace("-> Self", "-> t.Self")
        .replace("(BaseModel)", "(p.BaseModel)")
        .replace("@model_validator", "@p.model_validator"),
        True,
    ),
    ("typing-extensions", _BASE.replace("from typing import", "from typing_extensions import"), True),
    (
        "functional-validator-import",
        _BASE.replace(
            "from pydantic import BaseModel, model_validator",
            "from pydantic import BaseModel\nfrom pydantic.functional_validators import model_validator",
        ),
        True,
    ),
    ("docstring", _BASE.replace("        if self.kind", '        "Validate delivery."\n        if self.kind'), True),
    ("assertion-error", _BASE.replace("raise ValueError", "raise AssertionError"), True),
    (
        "suppressed",
        _BASE.replace(
            "self.address is None:", "self.address is None:  # sarj-noqa: SARJ510 -- wire contract remains fixed"
        ),
        False,
    ),
    (
        "unrelated-suppression",
        _BASE.replace("self.address is None:", "self.address is None:  # sarj-noqa: SARJ435 -- independent advisory"),
        True,
    ),
)


@pytest.mark.parametrize(("label", "source", "matches"), _CASES, ids=[case[0] for case in _CASES])
def test_labeled_domain_states(label: str, source: str, *, matches: bool) -> None:
    case = EvaluationCase(
        label,
        Language.PYTHON,
        source,
        ExpectedOutcome.MATCH if matches else ExpectedOutcome.NO_MATCH,
        PurePosixPath("app/models.py"),
    )
    findings = _check(case.source)
    assert len(findings) == int(case.expected is ExpectedOutcome.MATCH)


def test_native_spec_and_public_examples() -> None:
    assert _PROBLEM.bad_examples == (_BASE,)
    assert verify_native_rule(PreferDiscriminatedModelUnion, analyze) == 2


def test_multiple_variant_requirements_produce_one_model_review() -> None:
    source = _BASE.replace("    @model_validator", "    location: str | None = None\n    @model_validator").replace(
        "        return self",
        "        if self.kind == 'pickup' and self.location is None:\n"
        "            raise ValueError('Pickup requires a location')\n        return self",
    )
    [finding] = _check(source)
    assert finding.line == 9
    assert finding.col == 9
    assert finding.severity is Severity.WARNING
    assert "preserve every other accepted combination" in finding.message


def test_payload_required_for_every_tag_is_a_common_field_constraint() -> None:
    source = _BASE.replace(
        "        return self",
        "        if self.kind == 'pickup' and self.address is None:\n"
        "            raise ValueError('Pickup requires an address')\n        return self",
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    ("message", "matches"),
    [
        ("message = 'Email requires an address'\n            raise ValueError(message)", True),
        ("message = 'Email requires an address'\n            raise AssertionError(message)", True),
        ("message = translated_message()\n            raise ValueError(message)", False),
        ("message = 'Email requires an address'\n            raise ValueError(other)", False),
        ("self.message = 'Email requires an address'\n            raise ValueError(self.message)", False),
        (
            "message = 'Email requires an address'\n            normalize(self)\n            raise ValueError(message)",
            False,
        ),
    ],
)
def test_local_message_assignment_respects_existing_exception_style(message: str, *, matches: bool) -> None:
    source = _BASE.replace("raise ValueError('Email requires an address')", message)
    assert len(_check(source)) == int(matches)


def test_common_requirement_does_not_hide_an_independent_variant_dependency() -> None:
    source = _BASE.replace("    @model_validator", "    location: str | None = None\n    @model_validator").replace(
        "        return self",
        "        if self.kind == 'pickup' and self.address is None:\n"
        "            raise ValueError('Pickup requires an address')\n"
        "        if self.kind == 'pickup' and self.location is None:\n"
        "            raise ValueError('Pickup requires a location')\n        return self",
    )
    [finding] = _check(source)
    assert "`location`" in finding.message
    assert finding.line == 13


@pytest.mark.parametrize(
    ("payload", "matches"),
    [
        ("None | None", False),
        ("Optional[None]", False),
        ("Optional[Optional[None]]", False),
        ("Never | None", False),
        ("NoReturn | None", False),
        ("Optional[Never]", False),
        ("Optional[NoReturn]", False),
        ("Literal[None] | None", False),
        ("Any | None", False),
        ("object | None", False),
        ("UnknownPayload | None", False),
        ("str | UnknownPayload | None", False),
        ("str | Any | None", False),
        ("str | object | None", False),
        ("tuple[Never] | None", False),
        ("str | Never | None", False),
        ("Optional[str | None]", True),
        ("list[str] | None", True),
        ("dict[str, str] | None", True),
        ("set[int] | None", True),
        ("tuple[str, ...] | None", True),
        ("tuple[()] | None", True),
    ],
)
def test_nullable_payload_needs_a_source_proven_non_none_member(payload: str, *, matches: bool) -> None:
    source = "from typing import Any, Never, NoReturn, Optional\n" + _BASE.replace("str | None", payload)
    assert len(_check(source)) == int(matches)


@pytest.mark.parametrize("name", ["Literal", "BaseModel", "model_validator", "str"])
def test_class_scope_shadowing_abstains(name: str) -> None:
    source = _BASE.replace("    kind:", f"    {name}: ClassVar = custom\n    kind:")
    assert _check(source) == []


def test_nfkc_normalized_validator_import_keeps_alias_evidence() -> None:
    source = _BASE.replace(
        "BaseModel, model_validator", "BaseModel, ｍｏｄｅｌ_ｖａｌｉｄａｔｏｒ as validate"
    ).replace("@model_validator", "@validate")
    assert len(_check(source)) == 1


def test_nearby_type_rules_keep_one_deterministic_model_review() -> None:
    selectors = (
        PreferDiscriminatedModelUnion.id,
        "prefer-str-enum",
        "prefer-nominal-id-types",
        "prefer-match-assert-never",
        "typed-error-reasons",
    )
    for order in (selectors, tuple(reversed(selectors))):
        rules = [REGISTRY[name]() for name in order]
        findings = check_source(rules, Path("app/models.py"), _BASE)
        assert [finding.code for finding in findings] == ["SARJ510"]
        assert check_source(rules, Path("app/models.py"), _BASE) == findings
        replacement = PreferDiscriminatedModelUnion.public_examples()[1].focus_file.source
        assert check_source(rules, Path("app/models.py"), replacement) == []


def test_warning_registration_suppression_and_exit_behavior(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = check_source([PreferDiscriminatedModelUnion()], Path("app/models.py"), _BASE)
    assert len(result) == 1
    assert result[0].code == "SARJ510"
    path = tmp_path / "delivery.py"
    path.write_text(_BASE)
    assert main(["check", "--rule", PreferDiscriminatedModelUnion.id, str(path)]) == 0
    assert "SARJ510 warning:" in capsys.readouterr().out
    assert _check(_BASE, "tests/test_delivery.py") == []


class _ValidatedDelivery(BaseModel):
    kind: Literal["email", "pickup"]
    address: str | None = None

    @model_validator(mode="after")
    def validate_address(self) -> Self:
        if self.kind == "email" and self.address is None:
            message = "Email requires an address"
            raise ValueError(message)
        return self


class _EmailDelivery(BaseModel):
    kind: Literal["email"]
    address: str


class _PickupDelivery(BaseModel):
    kind: Literal["pickup"]
    address: str | None = None


class _VariantDelivery(RootModel[Annotated[_EmailDelivery | _PickupDelivery, Field(discriminator="kind")]]):
    pass


class _AliasedValidatedDelivery(_ValidatedDelivery):
    address: str | None = Field(default="default@example.com", alias="destination")


class _AliasedEmailDelivery(_EmailDelivery):
    address: str = Field(default="default@example.com", alias="destination")


class _AliasedPickupDelivery(_PickupDelivery):
    address: str | None = Field(default="default@example.com", alias="destination")


class _AliasedVariantDelivery(
    RootModel[Annotated[_AliasedEmailDelivery | _AliasedPickupDelivery, Field(discriminator="kind")]]
):
    pass


@pytest.mark.parametrize(
    ("original_model", "variant_model", "address_key"),
    [
        (_ValidatedDelivery, _VariantDelivery, "address"),
        (_AliasedValidatedDelivery, _AliasedVariantDelivery, "destination"),
    ],
    ids=["nullable-default", "aliased-nonnullable-default"],
)
@pytest.mark.parametrize("kind", ["email", "pickup", "unknown"])
@pytest.mark.parametrize(
    "payload",
    [{}, {"address": None}, {"address": ""}, {"address": "user@example.com"}],
    ids=["omitted", "null", "empty", "supplied"],
)
def test_variant_example_preserves_every_wire_state(
    original_model: type[BaseModel],
    variant_model: type[BaseModel],
    address_key: str,
    kind: str,
    payload: dict[str, str | None],
) -> None:
    wire = {"kind": kind, **{address_key if key == "address" else key: value for key, value in payload.items()}}
    try:
        original = original_model.model_validate(wire)
    except ValidationError:
        with pytest.raises(ValidationError):
            variant_model.model_validate(wire)
    else:
        variant = variant_model.model_validate(wire)
        assert variant.model_dump() == original.model_dump()
        assert variant.model_dump(by_alias=True) == original.model_dump(by_alias=True)
        assert variant.model_dump(exclude_unset=True) == original.model_dump(exclude_unset=True)
