from __future__ import annotations

import ast
from collections import Counter
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
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import walk
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_XFAIL = "xfail"

# Reason text that identifies a pinned defect rather than an environment gate.
_DEFECT_RE = re.compile(r"\b(bug|broken|defect|regression|incorrect|wrong|fixme)\b", re.IGNORECASE)
_SHOULD_CONTRAST_RE = re.compile(r"\bshould\b.+\b(but|instead)\b", re.IGNORECASE)

# A linked tracker issue is itself an explicit defect pin.  Keep this narrow to
# GitHub's canonical issue route: arbitrary URLs frequently document platform
# requirements or upstream behavior rather than a defect this test pins.
_GITHUB_ISSUE_RE = re.compile(r"https?://github\.com/[^/\s]+/[^/\s]+/issues/\d+\b", re.IGNORECASE)

# Reason text conceding the outcome genuinely varies run to run.
_NONDETERMINISM_RE = re.compile(r"intermittent|flak|sometimes|non-?deterministic|varies", re.IGNORECASE)

# Sibling markers that declare a nondeterministic dependency.
_NONDETERMINISTIC_MARKERS = frozenset({"real_llm", "flaky", "network"})

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
        summary="A deterministic known-defect `xfail` must set literal `strict=True` so XPASS fails the suite.",
        rationale=(
            "A defect pin that relies on pytest's configurable strictness default can stay green after the defect is "
            "fixed, leaving stale coverage and markers behind. Literal local strictness keeps the invariant attached "
            "to the pin independently of repository configuration."
        ),
        remediation=(
            "Set literal `strict=True` so an unexpected pass fails. If only some parameter cases carry the defect, "
            "move the marker to those `pytest.param(...)` cases before making it strict."
        ),
        category=RuleCategory.TESTING,
        aliases=("defect-xfail-requires-strict", "xfail-requires-strict"),
        limitations=(
            "Only markers resolved through an unambiguous pytest or pytest.mark import are analyzed.",
            "Only xfail reasons that explicitly identify a defect are analyzed.",
            "Nondeterministic, recognized Hypothesis, network, environment-gated, run=False, and statically disabled pins are excluded.",
            "Repository-level strict_xfail / xfail_strict configuration is intentionally not consulted: defect pins remain locally explicit.",
            "Default pytest test_/Test collection names are recognized; repositories with custom collection patterns may need a local suppression.",
        ),
        examples=(
            RuleExample(
                example_id="non-strict-defect-pin",
                title="Unexpected pass does not fail the suite",
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
                title="Unexpected pass fails the suite",
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
        if not is_test_path(path) or path.name == "conftest.py" or is_generated(path, source):
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
                    "fixed its XPASS may not fail the suite. Add literal `strict=True`; if only some "
                    "parameter cases fail, move the marker to those `pytest.param` cases first."
                ),
                severity=Severity.WARNING,
            )
            for node in _rotting_bug_pins(tree, imports)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _rotting_bug_pins(tree: ast.Module, imports: ImportIndex) -> list[ast.Call]:
    xfail_aliases = _module_xfail_aliases(tree, imports)
    collected = list(_collected_functions(tree.body))
    hits = (
        _rotting_markers(_module_pytest_markers(tree, imports, xfail_aliases), imports, xfail_aliases)
        if collected
        else []
    )
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not node.name.startswith("Test"):
            continue
        methods = list(_collected_functions(node.body))
        if methods:
            hits.extend(_rotting_markers(node.decorator_list, imports, xfail_aliases))
        collected.extend(methods)
    for node in collected:
        if _is_fixture(node.decorator_list, imports):
            continue
        hits.extend(_rotting_markers(node.decorator_list, imports, xfail_aliases))
        hits.extend(_rotting_param_markers(node.decorator_list, imports, xfail_aliases))
    return hits


def _collected_functions(body: list[ast.stmt]) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [node for node in body if isinstance(node, _FUNC_NODES) and node.name.startswith("test")]


def _rotting_markers(markers: list[ast.expr], imports: ImportIndex, xfail_aliases: frozenset[str]) -> list[ast.Call]:
    if _has_nondeterministic_marker(markers, imports):
        return []
    return [
        marker
        for marker in markers
        if isinstance(marker, ast.Call) and _is_rotting_xfail(marker, imports, xfail_aliases)
    ]


def _rotting_param_markers(
    decorators: list[ast.expr], imports: ImportIndex, xfail_aliases: frozenset[str]
) -> list[ast.Call]:
    if _has_nondeterministic_marker(decorators, imports):
        return []
    return [
        nested
        for decorator in decorators
        if _pytest_marker_name(decorator, imports) == _PARAMETRIZE_ATTR
        for nested in walk(decorator)
        if isinstance(nested, ast.Call)
        and nested is not decorator
        and _is_rotting_xfail(nested, imports, xfail_aliases)
    ]


def _module_pytest_markers(tree: ast.Module, imports: ImportIndex, xfail_aliases: frozenset[str]) -> list[ast.expr]:
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
    return (
        markers
        if markers and all(_pytest_marker_name(marker, imports, xfail_aliases) is not None for marker in markers)
        else []
    )


def _has_nondeterministic_marker(decorators: list[ast.expr], imports: ImportIndex) -> bool:
    return any(
        _pytest_marker_name(dec, imports) in _NONDETERMINISTIC_MARKERS or _is_property_based(dec, imports)
        for dec in decorators
    )


