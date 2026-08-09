"""SARJ080 — Prefer match/case for explicit runtime type dispatch.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_match_type_dispatch.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_GENERIC_EXCEPTIONS = frozenset({"Exception", "BaseException"})
_MIN_SENTINEL_COUNT = 2
_MIN_TYPE_DISPATCH_BRANCHES = 3
_ISINSTANCE_ARG_COUNT = 2
_PAIR_COUNT = 2

# Lowercase builtins are valid class-pattern heads; other lowercase names may be runtime tuples or aliases.
_MATCHABLE_BUILTIN_TYPES = frozenset(
    {
        "bool",
        "bytearray",
        "bytes",
        "complex",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "memoryview",
        "object",
        "range",
        "set",
        "str",
        "tuple",
        "type",
    }
)

# A try body longer than this is a fault barrier, not a dispatch.
_MAX_TRY_BODY_LINES = 20


def _handler_exception_names(handler: ast.ExceptHandler) -> set[str] | None:
    """Extract the exception class names one handler catches."""
    if handler.type is None:
        return None
    caught: set[str] = set()
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    for node in types:
        if isinstance(node, ast.Name):
            caught.add(node.id)
        elif isinstance(node, ast.Attribute):
            caught.add(node.attr)
            caught.add(ast.unparse(node))
    return caught


def _first_matching_handler(try_node: ast.Try | ast.TryStar, exc_name: str) -> ast.ExceptHandler | None:
    """Find the handler that would actually receive `exc_name`."""
    for handler in try_node.handlers:
        names = _handler_exception_names(handler)
        if names is None or exc_name in names or bool(names & _GENERIC_EXCEPTIONS):
            return handler
    return None


def _raised_exception_name(raise_node: ast.Raise) -> str | None:
    """Extract exception class name from `raise Exc()` or `raise Exc`."""
    match raise_node.exc:
        case (
            ast.Call(func=ast.Name(id=name))
            | ast.Name(id=name)
            | ast.Call(func=ast.Attribute(attr=name))
            | ast.Attribute(attr=name)
        ):
            return name
        case _:
            pass
    return None


def _is_docstring(stmt: ast.stmt) -> bool:
    """Report whether `stmt` is a bare string expression."""
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _always_raises(body: list[ast.stmt]) -> bool:
    """Report whether every terminal path through `body` ends in a `raise`."""
    stmts = [stmt for stmt in body if not _is_docstring(stmt)]
    if not stmts:
        return False
    last = stmts[-1]
    match last:
        case ast.Raise():
            return True
        case ast.If(body=body, orelse=orelse):
            return bool(orelse) and _always_raises(body) and _always_raises(orelse)
        case ast.With() | ast.AsyncWith():
            return _always_raises(last.body)
        case ast.Try() | ast.TryStar():
            return _always_raises(last.orelse or last.body) and all(
                _always_raises(handler.body) for handler in last.handlers
            )
        case _:
            return False


def _try_body_span(try_node: ast.Try | ast.TryStar) -> int:
    """Measure the try body in source lines."""
    end = max((stmt.end_lineno or stmt.lineno) for stmt in try_node.body)
    return end - try_node.lineno


def _is_bare_raise_body(try_node: ast.Try | ast.TryStar) -> bool:
    """Report whether the try body is nothing but a single `raise`."""
    return len(try_node.body) == 1 and isinstance(try_node.body[0], ast.Raise)


def _shadows_isinstance(tree: ast.Module) -> bool:
    """Take a whole-file false negative if the builtin cannot be proven."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == "isinstance":
            return True
        if isinstance(node, ast.arg) and node.arg == "isinstance":
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == "isinstance":
            return True
        if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name == "isinstance":
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound_name = alias.asname or (
                    alias.name if isinstance(node, ast.ImportFrom) else alias.name.split(".", 1)[0]
                )
                if bound_name == "isinstance":
                    return True
    return False


def _matchable_isinstance_test(test: ast.expr) -> str | None:
    """Extract the simple subject of an isinstance test convertible to patterns."""
    if not isinstance(test, ast.Call) or not isinstance(test.func, ast.Name) or test.func.id != "isinstance":
        return None
    if len(test.args) != _ISINSTANCE_ARG_COUNT or test.keywords or not isinstance(test.args[0], ast.Name):
        return None

    checked_types = test.args[1]
    if isinstance(checked_types, ast.Tuple):
        if not checked_types.elts or not all(_matchable_class_reference(item) for item in checked_types.elts):
            return None
    elif not _matchable_class_reference(checked_types):
        return None
    return test.args[0].id


