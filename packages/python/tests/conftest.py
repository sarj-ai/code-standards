from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sarj_python_lint.rule_base import Diagnostic, Rule

    _Check = Callable[[Rule, Path, str], list[Diagnostic]]

_FIRED: set[str] = set()
_CLEAN: set[str] = set()

# The file of the test currently running, in a one-slot holder so the hook can rebind it without a module-level `global`.
_CURRENT_TEST_MODULE: list[str] = [""]


def _recording(rule_id: str, examples_path: str, original: _Check) -> _Check:
    def wrapper(self: Rule, path: Path, source: str) -> list[Diagnostic]:
        result = original(self, path, source)
        if _CURRENT_TEST_MODULE[0] == examples_path:
            target = _FIRED if result else _CLEAN
            target.add(rule_id)
        return result

    return wrapper


def pytest_runtest_setup(item: pytest.Item) -> None:
    _CURRENT_TEST_MODULE[0] = item.path.as_posix()


def pytest_configure(config: pytest.Config) -> None:
    root = config.rootpath.parents[1]
    for rule_id, cls in REGISTRY.items():
        examples = (root / cls.examples_path()).as_posix()
        cls.check = _recording(rule_id, examples, cls.check)  # pyright: ignore[reportAttributeAccessIssue] — deliberate session-scoped instrumentation of a method


def _is_narrowed(config: pytest.Config) -> bool:
    keyword: object = config.option.keyword  # pyright: ignore[reportAny] — pytest's option namespace is untyped
    markexpr: object = config.option.markexpr  # pyright: ignore[reportAny] — same
    if keyword or markexpr:
        return True
    default = {"tests", str(config.rootpath / "tests")}
    return any(arg not in default for arg in config.args)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if exitstatus != 0 or _is_narrowed(session.config):
        return

    unexercised = sorted(
        f"{rule_id}: {cls.examples_path()} never makes it {'report' if rule_id not in _FIRED else 'stay quiet'}"
        for rule_id, cls in REGISTRY.items()
        if rule_id not in _FIRED or rule_id not in _CLEAN
    )
    if not unexercised:
        return

    session.exitstatus = pytest.ExitCode.TESTS_FAILED
    print(  # ruff: ignore[print] — the terminal reporter has already finished by sessionfinish
        "\nrules whose tests do not exercise them in both directions:\n  "
        + "\n  ".join(unexercised)
        + "\nEvery rule needs at least one case it flags and one it deliberately does "
        "not. A rule pinned in only one direction is either untested for recall or "
        "untested for precision."
    )
