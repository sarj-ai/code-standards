from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_discriminated_model_union import PreferDiscriminatedModelUnion


_BASE = (
    "from dataclasses import dataclass\n"
    "from typing import Annotated, Final\n"
    "from pydantic import Discriminator, Field, Tag\n"
    "from pydantic.fields import FieldInfo\n"
    "@dataclass\nclass Team:\n    team_id: str\n"
    "@dataclass\nclass Global:\n    group: str\n"
    "def scope(value: object) -> str:\n"
    "    if isinstance(value, dict):\n"
    "        return 'team' if 'team_id' in value else 'global'\n"
    "    return 'team' if isinstance(value, Team) else 'global'\n"
)
_UNION = "Annotated[Team, Tag('team')] | Annotated[Global, Tag('global')]"


def _case(case_id: str, setup: str, metadata: str, *, match: bool = False) -> EvaluationCase:
    return EvaluationCase(
        case_id,
        Language.PYTHON,
        _BASE + setup + f"type Access = Annotated[{_UNION}, {metadata}]\n",
        ExpectedOutcome.MATCH if match else ExpectedOutcome.NO_MATCH,
        path=PurePosixPath("app/access.py"),
    )


_FALSE_POSITIVE_CASES = (
    _case("fp-01-reusable-discriminator-object", "ACCESS_TAGGER = Discriminator(scope)\n", "ACCESS_TAGGER"),
    EvaluationCase(
        "fp-02-imported-pydantic-types-module",
        Language.PYTHON,
        (_BASE + f"type Access = Annotated[{_UNION}, Discriminator(scope)]\n")
        .replace("from pydantic import Discriminator, Field, Tag", "from pydantic import types as pt")
        .replace("Discriminator(scope)", "pt.Discriminator(scope)")
        .replace("Tag('", "pt.Tag('"),
        ExpectedOutcome.NO_MATCH,
        path=PurePosixPath("app/access.py"),
    ),
    _case(
        "fp-03-annotated-reusable-field-info",
        "ACCESS_FIELD: FieldInfo = Field(discriminator=Discriminator(scope))\n",
        "ACCESS_FIELD",
    ),
)
_EXPANSION_CASES = (
    _case("expansion-01-field-name-string-binding", "FIELD_NAME = 'scope'\n", "Discriminator(FIELD_NAME)", match=True),
    _case(
        "expansion-02-final-field-name-alias-chain",
        "FIELD_NAME: Final[str] = 'scope'\nDISCRIMINATOR_FIELD: Final = FIELD_NAME\n",
        "Discriminator(discriminator=DISCRIMINATOR_FIELD)",
        match=True,
    ),
    _case("expansion-03-concatenated-field-name-literals", "", "Discriminator('sc' + 'ope')", match=True),
    _case(
        "expansion-04-mutated-field-discriminator-control",
        "ACCESS_FIELD = Field(discriminator=Discriminator(scope))\nACCESS_FIELD.discriminator = 'scope'\n",
        "ACCESS_FIELD",
        match=True,
    ),
)
_CASES = (*_FALSE_POSITIVE_CASES, *_EXPANSION_CASES)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_discriminated_union_metadata_followups(case: EvaluationCase) -> None:
    findings = PreferDiscriminatedModelUnion().check(Path(case.path), case.source)
    assert len(findings) == int(case.expected is ExpectedOutcome.MATCH)
    for finding in findings:
        assert finding.code == "SARJ510"
        assert finding.severity is Severity.WARNING
        assert finding.line == len(case.source.splitlines())
        assert finding.col == 1


@pytest.mark.parametrize(
    "source",
    [
        _FALSE_POSITIVE_CASES[0].source.replace(
            "from pydantic import Discriminator, Field, Tag",
            "from custom import Discriminator\nfrom pydantic import Field, Tag",
        ),
        _FALSE_POSITIVE_CASES[0].source.replace("type Access =", "ACCESS_TAGGER = object()\ntype Access ="),
        _FALSE_POSITIVE_CASES[1].source.replace("type Access =", "pt.Discriminator = object\ntype Access ="),
    ],
    ids=("unproven-constructor", "rebound-metadata-object", "mutated-imported-submodule"),
)
def test_metadata_discriminator_requires_stable_provenance(source: str) -> None:
    findings = PreferDiscriminatedModelUnion().check(Path("app/access.py"), source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ510"


@pytest.mark.parametrize(
    ("mutation", "expected_count"),
    [
        ("other.discriminator = 'scope'\n", 1),
        ("other.title = 'Access union'\n", 0),
        ("ACCESS_FIELD.title = 'Access union'\n", 0),
        ("other.discriminator = Discriminator(scope)\n", 0),
        (
            "def mutate(field: FieldInfo) -> None:\n    field.discriminator = 'scope'\nmutate(other)\n",
            0,
        ),
        (
            (
                "other.discriminator = 'scope'\n"
                "def restore(field: FieldInfo) -> None:\n    field.discriminator = Discriminator(scope)\nrestore(other)\n"
            ),
            0,
        ),
    ],
    ids=(
        "aliased-string-write",
        "passive-title-write",
        "direct-passive-title-write",
        "callable-write",
        "opaque-helper",
        "opaque-restoring-helper",
    ),
)
def test_aliased_metadata_mutation_preserves_uncertainty(mutation: str, expected_count: int) -> None:
    case = _case(
        "aliased-metadata-mutation",
        f"ACCESS_FIELD = Field(discriminator=Discriminator(scope))\nother = ACCESS_FIELD\n{mutation}",
        "ACCESS_FIELD",
    )
    findings = PreferDiscriminatedModelUnion().check(Path(case.path), case.source)
    assert len(findings) == expected_count


def test_global_string_binding_replaced_by_callable_abstains() -> None:
    case = _case(
        "global-string-rebinding",
        "FIELD_NAME: str | Callable[[object], str] = 'scope'\n"
        "def replace_discriminator() -> None:\n    global FIELD_NAME\n    FIELD_NAME = scope\n"
        "replace_discriminator()\n",
        "Discriminator(FIELD_NAME)",
    )
    source = f"from typing import Callable\n{case.source}"
    assert PreferDiscriminatedModelUnion().check(Path(case.path), source) == []
