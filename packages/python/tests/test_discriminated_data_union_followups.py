from __future__ import annotations

from pathlib import Path, PurePosixPath
import subprocess
import sys

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import check_source
from sarj_python_lint.rules.prefer_discriminated_model_union import PreferDiscriminatedModelUnion


_RECORDS = (
    "from dataclasses import dataclass\n"
    "from typing import Annotated, ClassVar, Final, Literal, TypeAlias\n"
    "@dataclass\nclass Team:\n    team_id: str\n"
    "@dataclass\nclass Global:\n    group: str\n"
    "type Access = Team | Global\n"
)
_MODELS = (
    "from pydantic import BaseModel\n"
    "from typing import Literal\n"
    "class Team(BaseModel):\n    team_id: str\n"
    "class Global(BaseModel):\n    group: str\n"
    "type Access = Team | Global\n"
)
_TYPED = (
    "from typing import TypedDict, Literal\n"
    "class Team(TypedDict):\n    team_id: str\n"
    "class Global(TypedDict):\n    group: str\n"
    "type Access = Team | Global\n"
)
_CALLABLE = (
    "from dataclasses import dataclass\nfrom typing import Annotated\n"
    "from pydantic import Discriminator, Tag\n"
    "@dataclass\nclass Team:\n    team_id: str\n"
    "@dataclass\nclass Global:\n    group: str\n"
    "def scope(value: object) -> str:\n"
    "    if isinstance(value, Team):\n        return 'team'\n"
    "    return 'global'\n"
    "type Access = Annotated[Annotated[Team, Tag('team')] | Annotated[Global, Tag('global')], "
    "Discriminator(scope)]\n"
)
_QUALIFIED_CALLABLE = (
    _CALLABLE.replace("from pydantic import Discriminator, Tag", "import pydantic as p")
    .replace("Tag('", "p.Tag('")
    .replace("Discriminator(scope)", "p.Discriminator(scope)")
)
_BOUNDS_PLAIN = (
    "from dataclasses import dataclass\nfrom typing import Annotated, Literal, TYPE_CHECKING\n"
    "@dataclass\nclass Alpha:\n    payload: str\n"
    "@dataclass\nclass Beta:\n    payload: str\n"
)
_BOUNDS_ALIAS = "type Outcome = Alpha | Beta\n"


def _tags(source: str, first: str, second: str) -> str:
    return source.replace("    team_id: str", f"    scope: {first}\n    team_id: str").replace(
        "    group: str", f"    scope: {second}\n    group: str"
    )


_TAGGED = _tags(_RECORDS, "Literal['team']", "Literal['global']")
_BOOLEAN_INTEGER = _tags(_RECORDS, "Literal[False]", "Literal[0]")
_BOUNDS_TAGGED = _BOUNDS_PLAIN.replace("    payload: str", "    kind: Literal['alpha']\n    payload: str", 1).replace(
    "class Beta:\n", "class Beta:\n    kind: Literal['beta']\n"
)


def _case(case_id: str, source: str, *, match: bool = False) -> EvaluationCase:
    return EvaluationCase(
        case_id,
        Language.PYTHON,
        source,
        ExpectedOutcome.MATCH if match else ExpectedOutcome.NO_MATCH,
        path=PurePosixPath("app/access.py"),
    )


def _final_tags(source: str, first: str, second: str) -> str:
    return (
        _tags(source, f"Final[Literal[{first!r}]] = {first!r}", f"Final[Literal[{second!r}]] = {second!r}")
        .replace("    team_id: str", "    team_id: str = ''")
        .replace("    group: str", "    group: str = ''")
    )


