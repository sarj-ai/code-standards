"""SARJ048: importing a private name — but only when the private name is OURS.

Reaching past a module's public surface is a design finding when the module is
ours and an unavoidable fact of life when it is not. `from bulbul.stores.task_store
import _row_to_task` says a first-party module has a helper someone needed and
did not export; the fix is to export it. `from livekit.agents.inference_runner
import _InferenceRunner` says a dependency moved an API private in a minor
release — livekit-agents 1.6.6 did exactly this to bulbul's custom EOU runner —
and there is no edit that satisfies the lint short of vendoring the library or
pinning it forever. A rule that cannot tell those apart is an instruction to
perform an impossible edit, which is how blanket suppressions get born.

This rule fires ONLY on the first case. Third-party privates are never flagged.

Ruff's `PLC2701 import-private-name` is the rule this replaces, and it does not
make the distinction. Its exemption is *same top-level package*, not
*first-party*: measured over bulbul's five packages it produced 80 findings, of
which 77 were first-party (real) and 3 were livekit reaches with no available
fix. Ruff has no configuration surface that separates them — the check is
purely lexical and never resolves an import to a location on disk. Pyright's
`reportPrivateUsage` fires on the same third-party import and likewise has no
first-party/third-party knob, so it still needs a per-line `# pyright: ignore`
at the reach site; this rule does not change that, it only stops ruff from
demanding a second, unfixable suppression on the same line.

Fires on:

* `from <first-party module> import _name` — a private symbol,
* `from <first-party package>._private_module import Name`, and
  `import <first-party package>._private_module` — a private *submodule*, which
  is just as much a non-public surface as a private symbol.

Deliberately NOT flagged:

* **anything third-party.** A module is first-party only when its top-level
  name resolves to a package directory inside the enclosing project (see
  `_first_party.py`); stdlib, site-packages and anything unresolvable are
  third-party. Unresolvable defaults to third-party on purpose: a missed
  finding is a smaller failure than an unfixable one.
* **relative imports** (`from . import _helper`, `from ._impl import Thing`) —
  a relative import cannot leave its own package by construction, and a
  package's own internals are its own business. This matches PLC2701.
* **same-top-level-package absolute imports** — `from agent.lk.get_models
  import _wire_fallback_metric` written from inside the `agent` package is the
  spelled-out form of the bullet above. Written from `agent/tests/` — which is
  not inside the package — it fires, because a white-box test reaching into a
  module's internals from outside is the finding, not the exemption.
* **dunder names** (`__version__`, `__all__`) — conventional module metadata,
  not private internals.
* **a private TOP-LEVEL package name** — `from _infra.fakes import FakeStt`,
  bulbul's shared test-support package. The underscore there is the package's
  own name, not a hidden corner of somebody else's module: there is no public
  spelling to switch to and no surface to widen. PLC2701 flags these (14 hits
  in bulbul's `agent` package alone) with no available fix. Private *sub*module
  segments still fire.
* `_`-prefixed *aliases* (`import json as _json`) — the alias is local shorthand
  and the imported name is public.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._first_party import is_first_party_module, own_top_package


if TYPE_CHECKING:
    from pathlib import Path


class NoFirstPartyPrivateImport(Rule):
    """A private name imported out of one of OUR modules — export it instead."""

    id: str = "no-first-party-private-import"
    code: str = "SARJ048"
    description: str = (
        "Importing a private (`_`-prefixed) name or module from a FIRST-PARTY module reaches past a "
        "surface we control and can widen. Third-party privates are never flagged — that API is not ours to change."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag every private import whose defining module is first-party.

        Returns:
            One diagnostic per private name (or private module) imported from
            one of this project's own modules, sorted by position.

        """
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        own_top = own_top_package(path)
        diags = [
            Diagnostic(path=path, line=line, col=col, code=self.code, message=_message(module, name))
            for line, col, module, name in _private_imports(tree)
            if _is_ours(module, path, own_top)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _message(module: str, name: str) -> str:
    return (
        f"`{name}` is private to `{module}`, which is first-party — importing it reaches past a public "
        f"surface we own and can widen. Export it under a public name, or move the caller behind a "
        f"function `{module}` already exports. (Private imports from third-party packages are never flagged.)"
    )


def _is_ours(module: str, path: Path, own_top: str | None) -> bool:
    """Report whether `module` is a first-party module OUTSIDE the file's own package.

    Returns:
        True when the private import crosses into another first-party package.

    """
    top = module.partition(".")[0]
    if own_top is not None and top == own_top:
        return False
    return is_first_party_module(module, path)


def _private_imports(tree: ast.Module) -> list[tuple[int, int, str, str]]:
    """Collect `(line, col, defining module, private name)` for every private import.

    Returns:
        One entry per private symbol or private module segment imported
        absolutely; relative imports are skipped.

    """
    hits: list[tuple[int, int, str, str]] = []
    for node in nodes(tree, ast.ImportFrom, ast.Import):
        if isinstance(node, ast.ImportFrom):
            hits.extend(_from_import_hits(node))
        else:
            hits.extend(_plain_import_hits(node))
    return hits


def _from_import_hits(node: ast.ImportFrom) -> list[tuple[int, int, str, str]]:
    # `node.level` > 0 is a relative import: inside its own package by construction.
    if node.level or not node.module:
        return []
    private_segment = _private_segment(node.module)
    if private_segment is not None:
        return [(node.lineno, node.col_offset + 1, node.module, private_segment)]
    return [
        (alias.lineno, alias.col_offset + 1, node.module, name)
        for alias in node.names
        if _is_private_name(name := alias.name)
    ]


def _plain_import_hits(node: ast.Import) -> list[tuple[int, int, str, str]]:
    hits: list[tuple[int, int, str, str]] = []
    for alias in node.names:
        private_segment = _private_segment(alias.name)
        if private_segment is not None:
            hits.append((alias.lineno, alias.col_offset + 1, alias.name, private_segment))
    return hits


def _private_segment(module: str) -> str | None:
    """Return the first private component BELOW the top level of a dotted module path.

    The top-level name is deliberately excluded. `pkg._internals` is a module
    `pkg` chose not to publish and could publish; a top-level package that is
    simply *named* `_infra` — bulbul's shared test-support package — has no
    other spelling and no wider surface to widen, so flagging its import asks
    for an edit that does not exist.

    Returns:
        The private segment, or None when every component below the top is public.

    """
    return next((part for part in module.split(".")[1:] if _is_private_name(part)), None)


def _is_private_name(name: str) -> bool:
    # `__version__` / `__all__` are module metadata by convention, not internals.
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))
