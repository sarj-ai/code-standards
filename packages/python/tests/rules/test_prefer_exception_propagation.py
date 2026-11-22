from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_exception_propagation import PreferExceptionPropagation


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
def test_message_only_wrappers_block(tmp_path: Path, source: str) -> None:
    path = tmp_path / "send.py"
    path.write_text(source)
    findings = analyze(["prefer-exception-propagation"], [path])
    assert [(finding.code, finding.severity, finding.fixes) for finding in findings] == [
        ("SARJ585", Severity.ERROR, ())
    ]


@pytest.mark.parametrize(
    "source",
    [
        "send()\n",
        _WRAPPER.replace("raise RuntimeError(str(error)) from error", "raise"),
        _WRAPPER.replace("raise RuntimeError(str(error)) from error", "raise error"),
        _WRAPPER.replace("RuntimeError", "TaskFailureError"),
        _WRAPPER.replace("RuntimeError(str(error))", "RuntimeError(str(error), retriable=True)"),
        _WRAPPER.replace("str(error)", "f'Provider failed: {error}'"),
        _WRAPPER.replace("str(error)", "f'{error!r}'"),
        _WRAPPER.replace("str(error)", "f'{error:>10}'"),
        _WRAPPER.replace("    raise", "    log(error)\n    raise"),
        _WRAPPER.replace("    raise", "    cleanup()\n    raise"),
        _WRAPPER.replace("    raise", "    if retriable(error):\n        retry()\n    raise"),
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
        "domain-error",
        "retry-metadata",
        "context-fstring",
        "repr",
        "format",
        "logging",
        "cleanup",
        "retry",
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


@pytest.mark.parametrize(
    "source",
    [
        _WRAPPER.replace("from error", "from None"),
        _WRAPPER.replace("str(error)", "'Provider failed'"),
        _WRAPPER + "finally:\n    cleanup()\n",
        _WRAPPER + "except OtherError:\n    recover()\n",
        "try:\n    execute()\nexcept FAILURES:\n    message = 'Operation failed'\n    raise SystemExit(message) from None\n",
        "import builtins as errors\ntry:\n    execute()\nexcept OSError:\n    raise errors.ValueError('Failed') from None\n",
        "from builtins import SystemExit as Exit\ntry:\n    execute()\nexcept OSError:\n    raise Exit('Failed')\n",
    ],
)
def test_generic_message_replacements_are_errors(tmp_path: Path, source: str) -> None:
    path = tmp_path / "send.py"
    path.write_text(source)
    findings = analyze(["prefer-exception-propagation"], [path])
    assert [(finding.code, finding.severity) for finding in findings] == [("SARJ585", Severity.ERROR)]


@pytest.mark.parametrize(
    "prefix",
    [
        "RuntimeError = First\nRuntimeError = Second\n",
        "from one import RuntimeError\nfrom two import RuntimeError\n",
    ],
)
def test_ambiguous_shadowed_error_is_not_a_builtin(tmp_path: Path, prefix: str) -> None:
    path = tmp_path / "send.py"
    path.write_text(prefix + _WRAPPER)
    assert not analyze(["prefer-exception-propagation"], [path])


@pytest.mark.parametrize(
    ("code", "expected"),
    [("SARJ585", 0), ("SARJ542", 1)],
    ids=["own-header-exception", "another-rule-does-not-suppress"],
)
def test_multiline_header_keeps_its_exact_formatter_stable_exception(code: str, expected: int) -> None:
    source = (
        "try:\n    send()\nexcept (\n    OSError\n"
        f") as error:  # sarj-noqa: {code} -- Preserve the established sanitized public rejection contract.\n"
        "    raise ValueError('Failed') from error\n"
    )
    assert len(PreferExceptionPropagation().check(Path("app.py"), source)) == expected
