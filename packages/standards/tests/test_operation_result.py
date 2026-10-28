from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sarj_standards import api


@pytest.mark.parametrize(
    ("status", "exit_code"),
    [
        (api.Status.OK, 0),
        (api.Status.CHANGED, 0),
        (api.Status.DRIFT, 1),
        (api.Status.INVALID, 2),
        (api.Status.FAILED, 1),
        (api.Status.FAILED, 2),
        (api.Status.FAILED, -9),
        (api.Status.INTERRUPTED, 130),
    ],
)
def test_result_preserves_valid_operation_specific_outcomes(status: api.Status, exit_code: int) -> None:
    result = api.Result(status, exit_code=exit_code)

    assert result.status is status
    assert result.exit_code == exit_code
    assert result.ok is (exit_code == 0)


@pytest.mark.parametrize("status", [api.Status.DRIFT, api.Status.INVALID, api.Status.FAILED, api.Status.INTERRUPTED])
def test_unsuccessful_result_cannot_inherit_successful_default(status: api.Status) -> None:
    with pytest.raises(ValueError, match="status and exit code must agree"):
        api.Result(status)


@pytest.mark.parametrize("status", [api.Status.OK, api.Status.CHANGED])
@pytest.mark.parametrize("exit_code", [1, 2, 130, -9])
def test_successful_result_cannot_have_unsuccessful_exit_code(status: api.Status, exit_code: int) -> None:
    with pytest.raises(ValueError, match="status and exit code must agree"):
        api.Result(status, exit_code=exit_code)


@pytest.mark.parametrize("exit_code", [False, True])
def test_boolean_exit_code_is_not_an_operation_outcome(exit_code: bool) -> None:
    with pytest.raises(TypeError, match="exit code must be an integer"):
        api.Result(api.Status.OK, exit_code=exit_code)


def test_result_replacement_cannot_erase_the_status_domain() -> None:
    result = api.Result(api.Status.OK)

    with pytest.raises(TypeError, match="status must be a Status"):
        replace(result, status="ok")


@pytest.mark.parametrize("exit_code", [0.0, "0", None])
def test_result_replacement_cannot_erase_the_exit_code_domain(exit_code: float | str | None) -> None:
    result = api.Result(api.Status.OK)

    with pytest.raises(TypeError, match="exit code must be an integer"):
        replace(result, exit_code=exit_code)


def test_result_retains_public_positional_payload_contract() -> None:
    findings = (api.Finding("operation.failed", "error", "operation failed"),)
    changes = (api.Change("write", "planned change", Path("config.toml")),)

    result = api.Result(api.Status.FAILED, findings, changes, 2)

    assert result.findings is findings
    assert result.changes is changes
    assert not result.ok
