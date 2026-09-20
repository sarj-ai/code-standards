from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_match_exception_dispatch import PreferMatchExceptionDispatch
from sarj_python_lint.rules.prefer_match_type_dispatch import PreferMatchTypeDispatch
from sarj_python_lint.rules.prefer_match_value_dispatch import PreferMatchValueDispatch


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/errors.py") -> list[Diagnostic]:
    return PreferMatchExceptionDispatch().check(Path(path), source)


_PROVIDER_CLASSIFIER = """
import asyncio
from http import HTTPStatus
from livekit.agents import APIConnectionError, APIStatusError, APITimeoutError

def provider_error_category(error: BaseException) -> str:
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    if isinstance(error, TimeoutError | APITimeoutError):
        return "timeout"
    if isinstance(error, APIStatusError):
        if error.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            return "rate_limit"
        if error.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            return "auth"
        if error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
            return "provider_5xx"
        if error.message == _EMPTY_RESPONSE_MESSAGE:
            return "empty_response"
        if "PROHIBITED_CONTENT" in error.message or "blocked by gemini" in error.message:
            return "content_filter"
    if isinstance(error, APIConnectionError):
        return "connection"
    return "unknown"
"""


_EXAMPLES = PreferMatchExceptionDispatch.public_examples()


@pytest.mark.parametrize("example", _EXAMPLES, ids=tuple(example.example_id for example in _EXAMPLES))
def test_documentation_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_path))) == example.expected_count


def test_flags_exact_provider_error_classifier_as_warning() -> None:
    diagnostics = _check(_PROVIDER_CLASSIFIER)

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ453"
    assert diagnostics[0].severity.value == "warning"
    assert diagnostics[0].line == 7
    assert "subclass order, guard evaluation, and fallthrough" in diagnostics[0].message


def test_does_not_duplicate_existing_match_dispatch_rules() -> None:
    path = Path("app/errors.py")
    assert PreferMatchTypeDispatch().check(path, _PROVIDER_CLASSIFIER) == []
    assert PreferMatchValueDispatch().check(path, _PROVIDER_CLASSIFIER) == []


@pytest.mark.parametrize("group", ["TimeoutError | APITimeoutError", "(TimeoutError, APITimeoutError)"])
def test_accepts_static_union_and_tuple_exception_groups(group: str) -> None:
    assert len(_check(_PROVIDER_CLASSIFIER.replace("TimeoutError | APITimeoutError", group))) == 1


def test_accepts_import_aliases_using_canonical_exception_name() -> None:
    source = _PROVIDER_CLASSIFIER.replace("import asyncio", "import asyncio as aio").replace(
        "asyncio.CancelledError", "aio.CancelledError"
    )
    source = source.replace("APITimeoutError", "TimedOut")
    source = source.replace("APIStatusError", "Status")
    source = source.replace("APIConnectionError", "Connect")
    source = source.replace(
        "Connect, Status, TimedOut",
        "APIConnectionError as Connect, APIStatusError as Status, APITimeoutError as TimedOut",
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("error: BaseException", "error: object"),
        ('    return "unknown"\n', ""),
        ("if isinstance(error, APIConnectionError)", "if isinstance(other, APIConnectionError)"),
        (
            (
                "        if error.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:\n"
                '            return "auth"\n'
                "        if error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:\n"
                '            return "provider_5xx"\n'
                "        if error.message == _EMPTY_RESPONSE_MESSAGE:\n"
                '            return "empty_response"\n'
                '        if "PROHIBITED_CONTENT" in error.message or "blocked by gemini" in error.message:\n'
                '            return "content_filter"\n'
            ),
            "",
        ),
        (
            "        if error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:",
            "        elif error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:",
        ),
        ("        if error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:", "        if ready:"),
        (
            "        if error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:",
            "        if (error := normalize(error)):",
        ),
    ],
    ids=(
        "non-exception-subject",
        "missing-fallback",
        "mixed-subjects",
        "one-refinement",
        "refinement-else",
        "unrelated-refinement",
        "subject-rebinding",
    ),
)
def test_excludes_incomplete_or_unsafe_classifier_shapes(old: str, new: str) -> None:
    assert _check(_PROVIDER_CLASSIFIER.replace(old, new)) == []


