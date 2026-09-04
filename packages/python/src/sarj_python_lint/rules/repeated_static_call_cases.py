from __future__ import annotations

import ast
from io import StringIO
from pathlib import PurePosixPath
import re
import tokenize
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
from sarj_python_lint.rules._comments import split_identifier
from sarj_python_lint.rules._paths import is_generated, is_test_path
from sarj_python_lint.rules.no_repeated_test_body import duplicate_test_owner_ids


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_MIN_CASES = 3
_MIN_DISTINCT_CASES = 2
_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_ACCESSOR_CALLEES = frozenset({"get"})
_ASSERTION_LINE_RE = re.compile(r"(?m)^\s*assert\b")
_SUPPRESSION_COMMENT_RE = re.compile(r"^#\s*sarj-noqa\b", re.IGNORECASE)
_UNSAFE_CALLEE_PARTS = frozenset({"mock", "snapshot", "spy"})
_MUTATING_CALLEE_WORDS = frozenset(
    {
        "add",
        "advance",
        "append",
        "commit",
        "consume",
        "create",
        "decrement",
        "delete",
        "execute",
        "increment",
        "insert",
        "next",
        "pop",
        "push",
        "put",
        "register",
        "remove",
        "send",
        "set",
        "transition",
        "update",
        "write",
    }
)


class _AssertionShape(NamedTuple):
    skeleton: object
    values: str


class _ParsedCall(NamedTuple):
    call: ast.Call
    awaited: bool


