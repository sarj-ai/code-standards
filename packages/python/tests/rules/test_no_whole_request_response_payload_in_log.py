from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_whole_request_response_payload_in_log import NoWholeRequestResponsePayloadInLog


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return NoWholeRequestResponsePayloadInLog().check(Path("service.py"), source)


_PUBLIC_EXAMPLES = NoWholeRequestResponsePayloadInLog.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(item.example_id for item in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoWholeRequestResponsePayloadInLog().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        "logger.info('order', response_payload=payload)",
        "logger.info('request', request_body=data)",
        "logger.info('order', response_payload=response_payload.model_dump())",
        "logger.info('order', response_body=response.json())",
        "logger.info('order', response_body=exc.response.json())",
        "logger.info('order', response_body=await request.json())",
        "logger.info('order', response_body=response.content)",
        "logger.info(f'Request failed: {request_json}')",
        "logger.info(f'Response failed: {response_body}')",
        "logger.info('Response failed: %s' % response_body)",
        "logger.info('Response failed: {}'.format(response_body))",
        "logger.info('Response failed: ' + response_body)",
        "logger.info('order', extra={'response_body': body})",
        "logger.info('order', truncated_response_payload=truncated_response_payload)",
        "logger.info('order', not_sanitized_response_body=body)",
        "logger.info(response_body)",
    ],
)
def test_warns_on_whole_request_response_payloads(source: str) -> None:
    [diagnostic] = _check(source)
    assert diagnostic.code == "SARJ436"
    assert diagnostic.severity is Severity.WARNING


@pytest.mark.parametrize(
    "source",
    [
        "logger.info(f'Input file: {input_json}')",
        "logger.info('health', response=response)",
        "logger.info('health', response=truncated_response)",
        "logger.info('health', payload_summary=summarize(payload))",
        "logger.info('health', response_body=sanitize(response))",
        "logger.info('health', response_body=response.model_dump(exclude={'token'}))",
        "logger.info('health', request_id=request.id)",
        "logger.info('health', response_status=response.status_code)",
        "logger.info('health', success=response_json.get('success'))",
        "logger.info('module', json)",
        "logger.info('email', body=email.body)",
        "logger.info(f'Document: {document.body}')",
        "logger.info('event', payload=event.payload)",
        "logger.info('schema', schema_json=schema_json)",
        "logger.info('config', config_json=config_json)",
    ],
)
def test_allows_non_payload_objects_and_derived_metadata(source: str) -> None:
    assert _check(source) == []


def test_non_logger_receiver_and_malformed_source_are_ignored() -> None:
    assert _check("client.info('order', payload=payload)") == []
    assert _check("logger.info(") == []


def test_secret_named_payload_is_owned_by_secret_rule() -> None:
    assert _check("logger.info(f'{secret_response_body}')") == []
