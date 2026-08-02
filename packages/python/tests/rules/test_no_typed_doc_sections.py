from pathlib import Path

from sarj_python_lint.rules.no_typed_doc_sections import NoTypedDocSections


def test_typed_returns_section_is_an_error() -> None:
    source = '''def decode(value: str) -> dict[str, object]:
    """Decode the value.

    Returns:
        The decoded object.
    """
    return {}
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
