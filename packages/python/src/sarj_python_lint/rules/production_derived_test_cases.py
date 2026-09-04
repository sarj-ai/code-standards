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
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._first_party import FirstPartyFacts, has_first_party_source, is_first_party_module
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


_COLLECTION_WRAPPERS = frozenset({"frozenset", "list", "set", "sorted", "tuple"})
_MEMBERSHIP_TOKENS = frozenset({"allowed", "eligible", "required", "supported"})
_PARAMETRIZE_CASES_INDEX = 1
_TEST_MODULE_PARTS = frozenset({"conftest", "fixture", "fixtures", "test", "testdata", "testing", "tests"})
_TEST_SUPPORT_TOKENS = frozenset({"double", "doubles", "fake", "fakes", "fixture", "fixtures", "mock", "mocks", "stub", "stubs", "test", "testing", "tests"})


class _PytestBindings(NamedTuple):
    modules: set[str]
    marks: set[str]


class _CollectedTest(NamedTuple):
    function: ast.FunctionDef | ast.AsyncFunctionDef
    class_bindings: set[str]


def _scope_binding_counts(statements: list[ast.stmt]) -> dict[str, int]:
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


def _imported_bindings(
    tree: ast.Module,
    binding_counts: dict[str, int],
    path: Path,
    facts: FirstPartyFacts,
) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.level == 0
            and _is_first_party_production_module(node.module, path, facts)
        ):
            bindings.update(
                (local, node.module)
                for alias in node.names
                if alias.name != "*"
                and binding_counts.get(local := alias.asname or alias.name, 0) == 1
                and _is_membership_contract(local)
            )
    return bindings


def _is_first_party_production_module(module: str, path: Path, facts: FirstPartyFacts) -> bool:
    parts = module.lower().split(".")
    if any(_is_test_support_module_part(part) for part in parts):
        return False
    top = module.partition(".")[0]
    path_parts = {part.lower() for part in path.parts}
    return top.lower() in path_parts or (
        is_first_party_module(module, path, facts=facts) and has_first_party_source(module, path, facts=facts)
    )


def _is_test_support_module_part(part: str) -> bool:
    return part in _TEST_MODULE_PARTS or bool(_TEST_SUPPORT_TOKENS & set(part.split("_")))


def _is_membership_contract(name: str) -> bool:
    return bool(_MEMBERSHIP_TOKENS & set(name.lower().split("_")))


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


def _direct_imported_collection(
    node: ast.expr,
    imported: Mapping[str, str],
    blocked: set[str],
    builtin_wrappers: frozenset[str],
) -> ast.Name | None:
    if isinstance(node, ast.Name) and node.id in imported and node.id not in blocked and not _is_registry(node.id):
        return node
    if isinstance(node, ast.Call) and _is_imported_collection_wrapper(node, imported, builtin_wrappers):
        # `list(Enum)` / `tuple(Enum)` is an intentional exhaustiveness sweep;
        # only set/sorted/tuple over an ALL_CAPS collection is the risky shape.
        candidate = node.args[0]
        return (
            candidate
            if isinstance(candidate, ast.Name)
            and candidate.id not in blocked
            and not _is_registry(candidate.id)
            else None
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Sub, ast.BitOr, ast.BitAnd)):
        for side in (node.left, node.right):
            found = _direct_imported_collection(side, imported, blocked, builtin_wrappers)
            if found is not None:
                return found
    return None


def _is_registry(name: str) -> bool:
    return name == "REGISTRY" or name.endswith("_REGISTRY")


def _is_imported_collection_wrapper(
    node: ast.Call,
    imported: Mapping[str, str],
    builtin_wrappers: frozenset[str],
) -> bool:
    return (
        isinstance(node.func, ast.Name)
        and node.func.id in builtin_wrappers
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
    if not isinstance(decorator, ast.Call):
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
    if len(decorator.args) > _PARAMETRIZE_CASES_INDEX:
        return decorator.args[_PARAMETRIZE_CASES_INDEX]
    return next((keyword.value for keyword in decorator.keywords if keyword.arg == "argvalues"), None)


def _collected_tests(tree: ast.Module) -> list[_CollectedTest]:
    tests: list[_CollectedTest] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            tests.append(_CollectedTest(node, set()))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            class_bindings = set(_scope_binding_counts(node.body))
            tests.extend(
                _CollectedTest(child, class_bindings)
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_")
            )
    return tests


def _independently_asserted_collections(
    tree: ast.Module,
    imported: Mapping[str, str],
    tests: list[_CollectedTest],
) -> set[str]:
    expected = _independent_expected_bindings(tree, _scope_binding_counts(tree.body))
    asserted: set[str] = set()
    assertions = [node for node in tree.body if isinstance(node, ast.Assert)]
    assertions.extend(
        statement
        for test in tests
        for statement in test.function.body
        if isinstance(statement, ast.Assert)
    )
    for node in assertions:
        if not isinstance(node.test, ast.Compare):
            continue
        compare = node.test
        if len(compare.ops) != 1 or not isinstance(compare.ops[0], ast.Eq) or len(compare.comparators) != 1:
            continue
        left, right = compare.left, compare.comparators[0]
        if isinstance(left, ast.Name) and left.id in imported and _is_independent_expected(right, expected):
            asserted.add(left.id)
        if isinstance(right, ast.Name) and right.id in imported and _is_independent_expected(left, expected):
            asserted.add(right.id)
    return asserted


def _independent_expected_bindings(tree: ast.Module, binding_counts: dict[str, int]) -> set[str]:
    return {
        target.id
        for statement in tree.body
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
        for target in _assignment_targets(statement)
        if isinstance(target, ast.Name)
        if binding_counts.get(target.id) == 1 and _is_immutable_literal_table(statement.value)
    }


def _assignment_targets(statement: ast.Assign | ast.AnnAssign) -> list[ast.expr]:
    return statement.targets if isinstance(statement, ast.Assign) else [statement.target]


def _is_independent_expected(node: ast.expr, expected: set[str]) -> bool:
    return (isinstance(node, ast.Name) and node.id in expected) or _is_literal_table(node)


def _is_immutable_literal_table(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Tuple) and _is_literal_table(node)


def _is_literal_table(node: ast.expr | None) -> bool:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)) or not node.elts:
        return False
    return all(isinstance(item, (ast.Constant, ast.Attribute)) for item in node.elts)


