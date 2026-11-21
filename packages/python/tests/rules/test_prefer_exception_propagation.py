from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_exception_propagation import PreferExceptionPropagation


if TYPE_CHECKING:
    from pathlib import Path


_WRAPPER = "try:\n    send()\nexcept Exception as error:\n    raise RuntimeError(str(error)) from error\n"


def test_documented_examples() -> None:
    verify_native_rule(PreferExceptionPropagation, analyze)


@pytest.mark.parametrize(
    "source",
    [
        _WRAPPER,
        _WRAPPER.replace(" from error", ""),
        _WRAPPER.replace("RuntimeError", "ValueError"),
        _WRAPPER.replace("str(error)", "f'{error}'"),
        _WRAPPER.replace("str(error)", "f'{error!s}'"),
        _WRAPPER.replace("    raise", "    message = str(error)\n    raise").replace(
            "RuntimeError(str(error))", "RuntimeError(message)"
        ),
        "async def send_once():\n"
        + "\n".join("    " + line for line in _WRAPPER.replace("    send()", "    await send()").splitlines())
        + "\n",
    ],
    ids=["chained", "implicit-chain", "value-error", "fstring", "str-conversion", "message-local", "async"],
)
def test_message_only_wrappers_warn(tmp_path: Path, source: str) -> None:
    path = tmp_path / "send.py"
    path.write_text(source)
    findings = analyze(["prefer-exception-propagation"], [path])
    assert [(finding.code, finding.severity, finding.fixes) for finding in findings] == [
        ("SARJ585", Severity.WARNING, ())
    ]


@pytest.mark.parametrize(
    "source",
    [
        "send()\n",
        _WRAPPER.replace("raise RuntimeError(str(error)) from error", "raise"),
        _WRAPPER.replace("raise RuntimeError(str(error)) from error", "raise error"),
        _WRAPPER.replace("from error", "from None"),
        _WRAPPER.replace("RuntimeError", "TaskFailureError"),
        _WRAPPER.replace("RuntimeError(str(error))", "RuntimeError(str(error), retriable=True)"),
        _WRAPPER.replace("str(error)", "'Provider failed'"),
        _WRAPPER.replace("str(error)", "f'Provider failed: {error}'"),
        _WRAPPER.replace("str(error)", "f'{error!r}'"),
        _WRAPPER.replace("str(error)", "f'{error:>10}'"),
        _WRAPPER.replace("    raise", "    log(error)\n    raise"),
        _WRAPPER.replace("    raise", "    cleanup()\n    raise"),
        _WRAPPER.replace("    raise", "    if retriable(error):\n        retry()\n    raise"),
        _WRAPPER + "finally:\n    cleanup()\n",
        _WRAPPER + "except OtherError:\n    recover()\n",
        _WRAPPER.replace("str(error)", "message_for(error)"),
        _WRAPPER.replace("from error", "from other"),
        "RuntimeError = DomainError\n" + _WRAPPER,
        "str = format_error\n" + _WRAPPER,
        "from unknown import *\n" + _WRAPPER,
    ],
    ids=[
        "propagated",
        "bare-raise",
        "named-raise",
        "privacy",
        "domain-error",
        "retry-metadata",
        "new-context",
        "context-fstring",
        "repr",
        "format",
        "logging",
        "cleanup",
        "retry",
        "finally",
        "multiple-handlers",
        "computed-message",
        "other-cause",
        "shadowed-error",
        "shadowed-str",
        "wildcard",
    ],
)
def test_preserves_error_contracts(tmp_path: Path, source: str) -> None:
    path = tmp_path / "send.py"
    path.write_text(source)
    assert not analyze(["prefer-exception-propagation"], [path])


def test_exact_code_suppression(tmp_path: Path) -> None:
    path = tmp_path / "send.py"
    path.write_text(
        _WRAPPER.replace(
            "except Exception as error:",
            "except Exception as error:  # sarj-noqa: SARJ585 -- documented public exception contract",
        )
    )
    assert not analyze(["prefer-exception-propagation"], [path])


def test_malformed_source_preserves_engine_parse_failure(tmp_path: Path) -> None:
    path = tmp_path / "broken.py"
    path.write_text("def broken(:\n")
    assert PreferExceptionPropagation().check_context(PythonFileContext(path, path.read_text())) == []
    with pytest.raises(ValueError, match="could not be parsed"):
        analyze(["prefer-exception-propagation"], [path])