_FALSE_POSITIVE_CASES = (
    _case(
        "fp01-qualified-imported-tag",
        "import organization_tags\n" + _TAGGED.replace("Literal['team']", "organization_tags.Scope"),
    ),
    _case(
        "fp02-runtime-type-alias-type-tag",
        _TAGGED.replace("from typing import ", "from typing import TypeAliasType, ")
        .replace(
            "@dataclass\nclass Team", 'TeamScope = TypeAliasType("TeamScope", Literal["team"])\n@dataclass\nclass Team'
        )
        .replace("Literal['team']", "TeamScope"),
    ),
    _case("fp03-final-literal-tag", _final_tags(_RECORDS, "team", "global")),
    _case("fp04-public-dunder-tag", _TAGGED.replace("    scope:", "    __kind__:")),
    _case("fp05-callable-discriminator", _CALLABLE),
    _case(
        "fp06-renamed-callable-discriminator",
        _CALLABLE.replace("import Discriminator, Tag", "import Discriminator as D, Tag as T")
        .replace("Tag('", "T('")
        .replace("Discriminator(scope)", "D(scope)"),
    ),
    _case(
        "fp07-qualified-callable-discriminator",
        _CALLABLE.replace("from pydantic import Discriminator, Tag", "import pydantic as p")
        .replace("Tag('", "p.Tag('")
        .replace("Discriminator(scope)", "p.Discriminator(scope)"),
    ),
    _case(
        "fp08-types-module-discriminator",
        _CALLABLE.replace("from pydantic import Discriminator, Tag", "from pydantic.types import Discriminator, Tag"),
    ),
    _case("fp09-shadowed-discriminator-near-miss", _CALLABLE + "Discriminator = object\n", match=True),
    _case(
        "fp10-unrelated-discriminator-name",
        _CALLABLE.replace("from pydantic import Discriminator, Tag", "from custom import Discriminator, Tag"),
        match=True,
    ),
    _case(
        "fp11-callable-discriminator-metadata-order",
        _CALLABLE.replace("Discriminator(scope)]", "'transport', Discriminator(scope), 'schema-v1']"),
    ),
    _case(
        "fp12-callable-field-discriminator",
        _CALLABLE.replace("import Discriminator, Tag", "import Discriminator, Field, Tag").replace(
            "Discriminator(scope)]", "Field(discriminator=Discriminator(scope))]"
        ),
    ),
    _case(
        "fp13-known-scalar-alias-control",
        _TAGGED.replace("@dataclass\nclass Team", "TeamScope: TypeAlias = str\n@dataclass\nclass Team").replace(
            "Literal['team']", "TeamScope"
        ),
        match=True,
    ),
    _case(
        "fp14-known-container-alias-control",
        "type TeamScope = list[str]\n" + _TAGGED.replace("Literal['team']", "TeamScope"),
        match=True,
    ),
    _case(
        "fp15-final-class-var-tag",
        _tags(
            _RECORDS,
            "ClassVar[Final[Literal['team']]] = 'team'",
            "ClassVar[Final[Literal['global']]] = 'global'",
        ),
    ),
    _case(
        "fp16-annotated-qualified-imported-tag",
        "import organization_tags\n"
        + _TAGGED.replace("Literal['team']", "Annotated[organization_tags.Scope, 'schema']"),
    ),
    _case("fp17-overlapping-final-tag-control", _final_tags(_RECORDS, "same", "same"), match=True),
    _case(
        "fp18-tags-without-discriminator-control",
        _CALLABLE.replace(
            "type Access = Annotated[Annotated[Team, Tag('team')] | Annotated[Global, Tag('global')], Discriminator(scope)]",
            "type Access = Annotated[Team, Tag('team')] | Annotated[Global, Tag('global')]",
        ),
        match=True,
    ),
)

