from pathlib import Path

import pytest

from sarj_python_lint.rules.no_typed_doc_sections import NoTypedDocSections


@pytest.mark.parametrize(
    "section",
    [
        "Args",
        "Arguments",
        "Parameters",
        "Params",
        "Keyword Args",
        "Keyword Arguments",
        "Returns",
        "Return",
        "Yields",
        "Yield",
    ],
)
def test_parameter_and_result_sections_are_errors_on_fully_typed_functions(section: str) -> None:
    source = f'''def decode(value: str) -> dict[str, object]:
    """Decode the value.

    {section}:
        Restates the typed signature.
    """
    return {{}}
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
            value: The value.
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


def test_pr_4213_typed_returns_section_is_rejected() -> None:
    source = '''def build_notify_url(url: str, params: dict[str, str | None]) -> str:
    """Assemble the callback URL.

    Returns:
        The URL with params appended.

    Raises:
        ValueError: If the URL cannot be prepared.
    """
    return url
'''
    assert len(NoTypedDocSections().check(Path("crm_service.py"), source)) == 1
