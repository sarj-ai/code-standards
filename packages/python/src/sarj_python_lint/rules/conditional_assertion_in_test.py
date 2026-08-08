"""SARJ065 — A test whose every assertion sits behind a branch or loop can pass asserting nothing.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_conditional_assertion_in_test.py
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


# Names that verify something, however the project spells them.
_ASSERTION_NAME_RE = re.compile(r"^_{0,2}(assert|check|verify|validate|expect|ensure)", re.IGNORECASE)

# `raises`/`warns` as a token anywhere in the name: `pytest.deprecated_call`,
# `pytest.RaisesGroup`, and project wrappers all verify by expecting a throw.
_RAISES_TOKEN_RE = re.compile(r"(^|_)(raises|warns|deprecated_call)", re.IGNORECASE)

# Bare pytest verbs, reached as `pytest.raises` or as `raises` after a
# `from pytest import raises`.
_VERIFY_NAMES = frozenset({"raises", "warns", "fail", "deprecated_call"})

# Calls that abandon the test rather than fail it.
_EXIT_NAMES = frozenset({"skip", "xfail", "exit", "skipTest", "importorskip"})

# Calls that end the test in failure: `pytest.fail(...)`, `self.fail(...)`.
_FAIL_NAMES = frozenset({"fail"})

# Fluent verification DSLs reached through an attribute rather than a call name.
_FLUENT_ATTRS = frozenset({"expect"})

# `unittest.TestCase.subTest` re-enters the loop body as its own sub-test; the
# suites that use it drive it from a table the rule cannot always resolve.
_SUBTEST = "subTest"

# Hypothesis' entry point: one `@given` expands into many generated inputs and a
# per-input branch is the normal shape.
_PROPERTY_DECORATORS = frozenset({"given", "settings", "example"})

_SKIP_MARKERS = frozenset({"skip", "skipif", "xfail"})

_PARAMETRIZE = "parametrize"
_PARAM = "param"

# Capability guards legitimately skip assertions where the environment cannot exercise them.
_CAPABILITY_RE = re.compile(
    r"support|feature|capabilit|available|installed|platform|implementation|version|hasattr|debug",
    re.IGNORECASE,
)

# pytest-subtests' fixture, the pytest spelling of `unittest`'s `subTest`.
_SUBTESTS_FIXTURE = "subtests"

# Accumulator methods: `results = []` then `results.append(...)` in a loop that
# is itself proven to run leaves `results` non-empty.
_ACCUMULATOR_METHODS = frozenset({"append", "add", "extend", "update"})

# Receivers whose attributes are class fixtures, not values this test computed.
_FIXTURE_ROOTS = frozenset({"self", "cls"})

_FIXTURE = "fixture"

_TEST_PREFIX = "test_"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_LOOP_NODES = (ast.For, ast.AsyncFor)
_WITH_NODES = (ast.With, ast.AsyncWith)
_COMP_NODES = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)

# Builtins that preserve "is this empty?" from their first argument.
_PASSTHROUGH_CALLS = frozenset(
    {
        "list",
        "tuple",
        "set",
        "frozenset",
        "sorted",
        "reversed",
        "iter",
        "enumerate",
        "dict",
        "as_completed",
    }
)

# Mapping views: `d.items()` is non-empty exactly when `d` is.
_VIEW_METHODS = frozenset({"items", "keys", "values"})

# `str.split(sep)` yields at least one element for every input, `""` included.
_ALWAYS_NONEMPTY_METHODS = frozenset({"split", "rsplit", "splitlines"})

# Attribute calls that inherit emptiness from their first argument, or from
# their receiver when called with none: `dict.fromkeys(words, 0)`,
# `itertools.product(alphabet, repeat=n)`, `rows.copy()`.
_PASSTHROUGH_METHODS = frozenset({"fromkeys", "product", "copy", "gather"})

# pytest's default `python_files`.
_COLLECTED_SUFFIX = "_test.py"

# Manual CLI probes live here under test_*.py names but are never collected.
_UNCOLLECTED_DIR_NAMES = frozenset({"scripts"})


@dataclass(frozen=True, slots=True)
class _Facts:
    """What the enclosing test proves about the names it loops over."""

    nonempty: frozenset[str]
    bindings: Mapping[str, ast.expr]
    imported: frozenset[str]
    helpers: frozenset[str]
    roots: frozenset[str] = frozenset()


class ConditionalAssertionInTest(Rule):
    id: str = "conditional-assertion-in-test"
    code: str = "SARJ065"
    description: str = "Every assertion in the test is inside a conditional or loop — it can pass asserting nothing."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag tests where no execution path is guaranteed to reach an assertion."""
        if not is_test_path(path) or not _is_collected_module(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        return [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"every assertion in `{node.name}` sits inside a conditional or loop that may not run, "
                    "so the test passes without checking anything when the branch is not taken or the "
                    "iterable is empty. Assert unconditionally, assert the collection's size before "
                    "looping (`assert len(rows) == 3`), or give the `if` an `else` that also asserts."
                ),
            )
            for node in _conditionally_asserting_tests(tree)
        ]


