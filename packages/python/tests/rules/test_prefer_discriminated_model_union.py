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
    assert verify_native_rule(PreferDiscriminatedModelUnion, analyze) == 4


def test_multiple_variant_requirements_produce_one_model_review() -> None:
    source = _BASE.replace("    @model_validator", "    location: str | None = None\n    @model_validator").replace(
        "        return self",
        "        if self.kind == 'pickup' and self.location is None:\n"
        "            raise ValueError('Pickup requires a location')\n        return self",
    )
    [finding] = _check(source)
    assert finding.line == 9
    assert finding.col == 9
    assert finding.severity is Severity.ERROR
    assert "preserve every other accepted combination" in finding.message


@pytest.mark.parametrize(
    ("tags", "condition"),
    [
        ("1, 2", "self.kind == 1"),
        ("-1, 2", "self.kind == -1"),
        ("True, False", "self.kind is True"),
        ("True, False", "self.kind == False"),
        ("'email', 'sms', 'pickup'", "self.kind in ('email', 'sms')"),
        ("'email', 'sms', 'pickup'", "self.kind != 'pickup'"),
        ("'email', 'sms', 'pickup'", "self.kind not in ['pickup']"),
        ("'email', 'sms', 'pickup'", "self.kind == 'email' or self.kind == 'sms'"),
        ("'email', 'sms', 'pickup'", "not (self.kind == 'pickup')"),
    ],
)
def test_finite_scalar_tag_subsets(tags: str, condition: str) -> None:
    source = _BASE.replace("'email', 'pickup'", tags).replace("self.kind == 'email'", f"({condition})")
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "condition",
    [
        "(self.kind == 'email' and self.address is None)",
        "not (self.kind != 'email' or self.address is not None)",
        "self.kind == 'email' and (self.address is None or self.subject is None)",
        "(self.kind == 'email' and self.address is None) or (self.kind == 'pickup' and self.subject is None)",
    ],
)
def test_exact_rejection_region_algebra(condition: str) -> None:
    source = _BASE.replace("    @model_validator", "    subject: str | None = None\n    @model_validator")
    source = source.replace("self.kind == 'email' and self.address is None", condition)
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "body",
    [
        "        if self.kind == 'email':\n            if self.address is None:\n                raise ValueError('required')\n        return self\n",
        "        if self.kind != 'email' or self.address is not None:\n            return self\n        raise ValueError('required')\n",
        "        if self.kind == 'email' and self.address is None:\n            raise ValueError('required')\n        else:\n            return self\n",
        "        if self.kind == 'email':\n            if self.address is not None:\n                return self\n            raise ValueError('required')\n        return self\n",
    ],
)
def test_nested_and_accepted_paths_prove_the_same_requirement(body: str) -> None:
    source = _BASE[: _BASE.index("        if self.kind")] + body
    assert len(_check(source)) == 1


def test_independent_pure_after_validators_and_common_constraints() -> None:
    source = _BASE.replace("    @model_validator", "    subject: str | None = None\n    @model_validator")
    source += (
        "    @model_validator(mode='after')\n    def validate_subject(self) -> Self:\n"
        "        if self.kind == 'pickup' and self.subject is None:\n"
        "            raise ValueError('required')\n        return self\n"
    )
    assert len(_check(source)) == 1
    common = source.replace("self.kind == 'pickup' and self.subject", "self.kind == 'pickup' and self.address")
    assert _check(common) == []


@pytest.mark.parametrize(
    "condition",
    [
        "self.kind == 'email' and self.address is None and self.subject is None",
        "self.kind == 'email' and self.address is None and self.subject is not None",
        "self.kind == 'email' and (self.address is None or helper())",
        "self.kind == 'email' and self.address is None and enabled",
        "self.kind == 'email' and self.other_kind == 'email' and self.address is None",
        "self.kind == 'email' and self.address == None",
        "self.kind == 'email' and not self.address",
        "self.kind in allowed and self.address is None",
        "self.kind in ('email', unknown) and self.address is None",
    ],
)
def test_unknown_or_jointly_missing_conditions_do_not_invent_individual_requirements(condition: str) -> None:
    source = _BASE.replace(
        "    @model_validator",
        "    subject: str | None = None\n    other_kind: Literal['email', 'pickup']\n    @model_validator",
    ).replace("self.kind == 'email' and self.address is None", condition)
    assert _check(source) == []


@pytest.mark.parametrize(
    ("annotation", "condition"),
    [
        ("Literal[True, 1, 'pickup']", "self.kind == True"),
        ("Literal[1, 'pickup']", "self.kind == 1"),
        ("Literal[1.5, 2.5]", "self.kind == 1.5"),
        ("Literal[1, 2]", "self.kind == True"),
        ("Literal[True, False]", "self.kind == 1"),
        ("Literal['email', 'pickup']", "self.kind in 'email'"),
        ("Literal['email', 'pickup']", "self.kind is 'email'"),
    ],
)
def test_tag_equality_identity_and_literal_domain_boundaries(annotation: str, condition: str) -> None:
    source = _BASE.replace("Literal['email', 'pickup']", annotation).replace("self.kind == 'email'", condition)
    assert _check(source) == []


@pytest.mark.parametrize("option", ["min_length=2, max_length=1", "pattern='(?!)'", "gt=3, lt=2"])
def test_field_constraints_cannot_supply_a_non_none_inhabitance_proof(option: str) -> None:
    source = _BASE.replace("from pydantic import", "from pydantic import Field,").replace(
        "address: str | None = None", f"address: str | None = Field(default=None, {option})"
    )
    assert _check(source) == []