def _matchable_class_reference(node: ast.expr) -> bool:
    """Report whether `node` can safely head a class pattern."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _matchable_class_reference(node.left) and _matchable_class_reference(node.right)
    if isinstance(node, ast.Name):
        return node.id in _MATCHABLE_BUILTIN_TYPES or (node.id[:1].isupper() and not node.id.isupper())
    if isinstance(node, ast.Attribute):
        matchable_leaf = node.attr in _MATCHABLE_BUILTIN_TYPES or (node.attr[:1].isupper() and not node.attr.isupper())
        return matchable_leaf and _is_dotted_name(node.value)
    return False


def _is_dotted_name(node: ast.expr) -> bool:
    """Report whether `node` is the prefix of a pattern-compatible dotted name."""
    if isinstance(node, ast.Name):
        return True
    return isinstance(node, ast.Attribute) and _is_dotted_name(node.value)


def _is_matchable_raise_guard(test: ast.expr) -> bool:
    """Report whether a raise is directly guarded by type or None dispatch."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _is_matchable_raise_guard(test.operand)
    if _matchable_isinstance_test(test) is not None:
        return True
    return (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], (ast.Is, ast.IsNot))
        and isinstance(test.left, ast.Name)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value is None
    )


def _isinstance_ladder(node: ast.If) -> tuple[str, int] | None:
    """Recognize a complete if/elif chain dispatching one name by runtime type."""
    subject: str | None = None
    branch_count = 0
    current = node
    while True:
        branch_subject = _matchable_isinstance_test(current.test)
        if branch_subject is None or (subject is not None and branch_subject != subject):
            return None
        subject = branch_subject
        branch_count += 1

        if not current.orelse:
            break
        if len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
            current = current.orelse[0]
            continue
        break

    if branch_count < _MIN_TYPE_DISPATCH_BRANCHES:
        return None
    return subject, branch_count


def _sequential_isinstance_dispatches(tree: ast.Module, path: Path, code: str) -> list[Diagnostic]:
    """Find exclusive type dispatch spelled as terminating sibling if statements."""
    findings: list[Diagnostic] = []
    for owner in ast.walk(tree):
        for statements in _statement_blocks(owner):
            if not statements:
                continue
            index = 0
            while index < len(statements):
                first = statements[index]
                if not isinstance(first, ast.If) or first.orelse or not _body_terminates(first.body):
                    index += 1
                    continue
                subject = _matchable_isinstance_test(first.test)
                if subject is None:
                    index += 1
                    continue
                end = index
                while end < len(statements):
                    candidate = statements[end]
                    if (
                        not isinstance(candidate, ast.If)
                        or candidate.orelse
                        or _matchable_isinstance_test(candidate.test) != subject
                        or not _body_terminates(candidate.body)
                    ):
                        break
                    end += 1
                branch_count = end - index
                guards = [_passthrough_guard_var(statement) for statement in statements[index:end]]
                owned_by_sentinel_arm = guards[:_MIN_SENTINEL_COUNT] == [subject] * _MIN_SENTINEL_COUNT
                if branch_count >= _MIN_TYPE_DISPATCH_BRANCHES and not owned_by_sentinel_arm:
                    findings.append(
                        Diagnostic(
                            path=path,
                            line=first.lineno,
                            col=first.col_offset + 1,
                            code=code,
                            message=(
                                f"{branch_count}-branch terminating isinstance dispatch on '{subject}' — use "
                                "match/case class patterns so the exclusive type dispatch is explicit."
                            ),
                        )
                    )
                index = max(end, index + 1)
    return findings


def _body_terminates(body: list[ast.stmt]) -> bool:
    """Prove a branch cannot fall through to the following sibling statement."""
    statements = [statement for statement in body if not _is_docstring(statement)]
    if not statements:
        return False
    last = statements[-1]
    match last:
        case ast.Return() | ast.Raise() | ast.Break() | ast.Continue():
            return True
        case ast.If(body=body, orelse=orelse):
            return bool(orelse) and _body_terminates(body) and _body_terminates(orelse)
        case ast.With() | ast.AsyncWith():
            return _body_terminates(last.body)
        case _:
            return False