def _is_collected_module(path: Path) -> bool:
    name = path.name
    matches_python_files = name.startswith(_TEST_PREFIX) or name.endswith(_COLLECTED_SUFFIX)
    return matches_python_files and not any(part in _UNCOLLECTED_DIR_NAMES for part in path.parts)


def _conditionally_asserting_tests(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    helpers = _asserting_helper_names(tree)
    module_bindings = _bindings_in(tree.body)
    # A sibling test can establish that a module-level case table is nonempty.
    module_nonempty = frozenset(_nonempty_claims(tree, helpers) & set(module_bindings))
    imported = _imported_names(tree)
    hits: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in _collectible_tests(tree):
        if _is_exempt(node, helpers):
            continue
        if not _body_contains_assertion(node, helpers):
            # No assertion at all is SARJ043's finding, not this one.
            continue
        facts = _facts_for(node, module_bindings, module_nonempty, imported, helpers)
        if _guaranteed(node.body, facts):
            continue
        hits.append(node)
    return hits


def _collectible_tests(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Collect the `test_*` functions pytest would actually run."""
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    containers: list[ast.Module | ast.ClassDef] = [tree]
    while containers:
        for stmt in containers.pop().body:
            if isinstance(stmt, ast.ClassDef):
                containers.append(stmt)
            elif isinstance(stmt, _FUNC_NODES) and stmt.name.startswith(_TEST_PREFIX):
                found.append(stmt)
    found.sort(key=lambda n: (n.lineno, n.col_offset))
    return found


def _is_exempt(node: ast.FunctionDef | ast.AsyncFunctionDef, helpers: frozenset[str]) -> bool:
    if any(arg.arg == _SUBTESTS_FIXTURE for arg in _parameters(node)):
        return True
    if any(_marker_name(dec) in _SKIP_MARKERS or _marker_name(dec) == _FIXTURE for dec in node.decorator_list):
        return True
    if any(_decorator_name(dec) in _PROPERTY_DECORATORS for dec in node.decorator_list):
        return True
    for stmt in node.body:
        for child in walk(stmt):
            # `with self.subTest(...)` drives a table whose emptiness this rule
            # cannot see; a nested `def` holding the assertions may be invoked
            # by a runner (`asyncio.run`, a callback registry) the rule cannot
            # follow.
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == _SUBTEST:
                return True
            if isinstance(child, _FUNC_NODES) and _contains_assertion(child, helpers):
                return True
    return False


def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    args = node.args
    return [*args.posonlyargs, *args.args, *args.kwonlyargs]


def _decorator_name(dec: ast.expr) -> str | None:
    target = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(target, ast.Name):
        return target.id
    return target.attr if isinstance(target, ast.Attribute) else None


def _marker_name(dec: ast.expr) -> str | None:
    target = dec.func if isinstance(dec, ast.Call) else dec
    return target.attr if isinstance(target, ast.Attribute) else None


# "Does executing this guarantee an assertion?"                                #


def _guaranteed(body: Sequence[ast.stmt], facts: _Facts) -> bool:
    return any(_stmt_guarantees(stmt, facts) for stmt in body)


def _branch_ok(body: Sequence[ast.stmt], facts: _Facts) -> bool:
    # A branch that bails out (`return`, `pytest.skip(...)`, `raise`) never
    # reaches the end of the test, so it owes no assertion.
    return _guaranteed(body, facts) or _exits(body)


def _stmt_guarantees(stmt: ast.stmt, facts: _Facts) -> bool:
    if isinstance(stmt, ast.If):
        return _if_guarantees(stmt, facts)
    if isinstance(stmt, _LOOP_NODES):
        return _loop_guarantees(stmt, facts)
    if isinstance(stmt, ast.While):
        if _guaranteed(stmt.orelse, facts):
            return True
        return _is_true_literal(stmt.test) and _guaranteed(stmt.body, facts)
    if isinstance(stmt, ast.Try):
        return _try_guarantees(stmt, facts)
    if isinstance(stmt, _WITH_NODES):
        return _with_verifies(stmt, facts) or _guaranteed(stmt.body, facts)
    if isinstance(stmt, ast.Match):
        return _match_guarantees(stmt, facts)
    if isinstance(stmt, (*_FUNC_NODES, ast.ClassDef)):
        # A definition is not an execution.
        return False
    if isinstance(stmt, (ast.Assert, ast.Raise)):
        return True
    return _holds_assertion_call(stmt, facts.helpers)


def _if_guarantees(stmt: ast.If, facts: _Facts) -> bool:
    if not stmt.orelse:
        # A conditional pytest.fail is an assertion on the negated condition.
        if _always_fails(stmt.body):
            return True
        return _is_capability_probe(stmt.test) and _guaranteed(stmt.body, facts)
    if _arms_guarantee(stmt.body, stmt.orelse, facts):
        return True
    complementary = _complementary_branch(stmt)
    return complementary is not None and _arms_guarantee(stmt.body, complementary, facts)


def _arms_guarantee(taken: Sequence[ast.stmt], other: Sequence[ast.stmt], facts: _Facts) -> bool:
    if not (_branch_ok(taken, facts) and _branch_ok(other, facts)):
        return False
    # Two branches that both bail out assert nothing between them.
    return _guaranteed(taken, facts) or _guaranteed(other, facts)


def _always_fails(body: Sequence[ast.stmt]) -> bool:
    """Report whether reaching this block always ends the test in failure."""
    return any(_stmt_always_fails(stmt) for stmt in body)


def _stmt_always_fails(stmt: ast.stmt) -> bool:
    match stmt:
        case ast.Raise():
            return True
        case ast.Assert(test=test):
            return _is_falsy_literal(test)
        case ast.If(body=body, orelse=orelse):
            return _always_fails(body) and bool(orelse) and _always_fails(orelse)
        case ast.With(body=body) | ast.AsyncWith(body=body):
            return _always_fails(body)
        case ast.Expr(value=value):
            return _is_failure_call(value)
        case _:
            return False


def _is_falsy_literal(test: ast.expr) -> bool:
    # `assert False` / `assert 0, "unreachable"` — a verdict, not a check.
    return isinstance(test, ast.Constant) and not test.value


def _is_failure_call(value: ast.expr) -> bool:
    # `pytest.fail(...)`, `self.fail(...)`, a bare `fail(...)` after `from
    # pytest import fail`. Unlike `skip`/`xfail`, these are verdicts, not exits.
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Attribute):
        return func.attr in _FAIL_NAMES
    return isinstance(func, ast.Name) and func.id in _FAIL_NAMES


def _complementary_branch(stmt: ast.If) -> list[ast.stmt] | None:
    """Read an `if X: ... elif not X: ...` chain as the `if`/`else` it is."""
    if len(stmt.orelse) != 1:
        return None
    inner = stmt.orelse[0]
    if not isinstance(inner, ast.If) or inner.orelse:
        return None
    return inner.body if _completes(stmt.test, inner.test) else None


def _completes(first: ast.expr, second: ast.expr) -> bool:
    # Reaching the `elif` means every disjunct of the `if` was false, so a
    # `not X` (or an `X` opposite a `not X`) among them makes the chain total.
    values = first.values if isinstance(first, ast.BoolOp) and isinstance(first.op, ast.Or) else [first]
    return any(_is_negation_pair(value, second) for value in values)


def _is_negation_pair(one: ast.expr, other: ast.expr) -> bool:
    return _negated_source(one) == _unparse(other) or _negated_source(other) == _unparse(one)


def _negated_source(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        return _unparse(expr.operand)
    return None


def _loop_guarantees(stmt: ast.For | ast.AsyncFor, facts: _Facts) -> bool:
    # A `for ... else:` clause runs whenever the loop was not broken out of.
    if _guaranteed(stmt.orelse, facts):
        return True
    if not _iterable_is_nonempty(stmt.iter, facts, frozenset()):
        return False
    # Nested collections reached through an item need not be proven nonempty globally.
    inner = _Facts(
        nonempty=facts.nonempty,
        bindings=facts.bindings,
        imported=facts.imported,
        helpers=facts.helpers,
        roots=facts.roots | _bound_names(stmt.target),
    )
    return _guaranteed(stmt.body, inner)


def _bound_names(target: ast.expr) -> frozenset[str]:
    return frozenset(node.id for node in walk(target) if isinstance(node, ast.Name))


def _try_guarantees(stmt: ast.Try, facts: _Facts) -> bool:
    # A try/except test can verify failure without an `assert` token.
    limbs: list[Sequence[ast.stmt]] = [stmt.body, stmt.orelse, stmt.finalbody]
    limbs.extend(handler.body for handler in stmt.handlers)
    return any(_guaranteed(limb, facts) for limb in limbs)


def _match_guarantees(stmt: ast.Match, facts: _Facts) -> bool:
    if not any(_is_wildcard_case(case) for case in stmt.cases):
        return False
    if not all(_branch_ok(case.body, facts) for case in stmt.cases):
        return False
    return any(_guaranteed(case.body, facts) for case in stmt.cases)


def _is_capability_probe(test: ast.expr) -> bool:
    """Report whether the condition gates on what the environment supports."""
    for node in walk(test):
        if isinstance(node, ast.Name) and _CAPABILITY_RE.search(node.id):
            return True
        if isinstance(node, ast.Attribute) and _CAPABILITY_RE.search(node.attr):
            return True
    return False


def _is_wildcard_case(case: ast.match_case) -> bool:
    return case.guard is None and isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None


def _is_true_literal(test: ast.expr) -> bool:
    return isinstance(test, ast.Constant) and test.value is True


def _with_verifies(stmt: ast.With | ast.AsyncWith, facts: _Facts) -> bool:
    # `with pytest.raises(ValueError):` / `with self.assertRaises(...):` is the
    # assertion; entering the block guarantees the check runs.
    return any(_expr_names_assertion(item.context_expr, facts.helpers) for item in stmt.items)


def _expr_names_assertion(expr: ast.expr, helpers: frozenset[str]) -> bool:
    target = expr.func if isinstance(expr, ast.Call) else expr
    return _names_assertion(target, helpers)


# "Is there an assertion in here at all?"                                      #


def _contains_assertion(node: ast.AST, helpers: frozenset[str]) -> bool:
    return any(_is_assertion(child, helpers) for child in walk(node))


def _body_contains_assertion(node: ast.FunctionDef | ast.AsyncFunctionDef, helpers: frozenset[str]) -> bool:
    # The body only: a decorator that happens to be an asserting local helper
    # (django's `@test_mutation()`, which wraps the body in an
    # `assertRaisesMessage`) is not an assertion this function executes.
    return any(_contains_assertion(stmt, helpers) for stmt in node.body)


def _holds_assertion_call(stmt: ast.stmt, helpers: frozenset[str]) -> bool:
    return any(_is_assertion(child, helpers) for child in walk(stmt))


def _is_assertion(child: ast.AST, helpers: frozenset[str]) -> bool:
    if isinstance(child, ast.Assert):
        return True
    return isinstance(child, ast.Call) and _names_assertion(child.func, helpers)


def _names_assertion(func: ast.expr, helpers: frozenset[str]) -> bool:
    if isinstance(func, ast.Name):
        return func.id in _VERIFY_NAMES or func.id in helpers or _reads_as_assertion(func.id)
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in _VERIFY_NAMES or func.attr in helpers or _reads_as_assertion(func.attr):
        return True
    # `result.expect.contains_function_call(...)` — the DSL marker sits partway
    # along the chain rather than at its end.
    return _chain_has_fluent_marker(func.value)


def _reads_as_assertion(name: str) -> bool:
    return bool(_ASSERTION_NAME_RE.match(name) or _RAISES_TOKEN_RE.search(name))


def _chain_has_fluent_marker(node: ast.expr) -> bool:
    while isinstance(node, ast.Attribute):
        if node.attr in _FLUENT_ATTRS:
            return True
        node = node.value
    return False


def _asserting_helper_names(tree: ast.Module) -> frozenset[str]:
    """Find the module's own functions that verify, directly or by delegation."""
    defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in nodes(tree, *_FUNC_NODES):
        defs.setdefault(node.name, node)
    verifying = {name for name, node in defs.items() if _contains_assertion(node, frozenset())}
    pending = {name: _called_names(node) for name, node in defs.items() if name not in verifying}
    while True:
        promoted = {name for name, called in pending.items() if called & verifying}
        if not promoted:
            return frozenset(verifying)
        verifying |= promoted
        pending = {name: called for name, called in pending.items() if name not in promoted}


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


# Early exits: a branch that bails out owes no assertion.                      #


def _exits(body: Sequence[ast.stmt]) -> bool:
    return any(_stmt_exits(stmt) for stmt in body)


def _stmt_exits(stmt: ast.stmt) -> bool:
    match stmt:
        case ast.Return() | ast.Raise() | ast.Continue() | ast.Break():
            return True
        case ast.If(body=body, orelse=orelse):
            return bool(orelse) and _exits(body) and _exits(orelse)
        case ast.Expr(value=value):
            return _is_exit_call(value)
        case _:
            return False


def _is_exit_call(value: ast.expr) -> bool:
    # `pytest.skip(...)`, `pytest.xfail(...)`, `self.skipTest(...)` and
    # `sys.exit(...)` all raise, ending the test before the fallthrough.
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Attribute):
        return func.attr in _EXIT_NAMES
    return isinstance(func, ast.Name) and func.id in _EXIT_NAMES


# Non-emptiness: which iterables are proven to run their loop body.            #


def _facts_for(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    module_bindings: Mapping[str, ast.expr],
    module_nonempty: frozenset[str],
    imported: frozenset[str],
    helpers: frozenset[str],
) -> _Facts:
    bindings = dict(module_bindings)
    bindings.update(_bindings_in(list(walk(node))))
    bindings.update(_default_bindings(node))
    nonempty = _nonempty_claims(node, helpers) | set(module_nonempty) | _parametrized_nonempty(node)
    base = _Facts(nonempty=frozenset(nonempty), bindings=bindings, imported=imported, helpers=helpers)
    filled = _accumulators_filled(node, base)
    if not filled:
        return base
    return _Facts(nonempty=base.nonempty | filled, bindings=bindings, imported=imported, helpers=helpers)


def _default_bindings(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, ast.expr]:
    """Read parameter defaults as bindings."""
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    bindings = {
        arg.arg: default
        for arg, default in zip(positional[len(positional) - len(args.defaults) :], args.defaults, strict=True)
    }
    bindings.update(
        {
            arg.arg: default
            for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
            if default is not None
        }
    )
    return bindings


def _accumulators_filled(node: ast.FunctionDef | ast.AsyncFunctionDef, facts: _Facts) -> frozenset[str]:
    """Find the `results = []` names a proven-to-run loop appends to."""
    filled: set[str] = set()
    for child in walk(node):
        if not isinstance(child, _LOOP_NODES) or not _iterable_is_nonempty(child.iter, facts, frozenset()):
            continue
        for inner in walk(child):
            if not (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)):
                continue
            receiver = inner.func.value
            if inner.func.attr in _ACCUMULATOR_METHODS and isinstance(receiver, ast.Name):
                filled.add(receiver.id)
    return frozenset(filled)


