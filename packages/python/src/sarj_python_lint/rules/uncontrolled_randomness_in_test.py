from __future__ import annotations

import ast
from dataclasses import dataclass
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


_PRNG_FUNCTIONS = frozenset(
    {
        "betavariate",
        "binomialvariate",
        "choice",
        "choices",
        "expovariate",
        "gammavariate",
        "gauss",
        "getrandbits",
        "lognormvariate",
        "normalvariate",
        "paretovariate",
        "randbytes",
        "randint",
        "random",
        "randrange",
        "sample",
        "shuffle",
        "triangular",
        "uniform",
        "vonmisesvariate",
        "weibullvariate",
    }
)
_REPEAT_NODES = (ast.For, ast.AsyncFor, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


@dataclass(frozen=True, slots=True)
class _RandomAliases:
    modules: set[str]
    functions: set[str]
    seeds: set[str]
    constructors: set[str]


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


def _random_aliases(tree: ast.Module) -> _RandomAliases:
    modules: set[str] = set()
    functions: set[str] = set()
    seeds: set[str] = set()
    constructors: set[str] = set()
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
                elif alias.name == "Random":
                    constructors.add(local)
    return _RandomAliases(modules, functions, seeds, constructors)


def _is_prng_call(node: ast.Call, modules: set[str], functions: set[str], instances: set[str]) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id in functions
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in _PRNG_FUNCTIONS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in modules | instances
    )


def _unseeded_instances(statements: list[ast.stmt], modules: set[str], constructors: set[str]) -> set[str]:
    binding_events = _scope_binding_events(statements)
    instances: set[str] = set()
    for statement in statements:
        if not (isinstance(statement, (ast.Assign, ast.AnnAssign)) and isinstance(statement.value, ast.Call)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else (statement.target,)
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            continue
        func = statement.value.func
        is_constructor = (isinstance(func, ast.Name) and func.id in constructors) or (
            isinstance(func, ast.Attribute)
            and func.attr == "Random"
            and isinstance(func.value, ast.Name)
            and func.value.id in modules
        )
        if not is_constructor:
            continue
        args = statement.value.args
        deterministic = (
            len(args) == 1
            and not statement.value.keywords
            and isinstance(args[0], ast.Constant)
            and args[0].value is not None
        )
        if not deterministic and binding_events.count(targets[0].id) == 1:
            instances.add(targets[0].id)
    return instances


def _is_seed_call(node: ast.Call, modules: set[str], seeds: set[str]) -> bool:
    return (isinstance(node.func, ast.Name) and node.func.id in seeds) or (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "seed"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in modules
    )


def _has_deterministic_seed(node: ast.Call, modules: set[str], seeds: set[str]) -> bool:
    return (
        _is_seed_call(node, modules, seeds)
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value is not None
        and isinstance(node.args[0].value, (int, float, str, bytes))
        and not isinstance(node.args[0].value, bool)
    )


def _test_nodes(test: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    stack: list[ast.AST] = [*reversed(test.body)]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _bounded_nodes(root: ast.AST) -> Iterator[ast.AST]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        if node is not root and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _test_nodes_for_statement(statement: ast.stmt) -> Iterator[ast.AST]:
    yield from _bounded_nodes(statement)


def _explicitly_disabled(statements: list[ast.stmt]) -> bool:
    for statement in statements:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else (statement.target,)
        if (
            any(isinstance(target, ast.Name) and target.id == "__test__" for target in targets)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is False
        ):
            return True
    return False


def _is_fixture(test: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == "fixture")
        or (isinstance(decorator, ast.Attribute) and decorator.attr == "fixture")
        or (
            isinstance(decorator, ast.Call)
            and (
                (isinstance(decorator.func, ast.Name) and decorator.func.id == "fixture")
                or (isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "fixture")
            )
        )
        for decorator in test.decorator_list
    )


def _collected_tests(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    if _explicitly_disabled(tree.body):
        return
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            and not _is_fixture(node)
        ):
            yield node
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test") and not _explicitly_disabled(node.body):
            yield from (
                child
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name.startswith("test_")
                and not _is_fixture(child)
            )


def _is_collected_module(path: Path) -> bool:
    return (path.name.startswith("test_") or path.name.endswith("_test.py")) and "scripts" not in path.parts


def _known_at_most_once(node: ast.expr) -> bool:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return len(node.elts) <= 1
    if isinstance(node, ast.Dict):
        return len(node.keys) <= 1
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "range"
        and not node.keywords
        and all(isinstance(arg, ast.Constant) and isinstance(arg.value, int) for arg in node.args)
    ):
        return False
    values = [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, int)]
    try:
        return len(range(*values)) <= 1
    except TypeError, ValueError:
        return False