def _statement_blocks(node: ast.AST) -> tuple[list[ast.stmt], ...]:
    """Return each ordered statement block directly owned by an AST node."""
    match node:
        case ast.Module() | ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return (node.body,)
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            return node.body, node.orelse
        case ast.With() | ast.AsyncWith() | ast.ExceptHandler() | ast.match_case():
            return (node.body,)
        case ast.Try() | ast.TryStar():
            return node.body, node.orelse, node.finalbody, *(handler.body for handler in node.handlers)
        case _:
            return ()


def _repeated_match_attribute_captures(node: ast.Match, path: Path, code: str) -> list[Diagnostic]:
    """Find OR-patterns that redundantly destructure one shared attribute."""
    findings: list[Diagnostic] = []
    if not isinstance(node.subject, ast.Name):
        return findings
    subject = node.subject.id
    for case in node.cases:
        if case.guard is not None or not isinstance(case.pattern, ast.MatchOr):
            continue
        alternatives = case.pattern.patterns
        if len(alternatives) < _PAIR_COUNT:
            continue
        capture_maps = [_class_pattern_keyword_captures(pattern) for pattern in alternatives]
        if any(captures is None for captures in capture_maps):
            continue
        class_captures = [captures for captures in capture_maps if captures is not None]
        if subject in _bound_pattern_names(case.pattern):
            continue
        _, subject_rebound = _body_name_contexts(case.body, subject)
        if subject_rebound:
            continue

        shared = set(class_captures[0].items())
        for captures in class_captures[1:]:
            shared.intersection_update(captures.items())

        used_shared: list[tuple[str, str]] = []
        for attribute, capture in sorted(shared):
            loaded, rebound = _body_name_contexts(case.body, capture)
            if loaded and not rebound and not _unsafe_direct_attribute_use(case.body, subject, capture):
                used_shared.append((attribute, capture))
        if not used_shared:
            continue

        repeated = _join_guidance([f"`{attribute}={capture}`" for attribute, capture in used_shared])
        direct = _join_guidance([f"`{subject}.{attribute}`" for attribute, _ in used_shared])
        findings.append(
            Diagnostic(
                path=path,
                line=case.pattern.lineno,
                col=case.pattern.col_offset + 1,
                code=code,
                message=(
                    f"Class OR-pattern repeats {repeated} across {len(alternatives)} class alternatives — "
                    f"match the types without the repeated capture and use {direct} in the case body."
                ),
            )
        )
    return findings


def _class_pattern_keyword_captures(pattern: ast.pattern) -> dict[str, str] | None:
    """Return direct ``attribute=name`` captures from one class pattern."""
    if not isinstance(pattern, ast.MatchClass):
        return None
    captures: dict[str, str] = {}
    for attribute, keyword_pattern in zip(pattern.kwd_attrs, pattern.kwd_patterns, strict=True):
        capture = _simple_pattern_capture(keyword_pattern)
        if capture is not None:
            captures[attribute] = capture
    return captures


def _simple_pattern_capture(pattern: ast.pattern) -> str | None:
    """Return the name bound by a plain keyword capture pattern."""
    match pattern:
        case ast.MatchAs(pattern=None, name=str() as name):
            return name
        case _:
            return None


def _bound_pattern_names(pattern: ast.pattern) -> set[str]:
    """Collect every name a pattern binds in its case body."""
    names: set[str] = set()
    for node in ast.walk(pattern):
        match node:
            case (
                ast.MatchAs(name=str() as name)
                | ast.MatchStar(name=str() as name)
                | ast.MatchMapping(rest=str() as name)
            ):
                names.add(name)
            case _:
                pass
    return names


def _body_name_contexts(body: list[ast.stmt], name: str) -> tuple[bool, bool]:
    """Report whether a case body loads and rebinds one name."""
    loaded = False
    rebound = False
    for statement in body:
        for node in ast.walk(statement):
            if not isinstance(node, ast.Name) or node.id != name:
                continue
            if isinstance(node.ctx, ast.Load):
                loaded = True
            else:
                rebound = True
    return loaded, rebound


def _unsafe_direct_attribute_use(body: list[ast.stmt], subject: str, capture: str) -> bool:
    """Reject bodies where a capture is a snapshot rather than a direct read."""
    for statement in body:
        for node in ast.walk(statement):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)) and any(
                isinstance(nested, ast.Name) and nested.id == capture for nested in ast.walk(node)
            ):
                return True
            if (
                isinstance(node, (ast.Attribute, ast.Subscript))
                and not isinstance(node.ctx, ast.Load)
                and _rooted_in_name(node, subject)
            ):
                return True
    return False