def test_excludes_intervening_refinement_side_effect() -> None:
    source = _PROVIDER_CLASSIFIER.replace(
        "        if error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:",
        "        observe(error)\n        if error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:",
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "type_name",
    ["RetryableErrors", "ProviderErrorTypes", "ResponseKinds", "make_error_type()", "Errors[0]"],
)
def test_excludes_dynamic_or_runtime_type_groups(type_name: str) -> None:
    source = _PROVIDER_CLASSIFIER.replace("APIConnectionError", type_name)
    assert _check(source) == []


def test_excludes_rebound_imported_exception() -> None:
    source = _PROVIDER_CLASSIFIER.replace(
        "def provider_error_category", "APIStatusError = load_types()\n\ndef provider_error_category"
    )
    assert _check(source) == []


def test_excludes_undefined_exception_shaped_names() -> None:
    source = _PROVIDER_CLASSIFIER.replace("asyncio.CancelledError", "FirstError")
    assert _check(source) == []


def test_excludes_function_local_exception_imports() -> None:
    source = _PROVIDER_CLASSIFIER.replace(
        "def provider_error_category(error: BaseException) -> str:",
        "def provider_error_category(error: BaseException) -> str:\n    from local_errors import APIStatusError",
    )
    assert _check(source) == []


def test_excludes_shadowed_isinstance() -> None:
    source = _PROVIDER_CLASSIFIER.replace(
        "def provider_error_category(error: BaseException) -> str:",
        "def provider_error_category(error: BaseException, isinstance) -> str:",
    )
    assert _check(source) == []


def test_does_not_report_suffix_after_duplicate_type() -> None:
    duplicate = '    if isinstance(error, asyncio.CancelledError):\n        return "again"\n'
    source = _PROVIDER_CLASSIFIER.replace(
        "    if isinstance(error, APIConnectionError):",
        f"{duplicate}    if isinstance(error, APIConnectionError):",
    )
    assert _check(source) == []


def test_accepts_multiple_refined_exception_types_once() -> None:
    second_refinement = (
        "    if isinstance(error, APIConnectionError):\n"
        "        if error.code == 1:\n"
        '            return "connection_one"\n'
        "        if error.code == 2:\n"
        '            return "connection_two"\n'
    )
    source = _PROVIDER_CLASSIFIER.replace(
        '    if isinstance(error, APIConnectionError):\n        return "connection"\n',
        second_refinement,
    )
    assert len(_check(source)) == 1


def test_excludes_mixed_refinement_predicate() -> None:
    source = _PROVIDER_CLASSIFIER.replace(
        "if error.status_code == HTTPStatus.TOO_MANY_REQUESTS:",
        "if ready and error.status_code == HTTPStatus.TOO_MANY_REQUESTS:",
    )
    assert _check(source) == []


def test_context_manager_does_not_prove_outer_branch_termination() -> None:
    source = _PROVIDER_CLASSIFIER.replace(
        '        return "cancelled"',
        "        with suppress(Exception):\n            raise CancelledError",
    )
    assert _check(source) == []


def test_excludes_wildcard_import() -> None:
    assert _check("from providers import *\n" + _PROVIDER_CLASSIFIER) == []


@pytest.mark.parametrize("minimum", ["3.8", "3.9"])
def test_excludes_projects_declaring_pre_match_python(tmp_path: Path, minimum: str) -> None:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nrequires-python = ">={minimum}"\n')
    assert _check(_PROVIDER_CLASSIFIER, str(tmp_path / "errors.py")) == []


@pytest.mark.parametrize("source", ["if:", "# Generated file; do not edit\n" + _PROVIDER_CLASSIFIER])
def test_excludes_invalid_and_generated_sources(source: str) -> None:
    assert _check(source) == []


def test_reports_two_classifiers_once_each_in_source_order() -> None:
    source = _PROVIDER_CLASSIFIER + _PROVIDER_CLASSIFIER.replace("provider_error_category", "secondary_error_category")
    diagnostics = _check(source)
    assert len(diagnostics) == 2
    assert [diagnostic.line for diagnostic in diagnostics] == sorted(diagnostic.line for diagnostic in diagnostics)


def test_rule_has_no_automatic_fix() -> None:
    assert PreferMatchExceptionDispatch.documentation is not None
    assert PreferMatchExceptionDispatch.documentation.autofix.value == "none"
