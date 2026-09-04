from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.require_pydantic_ordinal_lower_bound import (
    RequirePydanticOrdinalLowerBound,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "app/api.py"):
    return RequirePydanticOrdinalLowerBound().check(Path(path), source)


@pytest.mark.parametrize(
    "source",
    [
        "from pydantic import BaseModel, Field\nclass Detail(BaseModel):\n attempt: int=Field(default=1,description='1 for the first attempt')",
        "import pydantic\nclass Detail(pydantic.BaseModel):\n index: int=pydantic.Field(default=0,description='0 for first item')",
        "from pydantic import BaseModel as BM, Field as F\nclass Detail(BM):\n attempt: int=F(1,description='1 for first attempt')",
        "from typing import Annotated\nfrom pydantic import BaseModel, Field\nclass Detail(BaseModel):\n attempt: Annotated[int,Field(description='1 for first attempt')]=1",
    ],
)
def test_flags_literal_ordinal_contract_without_bound(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ418"


@pytest.mark.parametrize(
    "source",
    [
        "from pydantic import BaseModel,Field\nclass Detail(BaseModel):\n attempt:int=Field(default=1,ge=1,description='1 for first attempt')",
        "from pydantic import BaseModel,Field,PositiveInt\nclass Detail(BaseModel):\n attempt:PositiveInt=Field(default=1,description='1 for first attempt')",
        "from pydantic import BaseModel,Field\nclass Detail(BaseModel):\n attempt:int=Field(default=1,description='Attempt number')",
        "from pydantic import BaseModel,Field\nclass Detail(BaseModel):\n attempt:int=Field(default=2,description='1 for first attempt')",
        "from pydantic import Field\nclass Plain:\n attempt:int=Field(default=1,description='1 for first attempt')",
        "class BaseModel: ...\ndef Field(**kwargs): ...\nclass Detail(BaseModel):\n attempt:int=Field(default=1,description='1 for first attempt')",
        "from pydantic import BaseModel,Field\nclass Detail(BaseModel):\n _attempt:int=Field(default=1,description='1 for first attempt')",
        "from typing import ClassVar\nfrom pydantic import BaseModel,Field\nclass Detail(BaseModel):\n attempt:ClassVar[int]=Field(default=1,description='1 for first attempt')",
        "from pydantic import BaseModel,Field\nclass Detail(BaseModel):\n delay:int=Field(default=1,description='Wait 1 for the first request')",
        "from pydantic import BaseModel,Field\nclass Detail(BaseModel):\n delay_seconds:int=Field(default=1,description='Backoff delay (1 for the first request; 5 thereafter)')",
        "from pydantic import BaseModel,Field\nclass Detail(BaseModel):\n attempt:int=Field(default=1,description='Offset (1 for the first-aid response)')",
        "from pydantic import BaseModel,Field\nclass Detail(BaseModel):\n attempt:int=Field(default=1,description='0 means unknown; 1 for first attempt')",
        "from pydantic import BaseModel,Field\nclass Detail(BaseModel):\n rank:int=Field(default=1,description='1 for first rank; zero means unranked')",
        "from pydantic import BaseModel,Field\nclass Detail(BaseModel):\n rank:int=Field(default=1,description='Negative values are unranked; 1 for first rank')",
    ],
)
def test_ignores_enforced_or_ambiguous_contracts(source: str) -> None:
    assert _check(source) == []


def test_field_validator_is_an_explicit_escape() -> None:
    source = """
from pydantic import BaseModel, Field, field_validator
class Detail(BaseModel):
    attempt: int = Field(default=1, description="1 for the first attempt")

    @field_validator("attempt")
    def validate_attempt(cls, value):
        return value
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    ("annotation", "imports"),
    [
        ("Annotated[int, Ge(1)]", "from typing import Annotated\nfrom annotated_types import Ge"),
        ("Annotated[int, Gt(0)]", "from typing import Annotated\nfrom annotated_types import Gt"),
        ("Ordinal", "from typing import Annotated\nfrom annotated_types import Ge\nOrdinal=Annotated[int,Ge(1)]"),
        ("Annotated[int, Field(ge=1)]", "from typing import Annotated"),
        ("int | PositiveInt", "from pydantic import PositiveInt"),
        ("Literal[1, 2]", "from typing import Literal"),
    ],
)
def test_top_level_annotation_constraint_handling(annotation: str, imports: str) -> None:
    diagnostics = _check(f"""
from pydantic import BaseModel, Field
{imports}
class Detail(BaseModel):
    attempt: {annotation} = Field(default=1, description="1 for first attempt")
""")
    if annotation == "int | PositiveInt":
        assert len(diagnostics) == 1
    else:
        assert diagnostics == []


def test_nested_element_bound_does_not_hide_unbounded_field() -> None:
    diagnostics = _check("""
from typing import Annotated
from annotated_types import Ge
from pydantic import BaseModel, Field
class Detail(BaseModel):
    attempt: list[Annotated[int, Ge(1)]] = Field(default=1, description="1 for first attempt")
""")
    assert diagnostics == []  # Unknown non-integer field contracts are outside the rule boundary.


@pytest.mark.parametrize("metadata", ["Gt(-1)", "Ge(0)", "Interval(ge=0)"])
def test_insufficient_known_annotated_bound_is_reported(metadata: str) -> None:
    diagnostics = _check(f"""
from typing import Annotated
from annotated_types import Ge, Gt, Interval
from pydantic import BaseModel, Field
class Detail(BaseModel):
    attempt: Annotated[int, {metadata}] = Field(default=1, description="1 for first attempt")
""")
    assert len(diagnostics) == 1


def test_exact_suppression() -> None:
    assert (
        _check("""
from pydantic import BaseModel, Field
class Detail(BaseModel):
    attempt: int = Field(default=1, description="1 for first attempt")  # sarj-noqa: SARJ418
""")
        == []
    )


@pytest.mark.parametrize(
    "field",
    [
        "attempt:int=Field(default=1,ge=LOWER,description='1 for first attempt')",
        "attempt:Annotated[int,Field(ge=LOWER)]=Field(default=1,description='1 for first attempt')",
        "attempt:conint(ge=LOWER)=Field(default=1,description='1 for first attempt')",
        "attempt:int=Field(default=1,description='1 for first attempt',**BOUNDS)",
    ],
)
def test_dynamic_constraint_abstains(field: str) -> None:
    assert (
        _check(f"""
from typing import Annotated
from pydantic import BaseModel, Field, conint
class Detail(BaseModel):
    {field}
""")
        == []
    )


@pytest.mark.parametrize("target", ['"*"', "*FIELDS"])
def test_wildcard_or_dynamic_validator_abstains(target: str) -> None:
    assert (
        _check(f"""
from pydantic import BaseModel, Field, field_validator
class Detail(BaseModel):
    attempt: int = Field(default=1, description="1 for first attempt")
    @field_validator({target})
    def validate_fields(cls, value): return value
""")
        == []
    )


@pytest.mark.parametrize("module", ["pydantic.class_validators", "pydantic.v1.class_validators"])
def test_legacy_validator_abstains(module: str) -> None:
    assert (
        _check(f"""
from pydantic import BaseModel, Field
from {module} import validator
class Detail(BaseModel):
    attempt: int = Field(default=1, description="1 for first attempt")
    @validator("attempt")
    def validate_attempt(cls, value): return value
""")
        == []
    )


def test_class_local_module_shadow_abstains() -> None:
    assert (
        _check("""
import pydantic
class Detail(pydantic.BaseModel):
    pydantic = Fake
    attempt: int = pydantic.Field(default=1, description="1 for first attempt")
""")
        == []
    )


def test_annotated_field_can_supply_default_and_description() -> None:
    diagnostics = _check("""
from typing import Annotated
from pydantic import BaseModel, Field
class Detail(BaseModel):
    attempt: Annotated[int, Field(default=1, description="1 for first attempt")]
""")
    assert len(diagnostics) == 1


def test_huge_ordinal_literal_does_not_crash() -> None:
    huge = "1" * 5_000
    assert (
        _check(f"""
from pydantic import BaseModel, Field
class Detail(BaseModel):
    attempt: int = Field(default=1, description="{huge} for first attempt")
""")
        == []
    )


def test_rebound_annotation_alias_is_not_trusted() -> None:
    diagnostics = _check("""
from typing import Annotated
from pydantic import BaseModel, Field
Ordinal = Annotated[int, Field(ge=1)]
Ordinal: type = int
class Detail(BaseModel):
    attempt: Ordinal = Field(default=1, description="1 for first attempt")
""")
    assert diagnostics == []  # Unknown rebound aliases are outside the proven boundary.


@pytest.mark.parametrize(
    "description",
    [
        "Values below 1 are rejected; 1 for first attempt",
        "Negative ranks are invalid; 1 for first rank",
        "Zero is not allowed (1 for first position)",
        "0 is invalid; 1 for first attempt",
    ],
)
def test_rejected_smaller_values_do_not_look_like_sentinels(description: str) -> None:
    diagnostics = _check(f"""
from pydantic import BaseModel, Field
class Detail(BaseModel):
    attempt_number: int = Field(default=1, description={description!r})
""")
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ("Annotated[int, Field(ge=1), Field(ge=0)]", 1),
        ("Annotated[int, Field(ge=0), Field(ge=1)]", 0),
        ("Annotated[conint(ge=1), Field(ge=0)]", 1),
        ("Annotated[int, Field(ge=0)]", 1),
        ("Annotated[Literal[1, 2], Field(ge=0)]", 0),
    ],
)
def test_last_constraint_of_each_kind_controls_effective_bound(annotation: str, expected: int) -> None:
    diagnostics = _check(f"""
from typing import Annotated, Literal
from pydantic import BaseModel, Field, conint
class Detail(BaseModel):
    attempt: {annotation} = Field(default=1, description="1 for first attempt")
""")
    assert len(diagnostics) == expected


@pytest.mark.parametrize(
    "description",
    [
        "0 means no attempt has occurred; 1 for first attempt",
        "0 represents an absent position; 1 for first position",
        "0 indicates disabled; 1 for first attempt",
        "0 is allowed as a sentinel; 1 for first attempt",
        "-1 means unknown; 1 for first attempt",
        "(-1 is reserved); 1 for first attempt",
    ],
)
def test_general_accepted_sentinel_semantics_abstain(description: str) -> None:
    assert (
        _check(f"""
from pydantic import BaseModel, Field
class Detail(BaseModel):
    attempt_number: int = Field(default=1, description={description!r})
""")
        == []
    )


def test_invalid_sentinel_wording_still_reports() -> None:
    diagnostics = _check("""
from pydantic import BaseModel, Field
class Detail(BaseModel):
    attempt_number: int = Field(default=1, description="0 means invalid; 1 for first attempt")
""")
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "annotation",
    [
        "Annotated[int, Field(ge=1), Field(ge=0)] | Literal[1]",
        "Union[Annotated[int, Field(ge=1), Field(ge=0)], Literal[1]]",
        "Optional[Annotated[int, Field(ge=1), Field(ge=0)]]",
    ],
)
def test_ordered_weakening_is_respected_inside_union_branches(annotation: str) -> None:
    diagnostics = _check(f"""
from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, Field
class Detail(BaseModel):
    attempt: {annotation} = Field(default=1, description="1 for first attempt")
""")
    assert len(diagnostics) == 1


@pytest.mark.parametrize("validator", ["AfterValidator", "PlainValidator"])
def test_unknown_annotated_validator_abstains(validator: str) -> None:
    assert (
        _check(f"""
from typing import Annotated
from pydantic import BaseModel, Field, {validator}
class Detail(BaseModel):
    attempt: Annotated[int, Field(ge=0), {validator}(enforce)] = Field(default=1, description="1 for first attempt")
""")
        == []
    )


@pytest.mark.parametrize("example", RequirePydanticOrdinalLowerBound.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count
