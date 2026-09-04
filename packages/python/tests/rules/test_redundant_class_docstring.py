from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.redundant_class_docstring import RedundantClassDocstring


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return RedundantClassDocstring().check(Path("<t>.py"), source)


def _cls(header: str, docstring: str, body: str = "    x: int = 1\n") -> list[Diagnostic]:
    return _check(f'class {header}:\n    """{docstring}"""\n\n{body}')


RESTATEMENTS = [
    ("ShipmentCreateData", "Shipment create data."),
    ("ReservationSummary", "A reservation summary."),
    ("TestNormaliseLabel", "Test normalise label."),
    ("RetryPolicy", "The retry policy."),
    ("InboundEventHandler", "Handles inbound events."),
]

_PUBLIC_EXAMPLES = RedundantClassDocstring.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(RedundantClassDocstring().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(("name", "docstring"), RESTATEMENTS)
def test_flags_name_restating_class_docstring(name: str, docstring: str):
    diags = _cls(name, docstring)
    assert len(diags) == 1
    assert diags[0].code == "SARJ085"
    assert (diags[0].line, diags[0].col) == (2, 5)


def test_inherited_class_is_out_of_scope():
    assert _cls("Handler(RetryPolicy)", "A retry policy handler.") == []


def test_negation_in_the_class_name_counts_towards_the_name():
    assert len(_cls("TaskNotRegisteredError", "Task not registered error.")) == 1


def test_inherited_class_with_novel_prose_is_out_of_scope():
    assert _cls("Handler(RetryPolicy)", "A retry policy handler for the replica pool.") == []


def test_one_novel_word_keeps_the_docstring():
    assert _cls("ReservationSummary", "Summary of a reservation, excluding cancelled holds.") == []


@pytest.mark.parametrize(
    ("name", "docstring"),
    [
        ("ParentChild", "Parent of the child."),
        ("ParentChild", "Child of the parent."),
        ("SourceTarget", "Target for the source."),
        ("SourceTarget", "Source is the target."),
    ],
)
def test_relational_words_keep_potentially_meaningful_prose(name: str, docstring: str) -> None:
    assert _cls(name, docstring) == []


def test_consumer_and_versioning_contract_keeps_the_docstring() -> None:
    assert (
        _cls(
            "AnalysisReport",
            "Versioned result for IDEs, CI annotations, and programmatic consumers.",
        )
        == []
    )


def test_nested_class_is_checked():
    src = 'class Outer:\n    class RetryPolicy:\n        """The retry policy."""\n\n        x: int = 1\n'
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    ("imports", "base"),
    [
        ("from pydantic import BaseModel", "BaseModel"),
        ("import pydantic", "pydantic.BaseModel"),
        ("from pydantic_settings import BaseSettings", "BaseSettings"),
        ("from pydantic import RootModel", "RootModel"),
        ("from typing import TypedDict", "TypedDict"),
        ("from enum import Enum", "Enum"),
        ("from enum import EnumMeta", "EnumMeta"),
        ("from enum import Flag", "Flag"),
        ("from enum import StrEnum", "StrEnum"),
        ("from enum import IntEnum", "IntEnum"),
        ("from enum import IntFlag", "IntFlag"),
        ("from enum import ReprEnum", "ReprEnum"),
        ("import enum", "enum.Enum"),
    ],
)
def test_schema_carrying_bases_are_exempt(imports: str, base: str):
    # A pydantic model's class docstring is emitted as the JSON-Schema `description`, which FastAPI publishes and an LLM tool schema ships to the model.
    source = f'{imports}\nclass ShipmentResponse({base}):\n    """Shipment response."""\n\n    x: int = 1\n'
    assert _check(source) == []


def test_a_generic_schema_base_is_exempt():
    source = 'from pydantic import RootModel\nclass Page(RootModel[int]):\n    """Page root model."""\n\n    x = 1\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    ("imports", "decorator"),
    [
        ("import pydantic.dataclasses", "@pydantic.dataclasses.dataclass"),
        ("import strawberry", "@strawberry.type"),
        ("import msgspec", "@msgspec.defstruct"),
    ],
)
def test_schema_decorators_are_exempt(imports: str, decorator: str):
    src = f'{imports}\n{decorator}\nclass ReservationSummary:\n    """Summary of a reservation."""\n\n    x: int = 1\n'
    assert _check(src) == []


def test_a_plain_dataclass_is_out_of_scope():
    src = 'from dataclasses import dataclass\n\n@dataclass\nclass ReservationSummary:\n    """Summary of a reservation."""\n\n    x: int = 1\n'
    assert _check(src) == []


def test_a_class_whose_body_is_the_docstring_is_exempt():
    # The exception-class idiom.
    assert _check('class ShipmentLimitError(DomainError):\n    """Shipment limit error."""\n') == []