@pytest.mark.parametrize("option", ["alias='destination'", "description='Wire address'", "default='ready'"])
def test_passive_field_metadata_and_defaults_preserve_the_requirement(option: str) -> None:
    source = _BASE.replace("from pydantic import", "from pydantic import Field,").replace(
        "address: str | None = None", f"address: str | None = Field({option})"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "suffix",
    [
        "Delivery.model_fields['kind'].annotation = Literal['pickup']\nDelivery.model_rebuild(force=True)\n",
        "configure(Delivery)\n",
        "Alias = Delivery\n",
        "Delivery = other\n",
        "Delivery.validate_address = replacement\n",
        "alias: object = Delivery\n",
    ],
)
def test_mutated_rebuilt_escaped_or_rebound_models_abstain(suffix: str) -> None:
    assert _check(_BASE + suffix) == []


def test_direct_validated_construction_and_type_annotations_preserve_model_identity() -> None:
    source = _BASE + "value: Delivery = Delivery.model_validate({'kind': 'pickup'})\n"
    assert len(_check(source)) == 1


def test_overridden_validator_definitions_and_implicit_class_binding_abstain() -> None:
    duplicate = _BASE + (
        "    @model_validator(mode='after')\n    def validate_address(self) -> Self:\n        return self\n"
    )
    assert _check(duplicate) == []
    assert _check(_BASE.replace("self", "cls")) == []


@pytest.mark.parametrize(
    "annotation", ["tuple[str, int] | None", "tuple[None] | None", "tuple[list[str], tuple[int, bool]] | None"]
)
def test_fixed_tuple_payloads_have_a_concrete_non_none_witness(annotation: str) -> None:
    assert len(_check(_BASE.replace("str | None", annotation))) == 1


def test_canonical_union_payload_and_imported_builtin_rejection() -> None:
    source = _BASE.replace("Literal, Self", "Literal, Self, Union").replace("str | None", "Union[str, None]")
    source = "from builtins import ValueError as Rejected\n" + source.replace("raise ValueError", "raise Rejected")
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "annotation",
    ["Literal['email'] | Literal['pickup']", "Union[Literal['email'], Literal['pickup']]", "Literal['email', None]"],
)
def test_composed_literal_domains_and_explicit_null_tag_state(annotation: str) -> None:
    source = "from typing import Union\n" + _BASE.replace("Literal['email', 'pickup']", annotation)
    assert len(_check(source)) == 1


def test_null_tag_identity_is_not_missing_input() -> None:
    source = _BASE.replace("Literal['email', 'pickup']", "Literal['email', None]").replace(
        "self.kind == 'email'", "self.kind is None"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "annotation",
    ["Literal['email'] | str", "Literal[True] | Literal[1]", "Literal['email'] | Literal['email']", "TagAlias"],
)
def test_composed_tag_domains_keep_open_collision_duplicate_and_alias_boundaries(annotation: str) -> None:
    assert _check(_BASE.replace("Literal['email', 'pickup']", annotation)) == []


def test_many_literal_tags_and_boolean_regions_are_bounded() -> None:
    tags = ",".join(repr(str(index)) for index in range(2000))
    source = _BASE.replace("Literal['email', 'pickup']", f"Literal[{tags}]").replace("== 'email'", "== '0'")
    assert _check(source) == []


def test_rejection_region_complexity_abstains_without_changing_ordinary_cases() -> None:
    alternatives = " or ".join("self.address is None" for _ in range(256))
    source = _BASE.replace("self.address is None:", f"({alternatives}):")
    assert _check(source) == []
    nested = "not " * 80 + "(self.address is None)"
    assert _check(_BASE.replace("self.address is None", nested)) == []
    assert len(_check(_BASE)) == 1


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


@pytest.mark.parametrize(
    ("keyword", "mode", "matches"),
    [
        ("mode", r"'a\x66ter'", True),
        ("mode", r"'\u0061fter'", True),
        ("mode", "'af' 'ter'", True),
        ("ｍｏｄｅ", "'af' 'ter'", True),
        ("mode", "'be' 'fore'", False),
        ("mode", r"'a\x66ters'", False),
    ],
)
def test_validator_mode_uses_native_literal_and_keyword_identity(keyword: str, mode: str, *, matches: bool) -> None:
    source = _BASE.replace("mode='after'", f"{keyword}={mode}")
    assert len(_check(source)) == int(matches)


@pytest.mark.parametrize("member", ["str", "UnknownPayload"])
def test_deep_payload_union_keeps_proven_scalar_and_unknown_member_boundaries(member: str) -> None:
    annotation = " | ".join(["str"] * 3000 + [member, "None"])
    source = _BASE.replace("str | None", annotation)
    assert len(_check(source)) == int(member == "str")


@pytest.mark.parametrize("scalar_count", [501, 3001])
def test_supported_deep_union_preserves_the_error_under_the_complete_profile(tmp_path: Path, scalar_count: int) -> None:
    annotation = " | ".join(["str"] * scalar_count + ["None"])
    path = tmp_path / "models.py"
    path.write_text(_BASE.replace("str | None", annotation), encoding="utf-8", newline="")
    findings = analyze(list(REGISTRY), [path])
    warnings = [finding for finding in findings if finding.code == PreferDiscriminatedModelUnion.code]
    assert len(warnings) == 1
    assert warnings[0].severity is Severity.ERROR


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


def test_error_registration_suppression_and_exit_behavior(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = check_source([PreferDiscriminatedModelUnion()], Path("app/models.py"), _BASE)
    assert len(result) == 1
    assert result[0].code == "SARJ510"
    path = tmp_path / "delivery.py"
    path.write_text(_BASE)
    assert main(["check", "--rule", PreferDiscriminatedModelUnion.id, str(path)]) == 1
    output = capsys.readouterr().out
    assert "SARJ510" in output
    assert "warning:" not in output
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
