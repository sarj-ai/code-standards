from __future__ import annotations

from dataclasses import InitVar, asdict, dataclass, fields
from pathlib import Path, PurePosixPath

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rules.prefer_discriminated_model_union import PreferDiscriminatedModelUnion


_BASE = (
    "from dataclasses import dataclass, InitVar\n"
    "from typing import Annotated, Literal\n"
    "from pydantic import Discriminator, Tag\n"
    "@dataclass\nclass Team:\n    team_id: str\n"
    "@dataclass\nclass Global:\n    group: str\n"
    "def scope(value: object) -> str:\n"
    "    if isinstance(value, dict):\n"
    "        return 'team' if 'team_id' in value else 'global'\n"
    "    return 'team' if isinstance(value, Team) else 'global'\n"
)


def _case(case_id: str, source: str, *, match: bool = True) -> EvaluationCase:
    return EvaluationCase(
        case_id,
        Language.PYTHON,
        source,
        ExpectedOutcome.MATCH if match else ExpectedOutcome.NO_MATCH,
        path=PurePosixPath("app/access.py"),
    )


_CASES = (
    _case(
        "expansion-01-callable-metadata-on-single-records",
        _BASE
        + "type Access = Annotated[Team, Tag('team'), Discriminator(scope)] "
        + "| Annotated[Global, Tag('global'), Discriminator(scope)]\n",
        match=False,
    ),
    _case(
        "expansion-02-callable-metadata-on-collapsed-duplicate-aliases",
        _BASE
        + "type TeamOnly = Team | Team\ntype GlobalOnly = Global | Global\n"
        + "type Access = Annotated[TeamOnly, Tag('team'), Discriminator(scope)] "
        + "| Annotated[GlobalOnly, Tag('global'), Discriminator(scope)]\n",
        match=False,
    ),
    _case(
        "expansion-03-shared-initvar-is-constructor-only",
        _BASE.replace("    team_id: str", "    request: InitVar[str]\n    team_id: str").replace(
            "    group: str", "    request: InitVar[str]\n    group: str"
        )
        + "type Access = Team | Global\n",
    ),
    _case(
        "expansion-04-initvar-literals-are-not-instance-tags",
        _BASE.replace("    team_id: str", "    kind: InitVar[Literal['team']]\n    team_id: str").replace(
            "    group: str", "    kind: InitVar[Literal['global']]\n    group: str"
        )
        + "type Access = Team | Global\n",
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_round2_expansion_contexts(case: EvaluationCase) -> None:
    findings = PreferDiscriminatedModelUnion().check(Path(case.path), case.source)
    assert len(findings) == int(case.expected is ExpectedOutcome.MATCH)
    assert all(finding.code == "SARJ510" for finding in findings)


@pytest.mark.parametrize(
    "annotation",
    ["InitVar[str] = ''", "InitVar[Literal['request']] = 'request'", "InitVar[object] = object()"],
)
@pytest.mark.parametrize(
    ("imports", "annotation_owner"),
    [
        ("from dataclasses import dataclass, InitVar", "InitVar"),
        ("from dataclasses import dataclass, InitVar as Input", "Input"),
        ("from dataclasses import dataclass\nimport dataclasses as dc", "dc.InitVar"),
    ],
)
def test_defaulted_constructor_only_input_cannot_hide_missing_data_tag(
    annotation: str, imports: str, annotation_owner: str
) -> None:
    source = (
        _BASE.replace("from dataclasses import dataclass, InitVar", imports)
        .replace("    team_id: str", f"    team_id: str\n    request: {annotation}")
        .replace("    group: str", f"    group: str\n    request: {annotation}")
        .replace("request: InitVar", f"request: {annotation_owner}")
        + "type Access = Team | Global\n"
    )
    findings = PreferDiscriminatedModelUnion().check(Path("app/access.py"), source)
    assert len(findings) == 1
    assert findings[0].severity.value == "error"


def test_defaulted_initvar_is_absent_from_the_serialized_data_contract() -> None:
    @dataclass
    class Team:
        team_id: str
        request: InitVar[str] = "request"

    team = Team("team-1", "caller-context")
    assert asdict(team) == {"team_id": "team-1"}
    assert tuple(field.name for field in fields(Team)) == ("team_id",)


@pytest.mark.parametrize("rebind", ["InitVar = custom_input", "dataclass = custom_record"])
def test_defaulted_initvar_requires_its_actual_unrebound_dataclass_owner(rebind: str) -> None:
    source = (
        _BASE.replace("from typing import Annotated, Literal", f"from typing import Annotated, Literal\n{rebind}")
        .replace("    team_id: str", "    team_id: str\n    request: InitVar[str] = ''")
        .replace("    group: str", "    group: str\n    request: InitVar[str] = ''")
        + "type Access = Team | Global\n"
    )
    assert PreferDiscriminatedModelUnion().check(Path("app/access.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        _CASES[2]
        .source.replace("import dataclass, InitVar", "import dataclass, InitVar as ConstructorInput")
        .replace("request: InitVar[str]", "request: ConstructorInput[str]"),
        _CASES[2]
        .source.replace("from dataclasses import dataclass, InitVar", "import dataclasses as dc")
        .replace("@dataclass", "@dc.dataclass")
        .replace("request: InitVar[str]", "request: dc.InitVar[str]"),
    ],
    ids=("aliased-initvar-import", "qualified-initvar-import"),
)
def test_direct_initvar_import_identity(source: str) -> None:
    assert len(PreferDiscriminatedModelUnion().check(Path("app/access.py"), source)) == 1


@pytest.mark.parametrize(
    ("source", "expected_count"),
    [
        (_CASES[2].source.replace("request: InitVar[str]", "request: Annotated[InitVar[str], 'transport']"), 0),
        (
            _CASES[2]
            .source.replace("@dataclass\nclass Team", "type Input = InitVar[str]\n@dataclass\nclass Team")
            .replace("request: InitVar[str]", "request: Input"),
            0,
        ),
        (
            _CASES[2]
            .source.replace("@dataclass\nclass Team", "Input = InitVar[str]\n@dataclass\nclass Team")
            .replace("request: InitVar[str]", "request: Input"),
            0,
        ),
        (
            _CASES[3]
            .source.replace("kind: InitVar[Literal['team']]", "kind: InitVar[Literal['team']] = 'team'")
            .replace("kind: InitVar[Literal['global']]", "kind: InitVar[Literal['global']] = 'global'")
            .replace("team_id: str", "team_id: str = ''")
            .replace("group: str", "group: str = ''"),
            1,
        ),
    ],
    ids=(
        "annotated-stored-field",
        "pep695-stored-field",
        "runtime-initvar-alias-excluded",
        "defaulted-class-attribute",
    ),
)
def test_initvar_alias_wrappers_and_defaults_follow_storage_contract(source: str, expected_count: int) -> None:
    findings = PreferDiscriminatedModelUnion().check(Path("app/access.py"), source)
    assert len(findings) == expected_count
    assert all(finding.code == "SARJ510" for finding in findings)