def test_a_class_with_pass_after_the_docstring_is_still_checked():
    assert len(_cls("ShipmentLimitError", "Shipment limit error.", "    pass\n")) == 1


@pytest.mark.parametrize(
    "docstring",
    [
        pytest.param("Retry policy. See PROJ-249.", id="external-reference"),
        pytest.param("Retry policy since Python 3.11.", id="version-constraint"),
        pytest.param("Retry policy for HTTP 429 responses.", id="unit-or-status"),
        pytest.param("Retry policy, because the upstream caps concurrency.", id="causal-reason"),
        pytest.param("Retry policy. Never used on the write path.", id="negation"),
        pytest.param("Retry policy required by an upstream regression.", id="upstream-contract"),
        pytest.param("Retry policy must run before the lock.", id="invariant"),
        pytest.param("Retry policy prevents a timing attack.", id="security-reason"),
        pytest.param("Retry policy; Stripe rejects duplicates.", id="vendor-behavior"),
    ],
)
def test_each_protected_signal_keeps_the_docstring(docstring: str):
    assert _cls("RetryPolicy", docstring) == []


@pytest.mark.parametrize(
    "docstring",
    [
        "Retry policy. See https://example.com/retries.",
        "Retry policy (RFC 7231).",
        "Retry policy — retries within 30 seconds.",
        "Retry policy.\\n\\n    Raises:\\n        ValueError: on a negative budget.",
    ],
)
def test_value_markers_keep_the_docstring(docstring: str):
    assert _cls("RetryPolicy", docstring.replace("\\n", "\n")) == []


@pytest.mark.parametrize(
    ("imports", "decorator"),
    [
        ("import mcp", "@mcp.tool()"),
        ("from openai.agents import function_tool", "@function_tool"),
        ("import click", "@click.command()"),
    ],
    ids=["prompt", "llm-tool", "cli"],
)
def test_proven_runtime_docstring_decorators_are_exempt(imports: str, decorator: str):
    src = f'{imports}\n{decorator}\nclass RetryPolicy:\n    """The retry policy."""\n\n    x: int = 1\n'
    assert _check(src) == []


def test_generated_file_is_skipped():
    src = '# Code generated by openapi-generator. DO NOT EDIT.\nclass RetryPolicy:\n    """The retry policy."""\n\n    x: int = 1\n'
    assert _check(src) == []


def test_class_without_a_docstring_is_ignored():
    assert _check("class RetryPolicy:\n    x: int = 1\n") == []


def test_module_and_function_docstrings_are_out_of_scope():
    src = '"""Retry policy."""\n\n\ndef retry_policy() -> None:\n    """Retry policy."""\n    return None\n'
    assert _check(src) == []


def test_unparseable_source_returns_nothing():
    assert _check("class (:\n") == []


@pytest.mark.parametrize(
    ("imports", "base"),
    [
        ("from pydantic import BaseModel as PM", "PM"),
        ("from enum import Enum as E", "E"),
        ("from typing import TypedDict as TD", "TD"),
        ("from sqlmodel import SQLModel", "SQLModel"),
        ("from graphene import ObjectType as GraphType", "GraphType"),
    ],
)
def test_aliased_schema_bases_are_exempt(imports: str, base: str) -> None:
    source = f'{imports}\nclass RetryPolicy({base}):\n    """The retry policy."""\n\n    attempts = 3\n'

    assert _check(source) == []


def test_local_descendant_of_schema_base_is_exempt() -> None:
    source = '''
from pydantic import BaseModel

class SchemaBase(BaseModel):
    pass

class RetryPolicy(SchemaBase):
    """The retry policy."""

    attempts = 3
'''

    assert _check(source) == []


def test_aliased_schema_decorator_is_exempt() -> None:
    source = '''
from pydantic.dataclasses import dataclass as schema_dataclass

@schema_dataclass
class RetryPolicy:
    """The retry policy."""

    attempts: int = 3
'''

    assert _check(source) == []


def test_any_decorated_class_is_out_of_scope() -> None:
    source = '''
@thing.command
class RetryPolicy:
    """The retry policy."""

    attempts = 3
'''

    assert _check(source) == []


def test_direct_docstring_consumer_preserves_runtime_contract() -> None:
    source = '''
class RetryPolicy:
    """The retry policy."""

    attempts = 3

REGISTRY = {RetryPolicy.__doc__: RetryPolicy}
'''

    assert _check(source) == []


@pytest.mark.parametrize("qualifier", ["Default", "Optional", "Required", "Standard"])
def test_meaningful_qualifier_keeps_docstring(qualifier: str) -> None:
    assert _cls("RetryPolicy", f"{qualifier} retry policy.") == []


