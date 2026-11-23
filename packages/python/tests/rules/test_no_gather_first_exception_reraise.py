from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_gather_first_exception_reraise import NoGatherFirstExceptionReraise


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint.rule_base import Diagnostic


_GATHER = (
    "import asyncio\n\n\n"
    "async def delete_all(paths: list[str]) -> None:\n"
    "    results = await asyncio.gather(*(delete(path) for path in paths), return_exceptions=True)\n"
)
_LOOP = (
    _GATHER + "    for result in results:\n        if isinstance(result, BaseException):\n            raise result\n"
)
_UNPACKED = (
    "import asyncio\n\n\n"
    "async def load() -> tuple[object, object]:\n"
    "    config, quota = await asyncio.gather(fetch_config(), fetch_quota(), return_exceptions=True)\n"
    "    if isinstance(config, BaseException):\n        raise config\n"
    "    if isinstance(quota, BaseException):\n        raise quota\n"
    "    return config, quota\n"
)


def _findings(tmp_path: Path, source: str, name: str = "cleanup.py") -> list[Diagnostic]:
    path = tmp_path / "app" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return analyze(["no-gather-first-exception-reraise"], [path])


def test_documented_examples() -> None:
    verify_native_rule(NoGatherFirstExceptionReraise, analyze)


@pytest.mark.parametrize(
    "source",
    [
        _LOOP,
        _LOOP.replace("BaseException)", "Exception)"),
        _LOOP.replace("BaseException)", "(ValueError, Exception))"),
        _LOOP.replace("BaseException)", "ValueError | BaseException)"),
        _LOOP.replace("raise result\n", "raise result from None\n"),
        _LOOP.replace("raise result\n", "logger.error('cleanup failed')\n            raise result\n"),
        _LOOP.replace("for result in results:", "for path, result in zip(paths, results, strict=True):"),
        _LOOP.replace("for result in results:", "for index, result in enumerate(results):"),
        _LOOP.replace("    results = await", "    results: list[object] = await"),
        _LOOP.replace("asyncio.gather", "gather").replace("import asyncio\n", "from asyncio import gather\n"),
        _GATHER.replace("    results", "    try:\n        work()\n    finally:\n        results").replace(
            "return_exceptions=True)\n", "return_exceptions=True)\n"
        )
        + "        for result in results:\n            if isinstance(result, BaseException):\n                raise result\n",
    ],
    ids=[
        "base-exception",
        "exception",
        "tuple-classes",
        "union-classes",
        "raise-from",
        "logged-first",
        "zip",
        "enumerate",
        "annotated",
        "imported-gather",
        "nested-suite",
    ],
)
def test_first_failure_reraise_warns(tmp_path: Path, source: str) -> None:
    assert [(finding.code, finding.severity) for finding in _findings(tmp_path, source)] == [
        ("SARJ598", Severity.WARNING)
    ]


def test_unpacked_sequence_reports_once_at_first_raise(tmp_path: Path) -> None:
    assert [(finding.code, finding.line, finding.severity) for finding in _findings(tmp_path, _UNPACKED)] == [
        ("SARJ598", 7, Severity.WARNING)
    ]


@pytest.mark.parametrize(
    "source",
    [
        _GATHER
        + "    failures = [result for result in results if isinstance(result, Exception)]\n"
        + "    if failures:\n        raise ExceptionGroup('cleanup failed', failures)\n",
        _GATHER
        + "    for result in results:\n        if isinstance(result, BaseException):\n"
        + "            failures.append(result)\n",
        _GATHER
        + "    for path, result in zip(paths, results, strict=True):\n"
        + "        if isinstance(result, BaseException):\n            logger.warning('skip', path=path)\n"
        + "        else:\n            done.append(result)\n",
        _LOOP.replace("BaseException)", "ValueError)"),
        _LOOP.replace("BaseException)", "asyncio.CancelledError)"),
        _LOOP.replace("raise result\n", "raise CleanupError(path) from result\n"),
        _LOOP.replace("return_exceptions=True", "return_exceptions=False"),
        _LOOP.replace(", return_exceptions=True", ""),
        _LOOP.replace("return_exceptions=True", "return_exceptions=collect"),
        _LOOP.replace("asyncio.gather", "gather"),
        _LOOP.replace("for result in results:", "for result in other:"),
        _LOOP.replace("raise result\n", "raise other\n"),
        _LOOP.replace("    for result", "    results = []\n    for result").replace(
            "    results = await", "    settled = await"
        ),
        "isinstance = check\n" + _LOOP,
        "BaseException = Marker\n" + _LOOP,
        _UNPACKED.replace("    if isinstance(quota, BaseException):\n        raise quota\n", ""),
        _UNPACKED.replace("raise config\n", "raise ExceptionGroup('load failed', [config])\n"),
        _GATHER.replace("results = await", "(result,) = await")
        + "    if isinstance(result, BaseException):\n        raise result\n",
        _LOOP.replace("raise result\n", "raise result  # sarj-noqa: SARJ598 -- single operation\n"),
    ],
    ids=[
        "exception-group",
        "collected",
        "handled-individually",
        "specific-type",
        "cancellation-only",
        "translated-with-cause",
        "return-exceptions-false",
        "default-return-exceptions",
        "dynamic-return-exceptions",
        "unresolved-gather",
        "other-iterable",
        "other-raise",
        "rebound-results",
        "shadowed-isinstance",
        "shadowed-base-exception",
        "single-unpacked-check",
        "unpacked-exception-group",
        "single-result",
        "suppressed",
    ],
)
def test_complete_or_individual_handling_passes(tmp_path: Path, source: str) -> None:
    assert _findings(tmp_path, source) == []


@pytest.mark.parametrize("name", ["test_cleanup.py", "conftest.py"])
def test_tests_are_excluded(tmp_path: Path, name: str) -> None:
    assert _findings(tmp_path, _LOOP, name) == []


def test_generated_sources_abstain(tmp_path: Path) -> None:
    assert _findings(tmp_path, "# Code generated by tool. DO NOT EDIT.\n" + _LOOP) == []