_EXPANSION_CASES = (
    _case(
        "e01-final-outside-dataclass",
        "from typing import final\n" + _RECORDS.replace("@dataclass", "@final\n@dataclass"),
        match=True,
    ),
    _case(
        "e02-final-inside-dataclass",
        "import typing as t\n" + _RECORDS.replace("@dataclass", "@dataclass\n@t.final"),
        match=True,
    ),
    _case(
        "e03-final-direct-pydantic",
        "from typing import final as sealed\n" + _MODELS.replace("class ", "@sealed\nclass "),
        match=True,
    ),
    _case(
        "e04-unproven-final-decorator",
        "from custom import final\n" + _RECORDS.replace("@dataclass", "@final\n@dataclass"),
    ),
    _case(
        "e05-reassigned-final-decorator",
        "from typing import final\n" + _RECORDS.replace("@dataclass", "@final\n@dataclass") + "final = adapt\n",
    ),
    # Runtime TypeAliasType union declarations remain outside the supported alias forms.
    _case(
        "e06-explicit-runtime-type-alias-excluded",
        "from typing import TypeAliasType\n"
        + _RECORDS.replace("type Access = Team | Global", "Access = TypeAliasType('Access', Team | Global)"),
    ),
    _case(
        "e07-qualified-runtime-type-alias-tagged",
        "import typing as t\n"
        + _TAGGED.replace("type Access = Team | Global", "Access = t.TypeAliasType('Access', Team | Global)"),
    ),
    _case(
        "e08-custom-runtime-alias-constructor",
        "from custom import TypeAliasType\n"
        + _RECORDS.replace("type Access = Team | Global", "Access = TypeAliasType('Access', Team | Global)"),
    ),
    _case(
        "e09-generic-runtime-type-alias",
        "from typing import TypeAliasType, TypeVar\nT = TypeVar('T')\n"
        + _RECORDS.replace(
            "type Access = Team | Global", "Access = TypeAliasType('Access', Team | Global, type_params=(T,))"
        ),
    ),
    _case(
        "e10-nested-literal-overlap",
        _tags(_RECORDS, "Literal[Literal['team', 'global']]", "Literal['global']"),
        match=True,
    ),
    _case(
        "e11-nested-literal-disjoint",
        _tags(_RECORDS, "Literal[Literal['team'], Literal['partner']]", "Literal['global']"),
    ),
    _case(
        "e12-pep695-alias-inside-literal-overlap",
        _tags(_RECORDS, "Literal[Shared]", "Literal['global']").replace(
            "from typing import Annotated", "type Shared = Literal['team', 'global']\nfrom typing import Annotated"
        ),
        match=True,
    ),
    _case(
        "e13-legacy-alias-inside-literal-disjoint",
        _tags(_RECORDS, "Literal[TeamTag]", "Literal['global']").replace(
            "@dataclass\nclass Team", "TeamTag: TypeAlias = Literal['team']\n@dataclass\nclass Team"
        ),
    ),
    # TypedDict schema keywords are deliberately not guessed from partially modeled options.
    _case("e14-closed-typed-dict-excluded", _TYPED.replace("TypedDict):", "TypedDict, closed=True):")),
    _case("e15-boolean-integer-static-literal-distinction", _BOOLEAN_INTEGER),
    # Class-body configuration assignments keep this model outside direct field-only records.
    _case(
        "e16-frozen-pydantic-config-excluded",
        _MODELS.replace("import BaseModel", "import BaseModel, ConfigDict").replace(
            "(BaseModel):", "(BaseModel):\n    model_config = ConfigDict(frozen=True)"
        ),
    ),
    _case(
        "e17-keyword-only-pseudo-field",
        _RECORDS.replace("import dataclass", "import dataclass, KW_ONLY")
        .replace("class Team:\n", "class Team:\n    _: KW_ONLY\n")
        .replace("class Global:\n", "class Global:\n    _: KW_ONLY\n"),
        match=True,
    ),
)


def _linear_aliases() -> str:
    aliases = "type Link0 = Alpha\n" + "".join(f"type Link{i} = Link{i - 1}\n" for i in range(1, 140))
    return _BOUNDS_PLAIN + aliases + "type Outcome = Link139 | Beta\n"


def _doubling_aliases() -> str:
    aliases = "type Link0 = Alpha\n" + "".join(f"type Link{i} = Link{i - 1} | Link{i - 1}\n" for i in range(1, 9))
    return _BOUNDS_PLAIN + aliases + "type Outcome = Link8 | Beta\n"


def _field_wrappers() -> str:
    prefix = ["Annotated["] * 140
    suffix = [", 0]"] * 140
    alpha = "".join([*prefix, "Literal['alpha']", *suffix])
    beta = "".join([*prefix, "Literal['beta']", *suffix])
    return _BOUNDS_TAGGED.replace("Literal['alpha']", alpha).replace("Literal['beta']", beta) + _BOUNDS_ALIAS


