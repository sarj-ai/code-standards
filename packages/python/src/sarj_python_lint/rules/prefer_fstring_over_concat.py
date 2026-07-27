r"""SARJ065: build a string with an f-string, not `"literal" + expression`.

`"user " + name + " failed"` is worse than `f"user {name} failed"` in four
concrete ways: every non-`str` operand needs an explicit `str()` wrapper and
raises `TypeError` the day someone forgets one; the literal fragments' leading
and trailing spaces are invisible at a glance (`"user "` vs `"user"`); a chain
of three or more `+` reads as arithmetic rather than as a template; and the
value's shape is not recoverable by any tooling that understands format
strings. The f-string is one expression whose final text is readable in source
order.

WHY THIS IS NOT ALREADY COVERED BY RUFF
---------------------------------------

Measured, not remembered: a probe file was run through `ruff check` with this
repo's `ruff.strict.toml` (`select = ["ALL"]`, `preview = true`). Of the
string-formatting rules that sound relevant, none flags a literal concatenated
with an expression:

* `ISC001/002` cover *implicit* concatenation (`"a" "b"`), and `ISC003` covers
  *explicit* concatenation of string LITERALS only — it fired on
  `("long one " + "long two")` and stayed silent on `"prefix" + name`,
  `"id=" + str(x)`, `name + "!"` and `"a" + name + "b" + path + "c"`. Literal +
  literal is ruff's; literal + expression is nobody's. The two never overlap,
  because this rule requires at least one NON-literal operand,
* `UP031` (`%` → f-string) and `UP032` (`.format` → f-string) fired only on the
  `%`/`.format` spellings; `+` is untouched,
* `FLY002` fired only on a static `str.join` of literals,
* `G003` fired on `logger.info("x " + name)` — see the logging exemption below,
  which is why this rule stays silent there and there is no double report,
* `S608` fired on `"SELECT * FROM " + table`; that literal shape is exempted
  here rather than double-reported (see below).

RELATIONSHIP TO SIBLING SARJ RULES
----------------------------------

* **SARJ002 `inefficient-string-concat-in-loop`** is a *performance* rule about
  `s += x` / `s = s + x` STATEMENTS whose target accumulates across loop
  iterations — O(n²) growth, remedied by `"".join`. This is a *readability*
  rule about `+` EXPRESSIONS anywhere, remedied by an f-string. The populations
  barely intersect: SARJ002 needs a self-referential assignment inside a loop,
  this rule needs a literal operand and does not care where it sits,
* **SARJ017 `no-fstring-in-log`** says the *opposite* inside logging calls:
  stdlib/loguru logging wants a constant template with lazy `%s`/keyword
  parameters, so an f-string there is the defect. Recommending an f-string for
  `log.info("call " + cid + " failed")` would produce code SARJ017 immediately
  flags. This rule therefore never fires inside a logging call — the logger
  receiver is resolved with the same shared `_logging.is_logger_expr` helper
  SARJ012/SARJ017 use, so the three rules can never disagree about what a
  logger is. `warnings.warn(...)` is deliberately NOT exempt: it formats
  eagerly, so an f-string is correct there.

Fires on the OUTERMOST `+` chain (never once per operand) when ALL hold:

* every `Constant` operand in the flattened chain is a `str` — that literal is
  the only type evidence available without a type checker, and
* at least one operand is a runtime expression (`Name`, `Attribute`, `Call`,
  `Subscript`, an f-string, …).

CORPUS EVIDENCE
---------------

Swept over 6,155 Python files — bulbul (1,179), noura-be (502), django (2,927),
fastapi (1,130), celery (417). 717 raw candidates; the guards below removed 181
of them (25%), leaving 536: bulbul 24, noura-be 15, django 379, fastapi 29,
celery 89. A 25-hit manual sample spread across all five corpora classified 24
true positives and 1 false positive (4%) — the survivor is noted under the
character-set bullet below. Separately, 773 chains were rejected outright by the
"every literal must be a `str`" test (integer arithmetic and `bytes`
concatenation reaching a `+` with a literal in it); without that test the rule
would have fired on more arithmetic than string building.

Deliberately NOT flagged:

* **any chain containing a non-`str` literal.** `x + 1`, `b"GET " + path`,
  `offset + 0x20`. With no types, a string literal in the chain is the only
  evidence the `+` is concatenation at all; a numeric or `bytes` literal is
  positive evidence it is not, and `bytes` has no f-string equivalent
  (`f"..."` is `str`). This is also what keeps `a + b` — two bare names that
  could be ints, lists, `timedelta`, `Path`, numpy arrays or a domain type with
  an `__add__` overload — permanently silent: no literal, no diagnostic,
* **logging calls** (mandatory, see SARJ017 above). `logger.info("x " + name)`,
  `log.bind(...).error("x " + name)`. Ruff's `G003` already reports these with
  the correct `%s`-parameter advice. Keyword arguments are exempt too, so
  `logger.info("done", detail="x " + y)` is silent — the whole call is the
  logging boundary. 4 hits,
* **a literal containing `{` or `}`.** The f-string rewrite has to double every
  brace, which is exactly the transcription error the rule is meant to prevent.
  This is what regex assembly and format templates look like in practice:
  noura-be's `voice/agents/tts_pronunciation.py:23,35,45,57` builds four
  `re.compile` patterns as `r"(\d{4,6})(?!\s*" + CURRENCY_TERMS + r")"`, and
  `common/logging.py:336` returns `format_string + "\n{exception}"` — a loguru
  template whose braces are *meant* to survive. bulbul's
  `sdk/src/sarj_platform_sdk/utils/url.py:44` (`path.replace("{" + key + "}",
  ...)`) is the same shape. 12 hits,
* **an operand that is a `.join(...)` call.** `"header\n" + "\n".join(rows)`
  becomes `f"header\n{'\n'.join(rows)}"` — a quoted, backslash-bearing
  expression nested inside the f-string, which was a syntax error before 3.12
  and is unreadable after. The `+` spelling is the better one. This is the
  dominant assertion-message idiom in both house repos:
  `bulbul/python/webserver/tests/test_webserver_route_coverage.py:31,42,52`,
  `worker/tests/test_worker_route_coverage.py:28,37,45`,
  `integration/tests/test_integration_route_coverage.py:28,37,45`, and
  noura-be's `dashboard/stores/user_store.py:399`
  (`"WHERE " + " AND ".join(conditions)`). 43 hits — the single largest guard
  after string repetition,
* **an operand that is string repetition** (`"A" * N + " tail"`,
  `"x" + "\n" * 51 + "y"`). `f"{'A' * N} tail"` is strictly worse than the
  original. Found in bulbul's
  `tests/store/test_scenario_generation_log_store.py:160,436,445` and
  noura-be's `noura/tests/test_chatbot_v3_chat.py:732,734`, plus django's
  padding and separator-bar helpers. 67 hits, the largest single guard,
* **a two-operand chain whose only literal is whitespace** — `payload + "\n"`,
  `"\n" + body`. Appending a terminator is not string building, and
  `f"{json.dumps(payload, indent=2)}\n"` is not an improvement on
  `json.dumps(payload, indent=2) + "\n"`. Found identically in five bulbul and
  four noura-be ratchet scripts (`scripts/check_coverage_ratchet.py:72` and
  siblings). Three or more operands still fire, because `a + " " + b` really is
  clearer as `f"{a} {b}"`. 32 hits,
* **a chain that is the left operand of `%`.** `("%0" + width + "d. %s") % (i,
  line)` assembles a *format template*, not a message; rewriting the left side
  as an f-string leaves a confusing f-string/`%`-format hybrid. django's
  `template/defaultfilters.py:240,243,292`. 3 hits,
* **an operand that is a translation or safe-string call** (`_`, `gettext`,
  `gettext_lazy`, `ngettext`, `pgettext`, `format_lazy`, `lazy`, `mark_safe`,
  `format_html`). Interpolating a lazy translation proxy into an f-string forces
  it to render at concatenation time instead of at display time, which is the
  entire bug `format_lazy` exists to avoid; interpolating a `SafeString` returns
  a plain `str` and silently drops the "already escaped" marking. This is a
  behaviour change, not a restyle. 1 hit,
* **an operand that is a conditional expression.** `("-" if desc else "") +
  "datefield"` becomes `f"{'-' if desc else ''}datefield"`, which buries a
  branch inside a format placeholder. django's `db/models/query.py:1617,1650`
  and `db/backends/oracle/base.py:324`. 7 hits,
* **a literal ending in a SQL keyword** (`"SELECT * FROM " + table`,
  `"... WHERE id = " + uid`). Ruff's `S608` already reports that exact shape as
  an injection vector, and SARJ021 covers `SELECT *`; answering "use an
  f-string" would restyle an injection instead of fixing it, and this rule must
  not become a competing SQL rule. The keyword match is case-SENSITIVE, so
  prose like `"copied from " + src` is not mistaken for a query. 7 hits,
* **generated files** (`_paths.is_generated_source`). Re-running the generator
  discards any edit, so a style finding there can never be acted on — the same
  exemption SARJ002 makes. 5 hits, all in bulbul's Speakeasy
  `python/sdk/src/sarj_platform_sdk/`.

Known and accepted (the 1 false positive in the 25-hit sample): a module-level
character-set constant composed from another constant —
`noura-be/python/common/tests/test_validator_properties.py:60`,
`_DIGITS_AND_LETTERS = _DIGITS + "abXY"`. There `+` reads as alphabet union and
the f-string adds nothing. Guarding it would require knowing the constant is a
character set, which the AST cannot tell from any other module-level string
constant; suppress it with `# sarj-noqa: SARJ065 — <reason>`.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._logging import is_logger_expr
from sarj_python_lint.rules._paths import is_generated_source


if TYPE_CHECKING:
    from pathlib import Path


# Method names that make a logger-receiver call a logging call. Kept in sync by
# construction with SARJ017's list; the receiver test is the shared helper.
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

# A literal ENDING in an UPPERCASE SQL keyword is a query fragment awaiting
# interpolation — ruff's S608 and SARJ021 own that shape. Anchored at the end,
# and case-SENSITIVE: SQL keywords are written in caps by universal convention,
# so `"copied from "` in prose is not mistaken for a query fragment.
_SQL_RE = re.compile(
    r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|WHERE|FROM|JOIN|ORDER\s+BY|GROUP\s+BY|VALUES|SET)\b\s*$"
)

# Calls returning a lazy translation proxy or an escape-aware SafeString.
# Interpolating either into an f-string changes behaviour, not just style.
_LAZY_CALLS = frozenset(
    {
        "_",
        "lazy",
        "format_lazy",
        "gettext",
        "gettext_lazy",
        "ngettext",
        "ngettext_lazy",
        "pgettext",
        "pgettext_lazy",
        "npgettext",
        "npgettext_lazy",
        "ugettext",
        "ugettext_lazy",
        "mark_safe",
        "format_html",
    }
)

# Past this many operands an f-string is a wall of placeholders and `"".join`
# (or a template) is usually the better answer; the message says so.
_JOIN_RECOMMENDATION_OPERANDS = 5

# A `<expr> + "<whitespace>"` pair is a terminator, not string building.
_TERMINATOR_OPERANDS = 2


class PreferFstringOverConcat(Rule):
    """String built with `+` from a literal and an expression — use an f-string."""

    id: str = "prefer-fstring-over-concat"
    code: str = "SARJ065"
    description: str = (
        "String built with `+` from a literal and a runtime expression — an f-string needs no "
        "`str()` coercion and keeps the literal's spacing visible."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag `+` string building that an f-string expresses better.

        Returns:
            One diagnostic per outermost offending concatenation, sorted by position.

        """
        if "+" not in source or is_generated_source(source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        # One walk collects everything: the candidate chains, the inner links of
        # each chain (so a 4-operand chain reports once), and the chains sitting
        # in a context whose rewrite would be wrong.
        inner: set[int] = set()
        excluded: set[int] = set()
        adds: list[ast.BinOp] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                adds.append(node)
                for side in (node.left, node.right):
                    if isinstance(side, ast.BinOp) and isinstance(side.op, ast.Add):
                        inner.add(id(side))
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                # `("%0" + width + "d") % args` builds a format template.
                excluded.add(id(node.left))
            elif isinstance(node, ast.Call) and _is_logging_call(node):
                arguments: list[ast.expr] = [*node.args, *(kw.value for kw in node.keywords)]
                excluded.update(id(sub) for arg in arguments for sub in ast.walk(arg))

        diags: list[Diagnostic] = []
        for node in adds:
            if id(node) in inner or id(node) in excluded:
                continue
            message = _verdict(node)
            if message is not None:
                diags.append(
                    Diagnostic(path=path, line=node.lineno, col=node.col_offset + 1, code=self.code, message=message)
                )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_logging_call(node: ast.Call) -> bool:
    """Report whether `node` is a logging call, using SARJ017's receiver resolver.

    Returns:
        True when the call is `<logger>.<level>(...)`.

    """
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _LOG_METHODS:
        return False
    return is_logger_expr(func.value)


def _flatten(node: ast.expr) -> list[ast.expr]:
    """Flatten a nested `+` chain into its operands.

    Returns:
        The operand expressions, left to right.

    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _flatten(node.left) + _flatten(node.right)
    return [node]


def _verdict(node: ast.BinOp) -> str | None:
    """Judge one outermost `+` chain and build its message.

    Returns:
        The diagnostic message, or None when the chain is not an f-string candidate.

    """
    literals: list[str] = []
    dynamic: list[ast.expr] = []
    operands = _flatten(node)
    for operand in operands:
        if isinstance(operand, ast.Constant):
            if not isinstance(operand.value, str):
                # A bytes/int/float literal is positive evidence this `+` is not
                # string concatenation at all.
                return None
            literals.append(operand.value)
        else:
            dynamic.append(operand)
    if not literals or not dynamic:
        return None
    if any("{" in text or "}" in text for text in literals):
        return None
    if any(_SQL_RE.search(text) for text in literals):
        return None
    if any(_is_join_call(expr) or _is_string_repetition(expr) or _is_lazy_call(expr) for expr in dynamic):
        return None
    if any(isinstance(expr, ast.IfExp) for expr in dynamic):
        return None
    if len(operands) == _TERMINATOR_OPERANDS and all(not text.strip() for text in literals):
        return None

    message = (
        "string built with `+` from a literal and a runtime value — write it as one f-string, "
        "which keeps the literal's spacing visible and needs no `str()` coercion"
    )
    if any(_is_str_call(expr) for expr in dynamic):
        message += "; the `str(...)` wrapper disappears"
    if len(operands) >= _JOIN_RECOMMENDATION_OPERANDS:
        message += f"; at {len(operands)} operands `''.join(...)` may read better still"
    return message


def _is_join_call(expr: ast.expr) -> bool:
    """Report whether `expr` is a `<sep>.join(...)` call.

    Returns:
        True for any `.join(...)` attribute call.

    """
    return isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr == "join"


def _is_lazy_call(expr: ast.expr) -> bool:
    """Report whether `expr` yields a lazy translation proxy or a SafeString.

    Returns:
        True when interpolating the operand would change behaviour.

    """
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
    return name in _LAZY_CALLS


def _is_str_call(expr: ast.expr) -> bool:
    """Report whether `expr` is a `str(...)` coercion the f-string would delete.

    Returns:
        True for a bare `str(...)` call.

    """
    return isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "str"


def _is_string_repetition(expr: ast.expr) -> bool:
    """Report whether `expr` is a `"x" * n` padding/separator construction.

    Returns:
        True when the operand multiplies a string literal.

    """
    if not isinstance(expr, ast.BinOp) or not isinstance(expr.op, ast.Mult):
        return False
    return any(isinstance(side, ast.Constant) and isinstance(side.value, str) for side in (expr.left, expr.right))