@final
class RepeatedStaticCallCases(Rule):
    id = "repeated-static-call-cases"
    code = "SARJ413"
    documentation = RuleDocumentation(
        summary="Three same-shape literal call assertions may be independent parameter cases.",
        rationale=(
            "When the calls are independent, named parameters isolate failures and identify the input that failed. "
            "Literal syntax alone cannot prove independence."
        ),
        remediation=(
            "Consider a named pytest parameter table only when call order, shared state, fixture lifecycle, and object "
            "identity are not part of the contract; otherwise keep the assertions together or suppress the warning."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        aliases=("repeated-static-call-assertions",),
        limitations=(
            "Only undecorated, zero-parameter pytest functions and methods on undecorated, base-free Test* classes are checked.",
            "The entire executable test body must be at least three top-level assertions of the same direct-name call with literal inputs and expectations.",
            "Assertion messages, zero-argument calls, likely mutators, mocks, snapshots, spies, comments, and intervening setup are excluded.",
            "Exception and pytest.raises case tables are intentionally outside this assertion-only signal.",
            "Common mapping accessors are excluded because repeated field assertions usually describe one cohesive object contract, not independent input cases.",
            "Tests participating in a no-repeated-test-body group are left to SARJ066, which has the broader finding.",
            "Case names and parameter boundaries require judgment, so the rule has no autofix.",
        ),
        examples=(
            RuleExample(
                example_id="parameterized-parser-cases",
                title="Give each parser input a runner-visible case",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_parser.py",
                        "@pytest.mark.parametrize(('value', 'expected'), [('a', 1), ('b', 2), ('c', 3)])\ndef test_parse(value, expected):\n    assert parse(value) == expected\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_parser.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="repeated-parser-assertions",
                title="Do not hide independent inputs in one callback",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_parser.py",
                        "def test_parse():\n    assert parse('a') == 1\n    assert parse('b') == 2\n    assert parse('c') == 3\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_parser.py"),
                expected_count=1,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source) or len(_ASSERTION_LINE_RE.findall(source)) < _MIN_CASES:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        unsafe_callees = _mutating_aliases(tree)
        tests = list(_test_functions(tree))
        rough_candidates = [
            test
            for test in tests
            if any(_is_whole_executable_body(test, run) for run in _runs(test, frozenset(), unsafe_callees))
        ]
        if not rough_candidates:
            return []
        comments = _comment_lines(source)
        candidate_runs = [
            (test, run)
            for test in rough_candidates
            for run in _runs(test, comments, unsafe_callees)
            if _is_whole_executable_body(test, run)
        ]
        if not candidate_runs:
            return []
        duplicate_owners = duplicate_test_owner_ids(tree, source)
        source_lines = source.splitlines()
        findings = [
            Diagnostic(
                path=path,
                line=run[0].lineno,
                col=run[0].col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message=(
                    f"these {len(run)} same-shape literal call assertions may be independent cases; consider named "
                    "pytest parameters only if order, shared state, fixture lifecycle, and identity are irrelevant."
                ),
            )
            for test, run in candidate_runs
            if id(test) not in duplicate_owners and not is_suppressed(source_lines, run[0].lineno, self.code)
        ]
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _dotted_name(node: ast.expr) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return None if parent is None else (*parent, node.attr)
    return None


def _comment_lines(source: str) -> frozenset[int]:
    try:
        return frozenset(
            token.start[0]
            for token in tokenize.generate_tokens(StringIO(source).readline)
            if token.type == tokenize.COMMENT and not _SUPPRESSION_COMMENT_RE.match(token.string)
        )
    except IndentationError, tokenize.TokenError:
        return frozenset()


def _test_functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    if any(
        isinstance(statement, (ast.Assign, ast.AnnAssign)) and _disables_named_collection(statement, "__test__")
        for statement in tree.body
    ):
        return
    disabled_objects = _disabled_test_object_ids(tree.body)
    for statement in tree.body:
        if (
            isinstance(statement, _FUNC_NODES)
            and (statement.name,) not in disabled_objects
            and _eligible_test_function(statement, method=False)
        ):
            yield statement
        elif (
            isinstance(statement, ast.ClassDef)
            and (statement.name,) not in disabled_objects
            and _eligible_test_class(statement)
        ):
            disabled_methods = _disabled_test_object_ids(statement.body)
            yield from (
                child
                for child in statement.body
                if isinstance(child, _FUNC_NODES)
                and (child.name,) not in disabled_methods
                and (statement.name, child.name) not in disabled_objects
                and _eligible_test_function(child, method=True)
            )


def _eligible_test_function(node: ast.FunctionDef | ast.AsyncFunctionDef, *, method: bool) -> bool:
    if not node.name.startswith("test_") or node.decorator_list:
        return False
    parameters = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, node.args.vararg, node.args.kwarg]
    allowed: frozenset[str] = frozenset({"self", "cls"}) if method else frozenset()
    return all(parameter is None or parameter.arg in allowed for parameter in parameters)


def _eligible_test_class(node: ast.ClassDef) -> bool:
    if not node.name.startswith("Test") or node.bases or node.keywords or node.decorator_list:
        return False
    return not any(
        (isinstance(statement, _FUNC_NODES) and statement.name in {"__init__", "__new__"})
        or (isinstance(statement, (ast.Assign, ast.AnnAssign)) and _disables_pytest_collection(statement))
        for statement in node.body
    )


def _disables_pytest_collection(node: ast.Assign | ast.AnnAssign) -> bool:
    return _disables_named_collection(node, "__test__")


def _disables_named_collection(node: ast.Assign | ast.AnnAssign, name: str) -> bool:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    value = node.value
    return (
        any(isinstance(target, ast.Name) and target.id == name for target in targets)
        and value is not None
        and _is_statically_falsy(value)
    )


def _disabled_test_object_ids(body: list[ast.stmt]) -> frozenset[tuple[str, ...]]:
    aliases = _object_aliases(body)
    identities: set[tuple[str, ...]] = set()
    for statement in body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if statement.value is None or not _is_statically_falsy(statement.value):
            continue
        for target in targets:
            dotted = _dotted_name(target)
            if dotted is None or not dotted[:-1] or dotted[-1] != "__test__":
                continue
            identities.update(_resolve_aliases(dotted[:-1], aliases))
    return frozenset(identities)


def _object_aliases(body: list[ast.stmt]) -> dict[tuple[str, ...], frozenset[tuple[str, ...]]]:
    mutable_aliases: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
    for statement in body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)) or statement.value is None:
            continue
        source = _dotted_name(statement.value)
        if source is None:
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        for target in targets:
            if isinstance(target, ast.Name) and (target.id,) != source:
                mutable_aliases.setdefault((target.id,), set()).add(source)
    return {name: frozenset(sources) for name, sources in mutable_aliases.items()}


