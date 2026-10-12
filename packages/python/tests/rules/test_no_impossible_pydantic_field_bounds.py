from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rules.invalid_pydantic_field_default import InvalidPydanticFieldDefault
from sarj_python_lint.rules.no_impossible_pydantic_field_bounds import NoImpossiblePydanticFieldBounds


_PREFIX = "from pydantic import BaseModel, Field\nfrom typing import Annotated\n"
_CASES = (
    ("reverse-numeric", "value: float = Field(ge=5, le=4)", True),
    ("exclusive-equal", "value: float = Field(gt=1, le=1)", True),
    ("float-rounding", "value: float = Field(ge=9007199254740993, le=9007199254740992)", False),
    ("exact-large-float", "value: float = Field(ge=9007199254740994, le=9007199254740992)", True),
    ("large-int-stays-exact", "value: int = Field(ge=9007199254740993, le=9007199254740992)", True),
    ("float-overflow", "value: float = Field(ge=" + "1" + "0" * 400 + ", le=0)", False),
    ("integer-gap", "value: int = Field(gt=0, lt=1)", True),
    ("negative-gap", "value: int = Field(gt=-2, lt=-1)", True),
    ("length-gap", "value: str = Field(min_length=3, max_length=2)", True),
    ("array-gap", "value: list[str] = Field(min_length=3, max_length=2)", True),
    ("annotated", "value: Annotated[float, Field(ge=5, le=4)]", True),
    ("split-bounds", "value: Annotated[int, Field(gt=0)] = Field(lt=1)", True),
    ("equal-numeric", "value: float = Field(ge=1, le=1)", False),
    ("real-interval", "value: float = Field(gt=0, lt=1)", False),
    ("singleton", "value: int = Field(ge=0, lt=1)", False),
    ("negative-singleton", "value: int = Field(gt=-2, le=-1)", False),
    ("one-bound", "value: int = Field(gt=0)", False),
    ("dynamic", "value: int = Field(gt=limit, lt=0)", False),
    ("metadata-hook", "value: Annotated[int, hook, Field(gt=0, lt=1)]", False),
    ("custom-type", "value: Domain = Field(ge=5, le=4)", False),
    ("nullable", "value: int | None = Field(gt=0, lt=1)", False),
    ("unpacked", "value: int = Field(gt=0, lt=1, **options)", False),
    ("overridden-bound", "value: Annotated[int, Field(gt=10), Field(gt=0), Field(lt=5)]", False),
    ("assignment-override", "value: Annotated[int, Field(gt=0), Field(lt=5)] = Field(gt=10)", False),
    (
        "suppression",
        "value: int = Field(gt=0, lt=1)  # sarj-noqa: SARJ491 -- intentional invalid schema fixture",
        False,
    ),
)


@pytest.mark.parametrize(("label", "declaration", "matches"), _CASES, ids=[case[0] for case in _CASES])
def test_labeled_cases(label: str, declaration: str, *, matches: bool) -> None:
    case = EvaluationCase(
        case_id=label,
        language=Language.PYTHON,
        source=_PREFIX + f"class Model(BaseModel):\n    {declaration}\n",
        expected=ExpectedOutcome.MATCH if matches else ExpectedOutcome.NO_MATCH,
        path=PurePosixPath("app/models.py"),
    )
    findings = NoImpossiblePydanticFieldBounds().check(Path(case.path), case.source)
    assert len(findings) == int(case.expected is ExpectedOutcome.MATCH)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("class Model(Parent):\n    value: int = Field(gt=0, lt=1)", id="unknown-parent"),
        pytest.param("@adapt\nclass Model(BaseModel):\n    value: int = Field(gt=0, lt=1)", id="class-wrapper"),
        pytest.param("class Model(BaseModel, metaclass=Meta):\n    value: int = Field(gt=0, lt=1)", id="class-keyword"),
        pytest.param(
            "class Model(BaseModel):\n    value: int = Field(gt=0, lt=1)\n    def __get_pydantic_core_schema__(cls, *args): ...",
            id="schema-hook",
        ),
        pytest.param(
            "class Model(BaseModel):\n    value: int = Field(gt=0, lt=1)\n    value: int = Field(ge=0, le=1)",
            id="overwritten-field",
        ),
        pytest.param(
            "class Model(BaseModel):\n    value: int = Field(gt=0, lt=1)\n    exec(source)", id="dynamic-namespace"
        ),
        pytest.param(
            "def f(Field): ...\nclass Model(BaseModel):\n    value: int = Field(gt=0, lt=1)", id="shadowed-import"
        ),
        pytest.param("# @generated\nclass Model(BaseModel):\n    value: int = Field(gt=0, lt=1)", id="generated"),
        pytest.param("class Model(BaseModel):\n    value: [", id="malformed"),
        pytest.param(
            "class Model(BaseModel):\n    value: Annotated[int, Field(gt=0, lt=1)]\n    __annotations__ = {'value': int}",
            id="replaced-annotations",
        ),
    ],
)
def test_uncertain_contracts(body: str) -> None:
    assert not NoImpossiblePydanticFieldBounds().check(
        Path("app/models.py"),
        ("# @generated\n" + _PREFIX + body.removeprefix("# @generated\n"))
        if body.startswith("# @generated")
        else _PREFIX + body,
    )


