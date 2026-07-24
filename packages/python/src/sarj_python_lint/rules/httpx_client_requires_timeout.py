"""SARJ033: `httpx` client construction / convenience call without an explicit `timeout=`.

Every outbound HTTP call needs a deliberate deadline. httpx does ship an
implicit 5-second default, but review feedback treats relying on it as a bug:
the right budget for a CRM sync, an OAuth token exchange, or an LLM call is
never coincidentally "whatever the library defaults to", and an implicit
default is invisible at the call site, so nobody re-examines it when the
downstream SLA changes. (~10 production sites in the CRM/OAuth integrations
were retrofitted with explicit timeouts after incidents.)

Flags, without a `timeout=` kwarg:

* `httpx.Client(...)` / `httpx.AsyncClient(...)`,
* module-level convenience calls
  `httpx.get/post/put/patch/delete/head/options/request/stream(...)` (each
  builds a throwaway client).

The receiver/callee is resolved through the module's import bindings, so
aliased forms are caught too: `import httpx as hx` + `hx.AsyncClient(...)`,
and `from httpx import AsyncClient [as AC]` + `AsyncClient(...)`. A bare name
that was NOT imported from httpx (e.g. `from requests import get`) is never
flagged.

Never flags — each of these means the deadline decision is made elsewhere or
does not matter:

* a `**kwargs` spread in the call (the timeout may arrive through it),
* a `transport=` kwarg (a custom transport may own deadline behavior),
* a `mounts=` kwarg (per-mount transports, same reasoning),
* an explicit `timeout=None` / `timeout=...` of any shape (visible, deliberate,
  and reviewable — the rule only demands that the decision be written down),
* test files (`test_*.py`, `*_test.py`, `conftest.py`, anything under
  `tests`/`test` directories) — tests talk to local mocks where hangs surface
  immediately as test timeouts.

Suppress a deliberate default-timeout client with
`# sarj-noqa: SARJ033 — <reason>`.

References:
- https://www.python-httpx.org/advanced/timeouts/

"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_CLIENT_CLASSES = frozenset({"Client", "AsyncClient"})
_CONVENIENCE_FUNCS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "request", "stream"})
_FLAGGABLE = _CLIENT_CLASSES | _CONVENIENCE_FUNCS
_EXEMPTING_KWARGS = frozenset({"timeout", "transport", "mounts"})


class HttpxClientRequiresTimeout(Rule):
    """`httpx.(Async)Client(...)` / `httpx.get(...)` without an explicit `timeout=`."""

    id: str = "httpx-client-requires-timeout"
    code: str = "SARJ033"
    description: str = (
        "httpx client or convenience call without an explicit timeout= — the "
        "deadline budget must be written down at the call site."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        module_aliases, name_bindings = _httpx_bindings(tree)
        diags: list[Diagnostic] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = _httpx_callee(node.func, module_aliases, name_bindings)
            if callee is None or _has_exempting_kwarg(node):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"`httpx.{callee}(...)` without an explicit `timeout=` — "
                        "write the deadline budget down at the call site."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _httpx_bindings(tree: ast.Module) -> tuple[frozenset[str], dict[str, str]]:
    """Resolve the module's httpx import bindings.

    Returns:
        A pair of (names bound to the httpx module itself — `import httpx [as
        hx]`, mapping of local name -> original httpx name for `from httpx
        import Name [as Alias]`).

    """
    # The literal name `httpx` always counts as the module, even without a
    # visible import (e.g. a snippet or a re-exported module attribute).
    module_aliases: set[str] = {"httpx"}
    name_bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "httpx":
                    module_aliases.add(alias.asname or "httpx")
        elif isinstance(node, ast.ImportFrom) and node.module == "httpx" and node.level == 0:
            for alias in node.names:
                if alias.name in _FLAGGABLE:
                    name_bindings[alias.asname or alias.name] = alias.name
    return frozenset(module_aliases), name_bindings


def _httpx_callee(func: ast.expr, module_aliases: frozenset[str], name_bindings: dict[str, str]) -> str | None:
    """Return the flaggable httpx callee's original name, else None.

    An httpx-module receiver (`httpx.get`, `hx.AsyncClient`) or a bare name
    imported from httpx (`from httpx import AsyncClient`) counts. Attribute
    calls on anything else — most importantly `client.get(...)` on an
    already-constructed client, which inherits the client's timeout — do not.

    Returns:
        The original httpx attribute name when `func` is flaggable, else None.

    """
    match func:
        case ast.Attribute(value=ast.Name(id=recv), attr=attr) if recv in module_aliases and attr in _FLAGGABLE:
            return attr
        case ast.Name(id=name) if name in name_bindings:
            return name_bindings[name]
        case _:
            return None


def _has_exempting_kwarg(node: ast.Call) -> bool:
    """Report whether the call carries `timeout=`/`transport=`/`mounts=` or a `**spread`.

    Returns:
        True when the call is exempt.

    """
    return any(kw.arg is None or kw.arg in _EXEMPTING_KWARGS for kw in node.keywords)
