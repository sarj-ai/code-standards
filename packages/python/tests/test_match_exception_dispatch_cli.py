from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import main


if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture


_CLASSIFIER = """
from providers import ConnectionError, StatusError, TimeoutError

def category(error: BaseException):
    if isinstance(error, TimeoutError):{suppression}
        return "timeout"
    if isinstance(error, StatusError):
        if error.status == 429:
            return "rate_limit"
        if error.status >= 500:
            return "provider_5xx"
    if isinstance(error, ConnectionError):
        return "connection"
    return "unknown"
"""


@pytest.mark.parametrize(
    ("source", "expected_count"),
    [
        (_CLASSIFIER.format(suppression=""), 1),
        (
            _CLASSIFIER.format(suppression="  # sarj-noqa: SARJ453 — preserve custom instance checks"),
            0,
        ),
        (_CLASSIFIER.format(suppression="  # sarj-noqa: SARJ080 — unrelated suppression"), 1),
        ("# @generated\n" + _CLASSIFIER.format(suppression=""), 0),
        ("if value ==\n", 0),
    ],
    ids=("one-warning", "exact-suppression", "other-suppression", "generated", "malformed"),
)
def test_match_exception_dispatch_cli_is_advisory(
    tmp_path: Path,
    capsys: CaptureFixture[str],
    source: str,
    expected_count: int,
) -> None:
    path = tmp_path / "errors.py"
    path.write_text(source)

    result = main(["check", "--rule", "prefer-match-exception-dispatch", str(path)])

    assert result == 0
    output = capsys.readouterr()
    assert not output.err
    assert output.out.count("SARJ453 warning:") == expected_count
