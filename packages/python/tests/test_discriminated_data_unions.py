from __future__ import annotations

from pathlib import Path, PurePosixPath
import subprocess
import sys

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem

from sarj_python_lint.rules.prefer_discriminated_model_union import PreferDiscriminatedModelUnion


_PLAIN = (
    "from dataclasses import dataclass\n"
    "from typing import Annotated, ClassVar, Literal, Optional, TypeAlias, Union\n"
    "@dataclass(frozen=True, slots=True)\n"
    "class OrganizationMembership:\n"
    "    group: str\n"
    "    organization_id: str\n"
    "@dataclass(frozen=True, slots=True)\n"
    "class PlatformMembership:\n"
    "    group: str\n"
    "type Membership = OrganizationMembership | PlatformMembership\n"
)
_TAGGED = _PLAIN.replace(
    "    group: str\n    organization_id", "    scope: Literal['organization']\n    group: str\n    organization_id"
).replace("class PlatformMembership:\n", "class PlatformMembership:\n    scope: Literal['platform']\n")

_PROBLEM = RuleProblem(
    key="explicit-data-union-discriminator",
    summary="A declared union of local data variants has no shared disjoint Literal field.",
    harm="Consumers cannot narrow by a stable common tag and serialized variants have no explicit identity.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=(_PLAIN,),
    good_examples=(_TAGGED,),
    exclusions=(
        "Scalar unions, protocols, behavior classes, unresolved imported variants and inherited variants are excluded.",
        "This is an explicit modeling policy; nominal classes already support isinstance narrowing.",
    ),
)


def _model_source(*, tagged: bool, kind: str) -> str:
    source = _TAGGED if tagged else _PLAIN
    if kind == "pydantic":
        return (
            source.replace("from dataclasses import dataclass", "from pydantic import BaseModel")
            .replace("@dataclass(frozen=True, slots=True)\n", "")
            .replace("Membership:\n", "Membership(BaseModel):\n")
        )
    return (
        source.replace("from dataclasses import dataclass", "from typing import TypedDict")
        .replace("@dataclass(frozen=True, slots=True)\n", "")
        .replace("Membership:\n", "Membership(TypedDict):\n")
    )


def _case(case_id: str, source: str, *, match: bool = False, path: str = "app/membership.py") -> EvaluationCase:
    return EvaluationCase(
        case_id,
        Language.PYTHON,
        source,
        ExpectedOutcome.MATCH if match else ExpectedOutcome.NO_MATCH,
        path=PurePosixPath(path),
    )