def _is_property_based(dec: ast.expr, imports: ImportIndex) -> bool:
    target = dec.func if isinstance(dec, ast.Call) else dec
    if imports.resolves(target, sources=frozenset({"hypothesis"}), symbol="given"):
        return True
    if not isinstance(target, ast.Attribute) or target.attr != _PARAMETRIZE_ATTR:
        return False
    # Exclude pytest.mark.parametrize because its fixed table is not property-based generation.
    return _pytest_marker_name(dec, imports) != _PARAMETRIZE_ATTR


def _pytest_marker_name(dec: ast.expr, imports: ImportIndex, xfail_aliases: frozenset[str] = frozenset()) -> str | None:
    target = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(target, ast.Name) and target.id in xfail_aliases:
        return _XFAIL
    if not isinstance(target, ast.Attribute):
        return None
    if imports.resolves(target, sources=_PYTEST_MARK_MODULE, symbol=target.attr):
        return target.attr
    if imports.resolves(target.value, sources=_PYTEST, symbol=_PYTEST_MARK):
        return target.attr
    return None


def _is_rotting_xfail(dec: ast.expr, imports: ImportIndex, xfail_aliases: frozenset[str]) -> bool:
    if not isinstance(dec, ast.Call) or _pytest_marker_name(dec, imports, xfail_aliases) != _XFAIL:
        return False
    if _is_strict(dec) or _cannot_xpass(dec) or _is_environment_gated(dec, imports):
        return False
    reason = _reason_text(dec)
    if reason is None or _NONDETERMINISM_RE.search(reason):
        return False
    return bool(_DEFECT_RE.search(reason) or _SHOULD_CONTRAST_RE.search(reason) or _GITHUB_ISSUE_RE.search(reason))


def _module_xfail_aliases(tree: ast.Module, imports: ImportIndex) -> frozenset[str]:
    stores = Counter(node.id for node in walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store))
    aliases = {
        alias for statement in tree.body if (alias := _unique_xfail_alias(statement, stores, imports)) is not None
    }
    return frozenset(aliases)


def _unique_xfail_alias(statement: ast.stmt, stores: Counter[str], imports: ImportIndex) -> str | None:
    target: ast.Name | None = None
    value: ast.expr | None = None
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        target, value = statement.target, statement.value
    elif isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        assigned = statement.targets[0]
        if isinstance(assigned, ast.Name):
            target, value = assigned, statement.value
    if target is None or value is None or stores[target.id] != 1:
        return None
    return target.id if _pytest_marker_name(value, imports) == _XFAIL else None


# Imported probes that identify interpreter, operating-system, or runtime capabilities.
_ENV_PROBE_SYMBOLS = (
    ("sys", frozenset({"implementation", "platform", "version", "version_info", "pypy_version_info"})),
    ("os", frozenset({"environ", "getenv", "name", "uname"})),
    (
        "platform",
        frozenset(
            {"implementation", "machine", "platform", "python_implementation", "python_version", "release", "system"}
        ),
    ),
    ("sysconfig", frozenset({"get_config_var", "get_platform", "get_python_version"})),
)


def _is_environment_gated(dec: ast.Call, imports: ImportIndex) -> bool:
    conditions = [*dec.args, *(kw.value for kw in dec.keywords if kw.arg == "condition")]
    for condition in conditions:
        parsed_condition = condition
        if isinstance(condition, ast.Constant) and isinstance(condition.value, str):
            try:
                parsed_condition = ast.parse(condition.value, mode="eval").body
            except SyntaxError:
                continue
        for node in walk(parsed_condition):
            if not isinstance(node, ast.expr):
                continue
            for module, symbols in _ENV_PROBE_SYMBOLS:
                if any(imports.resolves(node, sources=frozenset({module}), symbol=symbol) for symbol in symbols):
                    return True
    return False


def _is_fixture(decorators: list[ast.expr], imports: ImportIndex) -> bool:
    return any(
        imports.resolves(dec.func if isinstance(dec, ast.Call) else dec, sources=_PYTEST, symbol="fixture")
        for dec in decorators
    )


def _is_strict(dec: ast.Call) -> bool:
    for kw in dec.keywords:
        if kw.arg is None:
            # `**marker_kwargs` may carry strict; decline to guess.
            return True
        if kw.arg == "strict":
            return isinstance(kw.value, ast.Constant) and kw.value.value is True
    return False


def _cannot_xpass(dec: ast.Call) -> bool:
    for kw in dec.keywords:
        if kw.arg == "run" and _is_statically_false(kw.value):
            return True
        if kw.arg == "condition" and _is_statically_false(kw.value, parse_string=True):
            return True
    return bool(dec.args and _is_statically_false(dec.args[0], parse_string=True))


def _is_statically_false(value: ast.expr, *, parse_string: bool = False) -> bool:
    candidate = value
    if parse_string and isinstance(value, ast.Constant) and isinstance(value.value, str):
        try:
            candidate = ast.parse(value.value, mode="eval").body
        except SyntaxError:
            return False
    if not isinstance(candidate, ast.Constant):
        return False
    match candidate.value:
        case None | False | 0 | "":
            return True
        case _:
            return False


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
            fragments: list[str] = []
            for part in parts:
                if not isinstance(part, ast.Constant) or not isinstance(part.value, str):
                    return None
                fragments.append(part.value)
            return "".join(fragments)
        case ast.BinOp(left=left_node, op=ast.Add(), right=right_node):
            left, right = _literal_text(left_node), _literal_text(right_node)
            return f"{left}{right}" if left is not None and right is not None else None
        case _:
            return None