@final
class ProductionDerivedTestCases(Rule):
    id = "production-derived-test-cases"
    code = "SARJ409"
    documentation = RuleDocumentation(
        summary="Warn when pytest membership-contract cases are derived only from the first-party production collection.",
        rationale=(
            "When exact eligibility or support membership is contractual, deriving cases from production lets a member "
            "change without an independent test oracle failing."
        ),
        remediation=(
            "For contractual membership, define a literal expected table, assert the production collection equals it, "
            "and drive behavior from the expected table. Suppress the warning with rationale for an intentional dynamic sweep."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only proven first-party, non-test imports with eligible, supported, allowed, or required in their names are checked in collected pytest parametrization.",
            "Direct collections, simple unshadowed builtin wrappers, set expressions, and positional or keyword argvalues are recognized.",
            "A direct module-level or collected-test equality against a distinct literal expected table proves an independent oracle; helper-indirected relationships remain unreported.",
        ),
        examples=(
            RuleExample(
                example_id="independent-model-cases",
                title="Drive behavior from an independent expected table",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/tests/test_models.py",
                        "import pytest\nfrom app.models import ELIGIBLE_MODELS\n\nEXPECTED_MODELS = ('a', 'b')\n\ndef test_model_membership():\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n\n@pytest.mark.parametrize('model', EXPECTED_MODELS)\ndef test_model(model):\n    assert build(model).tier == 'priority'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/tests/test_models.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="production-derived-model-cases",
                title="Do not derive cases from production eligibility",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/tests/test_models.py",
                        "import pytest\nfrom app.models import ELIGIBLE_MODELS\n\n@pytest.mark.parametrize('model', ELIGIBLE_MODELS)\ndef test_model(model):\n    assert build(model).tier == 'priority'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/tests/test_models.py"),
                expected_count=1,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        lowered = source.lower()
        if (
            "parametrize" not in source
            or not any(token in lowered for token in _MEMBERSHIP_TOKENS)
            or not is_test_path(path)
            or is_generated(path, source)
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        binding_counts = _scope_binding_counts(tree.body)
        facts = self._analysis_session.first_party if self._analysis_session is not None else FirstPartyFacts()
        imported = _imported_bindings(tree, binding_counts, path, facts)
        if not imported:
            return []
        pytest_bindings = _pytest_bindings(tree, binding_counts)
        tests = _collected_tests(tree)
        independently_asserted = _independently_asserted_collections(tree, imported, tests)
        builtin_wrappers = _COLLECTION_WRAPPERS - binding_counts.keys()
        source_lines = source.splitlines()
        findings: list[Diagnostic] = []
        for node, blocked in tests:
            for decorator in node.decorator_list:
                cases = _parametrize_cases(
                    decorator,
                    pytest_bindings.modules,
                    pytest_bindings.marks,
                    blocked,
                )
                if cases is None:
                    continue
                collection = _direct_imported_collection(cases, imported, blocked, frozenset(builtin_wrappers))
                if (
                    collection is None
                    or collection.id in independently_asserted
                    or is_suppressed(source_lines, decorator.lineno, self.code)
                ):
                    continue
                findings.append(
                    Diagnostic(
                        path=path,
                        line=decorator.lineno,
                        col=decorator.col_offset + 1,
                        code=self.code,
                        severity=Severity.ERROR,
                        message=(
                            f"`{collection.id}` supplies membership cases from production; if exact membership is "
                            "contractual, define an independent literal table, assert production equals it, and drive "
                            "behavior from that table."
                        ),
                    )
                )
        findings.sort(key=lambda finding: (finding.line, finding.col))
        return findings
