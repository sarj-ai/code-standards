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
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_PRNG_FUNCTIONS = frozenset({"choice", "choices", "randint", "random", "randrange", "sample", "shuffle", "uniform"})
_REPEAT_NODES = (ast.For, ast.AsyncFor, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _random_aliases(tree: ast.Module) -> tuple[set[str], set[str], set[str]]:
    modules: set[str] = set()
    functions: set[str] = set()
    seeds: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(alias.asname or alias.name for alias in node.names if alias.name == "random")
        elif isinstance(node, ast.ImportFrom) and node.module == "random":
            for alias in node.names:
                local = alias.asname or alias.name
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
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


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
            "A seed anywhere in the test suppresses the finding; interprocedural seeding is not inferred.",
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
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        modules, functions, seeds = _random_aliases(tree)
        if not modules and not functions:
            return []
        findings: list[Diagnostic] = []
        for test in ast.walk(tree):
            if not isinstance(test, (ast.FunctionDef, ast.AsyncFunctionDef)) or not test.name.startswith("test_"):
                continue
            nodes = list(_test_nodes(test))
            if any(isinstance(node, ast.Call) and _is_seed_call(node, modules, seeds) for node in nodes):
                continue
            for repeated in (node for node in nodes if isinstance(node, _REPEAT_NODES)):
                calls = [
                    node
                    for node in ast.walk(repeated)
                    if isinstance(node, ast.Call) and _is_prng_call(node, modules, functions)
                ]
                findings.extend(
                    Diagnostic(
                        path=path,
                        line=call.lineno,
                        col=call.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
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