def test_documented_examples() -> None:
    verify_native_rule(NoImpossiblePydanticFieldBounds, analyze)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(
            "class Model(BaseModel):\n    value: int = Field(default=0, gt=0, lt=1)\n",
            ["SARJ491"],
            id="primary-domain",
        ),
        pytest.param(
            "class Model(BaseModel):\n    x: int = Field(gt=0, lt=1); y: int = None\n",
            ["SARJ491", "SARJ400"],
            id="same-line-distinct-fields",
        ),
        pytest.param(
            "class Model(BaseModel):\n    value: int = Field(\n        default=0,\n        gt=0,\n        lt=1,\n    )\n",
            ["SARJ491"],
            id="multiline-field",
        ),
    ],
)
def test_default_diagnostic_precedence(body: str, expected: list[str]) -> None:
    findings = check_source(
        [NoImpossiblePydanticFieldBounds(), InvalidPydanticFieldDefault()], Path("app/models.py"), _PREFIX + body
    )
    assert [finding.code for finding in findings] == expected


def test_mutated_from_import_symbol() -> None:
    source = (
        _PREFIX
        + "from pydantic.fields import FieldInfo\ndef replacement(*args, **kwargs): return FieldInfo()\nField.__code__ = replacement.__code__\nclass Model(BaseModel):\n    value: int = Field(gt=0, lt=1)\n"
    )
    assert not NoImpossiblePydanticFieldBounds().check(Path("app/models.py"), source)


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param("from .helpers import Field", id="relative"),
        pytest.param("if flag:\n    from helpers import Field", id="conditional"),
        pytest.param("from .helpers import BaseModel", id="relative-base"),
        pytest.param("if flag:\n    from helpers import Annotated", id="conditional-annotation"),
        pytest.param("from .helpers import int", id="relative-builtin"),
        pytest.param("if flag:\n    from helpers import float as int", id="conditional-builtin"),
        pytest.param("globals()['int'] = float", id="global-type-replacement"),
        pytest.param("__builtins__.__dict__['int'] = float", id="implicit-builtin-module"),
        pytest.param("__builtins__['int'] = float", id="implicit-builtin-dictionary"),
        pytest.param("Field.__setattr__('__code__', replacement.__code__)", id="bound-field-setter"),
        pytest.param("alias = Field\nalias.__code__ = replacement.__code__", id="field-alias-mutation"),
        pytest.param("import pydantic as p\nnamespace = p\nnamespace.Field = replacement", id="module-alias-mutation"),
        pytest.param(
            "import pydantic as p\nalias = p.Field\nalias.__code__ = replacement.__code__", id="module-member-escape"
        ),
        pytest.param("import pydantic as p\np.__dict__.update({'Field': replacement})", id="namespace-update"),
        pytest.param("namespace = globals\nnamespace()['int'] = float", id="aliased-global-access"),
        pytest.param("import sys\nsys._getframe().f_globals['int'] = float", id="frame-global-write"),
        pytest.param(
            "class Identity:\n    def __getitem__(self, value): return value\nalias = Identity()[Field]\nalias.__code__ = replacement.__code__",
            id="runtime-indexing-escape",
        ),
        pytest.param("import sys\nsys.modules['pydantic'].Field = replacement", id="module-cache-write"),
        pytest.param("__import__('pydantic').Field = replacement", id="dynamic-import"),
        pytest.param(
            "from importlib import import_module as load\nload('pydantic').Field = replacement",
            id="import-loader-alias",
        ),
    ],
)
def test_uncertain_import_replacements(replacement: str) -> None:
    source = _PREFIX + replacement + "\nclass Model(BaseModel):\n    value: int = Field(gt=0, lt=1)\n"
    assert not NoImpossiblePydanticFieldBounds().check(Path("app/models.py"), source)


def test_nested_canonical_alias_can_replace_the_module_field() -> None:
    source = "import pydantic as p\nclass Holder:\n    import pydantic as local_p\n    local_p.Field = lambda **kwargs: None\nclass Model(p.BaseModel):\n    value: int = p.Field(gt=0, lt=1)\n"
    assert not NoImpossiblePydanticFieldBounds().check(Path("app/models.py"), source)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "from pydantic import BaseModel as Model, Field as F\nclass Example(Model):\n    value: int = F(gt=0, lt=1)\n",
            id="named-alias",
        ),
        pytest.param(
            "import pydantic as p\nclass Example(p.BaseModel):\n    value: int = p.Field(gt=0, lt=1)\n",
            id="namespace-alias",
        ),
        pytest.param(
            "from pydantic import BaseModel, Field\nfrom pydantic import Field\nclass Example(BaseModel):\n    value: int = Field(gt=0, lt=1)\n",
            id="same-origin-repeat",
        ),
    ],
)
def test_proven_import_aliases(source: str) -> None:
    assert len(NoImpossiblePydanticFieldBounds().check(Path("app/models.py"), source)) == 1
