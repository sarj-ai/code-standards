"""SARJ033: `httpx` client construction / convenience call without an explicit `timeout=`.

Every outbound HTTP call needs a deliberate deadline. httpx does ship an
implicit 5-second default, but review feedback treats relying on it as a bug:
the right budget for a CRM sync, an OAuth token exchange, or an LLM call is
never coincidentally "whatever the library defaults to", and an implicit
default is invisible at the call site, so nobody re-examines it when the
downstream SLA changes. (~10 production sites in the CRM/OAuth integrations
were retrofitted with explicit timeouts after incidents.)

Flags, when the receiver is the bare module name `httpx`:

* `httpx.Client(...)` / `httpx.AsyncClient(...)` without a `timeout=` kwarg,
* module-level convenience calls `httpx.get/post/put/patch/delete/request(...)`
  without a `timeout=` kwarg (each builds a throwaway client).

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
_CONVENIENCE_FUNCS = frozenset({"get", "post", "put", "patch", "delete", "request"})
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
        diags: list[Diagnostic] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = _httpx_callee(node.func)
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


def _httpx_callee(func: ast.expr) -> str | None:
    """Return the flaggable `httpx.<name>` attribute name, else None.

    Only the bare module receiver `httpx` counts — `client.get(...)` on an
    already-constructed client inherits the client's timeout and is fine.

    Returns:
        The attribute name when `func` is a flaggable httpx callee, else None.

    """
    match func:
        case ast.Attribute(value=ast.Name(id="httpx"), attr=attr) if (
            attr in _CLIENT_CLASSES or attr in _CONVENIENCE_FUNCS
        ):
            return attr
        case _:
            return None


def _has_exempting_kwarg(node: ast.Call) -> bool:
    """Report whether the call carries `timeout=`/`transport=`/`mounts=` or a `**spread`.

    Returns:
        True when the call is exempt.

    """
    return any(kw.arg is None or kw.arg in _EXEMPTING_KWARGS for kw in node.keywords)