def _resolve_aliases(
    identity: tuple[str, ...],
    aliases: dict[tuple[str, ...], frozenset[tuple[str, ...]]],
) -> frozenset[tuple[str, ...]]:
    pending = [identity]
    seen: set[tuple[str, ...]] = set()
    roots: set[tuple[str, ...]] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        sources = aliases.get(current)
        if sources:
            pending.extend(sources)
        elif len(current) > 1 and (prefix_sources := aliases.get(current[:1])):
            pending.extend((*source, *current[1:]) for source in prefix_sources)
        else:
            roots.add(current)
    return frozenset(roots or seen)


def _is_statically_falsy(node: ast.expr) -> bool:
    match node:
        case ast.Constant(value=value):
            return not bool(value)
        case ast.Tuple(elts=elts) | ast.List(elts=elts) | ast.Set(elts=elts):
            return not elts
        case ast.Dict(keys=keys):
            return not keys
        case ast.Call(func=ast.Name(id="set"), args=[], keywords=[]):
            return True
        case _:
            return False


def _mutating_aliases(tree: ast.Module) -> frozenset[str]:
    aliases: set[str] = set()
    for statement in tree.body:
        if not isinstance(statement, ast.ImportFrom):
            continue
        aliases.update(
            alias.asname or alias.name
            for alias in statement.names
            if not frozenset(split_identifier(alias.name)).isdisjoint(_MUTATING_CALLEE_WORDS)
        )

    changed = True
    while changed:
        changed = False
        for statement in tree.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)) or statement.value is None:
                continue
            source = _dotted_name(statement.value)
            if source is None or (
                source[-1] not in aliases and frozenset(split_identifier(source[-1])).isdisjoint(_MUTATING_CALLEE_WORDS)
            ):
                continue
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True
    return frozenset(aliases)


def _runs(
    test: ast.FunctionDef | ast.AsyncFunctionDef,
    comments: frozenset[int],
    unsafe_callees: frozenset[str],
) -> Iterator[list[ast.Assert]]:
    current: list[ast.Assert] = []
    current_shape: object | None = None
    current_values: set[str] = set()
    for statement in test.body:
        if not isinstance(statement, ast.Assert) or _has_attached_comment(statement, comments):
            if len(current) >= _MIN_CASES and len(current_values) >= _MIN_DISTINCT_CASES:
                yield current
            current, current_shape, current_values = [], None, set()
            continue
        parsed = _assertion_shape(statement, unsafe_callees)
        if parsed is None:
            if len(current) >= _MIN_CASES and len(current_values) >= _MIN_DISTINCT_CASES:
                yield current
            current, current_shape, current_values = [], None, set()
            continue
        if current and (parsed.skeleton != current_shape or _has_intervening_comment(current[-1], statement, comments)):
            if len(current) >= _MIN_CASES and len(current_values) >= _MIN_DISTINCT_CASES:
                yield current
            current, current_values = [], set()
        current.append(statement)
        current_shape = parsed.skeleton
        current_values.add(parsed.values)
    if len(current) >= _MIN_CASES and len(current_values) >= _MIN_DISTINCT_CASES:
        yield current


def _is_whole_executable_body(
    test: ast.FunctionDef | ast.AsyncFunctionDef,
    run: list[ast.Assert],
) -> bool:
    body = test.body[1:] if ast.get_docstring(test, clean=False) is not None else test.body
    return len(body) == len(run) and all(statement is assertion for statement, assertion in zip(body, run, strict=True))


