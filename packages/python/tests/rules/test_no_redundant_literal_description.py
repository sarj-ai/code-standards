from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

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
