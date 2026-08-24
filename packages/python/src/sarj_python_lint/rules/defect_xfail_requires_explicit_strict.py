from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_XFAIL = "xfail"

# Reason text that identifies a pinned defect rather than an environment gate.
_DEFECT_RE = re.compile(r"\b(bug|broken|defect|regression|incorrect|should|wrong|fixme)\b", re.IGNORECASE)

# A linked tracker issue is itself an explicit defect pin.  Keep this narrow to
# GitHub's canonical issue route: arbitrary URLs frequently document platform
# requirements or upstream behavior rather than a defect this test pins.
_GITHUB_ISSUE_RE = re.compile(r"https?://github\.com/[^/\s]+/[^/\s]+/issues/\d+\b", re.IGNORECASE)

# Reason text conceding the outcome genuinely varies run to run.
_NONDETERMINISM_RE = re.compile(r"intermittent|flak|sometimes|non-?deterministic|varies", re.IGNORECASE)

# Sibling markers that declare a nondeterministic dependency.
_NONDETERMINISTIC_MARKERS = frozenset({"real_llm", "flaky", "network"})

# Hypothesis' entry point.
_PROPERTY_DECORATORS = frozenset({"given"})

# schemathesis binds `.parametrize()` on a schema object.
_PARAMETRIZE_ATTR = "parametrize"
_PYTEST_MARK = "mark"
_PYTEST = frozenset({"pytest"})
_PYTEST_MARK_MODULE = frozenset({"pytest.mark"})

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_PYTESTMARK = "pytestmark"


