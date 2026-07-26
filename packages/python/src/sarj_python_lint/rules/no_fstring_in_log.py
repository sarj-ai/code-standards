"""SARJ017: flag an f-string passed as the message to a logging call.

The house logging style is structured: pass variables as keyword arguments so
log aggregators can index and filter on them, and so the message template stays
constant across calls:

    # flagged
    logger.info(f"call {call_id} finished in {elapsed}s")

    # preferred
    logger.info("call finished", call_id=call_id, elapsed=elapsed)

F-string interpolation bakes the values into the message text, defeating
structured search, breaking template grouping, and (for loguru) evaluating the
string even when the level is disabled.

To keep false positives near zero we require BOTH a logger-like receiver
(`logger`/`log`/`logging`/`loguru` and common aliases) AND a logging method
name — an f-string passed to some unrelated `.info(...)` is not flagged. The
receiver chain is resolved, so builder/factory forms are still caught:
`logger.bind(...).info(...)`, `logger.opt(lazy=True).debug(...)`. Only the first
positional argument (the message) is inspected.

The structured-keyword advice is loguru-specific: stdlib `logging` treats
trailing positional args as %-format parameters and reserves `exc_info` /
`stack_info` / `extra` keywords, so rewriting a stdlib call to
`logger.info("msg", key=value)` raises `TypeError: _log() got an unexpected
keyword argument`. We therefore suppress calls whose receiver is a stdlib
logger, and keep firing on the loguru-shaped calls the advice actually applies
to.

EXEMPTIONS, WITH CORPUS EVIDENCE
--------------------------------

Measured over 2,657 files of popular third-party Python (fastapi, pydantic,
black, sqlmodel, rich, flask, httpx, requests, anyio), the earlier version of
this rule reported 94 hits, of which 70 were false positives — every one of
them a **stdlib `logging` call**, for which the advice recommends a fix that
raises at runtime. Only the inline `logging.getLogger(__name__).info(...)`
spelling was recognised as stdlib; the two spellings that actually dominate
were not:

1. **The module-level convenience functions (59 hits, 63%)** — `logging.info(
   f"...")` on the root logger, with no `getLogger` anywhere. Evidence:
   `fastapi/scripts/notify_translations.py:312`, `fastapi/scripts/sponsors.py:155`,
   `fastapi/scripts/docs.py:656`, `sqlmodel/scripts/docs.py:206`,
   `pydantic/.github/actions/people/people.py:675`,
   `fastapi/scripts/label_approved.py:30`. Guard: a receiver naming a module
   bound by `import logging`.

2. **A module-level logger assigned once, then used by name (11 hits)** —
   `LOG = logging.getLogger(__name__)` at the top of the file, `LOG.info(
   f"...")` throughout. The receiver at the call site is a bare `Name`, so the
   existing chain walk could never reach the factory. Evidence:
   `black/scripts/release.py:17` (the binding) with hits at `:80`, `:123`,
   `:242`; `black/scripts/migrate-black.py:93`. Guard: resolve the binding —
   any name assigned from a `getLogger(...)` chain is a stdlib logger.

Already correct before the audit, and confirmed against the corpus: `f"static"`
with no interpolation is never flagged (harmless), and neither
`warnings.warn(f"...")` nor rich's `console.log(f"...")` fires, because the
receiver resolver requires a logger-shaped name — `warnings` and `console` are
not one. The 24 survivors are true positives by shape (`log.info(f"...")`), all
in one file: `black/tests/data/cases/preview_long_strings.py:311` and on, a
formatter fixture that pastes the same snippets twice (input and expected
output). No guard is warranted for that — it is a corpus artifact, not a rule
defect.

Suppress an intentional case with `# sarj-noqa: SARJ017 — <reason>`.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._logging import is_logger_expr


if TYPE_CHECKING:
    from pathlib import Path


_LOG_METHODS = frozenset(
    {
        "debug",
        "info",
        "warning",
        "warn",
        "error",
        "exception",
        "critical",
        "fatal",
        "trace",
        "success",
        "log",
    }
)

# Keyword arguments defined by stdlib `logging` (and never structured fields).
# Their presence marks the call as a stdlib logger, for which the loguru-style
# structured-keyword rewrite is wrong.
_STDLIB_ONLY_KWARGS = frozenset({"exc_info", "stack_info", "extra"})


class NoFstringInLog(Rule):
    """f-string passed as a logging message — use structured keyword arguments."""

    id: str = "no-fstring-in-log"
    code: str = "SARJ017"
    description: str = (
        "f-string message in a logging call — pass variables as structured "
        "keyword arguments so logs stay filterable and templates stay constant."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        candidates = _candidates(tree)
        if not candidates:
            return []
        # Resolving the file's stdlib-`logging` bindings costs a second walk, so
        # only pay for it once something is actually at stake.
        stdlib = _StdlibLoggers.from_tree(tree)
        diags: list[Diagnostic] = []
        for node, offending in candidates:
            if not _is_stdlib_logging_call(node, stdlib):
                diags.append(
                    Diagnostic(
                        path=path,
                        line=offending.lineno,
                        col=offending.col_offset + 1,
                        code=self.code,
                        message=(
                            "f-string logging message — pass variables as keyword "
                            "arguments (logger.info('msg', key=value)) instead."
                        ),
                    )
                )
        return diags


def _candidates(tree: ast.Module) -> list[tuple[ast.Call, ast.JoinedStr]]:
    """Find every logging call whose message argument interpolates an f-string.

    Returns:
        The `(call, f-string)` pairs still to be judged against the stdlib guard.

    """
    hits: list[tuple[ast.Call, ast.JoinedStr]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args or not _is_logging_call(node):
            continue
        offending = _interpolating_fstring(node.args[0])
        if offending is not None:
            hits.append((node, offending))
    return hits


def _is_logging_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _LOG_METHODS:
        return False
    return is_logger_expr(func.value)


class _StdlibLoggers:
    """The local names through which stdlib `logging` is reachable in one file.

    Both spellings that dominate real code hide the stdlib provenance from the
    call site: `logging.info(...)` names the module, and `LOG = logging.getLogger
    (__name__)` puts the factory in a different statement entirely. Resolving the
    bindings once per file is what lets the call site be judged.
    """

    def __init__(self) -> None:
        self.paths: set[str] = set()

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _StdlibLoggers:
        """Collect every local binding that resolves to stdlib `logging`.

        Returns:
            The populated name table.

        """
        found = cls()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found._add_import(node)
            elif isinstance(node, ast.Assign):
                found._add_assignment(node.targets, node.value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                found._add_assignment([node.target], node.value)
        return found

    def _add_import(self, node: ast.Import) -> None:
        # `import logging` and `import logging.handlers` both bind `logging`.
        for alias in node.names:
            if alias.name == "logging" or alias.name.startswith("logging."):
                self.paths.add(alias.asname or "logging")

    def _add_assignment(self, targets: list[ast.expr], value: ast.expr) -> None:
        # `LOG = logging.getLogger(__name__)`, `self.logger = getLogger("x")`.
        if not _chain_has_getlogger(value):
            return
        for target in targets:
            path = _dotted_path(target)
            if path is not None:
                self.paths.add(".".join(path))

    def owns(self, receiver: ast.expr) -> bool:
        """Report whether `receiver` resolves to one of this file's stdlib bindings.

        Matching is on the receiver's dotted path or a *prefix* of it, never on a
        loose name: `self.logger = logging.getLogger(...)` binds `self.logger`,
        which must not make an unrelated module-level loguru `logger` look
        stdlib. The prefix is what lets builder calls through —
        `logging.getLogger(x).bind(...)` has the path `logging.getLogger.bind`.

        Returns:
            True when the receiver, or a prefix of it, is a stdlib logging binding.

        """
        path = _dotted_path(receiver)
        if path is None:
            return False
        return any(".".join(path[: n + 1]) in self.paths for n in range(len(path)))


def _dotted_path(expr: ast.expr) -> list[str] | None:
    """Render `expr` as its dotted attribute path, descending through builder calls.

    Returns:
        The path components, or None when `expr` is not a name/attribute chain.

    """
    if isinstance(expr, ast.Name):
        return [expr.id]
    if isinstance(expr, ast.Attribute):
        base = _dotted_path(expr.value)
        return None if base is None else [*base, expr.attr]
    if isinstance(expr, ast.Call):
        return _dotted_path(expr.func)
    return None


def _is_stdlib_logging_call(node: ast.Call, stdlib: _StdlibLoggers) -> bool:
    """Report whether the call carries a stdlib-`logging` tell the loguru advice breaks.

    A stdlib-reserved keyword (`exc_info`/`stack_info`/`extra`), a
    `logging.getLogger(...)` factory anywhere in the receiver chain, or a
    receiver resolving to one of the file's stdlib `logging` bindings marks the
    logger as stdlib, whose message API is %-style positional, not structured
    keywords — so the rule must stay silent to avoid recommending a fix that
    raises `TypeError`.

    Returns:
        True when the call looks like a stdlib logging call.

    """
    if any(kw.arg in _STDLIB_ONLY_KWARGS for kw in node.keywords):
        return True
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    return _chain_has_getlogger(func.value) or stdlib.owns(func.value)


def _chain_has_getlogger(expr: ast.expr) -> bool:
    node = expr
    while True:
        if isinstance(node, ast.Call):
            called = node.func
            if isinstance(called, ast.Attribute) and called.attr == "getLogger":
                return True
            if isinstance(called, ast.Name) and called.id == "getLogger":
                return True
            node = called
        elif isinstance(node, ast.Attribute):
            node = node.value
        else:
            return False


def _interpolating_fstring(node: ast.expr) -> ast.JoinedStr | None:
    """Find an interpolating f-string in `node`, descending `+`-concat operands.

    A concatenated message like `f"{x}" + "!"` wraps the f-string in a `BinOp`,
    so the interpolation is not the top-level node — walk the `Add` tree to find
    it while leaving interpolation-free f-strings unflagged.

    Returns:
        The interpolating f-string node, or None if none is present.

    """
    if isinstance(node, ast.JoinedStr):
        return node if _has_interpolation(node) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _interpolating_fstring(node.left) or _interpolating_fstring(node.right)
    return None


def _has_interpolation(node: ast.JoinedStr) -> bool:
    """Report whether the f-string actually interpolates a value (not just `f"literal"`).

    Returns:
        True when the f-string contains a formatted value.

    """
    return any(isinstance(v, ast.FormattedValue) for v in node.values)
