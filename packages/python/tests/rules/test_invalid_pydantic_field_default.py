from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.invalid_pydantic_field_default import InvalidPydanticFieldDefault


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "models.py"):
    return InvalidPydanticFieldDefault().check(Path(path), dedent(source))


_PUBLIC_EXAMPLES = InvalidPydanticFieldDefault.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(InvalidPydanticFieldDefault().check(Path(focus.path), focus.source)) == example.expected_count


def test_ignores_float_default_coercible_to_integer_literal() -> None:
    source = "from typing import Literal\nfrom pydantic import BaseModel, Field\nclass Model(BaseModel):\n    value: Literal[1] = Field(default=1.0)\n"

    assert _check(source) == []


def test_checks_bytes_length_bounds() -> None:
    source = "from pydantic import BaseModel, Field\nclass Model(BaseModel):\n    token: bytes = Field(default=b'x', min_length=2)\n"

    findings = _check(source)

    assert len(findings) == 1
    assert "min_length" in findings[0].message


def test_checks_direct_default_against_local_annotated_alias() -> None:
    source = """
        from typing import Annotated
        from pydantic import BaseModel, Field

        NonEmptyStr = Annotated[str, Field(min_length=1)]

        class Model(BaseModel):
            name: NonEmptyStr = ""
    """

    findings = _check(source)

    assert len(findings) == 1
    assert "min_length" in findings[0].message


def test_merges_annotated_and_assignment_field_bounds() -> None:
    source = """
        from typing import Annotated
        from pydantic import BaseModel, Field

        Ratio = Annotated[float, Field(ge=0.0)]

        class Model(BaseModel):
            ratio: Ratio = Field(default=1.5, le=1.0)
    """

    findings = _check(source)

    assert len(findings) == 1
    assert "le=1.0" in findings[0].message


def test_checks_default_embedded_in_annotated_field() -> None:
    source = """
        from typing import Annotated
        from pydantic import BaseModel, Field

        class Model(BaseModel):
            attempts: Annotated[int, Field(default=0, gt=0)]
    """

    assert len(_check(source)) == 1


def test_checks_direct_none_default_without_field_call() -> None:
    source = """
        from pydantic import BaseModel

        class Model(BaseModel):
            name: str = None
    """

    findings = _check(source)

    assert len(findings) == 1
    assert "has a `None` default" in findings[0].message
    assert "gives `Field`" not in findings[0].message


def test_checks_generic_direct_base_model() -> None:
    source = """
        from typing import Generic, TypeVar
        from pydantic import BaseModel

        T = TypeVar("T")

        class Model(BaseModel, Generic[T]):
            name: str = None
    """

    assert len(_check(source)) == 1


def test_ignores_default_transformed_by_exact_field_validator() -> None:
    source = """
        from pydantic import BaseModel, Field, field_validator

        class Model(BaseModel):
            name: str = Field(None, validate_default=True)
            untouched: str = None

            @field_validator("name", mode="before")
            @classmethod
            def normalize_name(cls, value):
                return "anonymous" if value is None else value
    """

    findings = _check(source)

    assert len(findings) == 1
    assert "`untouched`" in findings[0].message


@pytest.mark.parametrize("mode", ["before", "wrap"])
def test_ignores_defaults_transformed_by_model_validator(mode: str) -> None:
    source = f"""\
        from pydantic import BaseModel, model_validator

        class Model(BaseModel):
            name: str = None

            @model_validator(mode="{mode}")
            @classmethod
            def normalize_model(cls, value):
                return value
    """

    assert _check(source) == []


@pytest.mark.parametrize("validator", ["BeforeValidator", "PlainValidator", "WrapValidator"])
def test_ignores_default_transformed_by_annotated_validator(validator: str) -> None:
    source = f"""\
        from typing import Annotated
        from pydantic import BaseModel, Field, {validator} as Normalize

        def normalize(value):
            return "anonymous" if value is None else value

        class Model(BaseModel):
            name: Annotated[str, Normalize(normalize)] = Field(None, validate_default=True)
    """

    assert _check(source) == []


