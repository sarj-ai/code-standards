"""Every rule's tests must exercise it in BOTH directions, measured by running them.

`test_every_rule_has_an_examples_module` checks that a rule has a test module and that
the module is non-empty. That is a file-existence check wearing a behaviour check's
clothes: a module full of "deliberately not flagged" cases satisfies it while proving
only that the rule is quiet, and a module that only ever asserts findings proves only
that it fires. The TypeScript plugin shipped `ban-loose-type-guards-in-tests` in its
strict preset at "error" with no test file at all for its entire life, and a corpus read
later found 39 findings and 0 true positives. Nothing here would have caught the same
thing on the Python side.

So this is measured rather than parsed. Every registry rule's `check` is wrapped for the
session and each call is recorded as firing or clean; at the end, a rule that was never
seen doing both fails the run. It cannot be satisfied by importing the rule, by naming
it, or by any shape of prose — only by tests that actually run it over code that should
be flagged and code that should not.

Only calls made from the rule's OWN examples module count. `test_perf.py` and the CLI
tests run the whole registry over shared sources, which hands every rule both outcomes
for free — scoping to `Rule.examples_path()` is what stops the gate from being satisfied
by somebody else's test. Measured: with that scoping, two of the 71 rules
(`prefer-walrus-comprehension-filter`, `prefer-walrus-stream-loop`) had one test each and
no case they deliberately leave alone; both gained three here.

The check is skipped for a NARROWED run (`-k`, `-m`, or an explicit path), where most
rules are legitimately never invoked. `make test` and `python-ci.yml` both run the whole
suite, which is where it binds.
"""

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

# The file of the test currently running, in a one-slot holder so the hook can
# rebind it without a module-level `global`. Set from a pytest hook rather than read
# off the call stack: one list index per `check` instead of a frame walk.
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
    """Wrap each rule class's own `check`, so attribution is per rule, not per base."""
    root = config.rootpath.parents[1]
    for rule_id, cls in REGISTRY.items():
        examples = (root / cls.examples_path()).as_posix()
        cls.check = _recording(rule_id, examples, cls.check)  # pyright: ignore[reportAttributeAccessIssue] — deliberate session-scoped instrumentation of a method


def _is_narrowed(config: pytest.Config) -> bool:
    """Was the run filtered to a subset? Then most rules are legitimately never run."""
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
        f"{rule_id}: {cls.examples_path()} never makes it "
        f"{'report' if rule_id not in _FIRED else 'stay quiet'}"
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