def _assertion_shape(node: ast.Assert, unsafe_callees: frozenset[str]) -> _AssertionShape | None:
    if node.msg is not None:
        return None
    expression = node.test
    polarity = "truthy"
    expectation: ast.expr | None = None
    call_expr: ast.expr
    if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
        polarity = "falsy"
        call_expr = expression.operand
    elif isinstance(expression, ast.Compare) and len(expression.ops) == 1 and len(expression.comparators) == 1:
        call_expr = expression.left
        expectation = expression.comparators[0]
        polarity = type(expression.ops[0]).__name__
    else:
        call_expr = expression
    parsed = _call(call_expr)
    if parsed is None or (expectation is not None and not _static(expectation)):
        return None
    callee = _dotted_name(parsed.call.func)
    if (
        callee is None
        or len(callee) != 1
        or not _eligible_callee(callee, unsafe_callees)
        or not _has_static_call_inputs(parsed.call)
    ):
        return None
    skeleton = (
        callee,
        parsed.awaited,
        polarity,
        tuple(_static_shape(arg) for arg in parsed.call.args),
        tuple((keyword.arg, _static_shape(keyword.value)) for keyword in parsed.call.keywords),
        None if expectation is None else _static_shape(expectation),
    )
    values = _static_value(
        ast.Tuple(
            elts=[*parsed.call.args, *(keyword.value for keyword in parsed.call.keywords)],
            ctx=ast.Load(),
        )
    )
    return _AssertionShape(skeleton, values)


def _has_static_call_inputs(call: ast.Call) -> bool:
    return (
        bool(call.args or call.keywords)
        and all(not isinstance(argument, ast.Starred) and _static(argument) for argument in call.args)
        and all(keyword.arg is not None and _static(keyword.value) for keyword in call.keywords)
    )


def _eligible_callee(callee: tuple[str, ...], unsafe_callees: frozenset[str]) -> bool:
    words = frozenset(split_identifier(callee[-1]))
    return (
        callee[-1] not in _ACCESSOR_CALLEES
        and callee[-1] not in unsafe_callees
        and words.isdisjoint(_MUTATING_CALLEE_WORDS)
        and not any(any(part in segment.lower() for part in _UNSAFE_CALLEE_PARTS) for segment in callee)
    )


def _has_intervening_comment(previous: ast.Assert, current: ast.Assert, comments: frozenset[int]) -> bool:
    return any((previous.end_lineno or previous.lineno) < line < current.lineno for line in comments)


def _has_attached_comment(statement: ast.Assert, comments: frozenset[int]) -> bool:
    return any(statement.lineno <= line <= (statement.end_lineno or statement.lineno) for line in comments)


def _call(node: ast.expr) -> _ParsedCall | None:
    awaited = isinstance(node, ast.Await)
    candidate = node.value if awaited else node
    return _ParsedCall(candidate, awaited) if isinstance(candidate, ast.Call) else None


def _static(node: ast.expr) -> bool:
    match node:
        case ast.Constant():
            return True
        case ast.UnaryOp(op=ast.UAdd() | ast.USub() | ast.Invert(), operand=operand):
            return _static(operand)
        case ast.Tuple() | ast.List() | ast.Set():
            return all(_static(elt) for elt in node.elts)
        case ast.Dict(keys=keys, values=values):
            return all(key is not None and _static(key) for key in keys) and all(_static(value) for value in values)
        case _:
            return False


def _static_shape(node: ast.expr) -> object:
    match node:
        case ast.Constant(value=value):
            return ("constant", type(value).__name__)
        case ast.UnaryOp(op=op, operand=operand):
            return (type(op).__name__, _static_shape(operand))
        case ast.Tuple() | ast.List() | ast.Set():
            return (type(node).__name__, tuple(_static_shape(elt) for elt in node.elts))
        case ast.Dict(keys=keys, values=values):
            return (
                "Dict",
                tuple(
                    (_static_shape(key), _static_shape(value)) for key, value in zip(keys, values, strict=True) if key
                ),
            )
        case _:
            raise AssertionError


def _static_value(node: ast.expr) -> str:
    rendered = ast.dump(node, annotate_fields=False, include_attributes=False)
    return rendered[:512]