def test_after_validator_does_not_hide_invalid_default() -> None:
    source = """
        from pydantic import BaseModel, field_validator

        class Model(BaseModel):
            name: str = None

            @field_validator("name", mode="after")
            @classmethod
            def normalize_name(cls, value):
                return value
    """

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("annotation", "default", "bound"),
    [
        ("list[int]", "[]", "min_length=1"),
        ("tuple[int, ...]", "(1, 2)", "max_length=1"),
        ("dict[str, int]", "{}", "min_length=1"),
        ("set[int]", "{1, 2}", "max_length=1"),
    ],
)
def test_checks_literal_container_length_bounds(annotation: str, default: str, bound: str) -> None:
    source = f"""\
        from pydantic import BaseModel, Field

        class Model(BaseModel):
            value: {annotation} = Field({default}, {bound})
    """

    findings = _check(source)

    assert len(findings) == 1
    assert bound in findings[0].message


def test_follows_unique_imported_annotated_alias(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    package = tmp_path / "app"
    package.mkdir()
    (package / "types.py").write_text(
        "from typing import Annotated\nfrom pydantic import Field\nNonEmptyStr = Annotated[str, Field(min_length=1)]\n",
        encoding="utf-8",
    )
    source = """
        from pydantic import BaseModel
        from app.types import NonEmptyStr

        class Model(BaseModel):
            name: NonEmptyStr = ""
    """

    findings = _check(source, str(package / "models.py"))

    assert len(findings) == 1
    assert "min_length" in findings[0].message


def test_imported_annotated_alias_with_valid_default_is_clean(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    package = tmp_path / "app"
    package.mkdir()
    (package / "types.py").write_text(
        "from typing import Annotated\nfrom pydantic import Field\nNonEmptyStr = Annotated[str, Field(min_length=1)]\n",
        encoding="utf-8",
    )
    source = """
        from pydantic import BaseModel
        from app.types import NonEmptyStr

        class Model(BaseModel):
            name: NonEmptyStr = "ready"
    """

    assert _check(source, str(package / "models.py")) == []


@pytest.mark.parametrize(
    ("source", "message"),
    [
        pytest.param(
            """
            from pydantic import BaseModel, Field
            class Model(BaseModel):
                name: str = Field(default=None)
            """,
            "excludes `None`",
            id="none-for-str",
        ),
        pytest.param(
            """
            import pydantic as pd
            class Model(pd.BaseModel):
                values: list[int] = pd.Field(None)
            """,
            "excludes `None`",
            id="aliased-module-positional-none",
        ),
        pytest.param(
            """
            from pydantic import BaseModel
            from pydantic.fields import Field as PydanticField
            from typing import Literal as L
            class Model(BaseModel):
                status: L["ready", "failed"] = PydanticField(default="pending")
            """,
            "outside its direct `Literal` domain",
            id="literal-mismatch-with-aliases",
        ),
        pytest.param(
            """
            from pydantic import BaseModel, Field
            from typing import Annotated, Literal
            class Model(BaseModel):
                status: Annotated[Literal["ready"], "wire"] = Field("failed")
            """,
            "outside its direct `Literal` domain",
            id="annotated-literal-mismatch",
        ),
        pytest.param(
            """
            from pydantic import BaseModel, Field
            from typing import Literal
            class Model(BaseModel):
                status: Literal["ready"] | None = Field("failed")
            """,
            "outside its direct `Literal` domain",
            id="optional-literal-mismatch",
        ),
        pytest.param(
            """
            from pydantic import BaseModel, Field
            class Model(BaseModel):
                retries: int = Field(default=2, gt=2)
            """,
            "violates `Field(gt=2)`",
            id="exclusive-lower-bound",
        ),
        pytest.param(
            """
            import pydantic
            class Model(pydantic.BaseModel):
                ratio: float = pydantic.Field(-1.5, ge=-1.0)
            """,
            "violates `Field(ge=-1.0)`",
            id="negative-inclusive-lower-bound",
        ),
        pytest.param(
            """
            from pydantic import BaseModel, Field
            class Model(BaseModel):
                retries: int = Field(default=4, lt=4)
            """,
            "violates `Field(lt=4)`",
            id="exclusive-upper-bound",
        ),
        pytest.param(
            """
            from pydantic import BaseModel, Field
            class Model(BaseModel):
                retries: int = Field(default=5, le=4)
            """,
            "violates `Field(le=4)`",
            id="inclusive-upper-bound",
        ),
        pytest.param(
            """
            from pydantic import BaseModel, Field
            class Model(BaseModel):
                code: str = Field(default="ab", min_length=3)
            """,
            "violates `Field(min_length=3)`",
            id="short-string",
        ),
        pytest.param(
            """
            from pydantic import BaseModel, Field
            class Model(BaseModel):
                code: str = Field(default="abcd", max_length=3)
            """,
            "violates `Field(max_length=3)`",
            id="long-string",
        ),
        pytest.param(
            """
            from pydantic import BaseModel, Field
            from typing import Literal
            class Model(BaseModel):
                code: Literal[1] = Field(default=True)
            """,
            "outside its direct `Literal` domain",
            id="bool-does-not-equal-int-literal",
        ),
    ],
)
def test_reports_proven_invalid_literal_defaults(source: str, message: str) -> None:
    findings = _check(source)

    assert len(findings) == 1
    assert findings[0].code == "SARJ400"
    assert message in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        """
        from pydantic import BaseModel, Field
        class Model(BaseModel):
            name: str | None = Field(default=None)
        """,
        """
        from pydantic import BaseModel, Field
        from typing import Optional
        class Model(BaseModel):
            name: Optional[str] = Field(None)
        """,
        """
        from pydantic import BaseModel, Field
        from typing import Any
        class Model(BaseModel):
            value: Any = Field(None)
        """,
        """
        from pydantic import BaseModel, Field
        class Model(BaseModel):
            value: object = Field(None)
        """,
        """
        from pydantic import BaseModel, Field
        MaybeName = str | None
        class Model(BaseModel):
            name: MaybeName = Field(None)
        """,
        """
        from pydantic import BaseModel, Field
        from typing import Literal
        class Model(BaseModel):
            status: Literal["ready", "failed"] = Field("ready")
            optional_status: Literal["ready"] | None = Field(None)
            enabled: Literal[True] = Field(True)
        """,
        """
        from enum import StrEnum
        from pydantic import BaseModel, Field
        from typing import Literal
        class Status(StrEnum): READY = "ready"
        class Model(BaseModel):
            status: Literal[Status.READY] = Field(Status.READY)
        """,
        """
        from pydantic import BaseModel, Field
        class Model(BaseModel):
            low: int = Field(2, ge=2)
            high: int = Field(4, le=4)
            code: str = Field("abc", min_length=3, max_length=3)
        """,
        """
        from pydantic import BaseModel, Field
        class Model(BaseModel):
            retries: int = Field(default=runtime_default(), gt=3)
            timeout: int = Field(default=2, gt=minimum())
            token: str = Field(default_factory=make_token, min_length=10)
        """,
        """
        from pydantic import BaseModel, Field
        class Model(BaseModel):
            required: str = Field(...)
            implicit_required: str = Field()
        """,
        """
        from pydantic import Field
        value: str = Field(None)
        """,
        """
        from pydantic import BaseModel, Field
        class Parent(BaseModel):
            value: str
        class Child(Parent):
            value: str = Field(None)
        """,
        """
        from pydantic import BaseModel, Field
        class Mixin: pass
        class Model(Mixin, BaseModel):
            value: str = Field(None)
        """,
        """
        from not_pydantic import BaseModel, Field
        class Model(BaseModel):
            value: str = Field(None)
        """,
        """
        from pydantic import BaseModel, Field
        def Field(*args, **kwargs): return args
        class Model(BaseModel):
            value: str = Field(None)
        """,
        """
        from pydantic import BaseModel, Field
        str = object
        class Model(BaseModel):
            value: str = Field(None)
        """,
        """
        from pydantic import BaseModel, Field
        from custom import Literal
        class Model(BaseModel):
            value: Literal["ready"] = Field("other")
        """,
    ],
)
def test_ignores_valid_or_not_provable_defaults(source: str) -> None:
    assert _check(source) == []


def test_reports_only_one_owned_reason_per_field() -> None:
    source = """
        from pydantic import BaseModel, Field
        from typing import Literal
        class Model(BaseModel):
            value: Literal[1] = Field(default=2, le=1)
    """

    findings = _check(source)

    assert len(findings) == 1
    assert "Literal" in findings[0].message


def test_skips_tests_generated_files_and_malformed_source() -> None:
    source = """
        from pydantic import BaseModel, Field
        class Model(BaseModel):
            value: str = Field(None)
    """
    assert _check(source, "tests/test_models.py") == []
    assert _check("# generated by schema compiler\n" + dedent(source)) == []
    assert _check("class Broken(") == []
