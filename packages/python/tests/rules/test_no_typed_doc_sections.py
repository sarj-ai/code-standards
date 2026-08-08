from pathlib import Path

import pytest

from sarj_python_lint.rules.no_typed_doc_sections import NoTypedDocSections


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


@pytest.mark.parametrize("section", ["Returns", "Return", "Yields", "Yield"])
def test_explicit_return_type_restatement_is_rejected(section: str) -> None:
    source = f'''def decode(value: str) -> dict[str, object]:
    """Decode the value.

    {section}:
        dict[str, object]: Decoded fields.
    """
    return {{}}
'''
    assert len(NoTypedDocSections().check(Path("app.py"), source)) == 1


@pytest.mark.parametrize("section", ["Returns", "Return", "Yields", "Yield"])
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
