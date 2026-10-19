from __future__ import annotations

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
    "source",
    [
        _CASES[2].source.replace("request: InitVar[str]", "request: Annotated[InitVar[str], 'transport']"),
        _CASES[2]
        .source.replace("@dataclass\nclass Team", "type Input = InitVar[str]\n@dataclass\nclass Team")
        .replace("request: InitVar[str]", "request: Input"),
        _CASES[2]
        .source.replace("@dataclass\nclass Team", "Input = InitVar[str]\n@dataclass\nclass Team")
        .replace("request: InitVar[str]", "request: Input"),
        _CASES[3]
        .source.replace("kind: InitVar[Literal['team']]", "kind: InitVar[Literal['team']] = 'team'")
        .replace("kind: InitVar[Literal['global']]", "kind: InitVar[Literal['global']] = 'global'")
        .replace("team_id: str", "team_id: str = ''")
        .replace("group: str", "group: str = ''"),
    ],
    ids=(
        "annotated-stored-field",
        "pep695-stored-field",
        "runtime-initvar-alias-excluded",
        "defaulted-class-attribute",
    ),
)
def test_initvar_alias_wrappers_and_defaults_remain_conservative(source: str) -> None:
    assert not PreferDiscriminatedModelUnion().check(Path("app/access.py"), source)