def _large_literal_domain() -> str:
    values = ", ".join(repr(f"alpha-{i}") for i in range(1000))
    return _BOUNDS_TAGGED.replace("Literal['alpha']", f"Literal[{values}]") + _BOUNDS_ALIAS


def _overlap_cycle(*, distinguished: bool) -> str:
    extra_alpha = "    ab: Literal['alpha']\n    ca: Literal['alpha']\n" if distinguished else ""
    extra_beta = "    ab: Literal['beta']\n    bc: Literal['beta']\n" if distinguished else ""
    extra_gamma = "    bc: Literal['gamma']\n    ca: Literal['gamma']\n" if distinguished else ""
    return (
        "from dataclasses import dataclass\nfrom typing import Literal\n"
        "@dataclass\nclass Alpha:\n    kind: Literal['a', 'b']\n"
        + extra_alpha
        + "@dataclass\nclass Beta:\n    kind: Literal['b', 'c']\n"
        + extra_beta
        + "@dataclass\nclass Gamma:\n    kind: Literal['c', 'a']\n"
        + extra_gamma
        + "type Outcome = Alpha | Beta | Gamma\n"
    )


_BOUNDS_CASES = (
    _case("bounds-01-linear-record-alias-budget", _linear_aliases()),
    _case("bounds-02-exponential-alias-dag-budget", _doubling_aliases()),
    _case(
        "bounds-03-recursive-literal-alias",
        _BOUNDS_TAGGED.replace("Literal['alpha']", "AlphaTag") + "type AlphaTag = AlphaTag\n" + _BOUNDS_ALIAS,
    ),
    _case("bounds-04-field-annotation-wrapper-budget", _field_wrappers()),
    _case("bounds-05-wide-finite-literal-domain", _large_literal_domain()),
    _case(
        "bounds-06-two-partially-unresolved-tag-domains",
        "from external import AlphaTag, BetaTag\n"
        + _BOUNDS_TAGGED.replace("Literal['alpha']", "AlphaTag | Literal['alpha']").replace(
            "Literal['beta']", "BetaTag | Literal['beta']"
        )
        + _BOUNDS_ALIAS,
    ),
    _case("bounds-07-cyclic-overlap-without-secondary-axis", _overlap_cycle(distinguished=False), match=True),
    _case("bounds-08-cyclic-overlap-with-subgroup-axes", _overlap_cycle(distinguished=True)),
    _case(
        "bounds-09-multiline-declaration-line-suppression",
        _BOUNDS_PLAIN + "type Outcome = (  # sarj-noqa: SARJ510 -- persisted wire format\n    Alpha | Beta\n)\n",
    ),
    _case(
        "bounds-10-multiline-closing-line-not-owner",
        _BOUNDS_PLAIN + "type Outcome = (\n    Alpha | Beta\n)  # sarj-noqa: SARJ510 -- another physical line\n",
        match=True,
    ),
    _case(
        "bounds-11-marker-inside-annotation-string",
        _BOUNDS_PLAIN + "type Outcome = Annotated[Alpha | Beta, '# sarj-noqa: SARJ510 -- metadata is not a comment']\n",
        match=True,
    ),
    _case(
        "bounds-12-two-aliases-on-one-line",
        _BOUNDS_PLAIN + "type First = Alpha | Beta; type Second = Alpha | Beta\n",
        match=True,
    ),
    _case(
        "bounds-13-type-checking-only-declarations",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
        + "".join("    " + line + "\n" for line in (_BOUNDS_PLAIN + _BOUNDS_ALIAS).splitlines()),
    ),
    _case(
        "bounds-14-deep-source-union-budget",
        _BOUNDS_PLAIN + "type Outcome = " + " | ".join(["Alpha"] * 5000 + ["Beta"]) + "\n",
    ),
    _case("bounds-15-combined-runner-repeated-invocation", _BOUNDS_PLAIN + _BOUNDS_ALIAS, match=True),
)

