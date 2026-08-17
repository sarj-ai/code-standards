"""SARJ410 — Repeated unseeded PRNG sampling makes a test probabilistic.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_uncontrolled_randomness_in_test.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
    from collections.abc import Iterator
    from pathlib import Path


_PRNG_FUNCTIONS = frozenset({"choice", "choices", "randint", "random", "randrange", "sample", "shuffle", "uniform"})
_REPEAT_NODES = (ast.For, ast.AsyncFor, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


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


def _scope_binding_events(statements: list[ast.stmt]) -> list[str]:
    """Return binding events in one scope without entering nested scopes."""
    bindings: list[str] = []
    stack: list[ast.AST] = [*reversed(statements)]
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings.append(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bindings.extend(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.Delete)):
            for target in node.targets:
                bindings.extend(_bound_target_names(target))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr, ast.For, ast.AsyncFor)):
            bindings.extend(_bound_target_names(node.target))
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name is not None:
            bindings.append(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            bindings.append(node.rest)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    bindings.extend(_bound_target_names(item.optional_vars))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    return bindings


def _scope_bindings(statements: list[ast.stmt]) -> set[str]:
    return set(_scope_binding_events(statements))


def _module_binding_counts(tree: ast.Module) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in _scope_binding_events(tree.body):
        counts[name] = counts.get(name, 0) + 1
    return counts


def _random_aliases(tree: ast.Module) -> tuple[set[str], set[str], set[str]]:
    modules: set[str] = set()
    functions: set[str] = set()
    seeds: set[str] = set()
    binding_counts = _module_binding_counts(tree)
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(
                local
                for alias in node.names
                if alias.name == "random" and binding_counts.get(local := alias.asname or alias.name, 0) == 1
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "random":
            for alias in node.names:
                local = alias.asname or alias.name
                if binding_counts.get(local, 0) != 1:
                    continue
                if alias.name in _PRNG_FUNCTIONS:
                    functions.add(local)
                elif alias.name == "seed":
                    seeds.add(local)
    return modules, functions, seeds


def _is_prng_call(node: ast.Call, modules: set[str], functions: set[str]) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id in functions
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in _PRNG_FUNCTIONS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in modules
    )


def _is_seed_call(node: ast.Call, modules: set[str], seeds: set[str]) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id in seeds
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "seed"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in modules
    )


def _test_nodes(test: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    """Walk one collected test without attributing nested helpers to it."""
    stack: list[ast.AST] = [*reversed(test.body)]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _bounded_nodes(root: ast.AST) -> Iterator[ast.AST]:
    """Walk a subtree without entering nested callable or class scopes."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        if node is not root and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _test_nodes_for_statement(statement: ast.stmt) -> Iterator[ast.AST]:
    yield from _bounded_nodes(statement)


def _collected_tests(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            yield node
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            yield from (
                child
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_")
            )


@final
class UncontrolledRandomnessInTest(Rule):
    id = "uncontrolled-randomness-in-test"
    code = "SARJ410"
    documentation = RuleDocumentation(
        summary="Test repeatedly samples the standard PRNG without a seed or injected deterministic random source.",
        rationale=(
            "Repeated unseeded sampling makes pass/fail outcomes vary across identical runs and broad frequency "
            "bounds can conceal heavily biased behavior."
        ),
        remediation="Inject a deterministic RNG, seed it explicitly, or use a property framework that records failing seeds.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only standard-library `random` calls nested in loops or comprehensions in collected tests are checked.",
            "Single draws, injected RNG objects, Hypothesis tests, and cryptographic randomness are excluded.",
            "Only an unconditional top-level seed before the repeated sample suppresses the finding; interprocedural seeding is not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="seeded-random-sampling",
                title="Make repeated random sampling reproducible",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_selector.py",
                        "import random\n\ndef test_distribution():\n    random.seed(17)\n    values = [random.random() for _ in range(50)]\n    assert values\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_selector.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="unseeded-random-sampling",
                title="Do not repeat probabilistic trials without reproducibility",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_selector.py",
                        "import random\n\ndef test_distribution():\n    values = [random.random() for _ in range(50)]\n    assert values\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_selector.py"),
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
        modules, functions, seeds = _random_aliases(tree)
        if not modules and not functions:
            return []
        findings: list[Diagnostic] = []
        for test in _collected_tests(tree):
            local_bindings = _scope_bindings(test.body) | {
                arg.arg for arg in (*test.args.posonlyargs, *test.args.args, *test.args.kwonlyargs)
            }
            if test.args.vararg is not None:
                local_bindings.add(test.args.vararg.arg)
            if test.args.kwarg is not None:
                local_bindings.add(test.args.kwarg.arg)
            test_modules = modules - local_bindings
            test_functions = functions - local_bindings
            test_seeds = seeds - local_bindings
            if not test_modules and not test_functions:
                continue
            nodes = list(_test_nodes(test))
            top_level_seed_indexes = {
                index
                for index, statement in enumerate(test.body)
                if isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Call)
                and _is_seed_call(statement.value, test_modules, test_seeds)
            }
            for repeated in (node for node in nodes if isinstance(node, _REPEAT_NODES)):
                owner_index = next(
                    (
                        index
                        for index, statement in enumerate(test.body)
                        if repeated is statement or repeated in _test_nodes_for_statement(statement)
                    ),
                    None,
                )
                if owner_index is not None and any(seed_index < owner_index for seed_index in top_level_seed_indexes):
                    continue
                calls = [
                    node
                    for node in _bounded_nodes(repeated)
                    if isinstance(node, ast.Call) and _is_prng_call(node, test_modules, test_functions)
                ]
                findings.extend(
                    Diagnostic(
                        path=path,
                        line=call.lineno,
                        col=call.col_offset + 1,
                        code=self.code,
                        severity=Severity.ERROR,
                        message=(
                            "this test repeatedly samples an unseeded PRNG, so the same code can pass or fail across "
                            "runs; inject a deterministic RNG, set an explicit seed, or use a property-testing "
                            "framework with recorded seeds."
                        ),
                    )
                    for call in calls
                )
        unique = {(finding.line, finding.col): finding for finding in findings}
        return [unique[key] for key in sorted(unique)]