_CASES = (
    _case("01-untagged-dataclass", _PLAIN, match=True),
    _case("02-tagged-dataclass", _TAGGED),
    _case("03-untagged-pydantic", _model_source(tagged=False, kind="pydantic"), match=True),
    _case("04-tagged-pydantic", _model_source(tagged=True, kind="pydantic")),
    _case("05-untagged-typed-dict", _model_source(tagged=False, kind="typed-dict"), match=True),
    _case("06-tagged-typed-dict", _model_source(tagged=True, kind="typed-dict")),
    _case("07-legacy-alias", _PLAIN.replace("type Membership =", "Membership: TypeAlias ="), match=True),
    _case("08-implicit-alias", _PLAIN.replace("type Membership =", "Membership ="), match=True),
    _case(
        "09-typing-union",
        _PLAIN.replace(
            "OrganizationMembership | PlatformMembership", "Union[OrganizationMembership, PlatformMembership]"
        ),
        match=True,
    ),
    _case(
        "10-optional-union",
        _PLAIN.replace(
            "OrganizationMembership | PlatformMembership", "Optional[OrganizationMembership | PlatformMembership]"
        ),
        match=True,
    ),
    _case("11-none-branch", _PLAIN.rstrip() + " | None\n", match=True),
    _case("12-tagged-none-branch", _TAGGED.rstrip() + " | None\n"),
    _case(
        "13-annotated-untagged",
        _PLAIN.replace(
            "OrganizationMembership | PlatformMembership",
            "Annotated[OrganizationMembership | PlatformMembership, 'wire']",
        ),
        match=True,
    ),
    _case(
        "14-annotated-tagged",
        _TAGGED.replace(
            "OrganizationMembership | PlatformMembership",
            "Annotated[OrganizationMembership | PlatformMembership, 'wire']",
        ),
    ),
    _case(
        "15-whole-string-union",
        _PLAIN.replace("OrganizationMembership | PlatformMembership", "'OrganizationMembership | PlatformMembership'"),
        match=True,
    ),
    _case(
        "16-forward-members",
        _PLAIN.replace(
            "OrganizationMembership | PlatformMembership", "Union['OrganizationMembership', 'PlatformMembership']"
        ),
        match=True,
    ),
    _case(
        "17-nested-union",
        _PLAIN.replace(
            "OrganizationMembership | PlatformMembership",
            "Union[OrganizationMembership, Union[PlatformMembership, None]]",
        ),
        match=True,
    ),
    _case("18-repeated-member", _PLAIN.rstrip() + " | OrganizationMembership\n", match=True),
    _case(
        "19-single-distinct-member",
        _PLAIN.replace(
            "OrganizationMembership | PlatformMembership", "OrganizationMembership | OrganizationMembership"
        ),
    ),
    _case("20-scalar-union", "type Data = str | bytes\n"),
    _case("21-model-with-scalar", _PLAIN.rstrip() + " | str\n"),
    _case(
        "22-one-record-optional",
        _PLAIN.replace("OrganizationMembership | PlatformMembership", "OrganizationMembership | None"),
    ),
    _case(
        "23-container-of-union",
        _PLAIN.replace(
            "OrganizationMembership | PlatformMembership", "list[OrganizationMembership | PlatformMembership]"
        ),
    ),
    _case("24-generic-alias", _PLAIN.replace("type Membership =", "type Membership[T] =")),
    _case("25-ordinary-classes", _PLAIN.replace("@dataclass(frozen=True, slots=True)\n", "")),
    _case(
        "26-inherited-record",
        _PLAIN.replace("class PlatformMembership:", "class PlatformMembership(OrganizationMembership):"),
    ),
    _case("27-unresolved-variant", _PLAIN.rstrip() + " | ExternalMembership\n"),
    _case(
        "28-imported-variant", "from external import ExternalMembership\n" + _PLAIN.rstrip() + " | ExternalMembership\n"
    ),
    _case("29-nested-definitions", "def build():\n" + "".join("    " + line + "\n" for line in _PLAIN.splitlines())),
    _case(
        "30-inline-return-annotation",
        _PLAIN.replace(
            "type Membership = OrganizationMembership | PlatformMembership",
            "def get() -> OrganizationMembership | PlatformMembership: ...",
        ),
    ),
    _case("31-missing-one-tag", _TAGGED.replace("    scope: Literal['platform']\n", ""), match=True),
    _case(
        "32-different-tag-field", _TAGGED.replace("scope: Literal['platform']", "kind: Literal['platform']"), match=True
    ),
    _case("33-overlapping-tags", _TAGGED.replace("Literal['platform']", "Literal['organization']"), match=True),
    _case("34-broad-tag", _TAGGED.replace("Literal['platform']", "str"), match=True),
    _case(
        "35-same-default-different-types",
        _PLAIN.replace("    group: str", "    scope: str = 'organization'\n    group: str"),
        match=True,
    ),
    _case("36-multivalue-tag", _TAGGED.replace("Literal['organization']", "Literal['organization', 'team']")),
    _case(
        "37-multivalue-overlap",
        _TAGGED.replace("Literal['organization']", "Literal['organization', 'platform']"),
        match=True,
    ),
    _case(
        "38-integer-tags",
        _TAGGED.replace("Literal['organization']", "Literal[1]").replace("Literal['platform']", "Literal[2]"),
    ),
    _case(
        "39-negative-integer-tags",
        _TAGGED.replace("Literal['organization']", "Literal[-1]").replace("Literal['platform']", "Literal[+1]"),
    ),
    _case(
        "40-boolean-tags",
        _TAGGED.replace("Literal['organization']", "Literal[True]").replace("Literal['platform']", "Literal[False]"),
    ),
    _case("41-none-tag", _TAGGED.replace("Literal['organization']", "Literal[None]")),
    _case(
        "42-boolean-integer-collision",
        _TAGGED.replace("Literal['organization']", "Literal[True]").replace("Literal['platform']", "Literal[1]"),
        match=True,
    ),
    _case(
        "43-bytes-tags",
        _TAGGED.replace("Literal['organization']", "Literal[b'organization']").replace(
            "Literal['platform']", "Literal[b'platform']"
        ),
    ),
    _case("44-unsupported-float-literal", _TAGGED.replace("Literal['organization']", "Literal[1.5]")),
    _case("45-unknown-enum-literal", _TAGGED.replace("Literal['organization']", "Literal[Scope.ORGANIZATION]")),
    _case("46-one-valid-shared-axis", _TAGGED.replace("    group: str", "    kind: Literal['same']\n    group: str")),
    _case(
        "47-class-var-tags",
        _TAGGED.replace("Literal['organization']", "ClassVar[Literal['organization']] = 'organization'").replace(
            "Literal['platform']", "ClassVar[Literal['platform']] = 'platform'"
        ),
    ),
    _case(
        "48-class-var-without-value",
        _TAGGED.replace("Literal['organization']", "ClassVar[Literal['organization']]").replace(
            "Literal['platform']", "ClassVar[Literal['platform']]"
        ),
        match=True,
    ),
    _case("49-forward-tag-annotation", _TAGGED.replace("Literal['organization']", "\"Literal['organization']\"")),
    _case(
        "50-annotated-tag-field",
        _TAGGED.replace("Literal['organization']", "Annotated[Literal['organization'], 'scope']"),
    ),
    _case(
        "51-literal-union-tag", _TAGGED.replace("Literal['organization']", "Literal['organization'] | Literal['team']")
    ),
    _case(
        "52-optional-tag-overlap",
        _TAGGED.replace("Literal['organization']", "Literal['organization'] | None").replace(
            "Literal['platform']", "Literal['platform'] | None"
        ),
        match=True,
    ),
    _case(
        "53-local-tag-alias",
        "type OrgScope = Literal['organization']\n" + _TAGGED.replace("Literal['organization']", "OrgScope"),
    ),
    _case(
        "54-local-record-alias",
        _PLAIN.replace("type Membership =", "type Org = OrganizationMembership\ntype Membership =").replace(
            "Membership = OrganizationMembership |", "Membership = Org |"
        ),
        match=True,
    ),
    _case(
        "55-alias-chain",
        _PLAIN.replace(
            "type Membership =", "type Org = OrganizationMembership\ntype Alias = Org\ntype Membership ="
        ).replace("Membership = OrganizationMembership |", "Membership = Alias |"),
        match=True,
    ),
    _case(
        "56-recursive-alias",
        _PLAIN.replace("type Membership =", "type Org = Org\ntype Membership =").replace(
            "Membership = OrganizationMembership |", "Membership = Org |"
        ),
    ),
    _case(
        "57-qualified-dataclass",
        _PLAIN.replace("from dataclasses import dataclass", "import dataclasses as dc").replace(
            "@dataclass(", "@dc.dataclass("
        ),
        match=True,
    ),
    _case(
        "58-aliased-dataclass",
        _PLAIN.replace("import dataclass", "import dataclass as record").replace("@dataclass(", "@record("),
        match=True,
    ),
    _case("59-bare-dataclass", _PLAIN.replace("@dataclass(frozen=True, slots=True)", "@dataclass"), match=True),
    _case(
        "60-qualified-literal",
        _TAGGED.replace("from typing import", "import typing as t\nfrom typing import").replace(
            "scope: Literal[", "scope: t.Literal["
        ),
    ),
    _case("61-typing-extensions", _TAGGED.replace("from typing import", "from typing_extensions import")),
    _case(
        "62-aliased-literal",
        _TAGGED.replace("ClassVar, Literal,", "ClassVar, Literal as L,").replace("scope: Literal[", "scope: L["),
    ),
    _case("63-custom-dataclass", _PLAIN.replace("from dataclasses import", "from custom import")),
    _case("64-shadowed-decorator", _PLAIN + "dataclass = adapt\n"),
    _case("65-shadowed-literal", _TAGGED + "Literal = CustomLiteral\n"),
    _case("66-wildcard-namespace", "from external import *\n" + _PLAIN),
    _case("67-rebound-variant", _PLAIN + "PlatformMembership = Other\n"),
    _case("68-deleted-variant", _PLAIN + "del PlatformMembership\n"),
    _case("69-duplicate-class", _PLAIN + "class PlatformMembership: pass\n"),
    _case("70-conditional-rebind", _PLAIN + "if enabled:\n    PlatformMembership = Other\n"),
    _case("71-mutated-variant", _PLAIN + "PlatformMembership.scope = 'platform'\n"),
    _case("72-dynamic-namespace", _PLAIN + "globals()[name] = value\n"),
    _case(
        "73-unknown-class-decorator", _PLAIN.replace("class PlatformMembership:", "@adapt\nclass PlatformMembership:")
    ),
    _case(
        "74-class-with-property",
        _TAGGED.replace(
            "    scope: Literal['platform']", "    @property\n    def scope(self) -> Literal['platform']: ..."
        ),
    ),
    _case(
        "75-custom-metaclass", _PLAIN.replace("class PlatformMembership:", "class PlatformMembership(metaclass=Meta):")
    ),
    _case("76-generic-record", _PLAIN.replace("class PlatformMembership:", "class PlatformMembership[T]:")),
    _case(
        "77-duplicate-field",
        _TAGGED.replace("    scope: Literal['platform']", "    scope: Literal['platform']\n    scope: str"),
    ),
    _case(
        "78-typed-dict-optional-tag",
        _model_source(tagged=True, kind="typed-dict").replace("TypedDict):", "TypedDict, total=False):"),
        match=True,
    ),
    _case(
        "79-typed-dict-required-tag",
        _model_source(tagged=True, kind="typed-dict")
        .replace("import TypedDict", "import Required, TypedDict")
        .replace("TypedDict):", "TypedDict, total=False):")
        .replace("Literal['organization']", "Required[Literal['organization']]")
        .replace("Literal['platform']", "Required[Literal['platform']]"),
    ),
    _case(
        "80-typed-dict-not-required",
        _model_source(tagged=True, kind="typed-dict")
        .replace("import TypedDict", "import NotRequired, TypedDict")
        .replace("Literal['platform']", "NotRequired[Literal['platform']]"),
        match=True,
    ),
    _case(
        "81-typed-dict-readonly-tag",
        _model_source(tagged=True, kind="typed-dict")
        .replace("import TypedDict", "import ReadOnly, TypedDict")
        .replace("Literal['platform']", "ReadOnly[Literal['platform']]"),
    ),
    _case(
        "82-union-of-three",
        _PLAIN.replace(
            "type Membership =", "@dataclass\nclass GuestMembership:\n    guest: str\ntype Membership ="
        ).rstrip()
        + " | GuestMembership\n",
        match=True,
    ),
    _case(
        "83-third-tag-overlap",
        _TAGGED.replace(
            "type Membership =", "@dataclass\nclass GuestMembership:\n    scope: Literal['platform']\ntype Membership ="
        ).rstrip()
        + " | GuestMembership\n",
        match=True,
    ),
    _case(
        "84-third-tag-distinct",
        _TAGGED.replace(
            "type Membership =", "@dataclass\nclass GuestMembership:\n    scope: Literal['guest']\ntype Membership ="
        ).rstrip()
        + " | GuestMembership\n",
    ),
    _case(
        "85-annotated-field-is-not-tag",
        _PLAIN.replace("    group: str", "    group: Annotated[str, 'discriminator']"),
        match=True,
    ),
    _case(
        "86-field-metadata-without-tags",
        _PLAIN.replace(
            "from dataclasses import dataclass", "from dataclasses import dataclass\nfrom pydantic import Field"
        ).replace(
            "OrganizationMembership | PlatformMembership",
            "Annotated[OrganizationMembership | PlatformMembership, Field(discriminator='scope')]",
        ),
        match=True,
    ),
    _case("87-exact-suppression", _PLAIN.rstrip() + "  # sarj-noqa: SARJ510 -- persisted legacy union\n"),
    _case(
        "88-different-code-suppression",
        _PLAIN.rstrip() + "  # sarj-noqa: SARJ511 -- different concern\n",
        match=True,
    ),
    _case("89-generated-source", "# @generated\n" + _PLAIN),
    _case("90-generated-path", _PLAIN, path="generated/membership.py"),
    _case("91-test-path", _PLAIN, path="tests/test_membership.py"),
    _case("92-malformed-source", _PLAIN + "def broken(\n"),
    _case("93-comment-only", "# " + _PLAIN.replace("\n", "\n# ")),
    _case("94-string-only", "example = " + repr(_PLAIN) + "\n"),
    _case(
        "95-deferred-alias-reference",
        "type Membership = OrganizationMembership | PlatformMembership\n" + _PLAIN[: _PLAIN.index("type Membership")],
        match=True,
    ),
    _case(
        "96-qualified-union",
        _PLAIN.replace("from typing import", "import typing as t\nfrom typing import").replace(
            "OrganizationMembership | PlatformMembership", "t.Union[OrganizationMembership, PlatformMembership]"
        ),
        match=True,
    ),
    _case(
        "97-shadowed-union",
        _PLAIN.replace(
            "OrganizationMembership | PlatformMembership", "Union[OrganizationMembership, PlatformMembership]"
        )
        + "Union = custom\n",
    ),
    _case("98-annotated-runtime-variable", _PLAIN.replace("type Membership =", "Membership: object =")),
    _case(
        "99-mixed-record-families",
        _PLAIN.replace(
            "from dataclasses import dataclass", "from dataclasses import dataclass\nfrom pydantic import BaseModel"
        ).replace(
            "@dataclass(frozen=True, slots=True)\nclass PlatformMembership:", "class PlatformMembership(BaseModel):"
        ),
        match=True,
    ),
    _case(
        "100-dataclass-field-default-tag",
        _TAGGED.replace("import dataclass", "import dataclass, field")
        .replace("Literal['organization']", "Literal['organization'] = field(default='organization', init=False)")
        .replace("Literal['platform']", "Literal['platform'] = field(default='platform', init=False)"),
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_data_union_discriminator(case: EvaluationCase) -> None:
    findings = PreferDiscriminatedModelUnion().check(Path(case.path), case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    for finding in findings:
        assert finding.code == "SARJ510"
        assert "discriminator" in finding.message


@pytest.mark.parametrize(
    "case",
    [
        _case(
            "repeated-local-alias-is-not-a-cycle",
            _PLAIN.replace("type Membership =", "type Org = OrganizationMembership\ntype Membership =")
            .replace("Membership = OrganizationMembership |", "Membership = Org |")
            .rstrip()
            + " | Org\n",
            match=True,
        ),
        _case(
            "ordinary-container-is-not-an-opaque-tag",
            _PLAIN.replace("    group: str", "    group: list[str]"),
            match=True,
        ),
        _case(
            "mutated-dataclasses-module",
            _PLAIN.replace("from dataclasses import dataclass", "import dataclasses as dc").replace(
                "@dataclass(", "@dc.dataclass("
            )
            + "dc.dataclass = adapt\n",
        ),
        _case(
            "mutated-pydantic-module",
            _model_source(tagged=False, kind="pydantic")
            .replace("from pydantic import BaseModel", "import pydantic as p")
            .replace("(BaseModel)", "(p.BaseModel)")
            + "p.BaseModel = Other\n",
        ),
        _case(
            "tag-alias-shared-on-distinct-paths",
            "type OrgScope = Literal['organization']\n"
            + _TAGGED.replace("Literal['organization']", "OrgScope | OrgScope"),
        ),
        _case(
            "partially-unresolved-tag-domain",
            "from external import OrganizationScope\n"
            + _TAGGED.replace("Literal['organization']", "OrganizationScope"),
        ),
        _case(
            "runtime-string-is-not-a-type-alias",
            _PLAIN.replace(
                "type Membership = OrganizationMembership | PlatformMembership",
                "expression = 'OrganizationMembership | PlatformMembership'",
            ),
        ),
        _case("mangled-tags-have-no-common-public-field", _TAGGED.replace("    scope:", "    __scope:"), match=True),
    ],
    ids=(
        "repeated-record-alias",
        "container-field",
        "mutated-dataclasses",
        "mutated-pydantic",
        "repeated-tag-alias",
        "unresolved-tag-domain",
        "runtime-string",
        "mangled-tags",
    ),
)
def test_audit_followups(case: EvaluationCase) -> None:
    findings = PreferDiscriminatedModelUnion().check(Path(case.path), case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)


_HIERARCHY = (
    "from dataclasses import dataclass\nfrom typing import Literal\n"
    "@dataclass\nclass First:\n    kind: Literal['family']\n    provider: Literal['first']\n"
    "@dataclass\nclass Second:\n    kind: Literal['family']\n    provider: Literal['second']\n"
    "@dataclass\nclass Other:\n    kind: Literal['other']\n"
    "type Result = First | Second | Other\n"
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (_HIERARCHY, 0),
        (_HIERARCHY.replace("Literal['second']", "Literal['first']"), 1),
        (_HIERARCHY.replace("    provider: Literal['second']\n", ""), 1),
        (
            _HIERARCHY.replace("type Result =", "type Family = First | Second\ntype Result =").replace(
                "Result = First | Second | Other", "Result = Family | Other"
            ),
            0,
        ),
    ],
    ids=("hierarchical-tags", "secondary-overlap", "missing-secondary-tag", "nested-union-alias"),
)
def test_literal_discriminator_hierarchy(source: str, expected: int) -> None:
    findings = PreferDiscriminatedModelUnion().check(Path("app/results.py"), source)
    assert len(findings) == expected


def test_tags_preserve_constructor_calls_and_support_static_narrowing(tmp_path: Path) -> None:
    example = PreferDiscriminatedModelUnion.public_examples()[3].focus_file.source
    target = tmp_path / "access.py"
    target.write_text(
        example
        + "\nfrom dataclasses import asdict\nfrom typing import assert_type\n"
        + "def identify(access: Access) -> str:\n"
        + "    if access.scope == 'team':\n"
        + "        assert_type(access, TeamAccess)\n        return access.team_id\n"
        + "    assert_type(access, GlobalAccess)\n    return access.group\n"
        + "assert identify(TeamAccess('team-1')) == 'team-1'\n"
        + "assert identify(GlobalAccess('operator')) == 'operator'\n"
        + "assert asdict(TeamAccess('team-1')) == {'scope': 'team', 'team_id': 'team-1'}\n",
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


def test_original_nominal_union_remains_valid_python_typing(tmp_path: Path) -> None:
    target = tmp_path / "nominal.py"
    target.write_text(
        _PROBLEM.bad_examples[0]
        + "\nfrom typing import assert_type\n"
        + "def identify(value: Membership) -> str:\n"
        + "    if isinstance(value, OrganizationMembership):\n"
        + "        assert_type(value, OrganizationMembership)\n        return value.organization_id\n"
        + "    assert_type(value, PlatformMembership)\n    return value.group\n",
        encoding="utf-8",
    )
    config = tmp_path / "pyrightconfig.json"
    config.write_text('{"typeCheckingMode": "basic", "pythonVersion": "3.14"}', encoding="utf-8")
    compiler = subprocess.run(
        [sys.executable, "-m", "basedpyright", "--project", str(config), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiler.returncode == 0, compiler.stdout + compiler.stderr