_CASES = (*_FALSE_POSITIVE_CASES, *_EXPANSION_CASES, *_BOUNDS_CASES)


def _expected_count(case: EvaluationCase) -> int:
    if case.case_id == "bounds-12-two-aliases-on-one-line":
        return 2
    return int(case.expected is ExpectedOutcome.MATCH)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_discriminated_data_union_followups(case: EvaluationCase) -> None:
    rule = PreferDiscriminatedModelUnion()
    if case.case_id == "bounds-15-combined-runner-repeated-invocation":
        counts = [
            len(check_source([rule], Path(case.path), source))
            for source in (case.source, _BOUNDS_TAGGED + _BOUNDS_ALIAS, case.source)
        ]
        assert counts == [1, 0, 1]
    findings = rule.check(Path(case.path), case.source)
    assert len(findings) == _expected_count(case)
    locations = [(finding.line, finding.col) for finding in findings]
    assert len(locations) == len(set(locations))
    assert all(finding.code == "SARJ510" for finding in findings)


@pytest.mark.parametrize("argument", ["'scope'", "discriminator='scope'"])
def test_field_name_discriminator_still_requires_literal_fields(argument: str) -> None:
    source = "from pydantic import Discriminator\n" + _RECORDS.replace(
        "Team | Global", f"Annotated[Team | Global, Discriminator({argument})]"
    )
    findings = PreferDiscriminatedModelUnion().check(Path("app/access.py"), source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ510"


@pytest.mark.parametrize(
    ("source", "expected_count"),
    [
        (_CALLABLE.rstrip() + " | None\n", 0),
        (
            "from typing import Optional\n"
            + _CALLABLE.replace("type Access = ", "type Access = Optional[").rstrip()
            + "]\n",
            0,
        ),
        (_CALLABLE + "type OptionalAccess = Access | None\n", 0),
        (
            _CALLABLE + "\ndef helper(Discriminator: object) -> object:\n    return Discriminator\n",
            0,
        ),
        (
            _CALLABLE.replace("type Access =", "@dataclass\nclass Third:\n    guest: str\ntype Access =").rstrip()
            + " | Third\n",
            1,
        ),
        (_QUALIFIED_CALLABLE + "p.Discriminator = object\n", 1),
        (_QUALIFIED_CALLABLE + "p = object\n", 1),
    ],
    ids=(
        "optional-pep604",
        "optional-wrapper",
        "optional-local-alias",
        "unrelated-helper-parameter",
        "uncovered-third-variant",
        "mutated-discriminator-module",
        "rebound-discriminator-module",
    ),
)
def test_callable_discriminator_coverage_and_scope(source: str, expected_count: int) -> None:
    findings = PreferDiscriminatedModelUnion().check(Path("app/access.py"), source)
    assert len(findings) == expected_count
    assert all(finding.code == "SARJ510" for finding in findings)


def test_boolean_and_integer_literal_tags_support_identity_narrowing(tmp_path: Path) -> None:
    target = tmp_path / "identity_tags.py"
    target.write_text(
        _BOOLEAN_INTEGER
        + "\nfrom typing import assert_type\n"
        + "def identify(value: Access) -> str:\n"
        + "    if value.scope is False:\n"
        + "        assert_type(value, Team)\n        return value.team_id\n"
        + "    assert_type(value, Global)\n    return value.group\n"
        + "assert identify(Team(False, 'team')) == 'team'\n"
        + "assert identify(Global(0, 'global')) == 'global'\n",
        encoding="utf-8",
    )
    runtime = subprocess.run([sys.executable, str(target)], capture_output=True, text=True, check=False)
    assert runtime.returncode == 0, runtime.stderr
    config = tmp_path / "pyrightconfig.json"
    config.write_text('{"typeCheckingMode": "basic", "pythonVersion": "3.14"}', encoding="utf-8")
    compiler = subprocess.run(
        [sys.executable, "-m", "basedpyright", "--project", str(config), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiler.returncode == 0, compiler.stdout + compiler.stderr