def test_inline_suppression_is_honored() -> None:
    source = 'class RetryPolicy:\n    """The retry policy."""  # sarj-noqa: SARJ085\n\n    attempts = 3\n'

    assert _check(source) == []


def test_later_schema_import_rebinding_does_not_risk_deletion() -> None:
    source = '''
from pydantic import BaseModel

class RetryPolicy(BaseModel):
    """The retry policy."""

    attempts = 3

BaseModel = object
'''

    assert _check(source) == []


def test_nested_descendant_of_schema_base_is_exempt() -> None:
    source = '''
from pydantic import BaseModel

def build():
    class SchemaBase(BaseModel):
        pass

    class RetryPolicy(SchemaBase):
        """The retry policy."""

        attempts = 3
'''

    assert _check(source) == []


def test_imported_pydantic_dataclasses_module_is_resolved() -> None:
    source = '''
from pydantic import dataclasses

@dataclasses.dataclass
class RetryPolicy:
    """The retry policy."""

    attempts = 3
'''

    assert _check(source) == []


def test_pydantic_v1_model_is_exempt() -> None:
    source = '''
from pydantic.v1 import BaseModel

class RetryPolicy(BaseModel):
    """The retry policy."""

    attempts = 3
'''

    assert _check(source) == []


@pytest.mark.parametrize(
    ("imports", "base"),
    [
        ("from pydantic.v1 import BaseSettings", "BaseSettings"),
        ("from pydantic.generics import GenericModel", "GenericModel"),
        ("from pydantic.v1.generics import GenericModel as Model", "Model"),
        ("from graphene import Enum", "Enum"),
        ("from graphene import Union as GraphUnion", "GraphUnion"),
    ],
)
def test_additional_schema_docstring_consumers_are_exempt(imports: str, base: str) -> None:
    source = f'{imports}\nclass RetryPolicy({base}):\n    """The retry policy."""\n\n    attempts = 3\n'

    assert _check(source) == []


def test_aliased_pydantic_dataclasses_module_is_resolved() -> None:
    source = '''
from pydantic import dataclasses as pdc

@pdc.dataclass
class RetryPolicy:
    """The retry policy."""

    attempts = 3
'''

    assert _check(source) == []


def test_qualifier_repeated_by_class_name_is_still_redundant() -> None:
    assert len(_cls("DefaultRetryPolicy", "Default retry policy.")) == 1


@pytest.mark.parametrize(
    "docstring",
    ["Current user.", "New user.", "All users.", "Returned user.", "Provided user.", "Given user."],
)
def test_semantic_terms_are_not_treated_as_grammar(docstring: str) -> None:
    assert _cls("User", docstring) == []


@pytest.mark.parametrize("docstring", ["Protocol version 3.", "Protocol version #3."])
def test_numeric_detail_is_preserved(docstring: str) -> None:
    assert _cls("ProtocolVersion", docstring) == []


def test_number_repeated_by_class_name_is_still_redundant() -> None:
    assert len(_cls("ProtocolVersion3", "Protocol version 3.")) == 1


@pytest.mark.parametrize("term", ["سريع", "سياسة", "例外"])
def test_non_latin_semantic_term_is_preserved(term: str) -> None:
    assert _cls("RetryPolicy", f"Retry policy {term}.") == []


def test_qualified_docstring_consumer_preserves_runtime_contract() -> None:
    source = '''
class RetryPolicy:
    """The retry policy."""

    attempts = 3

REGISTRY = {Namespace.RetryPolicy.__doc__: RetryPolicy}
'''

    assert _check(source) == []


@pytest.mark.parametrize(
    "consumer",
    [
        "inspect.getdoc(RetryPolicy)",
        "pydoc.render_doc(RetryPolicy)",
        'getattr(RetryPolicy, "__doc__")',
        "help(RetryPolicy)",
        'RetryPolicy.__dict__["__doc__"]',
        'vars(RetryPolicy)["__doc__"]',
        "Policy: type = RetryPolicy\nREGISTRY = Policy.__doc__",
        "if enabled:\n    Policy = RetryPolicy\n    REGISTRY = Policy.__doc__",
        "Policy = RetryPolicy\nREGISTRY = Policy.__doc__\nPolicy = Other",
    ],
)
def test_common_runtime_docstring_readers_are_exempt(consumer: str) -> None:
    source = f'''\
class RetryPolicy:
    """The retry policy."""

    attempts = 3

{consumer}
'''

    assert _check(source) == []


def test_docstring_consumer_through_module_alias_is_exempt() -> None:
    source = '''
class RetryPolicy:
    """The retry policy."""

    attempts = 3

Policy = RetryPolicy
REGISTRY = {Policy.__doc__: Policy}
'''

    assert _check(source) == []
