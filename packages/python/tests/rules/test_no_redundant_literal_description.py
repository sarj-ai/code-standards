from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_redundant_literal_description import NoRedundantLiteralDescription


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "models.py"):
    return NoRedundantLiteralDescription().check(Path(path), dedent(source))


_PUBLIC_EXAMPLES = NoRedundantLiteralDescription.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(item.example_id for item in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoRedundantLiteralDescription().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        """
        from typing import Literal
        from pydantic import BaseModel, Field
        class Request(BaseModel):
            kind: Literal["call"] = Field(description="Must be 'call'")
        """,
        """
        from enum import StrEnum
        from pydantic import BaseModel, Field
        class Kind(StrEnum):
            CALL = "call"
            CHAT = "chat"
        class Request(BaseModel):
            kind: Kind = Field(description="Should be 'call' or 'chat'.")
        """,
        """
        import pydantic as pd
        from typing_extensions import Annotated, Literal as L
        class Request(pd.BaseModel):
            kind: Annotated[L["call", "chat"], pd.Field(description="Must be one of 'call' or 'chat'")]
        """,
    ],
)
def test_reports_domain_only_descriptions(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ423"
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize(
    "source",
    [
        """
        from typing import Literal
        from pydantic import BaseModel, Field
        class Request(BaseModel):
            kind: Literal["call"] = Field(description="Routes the request through the realtime call provider.")
        """,
        """
        from pydantic import BaseModel, Field
        class Request(BaseModel):
            kind: str = Field(description="Must be a provider-supported identifier.")
        """,
        """
        from typing import Literal
        from pydantic import BaseModel
        class Request(BaseModel):
            kind: Literal["call"]
        """,
        """
        from typing import Literal
        from pydantic import BaseModel, Field
        class Request(BaseModel):
            kind: Literal["call"] = Field(description=DESCRIPTION)
        """,
        """
        from typing import Literal
        from pydantic import BaseModel, Field
        class Request(BaseModel):
            kind: Literal["call"] = Field(description="Must be a provider-supported identifier.")
        """,
        """
        from typing import Literal
        from pydantic import BaseModel, Field
        class Request(BaseModel):
            kind: Literal["call", "chat"] = Field(description="Must be 'call' for realtime routing.")
        """,
    ],
)
def test_keeps_nonredundant_or_unprovable_descriptions(source: str) -> None:
    assert _check(source) == []


def test_skips_tests_and_generated_files() -> None:
    source = """
        from typing import Literal
        from pydantic import BaseModel, Field
        class Request(BaseModel):
            kind: Literal["call"] = Field(description="Must be 'call'")
    """
    assert _check(source, "test_models.py") == []
    assert _check(source, "generated/models.py") == []


def test_reports_local_literal_alias_and_live_clause_shape() -> None:
    findings = _check(
        """
        from typing import Literal
        from pydantic import BaseModel, Field
        AmountInterval = Literal["BETWEEN_1K_5K", "ABOVE_50K"]
        class Request(BaseModel):
            amount: AmountInterval = Field(
                description="Monthly amount this should only be one of the following values: BETWEEN_1K_5K, ABOVE_50K"
            )
        """
    )
    assert len(findings) == 1


@pytest.mark.parametrize(
    "description",
    [
        "Allowed values: `call`, `chat`.",
        "Valid values: 'chat' or 'call'.",
        "Must be either 'call' or 'chat'.",
        "Should be one of: 'call', 'chat'.",
    ],
)
def test_reports_exact_closed_domain_clause_variants(description: str) -> None:
    source = f"""\
        from typing import Literal
        from pydantic import BaseModel, Field
        class Request(BaseModel):
            kind: Literal["call", "chat"] = Field(description={description!r})
    """
    assert len(_check(source)) == 1


def test_reports_literal_union_on_direct_model_with_mixin() -> None:
    findings = _check(
        """
        from typing import Literal
        from pydantic import BaseModel, Field
        class AuditMixin: ...
        class Request(AuditMixin, BaseModel):
            kind: Literal["call"] | Literal["chat"] = Field(description="Must be 'call' or 'chat'")
        """
    )
    assert len(findings) == 1


def test_supports_pydantic_v1_namespaces() -> None:
    findings = _check(
        """
        from typing import Literal
        from pydantic.v1 import BaseModel, Field
        class Request(BaseModel):
            kind: Literal["call", "chat"] = Field(description="Allowed values: 'call', 'chat'")
        """
    )
    assert len(findings) == 1


@pytest.mark.parametrize(
    "description",
    [
        "Allowed values: 'call'.",
        "Allowed values: 'call', 'chat', 'email'.",
        "Use 'call' for realtime audio and 'chat' for text.",
        "Must be 'call' or 'chat' because the provider requires it.",
    ],
)
def test_keeps_partial_extra_mapped_or_rationale_descriptions(description: str) -> None:
    source = f"""\
        from typing import Literal
        from pydantic import BaseModel, Field
        class Request(BaseModel):
            kind: Literal["call", "chat"] = Field(description={description!r})
    """
    assert _check(source) == []


def test_rebound_local_alias_abstains() -> None:
    assert (
        _check(
            """
            from typing import Literal
            from pydantic import BaseModel, Field
            Kind = Literal["call"]
            class Request(BaseModel):
                kind: Kind = Field(description="Must be 'call'")
            Kind = str
            """
        )
        == []
    )


def test_custom_json_schema_hooks_and_with_json_schema_abstain() -> None:
    assert (
        _check(
            """
            from typing import Annotated, Literal
            from pydantic import BaseModel, Field, WithJsonSchema
            class Request(BaseModel):
                kind: Annotated[
                    Literal["call"],
                    WithJsonSchema({"type": "string"}),
                ] = Field(description="Must be 'call'")
            """
        )
        == []
    )
    assert (
        _check(
            """
            from typing import Literal
            from pydantic import BaseModel, Field
            class Request(BaseModel):
                kind: Literal["call"] = Field(description="Must be 'call'")
                @classmethod
                def __get_pydantic_json_schema__(cls, core_schema, handler):
                    return {"type": "object"}
            """
        )
        == []
    )


def test_function_local_field_name_does_not_shadow_module_import() -> None:
    findings = _check(
        """
        from typing import Literal
        from pydantic import BaseModel, Field
        def helper(Field: object) -> object:
            return Field
        class Request(BaseModel):
            kind: Literal["call"] = Field(description="Must be 'call'")
        """
    )
    assert len(findings) == 1


def test_module_field_rebinding_abstains() -> None:
    assert (
        _check(
            """
            from typing import Literal
            from pydantic import BaseModel, Field
            Field = custom_field
            class Request(BaseModel):
                kind: Literal["call"] = Field(description="Must be 'call'")
            """
        )
        == []
    )
