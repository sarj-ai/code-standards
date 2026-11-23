from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_swallowed_exception import NoSwallowedException


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint.rule_base import Diagnostic


_HEADER = "import logging\n\nimport httpx\nfrom loguru import logger as loguru_logger\n\nlogger = logging.getLogger(__name__)\n\n"
_CLEANUP = (
    _HEADER
    + "def delete(path: str) -> None:\n"
    + "    try:\n"
    + "        remove(path)\n"
    + "    except (httpx.HTTPError, OSError) as error:\n"
    + "        logger.debug('cleanup unavailable', extra={'error_type': type(error).__name__})\n"
)


def _findings(tmp_path: Path, source: str, name: str = "cleanup.py") -> list[Diagnostic]:
    path = tmp_path / "app" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return analyze(["no-swallowed-exception"], [path])


def test_documented_examples() -> None:
    verify_native_rule(NoSwallowedException, analyze)


@pytest.mark.parametrize(
    "source",
    [
        _CLEANUP,
        _CLEANUP.replace("logger.debug", "loguru_logger.debug"),
        _CLEANUP.replace("logger.debug", "loguru_logger.bind(path=path).trace"),
        _CLEANUP.replace("logger.debug", "logging.debug"),
        _CLEANUP.replace("logger.debug", "self._log.debug").replace("def delete(path", "def delete(self, path"),
        _CLEANUP.replace("logger.debug", "logging.getLogger(__name__).debug"),
        _CLEANUP + "        return\n",
        _CLEANUP + "        return None\n",
        _CLEANUP + "        pass\n",
        _CLEANUP.replace("(httpx.HTTPError, OSError)", "OSError"),
        _CLEANUP.replace("(httpx.HTTPError, OSError)", "httpx.HTTPError"),
        _CLEANUP.replace(
            "def delete(path: str) -> None:\n", "def delete(paths: list[str]) -> None:\n    for path in paths:\n"
        )
        .replace("\n    try:", "\n        try:")
        .replace("\n        remove(path)", "\n            remove(path)")
        .replace("\n    except", "\n        except")
        .replace("\n        logger.debug", "\n            logger.debug")
        + "            continue\n",
        _CLEANUP.replace("def delete", "async def delete").replace("remove(path)", "await remove(path)"),
        _CLEANUP.replace("    try:", "    try:  # noqa: SARJ999 unrelated"),
    ],
    ids=[
        "stdlib-logger",
        "loguru",
        "loguru-bound-trace",
        "logging-module",
        "instance-logger",
        "logger-factory",
        "bare-return",
        "return-none",
        "pass",
        "builtin-type",
        "imported-attribute",
        "loop-continue",
        "async",
        "unrelated-comment",
    ],
)
def test_debug_only_handlers_warn(tmp_path: Path, source: str) -> None:
    assert [(finding.code, finding.severity) for finding in _findings(tmp_path, source)] == [
        ("SARJ597", Severity.WARNING)
    ]


@pytest.mark.parametrize(
    "source",
    [
        _CLEANUP.replace("logger.debug", "logger.warning"),
        _CLEANUP.replace("logger.debug", "logger.info"),
        _CLEANUP.replace("logger.debug", "logger.exception"),
        _CLEANUP.replace("})\n", "}, exc_info=True)\n"),
        _CLEANUP.replace("})\n", "}, exc_info=error)\n"),
        _CLEANUP.replace("logger.debug", "loguru_logger.opt(exception=error).debug"),
        _CLEANUP.replace("})\n", "}, **fields)\n"),
        _CLEANUP + "        raise\n",
        _CLEANUP + "        raise CleanupError(path) from error\n",
        _CLEANUP + "        return False\n",
        _CLEANUP.replace("-> None", "-> bool | None") + "        return None\n",
        _CLEANUP.replace(" -> None", "") + "        return\n",
        _CLEANUP + "        failures.append(error)\n",
        _CLEANUP + "        metrics.increment('cleanup_failed')\n",
        _CLEANUP.replace("        logger.debug", "        if retriable(error):\n            logger.debug").replace(
            "})\n", "})\n        raise\n"
        ),
        _CLEANUP.replace("logger.debug(", "audit.debug("),
        _CLEANUP.replace(
            "        logger.debug('cleanup unavailable', extra={'error_type': type(error).__name__})\n",
            "        pass\n",
        ),
        _CLEANUP.replace("(httpx.HTTPError, OSError) as error", "Exception as error"),
        _CLEANUP.replace("(httpx.HTTPError, OSError) as error", "(OSError, Exception) as error"),
        _CLEANUP.replace("(httpx.HTTPError, OSError) as error", "BaseException as error"),
        _CLEANUP.replace(" as error:", ":").replace("(httpx.HTTPError, OSError)", "").replace("except :", "except:"),
        _CLEANUP.replace("(httpx.HTTPError, OSError)", "ImportError"),
        _CLEANUP.replace("(httpx.HTTPError, OSError)", "(OSError, KeyError)"),
        _CLEANUP.replace("(httpx.HTTPError, OSError)", "FileNotFoundError"),
        _CLEANUP.replace("(httpx.HTTPError, OSError)", "asyncio.CancelledError").replace(
            "import logging\n", "import asyncio\nimport logging\n"
        ),
        _CLEANUP.replace("(httpx.HTTPError, OSError)", "_GoneError").replace(
            "def delete", "class _GoneError(Exception):\n    pass\n\n\ndef delete"
        ),
        _CLEANUP.replace("(httpx.HTTPError, OSError)", "CLEANUP_ERRORS").replace(
            "def delete", "CLEANUP_ERRORS = (OSError,)\n\n\ndef delete"
        ),
        _CLEANUP.replace("(httpx.HTTPError, OSError)", "Unknown"),
        _CLEANUP.replace("(httpx.HTTPError, OSError)", "errors[0]"),
        _CLEANUP.replace(" as error:", " as error:  # sarj-noqa: SARJ597 -- teardown has no reader"),
        "from unknown import *\n" + _CLEANUP,
        _CLEANUP.replace("logger = ", "OSError = KeyError\nlogger = ").replace("httpx.HTTPError, ", ""),
    ],
    ids=[
        "warning",
        "info",
        "exception",
        "exc-info-true",
        "exc-info-object",
        "loguru-opt-exception",
        "splatted-fields",
        "reraise",
        "translated",
        "observable-false",
        "optional-return",
        "unannotated-return",
        "collected",
        "metric",
        "compound",
        "non-logger-receiver",
        "pass-only",
        "broad-exception",
        "broad-in-tuple",
        "base-exception",
        "bare",
        "import-probe",
        "expected-lookup",
        "file-not-found",
        "cancelled",
        "module-local-class",
        "tuple-alias",
        "unresolved-name",
        "dynamic-expression",
        "suppressed",
        "wildcard-import",
        "shadowed-builtin",
    ],
)
def test_visible_or_deliberate_handlers_pass(tmp_path: Path, source: str) -> None:
    assert _findings(tmp_path, source) == []


@pytest.mark.parametrize("name", ["test_cleanup.py", "conftest.py"])
def test_tests_are_excluded(tmp_path: Path, name: str) -> None:
    assert _findings(tmp_path, _CLEANUP, name) == []


def test_generated_sources_abstain(tmp_path: Path) -> None:
    assert _findings(tmp_path, "# Code generated by tool. DO NOT EDIT.\n" + _CLEANUP) == []
