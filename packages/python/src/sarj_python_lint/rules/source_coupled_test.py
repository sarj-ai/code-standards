"""SARJ402 — tests must not use raw repository source text as behavioral proof.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_source_coupled_test.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

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
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_SOURCE_SUFFIXES = (".tf", ".tfvars", ".hcl", ".yaml", ".yml", ".py", ".js", ".mjs", ".ts")
_TEXT_TRANSFORMS = frozenset({"casefold", "lower", "lstrip", "replace", "rstrip", "strip", "upper"})
_TEXT_ASSERTIONS = frozenset({"count", "endswith", "find", "index", "startswith"})
_REGEX_ASSERTIONS = frozenset({"findall", "fullmatch", "match", "search"})
_EPHEMERAL_PATH_NAMES = frozenset({"tmp_path", "tmpdir", "temp_dir", "temporary_directory"})


@final
class SourceCoupledTest(Rule):
    id = "source-coupled-test"
    code = "SARJ402"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Test asserts on raw repository source text instead of parsed or executable behavior.",
        rationale="Substring and regex checks can pass on comments or unreachable configuration and fail after behavior-preserving formatting changes.",
        remediation="Parse the artifact, execute its validator, or assert on Terraform plan JSON or another runtime contract.",
        category=RuleCategory.TESTING,
        limitations=(
            "The rule follows local aliases and common text normalization only; dynamic paths and interprocedural flows remain unreported.",
            "When raw representation is genuinely the contract (for example a golden or compatibility sentinel), use an exact line suppression with the reason.",
        ),
        examples=(
            RuleExample(
                example_id="parsed-terraform-contract",
                title="Assert on parsed plan behavior",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_policy.py",
                        "def test_policy():\n    plan = json.loads(Path('plan.json').read_text())\n    assert verify(plan) == []\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_policy.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="terraform-substring-contract",
                title="Do not prove Terraform behavior with a substring",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_policy.py",
                        "def test_policy():\n    source = Path('main.tf').read_text()\n    assert 'prevent_destroy = true' in source\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_policy.py"),
                expected_count=1,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diagnostics: list[Diagnostic] = []
        for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            raw_names = _raw_bindings(function)
            if not raw_names:
                continue
            for assertion in (node for node in ast.walk(function) if isinstance(node, ast.Assert)):
                if _raw_text_oracle(assertion.test, raw_names):
                    diagnostics.append(
                        Diagnostic(
                            path=path,
                            line=assertion.lineno,
                            col=assertion.col_offset + 1,
                            code=self.code,
                            severity=Severity.WARNING,
                            message=(
                                "raw repository source text is the test oracle; parse or execute the artifact so comments, formatting, and unreachable blocks cannot satisfy the contract."
                            ),
                        )
                    )
                    break
        return diagnostics


def _raw_bindings(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    bindings: dict[str, ast.expr] = {}
    for node in ast.walk(function):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if value is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = value
    ephemeral_paths = set(_EPHEMERAL_PATH_NAMES)
    paths_changed = True
    while paths_changed:
        paths_changed = False
        for name, value in bindings.items():
            if name not in ephemeral_paths and _contains_ephemeral_path(value, ephemeral_paths):
                ephemeral_paths.add(name)
                paths_changed = True
    raw = {name for name, value in bindings.items() if _is_raw_source_read(value, ephemeral_paths)}
    changed = True
    while changed:
        changed = False
        for name, value in bindings.items():
            if name not in raw and _derived_raw_text(value, raw):
                raw.add(name)
                changed = True
    return raw


def _is_raw_source_read(node: ast.expr, ephemeral_paths: set[str] | frozenset[str] = _EPHEMERAL_PATH_NAMES) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute) and node.func.attr == "read_text":
        return _contains_source_suffix(node.func.value) and not _contains_ephemeral_path(
            node.func.value, ephemeral_paths
        )
    if isinstance(node.func, ast.Attribute) and node.func.attr == "read" and isinstance(node.func.value, ast.Call):
        opened = node.func.value
        return (
            isinstance(opened.func, ast.Name)
            and opened.func.id == "open"
            and bool(opened.args)
            and _contains_source_suffix(opened.args[0])
            and not _contains_ephemeral_path(opened.args[0], ephemeral_paths)
        )
    return False


def _contains_source_suffix(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and child.value.lower().endswith(_SOURCE_SUFFIXES)
        for child in ast.walk(node)
    )


def _contains_ephemeral_path(node: ast.AST, ephemeral_paths: set[str] | frozenset[str]) -> bool:
    return any(isinstance(child, ast.Name) and child.id in ephemeral_paths for child in ast.walk(node))


def _derived_raw_text(node: ast.expr, raw_names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in raw_names
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _TEXT_TRANSFORMS
        and _contains_raw_name(node.func.value, raw_names)
    )


def _contains_raw_name(node: ast.AST, raw_names: set[str]) -> bool:
    return any(isinstance(child, ast.Name) and child.id in raw_names for child in ast.walk(node))


def _raw_text_oracle(node: ast.expr, raw_names: set[str]) -> bool:
    if (
        isinstance(node, ast.Compare)
        and (
            _raw_text_expression(node.left, raw_names)
            or any(_raw_text_expression(comparator, raw_names) for comparator in node.comparators)
        )
        and any(isinstance(operator, (ast.In, ast.NotIn, ast.Eq, ast.NotEq)) for operator in node.ops)
    ):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in _TEXT_ASSERTIONS and _contains_raw_name(node.func.value, raw_names):
            return True
        if node.func.attr in _REGEX_ASSERTIONS and any(_contains_raw_name(arg, raw_names) for arg in node.args):
            return True
    return any(
        _raw_text_oracle(child, raw_names) for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr)
    )


def _raw_text_expression(node: ast.expr, raw_names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in raw_names
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in (_TEXT_TRANSFORMS | _TEXT_ASSERTIONS)
        and _raw_text_expression(node.func.value, raw_names)
    )
