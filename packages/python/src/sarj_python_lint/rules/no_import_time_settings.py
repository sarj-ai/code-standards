"""SARJ035: module-level `x = SomeSettings()` — settings must not load at import time.

A settings object constructed at module scope reads the environment the moment
the module is imported. That import-time side effect poisons everything
downstream: tests cannot patch the environment before the singleton exists
(one real conftest carries 31 `E402` noqas purely to sequence `os.environ`
writes before the settings import), a missing env var crashes *import* instead
of startup, and import order becomes load-bearing. The fix is a cached factory,
so the read happens at first call — after test setup, inside the app lifespan:

    # flagged
    settings = Settings()

    # preferred
    @lru_cache
    def get_settings() -> Settings:
        return Settings()

Fires only on the exact shape: a module-level assignment (`=` or annotated `=`)
whose value is a direct call to a callee whose name ends with `Settings`
(case-sensitive: `Settings()`, `AppSettings()`, `config.VoiceSettings()`).
Module level includes module-scope `try:`/`with:`/`for:`/`match:`/plain-`if:`
blocks, but NOT:

* function or class bodies (deferred construction is exactly the fix),
* the body of `if __name__ == "__main__":` (script entry, not import time) —
  the guard must literally use `==`; a `!=` body runs on import and IS checked,
* the body of `if TYPE_CHECKING:` (never executes).

The `else:` branch of either guard DOES run at import time and is checked.

Two scoping decisions, both settled by corpus validation:

* Designated settings modules (`config.py` / `settings.py`) are deliberately
  NOT exempt: the motivating incidents were module singletons in `config.py`
  files — exempting them would exempt every real occurrence of the bug.
* Test files ARE exempt: the hazard this rule targets is a prod config module
  poisoning import order for its importers (most painfully, tests). A
  module-level constant in a test file poisons nothing — and in practice the
  test corpus is where `*Settings`-named plain pydantic *models* (TTS provider
  configs, kwarg-constructed fixtures) live, which were the rule's only
  false-positive class.

Suppress a deliberate import-time singleton with
`# sarj-noqa: SARJ035 — <reason>`.

References:
- https://fastapi.tiangolo.com/advanced/settings/#creating-the-settings-only-once-with-lru_cache

"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_SETTINGS_SUFFIX = "Settings"


class NoImportTimeSettings(Rule):
    """Module-level `x = SomeSettings()` — construct settings in a cached factory."""

    id: str = "no-import-time-settings"
    code: str = "SARJ035"
    description: str = (
        "module-level Settings() construction reads the environment at import "
        "time — use a cached factory (lru_cache get_settings) instead."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for stmt in _module_level_statements(tree.body):
            call = _settings_construction(stmt)
            if call is None:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=stmt.lineno,
                    col=stmt.col_offset + 1,
                    code=self.code,
                    message=(
                        f"module-level `{_callee_name(call)}()` runs at import time — "
                        "construct settings in an `@lru_cache` factory instead."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _module_level_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Yield statements that execute at import time.

    Recurses through module-scope `if`/`try`/`with`/`for`/`match` blocks but
    never into function/class bodies or the bodies of `if __name__ ==
    "__main__":` / `if TYPE_CHECKING:`. The `else:` of either guard runs at
    import time, so it is always recursed.

    Yields:
        Each statement that runs when the module is imported.

    """
    for stmt in body:
        yield stmt
        match stmt:
            case ast.If():
                if not _is_main_or_type_checking_guard(stmt.test):
                    yield from _module_level_statements(stmt.body)
                yield from _module_level_statements(stmt.orelse)
            case ast.Try():
                yield from _module_level_statements(stmt.body)
                for handler in stmt.handlers:
                    yield from _module_level_statements(handler.body)
                yield from _module_level_statements(stmt.orelse)
                yield from _module_level_statements(stmt.finalbody)
            case ast.With() | ast.AsyncWith():
                yield from _module_level_statements(stmt.body)
            case ast.For() | ast.AsyncFor() | ast.While():
                yield from _module_level_statements(stmt.body)
                yield from _module_level_statements(stmt.orelse)
            case ast.Match():
                for case_ in stmt.cases:
                    yield from _module_level_statements(case_.body)
            case _:
                pass


def _is_main_or_type_checking_guard(test: ast.expr) -> bool:
    match test:
        case ast.Compare(
            left=ast.Name(id="__name__"),
            ops=[ast.Eq()],
            comparators=[ast.Constant(value="__main__")],
        ):
            return True
        case ast.Name(id="TYPE_CHECKING"):
            return True
        case ast.Attribute(attr="TYPE_CHECKING"):
            return True
        case _:
            return False


def _settings_construction(stmt: ast.stmt) -> ast.Call | None:
    """Parse `stmt` as `x = SomeSettings(...)` / `x: T = SomeSettings(...)`.

    Returns:
        The constructor call, or None when `stmt` is not a settings assignment.

    """
    match stmt:
        case ast.Assign(value=ast.Call() as call) | ast.AnnAssign(value=ast.Call() as call):
            pass
        case _:
            return None
    if _callee_name(call).endswith(_SETTINGS_SUFFIX):
        return call
    return None


def _callee_name(call: ast.Call) -> str:
    match call.func:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=name):
            return name
        case _:
            return ""