def _imported_names(tree: ast.Module) -> frozenset[str]:
    """Collect every name this module binds with an `import` statement."""
    names: set[str] = set()
    for node in nodes(tree, ast.Import, ast.ImportFrom):
        names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
    return frozenset(names)


def _nonempty_claims(node: ast.AST, helpers: frozenset[str]) -> set[str]:
    """Gather every expression this subtree proves to be a non-empty collection."""
    nonempty: set[str] = set()
    for child in walk(node):
        if isinstance(child, ast.Assert):
            nonempty |= _proves_nonempty(child.test)
        elif isinstance(child, ast.Call) and _names_assertion(child.func, helpers):
            nonempty |= _assert_call_proves(child)
        elif isinstance(child, ast.If) and _exits(child.body):
            nonempty |= _negation_proves(child.test)
    return nonempty


def _parametrized_nonempty(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Read the `@pytest.mark.parametrize` table for arguments that are never empty."""
    proven: set[str] = set()
    for dec in node.decorator_list:
        if not (isinstance(dec, ast.Call) and _marker_name(dec) == _PARAMETRIZE):
            continue
        names = _parametrize_names(dec)
        rows = _parametrize_rows(dec)
        if not names or rows is None:
            continue
        for index, name in enumerate(names):
            values = [_row_value(row, index, len(names)) for row in rows]
            if values and all(value is not None and _is_nonempty_literal(value) for value in values):
                proven.add(name)
    return proven


def _parametrize_names(dec: ast.Call) -> list[str]:
    argnames = dec.args[0] if dec.args else None
    if isinstance(argnames, ast.Constant) and isinstance(argnames.value, str):
        return [p for part in argnames.value.split(",") if (p := part.strip())]
    if isinstance(argnames, (ast.List, ast.Tuple)):
        return [val for elt in argnames.elts if isinstance(elt, ast.Constant) and isinstance(val := elt.value, str)]
    return []


def _parametrize_rows(dec: ast.Call) -> list[ast.expr] | None:
    argvalues = dec.args[1] if len(dec.args) > 1 else None
    if isinstance(argvalues, (ast.List, ast.Tuple)):
        return list(argvalues.elts)
    return None


def _row_value(row: ast.expr, index: int, width: int) -> ast.expr | None:
    # `pytest.param(a, b, id="x")` wraps the same tuple with metadata.
    if isinstance(row, ast.Call) and _decorator_name(row) == _PARAM:
        return row.args[index] if index < len(row.args) else None
    if width == 1:
        return row
    if isinstance(row, (ast.List, ast.Tuple)) and index < len(row.elts):
        return row.elts[index]
    return None


def _bindings_in(nodes: Sequence[ast.AST]) -> dict[str, ast.expr]:
    bindings: dict[str, ast.expr] = {}
    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                # First binding wins: a later `qs = qs.exclude(...)` narrows
                # what `qs = Country.objects.all()` already established, and it
                # is the original that says where the collection came from.
                bindings.setdefault(_unparse(target), node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            bindings.setdefault(_unparse(node.target), node.value)
    return bindings


def _unparse(expr: ast.expr) -> str:
    try:
        return ast.unparse(expr)
    except ValueError, RecursionError, AttributeError:  # pragma: no cover — malformed nodes only
        return ""


def _proves_nonempty(test: ast.expr) -> set[str]:
    """Read what an assertion's expression proves about a collection's size."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        proven: set[str] = set()
        for value in test.values:
            proven |= _proves_nonempty(value)
        return proven
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        return _comparison_proves(test.left, test.ops[0], test.comparators[0])
    if isinstance(test, (ast.Name, ast.Attribute, ast.Subscript, ast.Call)):
        # `assert rows` — truthy means non-empty for every container type.
        return {_unparse(test)}
    return set()


def _comparison_proves(left: ast.expr, op: ast.cmpop, right: ast.expr) -> set[str]:
    proven: set[str] = set()
    if isinstance(op, ast.In):
        # `assert item in rows` — a container with a member is not empty.
        return {_unparse(right)}
    for near, far in ((left, right), (right, left)):
        inner = _len_argument(near)
        if inner is not None and _bounds_below(op, far, flipped=near is right):
            proven.add(_unparse(inner))
        if isinstance(op, ast.Eq) and inner is None and _is_nonempty_literal(far):
            proven.add(_unparse(near))
    return proven


def _bounds_below(op: ast.cmpop, other: ast.expr, *, flipped: bool) -> bool:
    """Report whether `len(X) <op> other` forces `len(X) >= 1`."""
    value = other.value if isinstance(other, ast.Constant) else None
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    lower, upper = (op, value) if not flipped else (_mirror(op), value)
    match lower:
        case ast.Eq() | ast.GtE():
            return upper >= 1
        case ast.Gt():
            return upper >= 0
        case ast.NotEq():
            return upper == 0
        case _:
            return False


def _mirror(op: ast.cmpop) -> ast.cmpop:
    """Flip a comparison so the `len(...)` side reads on the left."""
    match op:
        case ast.Lt():
            return ast.Gt()
        case ast.LtE():
            return ast.GtE()
        case ast.Gt():
            return ast.Lt()
        case ast.GtE():
            return ast.LtE()
        case _:
            return op


def _len_argument(expr: ast.expr) -> ast.expr | None:
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "len" and len(expr.args) == 1:
        return expr.args[0]
    return None


def _is_nonempty_literal(expr: ast.expr) -> bool:
    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        return any(not isinstance(elt, ast.Starred) for elt in expr.elts)
    if isinstance(expr, ast.Dict):
        return any(key is not None for key in expr.keys)
    return False


# unittest's comparison assertions, normalised to the operator they imply.
_ASSERT_CMP_SUFFIXES: tuple[tuple[str, ast.cmpop], ...] = (
    ("greaterequal", ast.GtE()),
    ("greater", ast.Gt()),
    ("notequal", ast.NotEq()),
    ("countequal", ast.Eq()),
    ("equal", ast.Eq()),
)


def _assert_call_proves(call: ast.Call) -> set[str]:
    """Read what a `self.assertEqual(len(rows), 3)` style call proves."""
    name = _assertion_attr(call)
    if name is None:
        return set()
    flat = name.replace("_", "").lower()
    if flat in {"asserttrue", "assert"} and call.args:
        return _proves_nonempty(call.args[0])
    if flat.endswith("in") and len(call.args) >= 2:  # ruff:ignore[magic-value-comparison] — `assertIn(member, container)`
        return {_unparse(call.args[1])}
    if flat.endswith("len") and len(call.args) >= 2:  # ruff:ignore[magic-value-comparison] — `assertLen(seq, n)`
        return _comparison_proves(_as_len(call.args[0]), ast.Eq(), call.args[1])
    for suffix, op in _ASSERT_CMP_SUFFIXES:
        if flat.endswith(suffix) and len(call.args) >= 2:  # ruff:ignore[magic-value-comparison] — `assertEqual(a, b)`
            return _comparison_proves(call.args[0], op, call.args[1])
    return set()


def _as_len(expr: ast.expr) -> ast.Call:
    return ast.Call(func=ast.Name(id="len", ctx=ast.Load()), args=[expr], keywords=[])


def _assertion_attr(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else None


def _negation_proves(test: ast.expr) -> set[str]:
    """Read what `if <test>: return` proves once the guard is passed."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _proves_nonempty(test.operand)
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        return _emptiness_check_proves(test.left, test.ops[0], test.comparators[0])
    return set()


def _emptiness_check_proves(left: ast.expr, op: ast.cmpop, right: ast.expr) -> set[str]:
    proven: set[str] = set()
    for near, far in ((left, right), (right, left)):
        inner = _len_argument(near)
        if inner is None:
            continue
        value = far.value if isinstance(far, ast.Constant) else None
        if isinstance(op, ast.Eq) and value == 0:
            proven.add(_unparse(inner))
    return proven


def _iterable_is_nonempty(expr: ast.expr, facts: _Facts, seen: frozenset[str]) -> bool:
    """Report whether iterating `expr` is guaranteed to run the loop body once."""
    if isinstance(expr, (ast.Starred, ast.Await)):
        return _iterable_is_nonempty(expr.value, facts, seen)
    source = _unparse(expr)
    if source in facts.nonempty or (isinstance(expr, ast.Name) and expr.id in facts.roots):
        return True
    if _is_nonempty_literal(expr):
        return True
    if isinstance(expr, ast.Constant):
        return isinstance(expr.value, (str, bytes)) and len(expr.value) > 0
    if isinstance(expr, _COMP_NODES):
        generators = expr.generators
        first = generators[0] if generators else None
        return (
            len(generators) == 1
            and first is not None
            and not first.ifs
            and _iterable_is_nonempty(first.iter, facts, seen)
        )
    if isinstance(expr, ast.BinOp):
        return _binop_is_nonempty(expr, facts, seen)
    if isinstance(expr, ast.Call):
        return _call_is_nonempty(expr, facts, seen) or _is_static_table(expr, facts, seen)
    bound = facts.bindings.get(source)
    if bound is not None and bound is not expr and source not in seen:
        return _iterable_is_nonempty(bound, facts, seen | {source})
    return _is_static_table(expr, facts, seen)


def _is_static_table(expr: ast.expr, facts: _Facts, seen: frozenset[str]) -> bool:
    """Report whether the iterable names a fixed table rather than a computed result."""
    node = expr
    called = False
    while True:
        match node:
            case ast.Attribute(attr=attribute, value=value):
                if attribute[:1].isupper():
                    return True
                node = value
            case ast.Call(func=func):
                called = True
                node = func
            case ast.Subscript(value=value):
                node = value
            case _:
                break
    if not isinstance(node, ast.Name):
        return False
    if node.id[:1].isupper() or (node is not expr and node.id in facts.roots):
        return True
    # An imported *name* is a table in another file; an imported *function*
    # called here computes a fresh result, and that result can be empty.
    if not called and (node.id in facts.imported or (node is not expr and node.id in _FIXTURE_ROOTS)):
        return True
    # `validator = CommonPasswordValidator()` then `for p in validator.passwords:`
    # — the receiver has to be resolved before the chain reads as static.
    bound = facts.bindings.get(node.id)
    if bound is None or bound is expr or node.id in seen:
        return False
    return _is_static_table(bound, facts, seen | {node.id})


def _binop_is_nonempty(expr: ast.BinOp, facts: _Facts, seen: frozenset[str]) -> bool:
    if isinstance(expr.op, ast.Add):
        return _iterable_is_nonempty(expr.left, facts, seen) or _iterable_is_nonempty(expr.right, facts, seen)
    if isinstance(expr.op, ast.Mult):
        for seq, count in ((expr.left, expr.right), (expr.right, expr.left)):
            if _is_positive_int(count) and _iterable_is_nonempty(seq, facts, seen):
                return True
    return False


def _is_positive_int(expr: ast.expr) -> bool:
    return (
        isinstance(expr, ast.Constant)
        and isinstance(expr.value, int)
        and not isinstance(expr.value, bool)
        and expr.value > 0
    )


def _call_is_nonempty(expr: ast.Call, facts: _Facts, seen: frozenset[str]) -> bool:
    func = expr.func
    if isinstance(func, ast.Name):
        if func.id == "range":
            return _range_is_nonempty(expr, facts, seen)
        if func.id in _PASSTHROUGH_CALLS and expr.args:
            return _iterable_is_nonempty(expr.args[0], facts, seen)
        if func.id == "zip":
            # `zip` truncates to its shortest leg, so this is an assumption, not
            # a proof — but a test that zips two sequences together is asserting
            # they line up, and every corpus instance paired equal-length views
            # of one fixture (`zip(ref_geoms, ref_merged)`, `zip(t(), range(3))`).
            return any(_iterable_is_nonempty(arg, facts, seen) for arg in expr.args)
        return False
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in _ALWAYS_NONEMPTY_METHODS:
        return True
    if func.attr in _VIEW_METHODS and not expr.args:
        return _iterable_is_nonempty(func.value, facts, seen)
    if func.attr in _PASSTHROUGH_METHODS and expr.args:
        return _iterable_is_nonempty(expr.args[0], facts, seen)
    if func.attr in _PASSTHROUGH_METHODS:
        return _iterable_is_nonempty(func.value, facts, seen)
    return False


def _range_is_nonempty(expr: ast.Call, facts: _Facts, seen: frozenset[str]) -> bool:
    # `range(stop=3)` is legal to write but `range` takes no keywords, so a
    # keyword here means the name is not the builtin.
    if expr.keywords:
        return False
    # `for i in range(len(rows))` is `for row in rows` with an index.
    only = expr.args[0] if len(expr.args) == 1 else None
    sized = _len_argument(only) if only is not None else None
    if sized is not None:
        return _iterable_is_nonempty(sized, facts, seen)
    # `range(pickle.HIGHEST_PROTOCOL + 1)` — a count plus a positive offset is
    # empty only for a negative count, which no test means by it.
    if isinstance(only, ast.BinOp) and isinstance(only.op, ast.Add):
        return _is_positive_int(only.left) or _is_positive_int(only.right)
    bounds: list[int] = []
    for arg in expr.args:
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, int) and not isinstance(arg.value, bool)):
            return False
        bounds.append(arg.value)
    try:
        return len(range(*bounds)) > 0
    except ValueError, TypeError:
        # Invalid range arity or a zero step proves nothing about loop execution.
        return False