def _repeated_regions(node: ast.AST) -> tuple[ast.AST, ...]:
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return (
            ()
            if _known_at_most_once(node.iter)
            else tuple(
                statement
                for statement in node.body
                if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            )
        )
    if isinstance(node, ast.While):
        if isinstance(node.test, ast.Constant) and not node.test.value:
            return ()
        return (
            node.test,
            *(
                statement
                for statement in node.body
                if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ),
        )
    if not isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return ()
    regions: list[ast.AST] = []
    prior_generator_repeats = False
    for generator in node.generators:
        if prior_generator_repeats:
            regions.append(generator.iter)
        this_generator_repeats = not _known_at_most_once(generator.iter)
        if prior_generator_repeats or this_generator_repeats:
            regions.extend(generator.ifs)
        prior_generator_repeats = prior_generator_repeats or this_generator_repeats
    if prior_generator_repeats:
        if isinstance(node, ast.DictComp):
            regions.extend((node.key, node.value))
        else:
            regions.append(node.elt)
    return tuple(regions)


def _aliases_for_test(test: ast.FunctionDef | ast.AsyncFunctionDef, module_aliases: _RandomAliases) -> _RandomAliases:
    local_aliases = _random_aliases(ast.Module(body=test.body, type_ignores=[]))
    local_bindings = _scope_bindings(test.body) | {
        arg.arg for arg in (*test.args.posonlyargs, *test.args.args, *test.args.kwonlyargs)
    }
    if test.args.vararg is not None:
        local_bindings.add(test.args.vararg.arg)
    if test.args.kwarg is not None:
        local_bindings.add(test.args.kwarg.arg)
    local_alias_names = (
        local_aliases.modules | local_aliases.functions | local_aliases.seeds | local_aliases.constructors
    )
    shadowed = local_bindings - local_alias_names
    return _RandomAliases(
        modules=(module_aliases.modules - shadowed) | local_aliases.modules,
        functions=(module_aliases.functions - shadowed) | local_aliases.functions,
        seeds=(module_aliases.seeds - shadowed) | local_aliases.seeds,
        constructors=(module_aliases.constructors - shadowed) | local_aliases.constructors,
    )


@final
class UncontrolledRandomnessInTest(Rule):
    id = "no-repeated-unseeded-stdlib-random-in-test"
    code = "SARJ410"
    documentation = RuleDocumentation(
        summary="A collected test may repeatedly sample an unseeded standard-library PRNG.",
        rationale=(
            "Repeated unseeded sampling creates unreproducible generated inputs, making failures harder to replay "
            "and debug when sampled values affect behavior."
        ),
        remediation=(
            "Use an isolated deterministic generator such as `rng = random.Random(17)`, inject one, or use a "
            "property framework that records failing seeds."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        aliases=("uncontrolled-randomness-in-test",),
        limitations=(
            "Only standard-library `random` calls in potentially repeated loop or comprehension regions in default-collected test modules and callables are checked.",
            "Single draws, injected RNG objects, Hypothesis tests, and cryptographic randomness are excluded.",
            "Only a statically deterministic, unconditional seed before the repeated sample suppresses the finding; fixture, plugin, and interprocedural seeding are not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="seeded-random-sampling",
                title="Make repeated random sampling reproducible",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_selector.py",
                        "import random\n\ndef test_distribution():\n    rng = random.Random(17)\n    values = [rng.random() for _ in range(50)]\n    assert min(values) < 0.5\n",
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
                        "import random\n\ndef test_distribution():\n    values = [random.random() for _ in range(50)]\n    assert min(values) < 0.5\n",
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
        if not is_test_path(path) or not _is_collected_module(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        aliases = _random_aliases(tree)
        findings: list[Diagnostic] = []
        for test in _collected_tests(tree):
            test_aliases = _aliases_for_test(test, aliases)
            if not test_aliases.modules and not test_aliases.functions and not test_aliases.constructors:
                continue
            instances = _unseeded_instances(test.body, test_aliases.modules, test_aliases.constructors)
            nodes = list(_test_nodes(test))
            top_level_seed_indexes = {
                index
                for index, statement in enumerate(test.body)
                if isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Call)
                and _has_deterministic_seed(statement.value, test_aliases.modules, test_aliases.seeds)
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
                    for region in _repeated_regions(repeated)
                    for node in _bounded_nodes(region)
                    if isinstance(node, ast.Call)
                    and _is_prng_call(node, test_aliases.modules, test_aliases.functions, instances)
                ]
                if not calls:
                    continue
                call = min(calls, key=lambda item: (item.lineno, item.col_offset))
                findings.append(
                    Diagnostic(
                        path=path,
                        line=call.lineno,
                        col=call.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=(
                            "a standard-library PRNG sample runs in a potentially repeated test region without a "
                            "dominating deterministic seed; use an isolated `random.Random(seed)`, inject a "
                            "deterministic RNG, or use a property-testing framework with recorded seeds."
                        ),
                    )
                )
                break
        unique = {(finding.line, finding.col): finding for finding in findings}
        return [unique[key] for key in sorted(unique)]
