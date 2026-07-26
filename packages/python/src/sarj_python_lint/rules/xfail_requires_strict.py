"""SARJ046: a non-strict `xfail` bug-pin goes green forever once the bug is fixed.

`@pytest.mark.xfail(reason="BUG: returns 404 instead of the error envelope")`
pins a known defect: the test asserts the *correct* behaviour and is expected to
fail until someone fixes it. Without `strict=True`, the day the bug is fixed the
test XPASSes — which pytest reports as a pass. Nobody is told, the marker stays
forever, and the test silently stops guarding anything. With `strict=True` an
XPASS is a hard failure that says "the bug is fixed, delete this marker", which
is the entire value of the pin.

Both audited repos already invented this convention independently — noura-be has
a family of `test_known_*_bugs_xfail.py` modules whose docstrings spell out the
strict contract, and 45 of 52 `xfail` markers across the two repos already pass
`strict=True`. This rule locks in a practice the codebase chose, rather than
importing an outside opinion.

Fires when ALL of these hold:

* the file is a test file, and the decorator is `@pytest.mark.xfail(...)`,
* the marker carries a `reason=` naming a defect — the reason text matches
  `bug`, `broken`, `regression`, `should`, or `incorrect`,
* and `strict=` is absent or literally `False`.

**Exempting genuinely nondeterministic markers is not optional.** Of the five
non-strict `xfail`s found in noura-be, all five sit on `@pytest.mark.real_llm`
evals whose reasons say "intermittently" — a live model that answers differently
run to run legitimately cannot be strict, and forcing it would make CI flake on
every provider drift. A rule without this guard would have been 100% wrong on
that population. Any marker on the same function naming a nondeterministic
source (`real_llm`, `flaky`, `network`) suppresses the diagnostic, as does a
reason mentioning intermittence.

Deliberately NOT flagged:

* **property-based and fuzz tests.** A `@given(...)` (hypothesis) or
  `<schema>.parametrize()` (schemathesis) decorator means one test function
  expands into many generated cases, and a documented bug is typically tripped
  by only a subset of them — the rest legitimately XPASS. `strict=True` there
  turns every passing generated input into a failure, which is why these suites
  set `strict=False` deliberately. Found against bulbul's
  `test_calls_fuzz_known_bugs`, where the unroutable-id shapes trip the bug and
  the other generated ids do not,
* `xfail` with no `reason=`, or a reason describing an environment gate rather
  than a defect ("no GPU on CI") — those are not bug pins,
* `pytest.xfail(...)` called imperatively inside a body — that aborts the test
  immediately and has no strict/non-strict distinction,
* `xfail` used as a `pytest.param` marker argument, where the surrounding
  decorator context is not visible.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_XFAIL = "xfail"

# Reason text that identifies a pinned defect rather than an environment gate.
_DEFECT_RE = re.compile(r"\b(bug|broken|regression|incorrect|should|wrong|fixme)\b", re.IGNORECASE)

# Reason text conceding the outcome genuinely varies run to run.
_NONDETERMINISM_RE = re.compile(r"intermittent|flak|sometimes|non-?deterministic|varies", re.IGNORECASE)

# Sibling markers that declare a nondeterministic dependency.
_NONDETERMINISTIC_MARKERS = frozenset({"real_llm", "flaky", "network", "integration"})

# Hypothesis' entry point. One `@given` expands into many generated inputs.
_PROPERTY_DECORATORS = frozenset({"given"})

# schemathesis binds `.parametrize()` on a schema object. `pytest.mark.parametrize`
# is a fixed table and is NOT this — it is excluded by checking the receiver.
_PARAMETRIZE_ATTR = "parametrize"
_PYTEST_MARK = "mark"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class XfailRequiresStrict(Rule):
    """A bug-pinning `xfail` without `strict=True` silently passes once fixed."""

    id: str = "xfail-requires-strict"
    code: str = "SARJ046"
    description: str = "Bug-pinning `xfail` without `strict=True` — an XPASS reports as a pass and the pin rots."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag defect-pinning xfail markers that lack `strict=True`.

        Returns:
            One diagnostic per rotting bug pin, sorted by position.

        """
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    "this `xfail` pins a known defect but is not `strict=True`, so the day the bug is "
                    "fixed the test XPASSes, reports as a pass, and quietly stops guarding anything. "
                    "Add `strict=True` so a fix fails loudly and the marker gets deleted."
                ),
            )
            for node in _rotting_bug_pins(tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _rotting_bug_pins(tree: ast.Module) -> list[ast.Call]:
    hits: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, _FUNC_NODES):
            continue
        if _has_nondeterministic_marker(node.decorator_list):
            continue
        hits.extend(dec for dec in node.decorator_list if isinstance(dec, ast.Call) and _is_rotting_xfail(dec))
    return hits


def _has_nondeterministic_marker(decorators: list[ast.expr]) -> bool:
    return any(_marker_name(dec) in _NONDETERMINISTIC_MARKERS or _is_property_based(dec) for dec in decorators)


def _is_property_based(dec: ast.expr) -> bool:
    """Report whether `dec` expands the test into many generated inputs.

    Returns:
        True for a hypothesis `@given(...)` or a schemathesis
        `<schema>.parametrize()`, both of which make a partial XPASS normal.

    """
    target = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(target, ast.Name):
        return target.id in _PROPERTY_DECORATORS
    if not isinstance(target, ast.Attribute) or target.attr != _PARAMETRIZE_ATTR:
        return False
    # `pytest.mark.parametrize` is a fixed table, not a generator — the receiver
    # is `mark`. A schemathesis schema object is anything else.
    receiver = target.value
    return not (isinstance(receiver, ast.Attribute) and receiver.attr == _PYTEST_MARK)


def _marker_name(dec: ast.expr) -> str | None:
    target = dec.func if isinstance(dec, ast.Call) else dec
    return target.attr if isinstance(target, ast.Attribute) else None


def _is_rotting_xfail(dec: ast.expr) -> bool:
    if not isinstance(dec, ast.Call) or _marker_name(dec) != _XFAIL:
        return False
    if _is_strict(dec):
        return False
    reason = _reason_text(dec)
    if reason is None or _NONDETERMINISM_RE.search(reason):
        return False
    return bool(_DEFECT_RE.search(reason))


def _is_strict(dec: ast.Call) -> bool:
    for kw in dec.keywords:
        if kw.arg is None:
            # `**marker_kwargs` may carry strict; decline to guess.
            return True
        if kw.arg == "strict":
            return not (isinstance(kw.value, ast.Constant) and kw.value.value is False)
    return False


def _reason_text(dec: ast.Call) -> str | None:
    for kw in dec.keywords:
        if kw.arg == "reason":
            return _literal_text(kw.value)
    return None


def _literal_text(value: ast.expr) -> str | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    # Reasons are routinely wrapped across lines as implicit concatenation or a
    # parenthesised join; read the literal fragments so the match still works.
    if isinstance(value, ast.JoinedStr):
        return "".join(
            part.value for part in value.values if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
        left, right = _literal_text(value.left), _literal_text(value.right)
        return f"{left or ''}{right or ''}" or None
    return None
