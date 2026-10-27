from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_discriminated_model_union import PreferDiscriminatedModelUnion


_BASE = (
    "from dataclasses import dataclass\nfrom typing import Annotated\n"
    "from pydantic import Discriminator, Tag\n"
    "@dataclass\nclass Team:\n    team_id: str\n"
    "@dataclass\nclass Global:\n    group: str\n"
    "def scope(value: object) -> str:\n"
    "    if isinstance(value, dict):\n"
    "        return 'team' if 'team_id' in value else 'global'\n"
    "    return 'team' if isinstance(value, Team) else 'global'\n"
)
_UNION = "Annotated[Team, Tag('team')] | Annotated[Global, Tag('global')]"


def _case(case_id: str, source: str) -> EvaluationCase:
    return EvaluationCase(
        case_id, Language.PYTHON, source, ExpectedOutcome.NO_MATCH, path=PurePosixPath("app/access.py")
    )


_CASES = (
    _case(
        "round2-fp-01-class-namespace-metadata",
        _BASE
        + "class Markers:\n    access = Discriminator(scope)\n"
        + f"type Access = Annotated[{_UNION}, Markers.access]\n",
    ),
    _case(
        "round2-fp-02-immutable-tuple-metadata",
        _BASE + "CHOICES = (Discriminator(scope),)\n" + f"type Access = Annotated[{_UNION}, CHOICES[0]]\n",
    ),
    _case(
        "round2-fp-03-initvar-real-classvar-tag",
        "from dataclasses import InitVar, asdict, dataclass, fields\n"
        "from typing import Annotated, ClassVar, Literal, assert_type\n"
        "@dataclass\nclass Team:\n    team_id: str\n    request: InitVar[str]\n"
        "    scope: ClassVar[Annotated[Literal['team'], 'persistent-class-tag']] = 'team'\n"
        "@dataclass\nclass Global:\n    group: str\n    request: InitVar[str]\n"
        "    scope: ClassVar[Annotated[Literal['global'], 'persistent-class-tag']] = 'global'\n"
        "type Access = Team | Global\n",
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_metadata_carriers_and_constructor_only_inputs(case: EvaluationCase) -> None:
    assert PreferDiscriminatedModelUnion().check(Path(case.path), case.source) == []


@pytest.mark.parametrize(
    "source",
    [
        _CASES[0].source.replace("access = Discriminator(scope)", "access = 'transport'"),
        _CASES[1].source.replace("(Discriminator(scope),)", "('transport',)"),
        _CASES[0].source.replace("class Markers:", "@adapt\nclass Markers:"),
        _CASES[0].source.replace("class Markers:", "class Markers(Base):"),
        _CASES[0].source.replace("class Markers:\n", "class Markers:\n    Discriminator = custom\n"),
    ],
    ids=(
        "namespace-plain-data",
        "tuple-plain-data",
        "decorated-namespace",
        "inherited-namespace",
        "shadowed-constructor",
    ),
)
def test_carriers_require_a_proven_local_discriminator(source: str) -> None:
    findings = PreferDiscriminatedModelUnion().check(Path("app/access.py"), source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ510"
    assert findings[0].severity is Severity.ERROR


@pytest.mark.parametrize("carrier", [0, 1], ids=("namespace", "tuple"))
@pytest.mark.parametrize("tagged", [False, True], ids=("missing-tags", "literal-tags"))
def test_string_field_carriers_require_disjoint_persistent_tags(carrier: int, *, tagged: bool) -> None:
    source = (
        _CASES[carrier]
        .source.replace("from typing import Annotated", "from typing import Annotated, Literal")
        .replace("from pydantic import Discriminator, Tag", "from pydantic import Discriminator, Field, Tag")
        .replace("Discriminator(scope)", "Field(discriminator='scope')")
    )
    if tagged:
        source = source.replace("team_id: str", "team_id: str\n    scope: Literal['team'] = 'team'").replace(
            "group: str", "group: str\n    scope: Literal['global'] = 'global'"
        )
    findings = PreferDiscriminatedModelUnion().check(Path("app/access.py"), source)
    assert len(findings) == (0 if tagged else 1)
    assert all(finding.code == "SARJ510" and finding.severity is Severity.ERROR for finding in findings)


@pytest.mark.parametrize(
    "setup",
    [
        "Markers.access = object()\n",
        "alias = Markers\nalias.access = object()\n",
        "alias = Markers.access\nmutate(alias)\n",
        "mutate(Markers.access)\n",
        "def adapt() -> None:\n    global Markers\n    Markers = object\nadapt()\n",
    ],
    ids=("attribute-write", "namespace-alias-write", "member-escape", "helper-escape", "global-rebinding"),
)
def test_namespace_metadata_mutation_and_escape_abstain(setup: str) -> None:
    source = _CASES[0].source.replace("type Access =", f"{setup}type Access =")
    assert PreferDiscriminatedModelUnion().check(Path("app/access.py"), source) == []


@pytest.mark.parametrize(
    "setup",
    [
        "CHOICES[0].discriminator = 'scope'\n",
        "alias = CHOICES\nalias[0].discriminator = 'scope'\n",
        "mutate(CHOICES[0])\n",
        "def adapt() -> None:\n    global CHOICES\n    CHOICES = replacement\nadapt()\n",
    ],
    ids=("member-write", "container-alias-write", "helper-escape", "global-rebinding"),
)
def test_tuple_metadata_mutation_and_escape_abstain(setup: str) -> None:
    source = _CASES[1].source.replace("type Access =", f"{setup}type Access =")
    assert PreferDiscriminatedModelUnion().check(Path("app/access.py"), source) == []


@pytest.mark.parametrize("index", ["-1", "+0"])
def test_literal_tuple_indices_follow_python_indexing(index: str) -> None:
    source = _CASES[1].source.replace("CHOICES[0]", f"CHOICES[{index}]")
    assert PreferDiscriminatedModelUnion().check(Path("app/access.py"), source) == []


def test_unknown_tuple_index_abstains() -> None:
    source = (
        _CASES[1]
        .source.replace("type Access =", "selected = choose_index()\ntype Access =")
        .replace("CHOICES[0]", "CHOICES[selected]")
    )
    assert PreferDiscriminatedModelUnion().check(Path("app/access.py"), source) == []


def test_unrelated_local_carrier_names_do_not_escape_module_metadata() -> None:
    source = _CASES[1].source + "def helper(CHOICES: object) -> object:\n    return CHOICES\n"
    assert PreferDiscriminatedModelUnion().check(Path("app/access.py"), source) == []


def test_tuple_metadata_alias_expansion_is_bounded() -> None:
    aliases = "".join(f"LINK{i} = LINK{i - 1}\n" for i in range(1, 140))
    source = (
        _CASES[1]
        .source.replace("type Access =", f"LINK0 = CHOICES\n{aliases}type Access =")
        .replace("CHOICES[0]", "LINK139[0]")
    )
    assert PreferDiscriminatedModelUnion().check(Path("app/access.py"), source) == []
