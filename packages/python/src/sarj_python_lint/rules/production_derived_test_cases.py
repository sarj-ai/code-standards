"""SARJ409 — Imported production collections are not independent parametrized test oracles.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_production_derived_test_cases.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
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


_COLLECTION_WRAPPERS = frozenset({"sorted", "set", "tuple"})
_PARAMETRIZE_CASES_INDEX = 1
_PARAMETRIZE_MIN_ARGS = 2


class _PytestBindings(NamedTuple):
    modules: set[str]
    marks: set[str]


def _scope_binding_counts(statements: list[ast.stmt]) -> dict[str, int]:
    """Count bindings in one scope without attributing nested scopes to it."""
    counts: dict[str, int] = {}
    stack: list[ast.AST] = [*reversed(statements)]
    while stack:
        node = stack.pop()
        names: set[str] = set()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.Delete)):
            names.update(*(_bound_target_names(target) for target in node.targets))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr, ast.For, ast.AsyncFor)):
            names.update(_bound_target_names(node.target))
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name is not None:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            names.add(node.rest)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            names.update(
                *(_bound_target_names(item.optional_vars) for item in node.items if item.optional_vars is not None)
            )
        for name in names:
            counts[name] = counts.get(name, 0) + 1
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    return counts


def _bound_target_names(node: ast.AST) -> set[str]:
    match node:
        case ast.Name(id=name):
            return {name}
        case ast.Tuple() | ast.List():
            names: set[str] = set()
            for element in node.elts:
                names.update(_bound_target_names(element))
            return names
        case ast.Starred(value=value):
            return _bound_target_names(value)
        case _:
            return set()


def _imported_bindings(tree: ast.Module, binding_counts: dict[str, int]) -> set[str]:
    bindings: set[str] = set()
    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and not node.module.startswith(("test", "tests"))
        ):
            bindings.update(
                local
                for alias in node.names
                if alias.name != "*" and binding_counts.get(local := alias.asname or alias.name, 0) == 1
            )
    return bindings


def _pytest_bindings(tree: ast.Module, binding_counts: dict[str, int]) -> _PytestBindings:
    modules: set[str] = set()
    marks: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(
                local
                for alias in node.names
                if alias.name == "pytest" and binding_counts.get(local := alias.asname or alias.name, 0) == 1
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "pytest":
            marks.update(
                local
                for alias in node.names
                if alias.name == "mark" and binding_counts.get(local := alias.asname or alias.name, 0) == 1
            )
    return _PytestBindings(modules, marks)


def _direct_imported_collection(node: ast.expr, imported: set[str]) -> ast.Name | None:
    if isinstance(node, ast.Name) and node.id in imported and node.id.isupper() and not _is_registry(node.id):
        return node
    if isinstance(node, ast.Call) and _is_imported_collection_wrapper(node, imported):
        # `list(Enum)` / `tuple(Enum)` is an intentional exhaustiveness sweep;
        # only set/sorted/tuple over an ALL_CAPS collection is the risky shape.
        candidate = node.args[0]
        return (
            candidate
            if isinstance(candidate, ast.Name) and candidate.id.isupper() and not _is_registry(candidate.id)
            else None
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Sub, ast.BitOr, ast.BitAnd)):
        for side in (node.left, node.right):
            found = _direct_imported_collection(side, imported)
            if found is not None and found.id.isupper():
                return found
    return None


def _is_registry(name: str) -> bool:
    return name == "REGISTRY" or name.endswith("_REGISTRY")


def _is_imported_collection_wrapper(node: ast.Call, imported: set[str]) -> bool:
    return (
        isinstance(node.func, ast.Name)
        and node.func.id in _COLLECTION_WRAPPERS
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id in imported
    )


def _parametrize_cases(
    decorator: ast.expr,
    pytest_modules: set[str],
    pytest_marks: set[str],
    blocked: set[str],
) -> ast.expr | None:
    if not isinstance(decorator, ast.Call) or len(decorator.args) < _PARAMETRIZE_MIN_ARGS:
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute) or func.attr != "parametrize":
        return None
    owner = func.value
    module_owned = (
        isinstance(owner, ast.Attribute)
        and owner.attr == "mark"
        and isinstance(owner.value, ast.Name)
        and owner.value.id in pytest_modules - blocked
    )
    mark_owned = isinstance(owner, ast.Name) and owner.id in pytest_marks - blocked
    if not module_owned and not mark_owned:
        return None
    return decorator.args[_PARAMETRIZE_CASES_INDEX]


def _collected_tests(tree: ast.Module) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, set[str]]]:
    tests: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, set[str]]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            tests.append((node, set()))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            class_bindings = set(_scope_binding_counts(node.body))
            tests.extend(
                (child, class_bindings)
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_")
            )
    return tests


def _independently_asserted_collections(tree: ast.Module, imported: set[str]) -> set[str]:
    asserted: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert) or not isinstance(node.test, ast.Compare):
            continue
        compare = node.test
        if len(compare.ops) != 1 or not isinstance(compare.ops[0], ast.Eq) or len(compare.comparators) != 1:
            continue
        for side in (compare.left, compare.comparators[0]):
            if isinstance(side, ast.Name) and side.id in imported:
                asserted.add(side.id)
    return asserted


@final
class ProductionDerivedTestCases(Rule):
    id = "production-derived-test-cases"
    code = "SARJ409"
    documentation = RuleDocumentation(
        summary="Parametrized test cases come from the production collection whose membership they should protect.",
        rationale=(
            "Removing a production member can remove the corresponding test case too, allowing the same defect to "
            "weaken both the implementation and its supposed oracle."
        ),
        remediation="Define an independent expected table, assert production equals it, and drive behavior from that table.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct imported collections, simple collection wrappers, and direct set expressions in pytest parametrization are checked.",
            "Local expected tables, test-helper fixtures, enum exhaustiveness, names ending in `_REGISTRY`, and collections whose exact membership is asserted elsewhere in the module are excluded.",
            "Project-wide relationships hidden behind helpers require judgment and remain unreported.",
        ),
        examples=(
            RuleExample(
                example_id="independent-model-cases",
                title="Drive behavior from an independent expected table",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_models.py",
                        "import pytest\n\nEXPECTED_MODELS = ('a', 'b')\n\n@pytest.mark.parametrize('model', EXPECTED_MODELS)\ndef test_model(model):\n    assert build(model).tier == 'priority'\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_models.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="production-derived-model-cases",
                title="Do not derive cases from production eligibility",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_models.py",
                        "import pytest\nfrom app.models import ELIGIBLE_MODELS\n\n@pytest.mark.parametrize('model', ELIGIBLE_MODELS)\ndef test_model(model):\n    assert build(model).tier == 'priority'\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_models.py"),
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
        binding_counts = _scope_binding_counts(tree.body)
        imported = _imported_bindings(tree, binding_counts)
        pytest_bindings = _pytest_bindings(tree, binding_counts)
        independently_asserted = _independently_asserted_collections(tree, imported)
        findings: list[Diagnostic] = []
        for node, blocked in _collected_tests(tree):
            for decorator in node.decorator_list:
                cases = _parametrize_cases(
                    decorator,
                    pytest_bindings.modules,
                    pytest_bindings.marks,
                    blocked,
                )
                if cases is None:
                    continue
                collection = _direct_imported_collection(cases, imported)
                if collection is None or collection.id in independently_asserted:
                    continue
                findings.append(
                    Diagnostic(
                        path=path,
                        line=decorator.lineno,
                        col=decorator.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=(
                            f"`{collection.id}` supplies the cases from production, so removing a member can remove "
                            "the test that should catch the regression; define an independent expected case table and "
                            "assert the production collection equals it."
                        ),
                    )
                )
        findings.sort(key=lambda finding: (finding.line, finding.col))
        return findings
