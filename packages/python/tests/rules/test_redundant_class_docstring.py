from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.redundant_class_docstring import RedundantClassDocstring


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return RedundantClassDocstring().check(Path("<t>.py"), source)


def _cls(header: str, docstring: str, body: str = "    x: int = 1\n") -> list[Diagnostic]:
    """Wrap a class header and docstring in a class with a real body."""
    return _check(f'class {header}:\n    """{docstring}"""\n\n{body}')


RESTATEMENTS = [
    ("ShipmentCreateData", "Data for creating a shipment."),
    ("ReservationSummary", "Summary of a reservation."),
    ("TestNormaliseLabel", "Tests for normalise_label."),
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


def test_base_class_names_count_towards_the_name():
    assert len(_cls("Handler(RetryPolicy)", "A retry policy handler.")) == 1


def test_negation_in_the_class_name_counts_towards_the_name():
    assert len(_cls("NotRegistered(KeyError, TaskError)", "The task is not registered.")) == 1


def test_a_base_the_name_does_not_carry_keeps_the_docstring():
    # The reader sees the base on the class line, so a word it supplies is not
    # novel — but a word NEITHER carries is.
    assert _cls("Handler(RetryPolicy)", "A retry policy handler for the replica pool.") == []


def test_one_novel_word_keeps_the_docstring():
    assert _cls("ReservationSummary", "Summary of a reservation, excluding cancelled holds.") == []


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
    "base",
    [
        "BaseModel",
        "pydantic.BaseModel",
        "BaseSettings",
        "RootModel",
        "TypedDict",
        "Enum",
        "EnumMeta",
        "Flag",
        "StrEnum",
        "IntEnum",
        "IntFlag",
        "ReprEnum",
        "enum.Enum",
    ],
)
def test_schema_carrying_bases_are_exempt(base: str):
    # A pydantic model's class docstring is emitted as the JSON-Schema `description`, which FastAPI publishes and an LLM tool schema ships to the model.
    assert _cls(f"ShipmentResponse({base})", "Shipment response.") == []


def test_a_generic_schema_base_is_exempt():
    assert _cls("Page(RootModel[int])", "Page root model.") == []


@pytest.mark.parametrize(
    "decorator",
    [
        "@pydantic.dataclasses.dataclass",
        "@strawberry.type",
        "@graphene.ObjectType",
        "@msgspec.defstruct",
    ],
)
def test_schema_decorators_are_exempt(decorator: str):
    src = f'{decorator}\nclass ReservationSummary:\n    """Summary of a reservation."""\n\n    x: int = 1\n'
    assert _check(src) == []


def test_a_plain_dataclass_is_still_checked():
    src = 'from dataclasses import dataclass\n\n@dataclass\nclass ReservationSummary:\n    """Summary of a reservation."""\n\n    x: int = 1\n'
    assert len(_check(src)) == 1


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
    "decorator",
    ["@mcp.tool()", "@function_tool", "@click.command()", '@router.get("/retries")'],
    ids=["prompt", "llm-tool", "cli", "route"],
)
def test_prompt_cli_and_route_decorators_are_exempt(decorator: str):
    src = f'{decorator}\nclass RetryPolicy:\n    """The retry policy."""\n\n    x: int = 1\n'
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
