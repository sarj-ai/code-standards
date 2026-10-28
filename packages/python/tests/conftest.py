from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import pytest
from sarj_rule_contracts import RuleId

from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sarj_python_lint.rule_base import Diagnostic, Rule

    _Check = Callable[[Rule, Path, str], list[Diagnostic]]

_FIRED: set[str] = set()
_CLEAN: set[str] = set()
_WORKER_ERRORS: set[str] = set()

# The file of the test currently running, in a one-slot holder so the hook can rebind it without a module-level `global`.
_CURRENT_TEST_MODULE: list[str] = [""]


@runtime_checkable
class _WorkerOutput(Protocol):
    workeroutput: dict[  # sarj-noqa: SARJ528 -- pytest-xdist exposes an open Python metadata dictionary shared with other plugins.
        str, object
    ]


@runtime_checkable
class _TemporaryConfig(Protocol):
    _tmp_path_factory: pytest.TempPathFactory


def _worker_output(
    value: object,
) -> (
    dict[  # sarj-noqa: SARJ528 -- the runtime Protocol probes incoming worker metadata; consumers refine its values.
        str, object
    ]
    | None
):
    return value.workeroutput if isinstance(value, _WorkerOutput) else None


def _temporary_root(value: pytest.Config | _TemporaryConfig) -> Path | None:
    if isinstance(value, _TemporaryConfig):
        factory = value._tmp_path_factory  # ruff: ignore[private-member-access] # pyright: ignore[reportPrivateUsage] -- pytest plugin factory.
        return factory.getbasetemp()
    return None


def _recording(rule_id: RuleId, examples_path: str, original: _Check) -> _Check:
    def wrapper(self: Rule, path: Path, source: str) -> list[Diagnostic]:
        result = original(self, path, source)
        if _CURRENT_TEST_MODULE[0] == examples_path:
            target = _FIRED if result else _CLEAN
            target.add(rule_id)
        return result

    return wrapper


def pytest_runtest_setup(item: pytest.Item) -> None:
    _CURRENT_TEST_MODULE[0] = item.path.as_posix()


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    # Pytest exposes its own configured factory to plugins at configure time.
    temporary = _temporary_root(config)
    if temporary is not None:
        for ancestor in (temporary, *temporary.parents):
            if (ancestor / ".git").exists():
                msg = (
                    f"Python rule tests need a temporary directory outside Git; found {ancestor / '.git'}. "
                    "Set TMPDIR or --basetemp to a private non-Git path."
                )
                raise pytest.UsageError(msg)
    root = config.rootpath.parents[1]
    for rule_id, cls in REGISTRY.items():
        examples = (root / cls.examples_path()).as_posix()
        cls.check = _recording(RuleId(rule_id), examples, cls.check)  # pyright: ignore[reportAttributeAccessIssue] — deliberate session-scoped instrumentation of a method


def _is_narrowed(config: pytest.Config) -> bool:
    keyword: object = config.option.keyword  # pyright: ignore[reportAny] — pytest's option namespace is untyped
    markexpr: object = config.option.markexpr  # pyright: ignore[reportAny] — pytest's option namespace is untyped
    if keyword or markexpr:
        return True
    default = {"tests", str(config.rootpath / "tests")}
    return any(arg not in default for arg in config.args)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: object) -> None:
    output = _worker_output(node)
    if output is not None:
        fired = output.get("sarj_python_fired")
        clean = output.get("sarj_python_clean")
        if isinstance(fired, str) and isinstance(clean, str):
            _FIRED.update(fired.splitlines())
            _CLEAN.update(clean.splitlines())
            return
    _WORKER_ERRORS.add("Missing or invalid rule coverage report from a pytest worker.")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    output = _worker_output(session.config)
    if output is not None:
        output["sarj_python_fired"] = "\n".join(sorted(_FIRED))
        output["sarj_python_clean"] = "\n".join(sorted(_CLEAN))
        return
    collecting: object = session.config.option.collectonly  # pyright: ignore[reportAny] — pytest's option namespace is untyped
    if exitstatus != 0 or collecting or _is_narrowed(session.config):
        return

    if _WORKER_ERRORS:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        print("\n" + "\n".join(sorted(_WORKER_ERRORS)))  # ruff: ignore[print] — report a failed worker coverage transport after tests finish

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