def _rooted_in_name(node: ast.expr, name: str) -> bool:
    """Report whether an attribute or subscript chain starts at one name."""
    current = node
    while isinstance(current, (ast.Attribute, ast.Subscript)):
        current = current.value
    return isinstance(current, ast.Name) and current.id == name


def _join_guidance(items: list[str]) -> str:
    """Join a short diagnostic list without losing code formatting."""
    if len(items) == 1:
        return items[0]
    if len(items) == _PAIR_COUNT:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _passthrough_guard_var(stmt: ast.stmt) -> str | None:
    """Extract the variable of a sentinel *passthrough* guard."""
    if not isinstance(stmt, ast.If) or stmt.orelse or len(stmt.body) != 1:
        return None
    returned = stmt.body[0]
    if not isinstance(returned, ast.Return) or not isinstance(returned.value, ast.Name):
        return None
    var = returned.value.id

    if _is_type_check_call(stmt.test, var) or _is_none_identity_test(stmt.test, var):
        return var
    return None


def _is_type_check_call(test: ast.expr, var: str) -> bool:
    """Report whether `test` is `isinstance(var, ...)` or `issubclass(var, ...)`."""
    if not isinstance(test, ast.Call) or not isinstance(test.func, ast.Name):
        return False
    if test.func.id not in {"isinstance", "issubclass"} or not test.args:
        return False
    first = test.args[0]
    return isinstance(first, ast.Name) and first.id == var