class DefectXfailRequiresExplicitStrict(Rule):
    id: str = "defect-xfail-requires-explicit-strict"
    code: str = "SARJ046"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Defect-pinning `xfail` must explicitly set `strict=True` so an XPASS cannot silently pass.",
        rationale=(
            "A defect pin that relies on pytest's configurable strictness default can stay green after the defect is "
            "fixed, leaving stale coverage and markers behind. Local strictness keeps the invariant attached to the pin."
        ),
        remediation="Set `strict=True` so an unexpected pass fails and prompts removal of the obsolete marker.",
        category=RuleCategory.TESTING,
        aliases=("defect-xfail-requires-strict", "xfail-requires-strict"),
        limitations=(
            "Only markers resolved through an unambiguous pytest or pytest.mark import are analyzed.",
            "Only xfail reasons that explicitly identify a defect are analyzed.",
            "Nondeterministic, property-based, network, environment-gated, run=False, and statically disabled pins are excluded.",
            "Repository-level strict_xfail / xfail_strict configuration is intentionally not consulted: defect pins remain locally explicit.",
        ),
        examples=(
            RuleExample(
                example_id="non-strict-defect-pin",
                title="Fixed defect would pass silently",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_api.py",
                        'import pytest\n\n@pytest.mark.xfail(reason="BUG: wrong status code")\ndef test_status():\n    assert response_status() == 200\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="strict-defect-pin",
                title="Fixed defect fails loudly",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_api.py",
                        'import pytest\n\n@pytest.mark.xfail(reason="BUG: wrong status code", strict=True)\ndef test_status():\n    assert response_status() == 200\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_api.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        imports = ImportIndex.from_tree(tree)
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
            for node in _rotting_bug_pins(tree, imports)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _rotting_bug_pins(tree: ast.Module, imports: ImportIndex) -> list[ast.Call]:
    hits = _rotting_markers(_module_pytest_markers(tree, imports), imports)
    for node in nodes(tree, ast.ClassDef):
        if node.name.startswith("Test"):
            hits.extend(_rotting_markers(node.decorator_list, imports))
    for node in nodes(tree, *_FUNC_NODES):
        hits.extend(_rotting_markers(node.decorator_list, imports))
        hits.extend(_rotting_param_markers(node.decorator_list, imports))
    return hits


def _rotting_markers(markers: list[ast.expr], imports: ImportIndex) -> list[ast.Call]:
    if _has_nondeterministic_marker(markers, imports):
        return []
    return [marker for marker in markers if isinstance(marker, ast.Call) and _is_rotting_xfail(marker, imports)]


def _rotting_param_markers(decorators: list[ast.expr], imports: ImportIndex) -> list[ast.Call]:
    if _has_nondeterministic_marker(decorators, imports):
        return []
    return [
        nested
        for decorator in decorators
        if _pytest_marker_name(decorator, imports) == _PARAMETRIZE_ATTR
        for nested in walk(decorator)
        if isinstance(nested, ast.Call) and nested is not decorator and _is_rotting_xfail(nested, imports)
    ]


def _module_pytest_markers(tree: ast.Module, imports: ImportIndex) -> list[ast.expr]:
    values: list[ast.expr] = []
    for statement in tree.body:
        match statement:
            case ast.Assign(targets=[ast.Name(id=name)], value=value) if name == _PYTESTMARK:
                values.append(value)
            case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value) if name == _PYTESTMARK:
                values.append(value)
            case _:
                continue
    if len(values) != 1:
        return []
    value = values[0]
    markers = list(value.elts) if isinstance(value, (ast.List, ast.Tuple)) else [value]
    return markers if markers and all(_pytest_marker_name(marker, imports) is not None for marker in markers) else []


def _has_nondeterministic_marker(decorators: list[ast.expr], imports: ImportIndex) -> bool:
    return any(
        _pytest_marker_name(dec, imports) in _NONDETERMINISTIC_MARKERS or _is_property_based(dec, imports)
        for dec in decorators
    )


def _is_property_based(dec: ast.expr, imports: ImportIndex) -> bool:
    target = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(target, ast.Name):
        return target.id in _PROPERTY_DECORATORS
    if not isinstance(target, ast.Attribute) or target.attr != _PARAMETRIZE_ATTR:
        return False
    # Exclude pytest.mark.parametrize because its fixed table is not property-based generation.
    return _pytest_marker_name(dec, imports) != _PARAMETRIZE_ATTR


def _pytest_marker_name(dec: ast.expr, imports: ImportIndex) -> str | None:
    target = dec.func if isinstance(dec, ast.Call) else dec
    if not isinstance(target, ast.Attribute):
        return None
    if imports.resolves(target, sources=_PYTEST_MARK_MODULE, symbol=target.attr):
        return target.attr
    if imports.resolves(target.value, sources=_PYTEST, symbol=_PYTEST_MARK):
        return target.attr
    return None


def _is_rotting_xfail(dec: ast.expr, imports: ImportIndex) -> bool:
    if not isinstance(dec, ast.Call) or _pytest_marker_name(dec, imports) != _XFAIL:
        return False
    if _is_strict(dec) or _cannot_xpass(dec) or _is_environment_gated(dec):
        return False
    reason = _reason_text(dec)
    if reason is None or _NONDETERMINISM_RE.search(reason):
        return False
    return bool(_DEFECT_RE.search(reason) or _GITHUB_ISSUE_RE.search(reason))


# Modules whose reads describe the environment the suite happens to run in.
_ENV_PROBE_MODULES = frozenset({"sys", "os", "platform", "sysconfig"})

# Attribute / name words that identify an interpreter- or OS-version probe.
_ENV_PROBE_RE = re.compile(
    r"version|implementation|platform|machine|pypy|jython|win32|windows|linux|darwin|macos", re.IGNORECASE
)


def _is_environment_gated(dec: ast.Call) -> bool:
    conditions = [*dec.args, *(kw.value for kw in dec.keywords if kw.arg == "condition")]
    for condition in conditions:
        parsed_condition = condition
        if isinstance(condition, ast.Constant) and isinstance(condition.value, str):
            try:
                parsed_condition = ast.parse(condition.value, mode="eval").body
            except SyntaxError:
                continue
        for node in walk(parsed_condition):
            if isinstance(node, ast.Name) and (node.id in _ENV_PROBE_MODULES or _ENV_PROBE_RE.search(node.id)):
                return True
            if isinstance(node, ast.Attribute) and _ENV_PROBE_RE.search(node.attr):
                return True
    return False


def _is_strict(dec: ast.Call) -> bool:
    for kw in dec.keywords:
        if kw.arg is None:
            # `**marker_kwargs` may carry strict; decline to guess.
            return True
        if kw.arg == "strict":
            return not (isinstance(kw.value, ast.Constant) and kw.value.value is False)
    return False


def _cannot_xpass(dec: ast.Call) -> bool:
    for kw in dec.keywords:
        if kw.arg == "run" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
            return True
        if kw.arg == "condition" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
            return True
    return bool(dec.args and isinstance(dec.args[0], ast.Constant) and dec.args[0].value is False)


def _reason_text(dec: ast.Call) -> str | None:
    for kw in dec.keywords:
        if kw.arg == "reason":
            return _literal_text(kw.value)
    return None


def _literal_text(value: ast.expr) -> str | None:
    match value:
        case ast.Constant(value=str() as text):
            return text
        # Reasons are routinely wrapped across lines as implicit concatenation
        # or a parenthesised join; read the literal fragments so the match works.
        case ast.JoinedStr(values=parts):
            return "".join(
                text for part in parts if isinstance(part, ast.Constant) and isinstance(text := part.value, str)
            )
        case ast.BinOp(left=left_node, op=ast.Add(), right=right_node):
            left, right = _literal_text(left_node), _literal_text(right_node)
            return f"{left or ''}{right or ''}" or None
        case _:
            return None
