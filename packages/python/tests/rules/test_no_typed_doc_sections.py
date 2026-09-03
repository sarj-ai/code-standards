from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_typed_doc_sections import NoTypedDocSections


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_PUBLIC_EXAMPLES = NoTypedDocSections.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoTypedDocSections().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize("section", ["Args", "Arguments", "Parameters", "Params", "Keyword Args", "Keyword Arguments"])
def test_explicit_parameter_type_restatement_is_rejected(section: str) -> None:
    source = f'''def decode(value: str) -> dict[str, object]:
    """Decode the value.

    {section}:
        value (str): Text to decode.
    """
    return {{}}
'''
    findings = NoTypedDocSections().check(Path("app.py"), source)
    assert len(findings) == 1
    assert findings[0].line == 5


@pytest.mark.parametrize("section", ["Returns", "Return"])
def test_explicit_return_type_restatement_is_rejected(section: str) -> None:
    source = f'''def decode(value: str) -> dict[str, object]:
    """Decode the value.

    {section}:
        dict[str, object]: Decoded fields.
    """
    return {{}}
'''
    assert len(NoTypedDocSections().check(Path("app.py"), source)) == 1


@pytest.mark.parametrize("section", ["Returns", "Return"])
@pytest.mark.parametrize("annotation", ["str", "dict[str, object]", "list[Widget]", "None"])
def test_bare_single_line_return_type_restatement_is_rejected(section: str, annotation: str) -> None:
    source = f'''def decode(value: str) -> {annotation}:
    """Decode the value.

    {section}:
        {annotation}
    """
    raise NotImplementedError
'''
    findings = NoTypedDocSections().check(Path("app.py"), source)

    assert len(findings) == 1
    assert findings[0].line == 5


@pytest.mark.parametrize(
    ("annotation", "body"),
    [
        ("str", "bytes"),
        ("str", "The decoded value."),
        ("str", "str\n        Preserves the original encoding."),
        ("Iterator[int]", "int"),
        ("str", "str | None"),
    ],
)
def test_bare_return_type_requires_one_exact_type_only_line(annotation: str, body: str) -> None:
    source = f'''def decode(value: str) -> {annotation}:
    """Decode the value.

    Returns:
        {body}
    """
    raise NotImplementedError
'''

    assert NoTypedDocSections().check(Path("app.py"), source) == []


def test_numpy_parameter_type_restatement_is_rejected() -> None:
    source = '''def decode(value: str) -> str:
    """Decode the value.

    Parameters:
        value: str
    """
    return value
'''
    assert len(NoTypedDocSections().check(Path("app.py"), source)) == 1


def test_untyped_signature_is_out_of_scope() -> None:
    source = '''def decode(value):
    """Decode the value.

    Returns:
        The decoded object.
    """
    return {}
'''
    assert NoTypedDocSections().check(Path("app.py"), source) == []


def test_raises_section_is_not_type_restatement() -> None:
    source = '''def decode(value: str) -> str:
    """Decode the value.

    Raises:
        ValueError: When invalid.
    """
    return value
'''
    assert NoTypedDocSections().check(Path("app.py"), source) == []


@pytest.mark.parametrize(
    "decorator",
    [
        "@function_tool",
        "@click.command()",
        "@router.post('/decode')",
    ],
    ids=["model-tool-description", "cli-help", "openapi-schema"],
)
def test_runtime_consumed_docstrings_are_exempt(decorator: str) -> None:
    source = f'''{decorator}
def decode(value: str) -> str:
    """Decode the value.

    Args:
        value: Text exposed to the runtime consumer.

    Returns:
        Text exposed to the runtime consumer.
    """
    return value
'''
    assert NoTypedDocSections().check(Path("app.py"), source) == []


def test_self_does_not_need_an_annotation_for_a_method_to_be_fully_typed() -> None:
    source = '''class Decoder:
    def decode(self, value: str) -> str:
        """Decode the value.

        Args:
            value (str): The value.
        """
        return value
'''
    assert len(NoTypedDocSections().check(Path("app.py"), source)) == 1


@pytest.mark.parametrize(
    "signature",
    [
        "def decode(value) -> str:",
        "def decode(value: str):",
        "def decode(*values) -> str:",
        "def decode(**values) -> str:",
    ],
    ids=["untyped-parameter", "untyped-return", "untyped-varargs", "untyped-kwargs"],
)
def test_partially_typed_signatures_are_out_of_scope(signature: str) -> None:
    source = f'''{signature}
    """Decode the value.

    Returns:
        The decoded value.
    """
    return ""
'''
    assert NoTypedDocSections().check(Path("app.py"), source) == []


def test_behavioral_returns_contract_is_preserved() -> None:
    source = '''def build_notify_url(url: str, params: dict[str, str | None]) -> str:
    """Assemble the callback URL.

    Returns:
        The URL with params appended.

    Raises:
        ValueError: If the URL cannot be prepared.
    """
    return url
'''
    assert NoTypedDocSections().check(Path("crm_service.py"), source) == []