def _is_none_identity_test(test: ast.expr, var: str) -> bool:
    """Report whether `test` is `var is None` or `var is not None`."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], (ast.Is, ast.IsNot)):
        return False
    if not isinstance(test.left, ast.Name) or test.left.id != var:
        return False
    comparator = test.comparators[0]
    return isinstance(comparator, ast.Constant) and comparator.value is None


def _check_sequential_type_guards(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef, path: Path, code: str
) -> list[Diagnostic]:
    """Check for 2+ sequential sentinel passthrough guards on the SAME variable."""
    body = func_node.body
    if not body:
        return []

    start_idx = 1 if len(body) > 1 and _is_docstring(body[0]) else 0
    stmts = body[start_idx:]
    if len(stmts) < _MIN_SENTINEL_COUNT:
        return []

    target_var: str | None = None
    sentinel_count = 0
    for stmt in stmts:
        var = _passthrough_guard_var(stmt)
        if var is None or (target_var is not None and var != target_var):
            break
        target_var = var
        sentinel_count += 1

    if sentinel_count < _MIN_SENTINEL_COUNT:
        return []

    first_if = stmts[0]
    return [
        Diagnostic(
            path=path,
            line=getattr(first_if, "lineno", func_node.lineno),
            col=first_if.col_offset + 1,
            code=code,
            message=(
                f"Sequential sentinel/type guards ({sentinel_count} checks on '{target_var}') "
                f"in function '{func_node.name}' — refactor into Python 3.10+ match/case pattern matching "
                f"(e.g., 'case None | Unset():')."
            ),
        )
    ]


@final
class _TypeDispatchVisitor(ast.NodeVisitor):
    def __init__(
        self,
        path: Path,
        code: str,
        *,
        report_control_flow_raise: bool,
        report_isinstance_ladder: bool,
    ) -> None:
        self.path: Path = path
        self.code: str = code
        self.report_control_flow_raise: bool = report_control_flow_raise
        self.report_isinstance_ladder: bool = report_isinstance_ladder
        self.diags: list[Diagnostic] = []
        self.try_stack: list[ast.Try | ast.TryStar] = []
        self.if_stack: list[ast.If] = []
        self.ladder_continuations: set[int] = set()

    def visit_If(self, node: ast.If) -> None:
        if self.report_isinstance_ladder and id(node) not in self.ladder_continuations:
            continuation = node
            while len(continuation.orelse) == 1 and isinstance(continuation.orelse[0], ast.If):
                continuation = continuation.orelse[0]
                self.ladder_continuations.add(id(continuation))
            ladder = _isinstance_ladder(node)
            if ladder is not None:
                subject, branch_count = ladder
                self.diags.append(
                    Diagnostic(
                        path=self.path,
                        line=node.lineno,
                        col=node.col_offset + 1,
                        code=self.code,
                        message=(
                            f"{branch_count}-branch isinstance dispatch on '{subject}' — use match/case "
                            "class patterns (combining tuple members with `|`) so the type dispatch is explicit."
                        ),
                    )
                )
        self.if_stack.append(node)
        self.generic_visit(node)
        self.if_stack.pop()

    def visit_Match(self, node: ast.Match) -> None:
        self.diags.extend(_repeated_match_attribute_captures(node, self.path, self.code))
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        self.try_stack.append(node)
        for stmt in node.body:
            self.visit(stmt)
        self.try_stack.pop()
        for handler in node.handlers:
            self.visit(handler)
        for stmt in node.orelse:
            self.visit(stmt)
        for stmt in node.finalbody:
            self.visit(stmt)

    @override
    def visit_TryStar(self, node: ast.TryStar) -> None:
        self.visit_Try(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        if self.report_control_flow_raise:
            self._check_control_flow_raise(node)
        self.generic_visit(node)

    def _check_control_flow_raise(self, node: ast.Raise) -> None:
        if not self.if_stack or not _is_matchable_raise_guard(self.if_stack[-1].test):
            return
        exc_name = _raised_exception_name(node)
        if exc_name is None:
            return

        # Only the innermost try that would catch this exception can see it;
        # anything further out never runs, so the search stops there.
        target: tuple[ast.Try | ast.TryStar, ast.ExceptHandler] | None = None
        for try_node in reversed(self.try_stack):
            handler = _first_matching_handler(try_node, exc_name)
            if handler is not None:
                target = (try_node, handler)
                break
        if target is None:
            return
        try_node, handler = target

        names = _handler_exception_names(handler)
        if names is None or exc_name not in names:
            return
        if _always_raises(handler.body):
            return
        if _try_body_span(try_node) > _MAX_TRY_BODY_LINES:
            return
        if _is_bare_raise_body(try_node):
            return

        self.diags.append(
            Diagnostic(
                path=self.path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"Control-flow raise in try block — 'raise {exc_name}()' "
                    f"jumps directly to local except handler. Refactor to 'match/case' "
                    f"(e.g., 'case str():') to handle types directly."
                ),
            )
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.diags.extend(_check_sequential_type_guards(node, self.path, self.code))
        saved_stack = self.try_stack
        saved_if_stack = self.if_stack
        self.try_stack = []
        self.if_stack = []
        self.generic_visit(node)
        self.try_stack = saved_stack
        self.if_stack = saved_if_stack

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.diags.extend(_check_sequential_type_guards(node, self.path, self.code))
        saved_stack = self.try_stack
        saved_if_stack = self.if_stack
        self.try_stack = []
        self.if_stack = []
        self.generic_visit(node)
        self.try_stack = saved_stack
        self.if_stack = saved_if_stack

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.generic_visit(node)


class PreferMatchTypeDispatch(Rule):
    id: str = "prefer-match-type-dispatch"
    code: str = "SARJ080"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Use `match` for explicit runtime type dispatch instead of branching parser machinery.",
        rationale="Pattern matching makes type cases and sentinel cases explicit without control-flow exceptions or repeated dispatch checks.",
        remediation="Replace the detected guard or exception-driven dispatch with `match` arms for each supported value shape.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule targets several measured shapes, including control-flow raises, sequential guards, and repeated `isinstance` dispatch.",
            "Generated files and code that shadows `isinstance` are excluded; test files omit the control-flow-raise check.",
        ),
        examples=(
            RuleExample(
                example_id="sequential-type-guards",
                title="Parser dispatches through sequential guards",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/parser.py",
                        "def parse(value: object):\n"
                        "    if value is None:\n"
                        "        return value\n"
                        "    if isinstance(value, Unset):\n"
                        "        return value\n"
                        "    if isinstance(value, int):\n"
                        "        return str(value)\n"
                        "    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parser.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="match-type-cases",
                title="Parser names value shapes with match arms",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/parser.py",
                        "def parse(value: object):\n"
                        "    match value:\n"
                        "        case None | Unset():\n"
                        "            return value\n"
                        "        case int():\n"
                        "            return str(value)\n"
                        "        case _:\n"
                        "            return None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parser.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        visitor = _TypeDispatchVisitor(
            path,
            self.code,
            report_control_flow_raise=not is_test_path(path),
            report_isinstance_ladder=not _shadows_isinstance(tree),
        )
        visitor.visit(tree)
        if not _shadows_isinstance(tree):
            visitor.diags.extend(_sequential_isinstance_dispatches(tree, path, self.code))
        visitor.diags.sort(key=lambda d: (d.line, d.col))
        return visitor.diags
