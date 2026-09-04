from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, nodes, walk
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_DEFERRED_SCOPES = (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_NON_CACHEABLE_CALLEE_NAMES = frozenset(
    {
        "anext",
        "choice",
        "choices",
        "get_nowait",
        "getattr",
        "hasattr",
        "input",
        "isinstance",
        "issubclass",
        "next",
        "now",
        "perf_counter",
        "pop",
        "popleft",
        "random",
        "randint",
        "randrange",
        "read",
        "readline",
        "readlines",
        "recv",
        "recvfrom",
        "sample",
        "send",
        "shuffle",
        "throw",
        "time",
        "today",
        "utcnow",
        "uuid4",
    }
)


def _check_comprehension_node(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    source_lines: list[str],
    code: str,
    path: Path,
    parents: dict[ast.AST, ast.AST],
) -> list[Diagnostic]:
    if len(node.generators) != 1 or not _has_callable_scope(node, parents):
        return []

    gen = node.generators[0]
    if not gen.ifs:
        return []

    elt_nodes: list[ast.expr] = (
        [node.elt] if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp) else [node.key, node.value]
    )
    calls_in_elts = [candidate for elt in elt_nodes for candidate in _calls_in_immediate_scope(elt)]
    diags: list[Diagnostic] = []
    reported: set[str] = set()

    for if_clause in gen.ifs:
        calls_in_if = _calls_in_immediate_scope(if_clause)
        for call in calls_in_if:
            signature = ast.dump(call, include_attributes=False)
            if signature in reported or _should_abstain_for_callee(call):
                continue
            if not _runs_on_every_retained_path(call, if_clause, parents):
                continue
            if any(not ast.compare(call, other) for other in calls_in_if):
                continue
            if not any(ast.compare(call, candidate) for candidate in calls_in_elts):
                continue
            if any(not ast.compare(call, candidate) for candidate in calls_in_elts):
                continue
            reported.add(signature)
            line = getattr(if_clause, "lineno", 1)
            col = getattr(if_clause, "col_offset", 0) + 1
            if not is_suppressed(source_lines, line, code):
                diags.append(
                    Diagnostic(
                        path=path,
                        line=line,
                        col=col,
                        code=code,
                        message=(
                            "The same call runs in this comprehension filter and result — "
                            "if reevaluation is unintended, bind it once with a fresh name."
                        ),
                    )
                )

    return diags


def _calls_in_immediate_scope(expression: ast.expr) -> list[ast.Call]:
    if isinstance(expression, _DEFERRED_SCOPES):
        return []
    calls: list[ast.Call] = []
    stack: list[ast.AST] = [expression]
    while stack:
        current = stack.pop()
        if current is not expression and isinstance(current, _DEFERRED_SCOPES):
            continue
        if isinstance(current, (ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr)):
            continue
        if isinstance(current, ast.Call):
            if any(isinstance(descendant, ast.Call) for child in children(current) for descendant in walk(child)):
                continue
            calls.append(current)
            continue
        stack.extend(reversed(children(current)))
    return calls


def _runs_on_every_retained_path(call: ast.Call, clause: ast.expr, parents: dict[ast.AST, ast.AST]) -> bool:
    child: ast.AST = call
    while child is not clause:
        parent = parents.get(child)
        if parent is None:
            return False
        if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.Or) and parent.values[0] is not child:
            return False
        if isinstance(parent, ast.IfExp) and parent.test is not child:
            return False
        if isinstance(parent, _DEFERRED_SCOPES):
            return False
        child = parent
    return True


def _should_abstain_for_callee(call: ast.Call) -> bool:
    name = _callee_name(call)
    return name is None or name.casefold() in _NON_CACHEABLE_CALLEE_NAMES


def _callee_name(call: ast.Call) -> str | None:
    match call.func:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def _has_callable_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    child = node
    while (parent := parents.get(child)) is not None:
        match parent:
            case ast.TypeAlias() | ast.TypeVar() | ast.ParamSpec() | ast.TypeVarTuple():
                return False
            case ast.arg() | ast.AnnAssign() if child is parent.annotation:
                return False
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                if child is parent.returns:
                    return False
                if child in parent.body:
                    return True
            case ast.Lambda():
                if child is parent.body:
                    return True
            case ast.ClassDef():
                if child in parent.body:
                    return False
            case ast.Module():
                return False
            case _:
                pass
        child = parent
    return False


class PreferWalrusComprehensionFilter(Rule):
    id: str = "prefer-walrus-comprehension-filter"
    code: str = "SARJ076"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="The same call runs in a comprehension filter and its result.",
        rationale="When both evaluations are intended to produce one stable value, repeating the call wastes work and obscures that relationship.",
        remediation=(
            "If reevaluation is unintended, bind the result once in the filter with a fresh containing-scope name and reuse it. "
            "Keep separate calls or use an explicit loop when each evaluation is meaningful."
        ),
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only single-generator comprehensions inside non-test callable bodies are analyzed; generated code and nested or deferred expression scopes are excluded.",
            "Nested calls, differing sibling calls, unsafe short-circuit branches, and recognized type-inspection, consuming, or nondeterministic calls are excluded.",
            "The rule cannot prove referential transparency. A named expression binds in the containing callable, so the chosen name must be fresh and reviewed.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-comprehension-call",
                title="Comprehension evaluates one call twice",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/values.py",
                        "def normalized(values):\n    return [value.strip() for value in values if value.strip()]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/values.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="bound-comprehension-result",
                title="Comprehension evaluates the call once",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/values.py",
                        "def normalized(values):\n    return [clean for value in values if (clean := value.strip())]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/values.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source):
            return []
        if "for" not in source or "if" not in source or "(" not in source:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        comprehensions = nodes(tree, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        if not comprehensions:
            return []
        source_lines = source.splitlines()
        diags: list[Diagnostic] = []
        parents = {child: parent for parent in nodes(tree, ast.AST) for child in children(parent)}

        for node in comprehensions:
            diags.extend(_check_comprehension_node(node, source_lines, self.code, path, parents))

        return sorted(diags, key=lambda d: (d.line, d.col))