def test_behavioral_parameter_contract_is_preserved() -> None:
    source = '''def publish(message: str, *, retry: bool) -> None:
    """Publish one message.

    Args:
        message: Wire payload retained for the audit record.
        retry: Whether a prior partial write may be attempted again.
    """
'''
    assert NoTypedDocSections().check(Path("publisher.py"), source) == []


def test_documented_type_must_match_the_signature() -> None:
    source = '''def decode(value: str) -> str:
    """Decode a legacy integer payload.

    Args:
        value (int): Legacy integer supplied by the upstream schema.
    """
    return value
'''
    assert NoTypedDocSections().check(Path("app.py"), source) == []


def test_selector_names_the_exact_concern_and_preserves_compatibility() -> None:
    assert NoTypedDocSections.id == "no-docstring-type-restatement"
    assert NoTypedDocSections.documentation is not None
    assert NoTypedDocSections.documentation.aliases == ("no-typed-doc-sections",)


def test_collapses_multiple_restatements_to_one_warning() -> None:
    source = '''def decode(value: str, encoding: str) -> bytes:
    """Decode a value.

    Args:
        value (str): Wire value.
        encoding (str): Wire encoding.

    Returns:
        bytes: Decoded bytes.
    """
    return value.encode(encoding)
'''
    findings = NoTypedDocSections().check(Path("app.py"), source)

    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "3 type label(s)" in findings[0].message


def test_behavioral_return_prose_that_resembles_a_camelcase_type_is_preserved() -> None:
    source = '''def get_transfer(transfer_id: str) -> TransferDetailResult:
    """Get a transfer.

    Returns:
        Transfer detail result
    """
    raise NotImplementedError
'''
    assert NoTypedDocSections().check(Path("service.py"), source) == []


def test_optional_qualifier_is_not_erased_during_type_comparison() -> None:
    source = '''def decode(value: str = "") -> None:
    """Decode a value.

    Args:
        value (str, optional): Value supplied by the caller.
    """
'''
    assert NoTypedDocSections().check(Path("service.py"), source) == []


def test_quoted_forward_annotation_matches_a_documented_type() -> None:
    source = '''def decode(value: "Widget") -> "Widget":
    """Decode a widget.

    Args:
        value (Widget): Widget to decode.
    """
    return value
'''
    assert len(NoTypedDocSections().check(Path("service.py"), source)) == 1


@pytest.mark.parametrize("container", ["Iterator", "AsyncIterator", "Generator", "AsyncGenerator"])
def test_yield_section_compares_the_yielded_element_type(container: str) -> None:
    parameters = ", None, None" if container == "Generator" else ", None" if container == "AsyncGenerator" else ""
    source = f'''def values() -> {container}[int{parameters}]:
    """Yield values.

    Yields:
        int: One value.
    """
    raise NotImplementedError
'''
    assert len(NoTypedDocSections().check(Path("service.py"), source)) == 1


def test_yield_section_does_not_repeat_the_generator_container() -> None:
    source = '''def values() -> Iterator[int]:
    """Yield values.

    Yields:
        Iterator[int]: Values.
    """
    raise NotImplementedError
'''
    assert NoTypedDocSections().check(Path("service.py"), source) == []


@pytest.mark.parametrize("decorator", ["@property", "@abstractmethod", "@cached_property", "@overload"])
def test_public_contract_decorators_are_exempt(decorator: str) -> None:
    source = f'''class Service:
    {decorator}
    def value(self) -> str:
        """Return the value.

        Returns:
            str: Current value.
        """
        raise NotImplementedError
'''
    assert NoTypedDocSections().check(Path("service.py"), source) == []


def test_protocol_method_is_exempt() -> None:
    source = '''class Service(Protocol):
    def load(self, value: str) -> str:
        """Load a value.

        Args:
            value (str): Value to load.
        """
        ...
'''
    assert NoTypedDocSections().check(Path("service.py"), source) == []


def test_unrelated_dotted_decorator_does_not_look_like_a_runtime_tool() -> None:
    source = '''@tools.memoize
def decode(value: str) -> str:
    """Decode a value.

    Args:
        value (str): Value to decode.
    """
    return value
'''
    assert len(NoTypedDocSections().check(Path("service.py"), source)) == 1


@pytest.mark.parametrize(
    "example",
    [
        "```python\nArgs:\n    value (str): Example only.\n```",
        "Example::\n\n    Args:\n        value (str): Example only.",
        ">>> text = 'Args:'\n... value = 'value (str): Example only.'",
    ],
    ids=["markdown-fence", "rest-literal-block", "doctest"],
)
def test_literal_examples_do_not_create_typed_sections(example: str) -> None:
    source = f'''def decode(value: str) -> str:
    """Decode a value.

    {example}
    """
    return value
'''
    assert NoTypedDocSections().check(Path("service.py"), source) == []


def test_real_numpy_and_sphinx_type_fields_remain_with_their_convention() -> None:
    numpy = '''def decode(value: str) -> str:
    """Decode.

    Parameters
    ----------
    value : str
    """
    return value
'''
    sphinx = '''def decode(value: str) -> str:
    """Decode.

    :param str value: Value to decode.
    :rtype: str
    """
    return value
'''
    assert NoTypedDocSections().check(Path("service.py"), numpy) == []
    assert NoTypedDocSections().check(Path("service.py"), sphinx) == []
