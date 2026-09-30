from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
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
)
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._suppression_comments import scan_comments_or_none


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex
    from sarj_python_lint.rules._imports import ImportIndex


# A dispatch needs at least this many real (non-wildcard) arms to be flagged.
_MIN_ARMS = 2

_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum", "ReprEnum"})
_ARGUMENT_IGNORE = re.compile(r"^(?:type|pyright):\s*ignore\b(?:\[([^\]]*)\])?")
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})


class _EnumComparison(NamedTuple):
    target: ast.expr
    enum_name: str
    members: frozenset[str]


class _Binding(NamedTuple):
    name: str
    line: int


class _EnumMember(NamedTuple):
    enum_name: str
    member: str


class _EnumMemberSet(NamedTuple):
    enum_name: str
    members: frozenset[str]


@final
class PreferMatchAssertNever(Rule):
    id: str = "prefer-match-assert-never"
    code: str = "SARJ032"
    documentation = RuleDocumentation(
        summary="Typed enum dispatch must not silently ignore unhandled members.",
        rationale=(
            "A no-op wildcard or else branch hides missing enum members and lets newly added members pass unnoticed. "
            "Suppressing the argument-type error at assert_never also disables its static exhaustiveness guarantee."
        ),
        remediation=(
            "Handle every enum member, bind the catch-all value, and pass it to `typing.assert_never`; "
            "raise an explicit exception when static exhaustiveness is unavailable. Narrow the accepted type or "
            "handle missing variants instead of suppressing assert_never's argument check."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only subjects explicitly annotated as a locally declared Enum, StrEnum, IntEnum, or ReprEnum are checked.",
            "Flags, imported or untyped domains, class-pattern unions, guarded arms, generated files, and dynamic dispatch are excluded.",
            "Independently warns on import-proven assert_never calls with a trailing blanket or argument-type ignore; module-wide disables are not analyzed.",
        ),
        examples=(
            RuleExample(
                example_id="silent-closed-set-wildcard",
                title="Closed-set match silently ignores a variant",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "dispatch.py",
                        'from enum import StrEnum\n\nclass Kind(StrEnum):\n    A = "a"\n    B = "b"\n    C = "c"\n\ndef handle(kind: Kind) -> None:\n    match kind:\n        case Kind.A:\n            handle_a()\n        case Kind.B:\n            handle_b()\n        case _:\n            pass\n',
                    ),
                ),
                focus_path=PurePosixPath("dispatch.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-closed-set-failure",
                title="Closed-set match rejects an unhandled variant",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "dispatch.py",
                        'from enum import StrEnum\nfrom typing import assert_never\n\nclass Kind(StrEnum):\n    A = "a"\n    B = "b"\n    C = "c"\n\ndef handle(kind: Kind) -> None:\n    match kind:\n        case Kind.A:\n            handle_a()\n        case Kind.B:\n            handle_b()\n        case Kind.C:\n            handle_c()\n        case _ as unreachable:\n            assert_never(unreachable)\n',
                    ),
                ),
                focus_path=PurePosixPath("dispatch.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        module_classdefs = _module_scope_classdefs(tree)
        imports = context.imports
        local_enums = _local_enum_names(module_classdefs, imports, tree)
        enum_members = _enum_members(module_classdefs, local_enums)
        diags = _suppressed_exhaustiveness_calls(context, self.code)
        consumed_elifs: set[int] = set()
        for node in context.nodes(ast.Match, ast.If):
            if isinstance(node, ast.Match):
                enum_name = _annotated_local_enum(tree, node.subject, node, local_enums, node_index=context.node_index)
                wildcard = _silent_enum_wildcard(node, enum_name, enum_members)
                if wildcard is not None:
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=wildcard.pattern.lineno,
                            col=wildcard.pattern.col_offset + 1,
                            code=self.code,
                            severity=Severity.ERROR,
                            message=(
                                f"typed `{enum_name}` match has a no-op catch-all — an unhandled member "
                                "is silently ignored; bind it and call `assert_never`, or raise."
                            ),
                        )
                    )
            else:
                if id(node) in consumed_elifs:
                    continue
                enum_name = _silent_enum_chain(tree, node, enum_members, consumed_elifs, node_index=context.node_index)
                if enum_name is not None:
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=node.lineno,
                            col=node.col_offset + 1,
                            code=self.code,
                            severity=Severity.ERROR,
                            message=(
                                f"typed `{enum_name}` if/elif dispatch has a no-op `else` — an unhandled "
                                "member is silently ignored; prefer match/case with `assert_never`, or raise."
                            ),
                        )
                    )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _suppressed_exhaustiveness_calls(context: PythonFileContext, code: str) -> list[Diagnostic]:
    if "ignore" not in context.source:
        return []
    comments = scan_comments_or_none(context.source)
    if comments is None:
        return []
    ignored_lines = {
        comment.line for comment in comments if not comment.standalone and _ignores_argument_type(comment.body)
    }
    findings: list[Diagnostic] = []
    for call in context.nodes(ast.Call):
        if not context.imports.resolves(call.func, sources=_TYPING_SOURCES, symbol="assert_never"):
            continue
        call_lines = range(call.lineno, (call.end_lineno or call.lineno) + 1)
        if not any(line in ignored_lines for line in call_lines):
            continue
        if any(is_suppressed(context.source_lines, line, code) for line in call_lines):
            continue
        findings.append(
            Diagnostic(
                path=context.path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=code,
                severity=Severity.WARNING,
                message=(
                    "assert_never has its argument-type check suppressed; handle the missing variants, narrow "
                    "the accepted type, or use an explicit runtime exception instead of claiming exhaustiveness."
                ),
            )
        )
    return findings


def _ignores_argument_type(comment: str) -> bool:
    match = _ARGUMENT_IGNORE.match(comment)
    if match is None:
        return False
    codes = match.group(1)
    return codes is None or bool({code.strip() for code in codes.split(",")} & {"reportArgumentType", "arg-type"})


def _module_scope_classdefs(tree: ast.Module) -> list[ast.ClassDef]:
    return [stmt for stmt in tree.body if isinstance(stmt, ast.ClassDef)]


def _local_enum_names(module_classdefs: list[ast.ClassDef], imports: ImportIndex, tree: ast.Module) -> frozenset[str]:
    return frozenset(
        node.name
        for node in module_classdefs
        if any(_is_enum_base(base, imports) for base in node.bases)
        and sum(bound == node.name for bound, _ in _scope_bindings(tree.body)) == 1
    )


def _is_enum_base(base: ast.expr, imports: ImportIndex) -> bool:
    return any(imports.resolves(base, sources=frozenset({"enum"}), symbol=symbol) for symbol in _ENUM_BASES)


def _enum_members(classdefs: list[ast.ClassDef], local_enums: frozenset[str]) -> dict[str, frozenset[str]]:
    return {classdef.name: _class_enum_members(classdef) for classdef in classdefs if classdef.name in local_enums}


def _annotated_local_enum(
    tree: ast.Module,
    subject: ast.expr,
    anchor: ast.stmt,
    local_enums: frozenset[str],
    *,
    node_index: NodeIndex | None = None,
) -> str | None:
    if not isinstance(subject, ast.Name):
        return None
    scopes = [
        scope
        for scope in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef, index=node_index)
        if scope.lineno <= anchor.lineno <= (scope.end_lineno or scope.lineno)
    ]
    if not scopes:
        return None
    scope = min(scopes, key=lambda candidate: (candidate.end_lineno or candidate.lineno) - candidate.lineno)
    parameters = (
        *scope.args.posonlyargs,
        *scope.args.args,
        *scope.args.kwonlyargs,
        *((scope.args.vararg,) if scope.args.vararg is not None else ()),
        *((scope.args.kwarg,) if scope.args.kwarg is not None else ()),
    )
    parameter = next((arg for arg in parameters if arg.arg == subject.id), None)
    if parameter is None:
        return None
    enum_name = _simple_annotation_name(parameter.annotation)
    if enum_name not in local_enums:
        return None
    bindings = _scope_bindings(scope.body)
    if any(name == enum_name for name, _ in bindings) or any(argument.arg == enum_name for argument in parameters):
        return None
    if any(name == subject.id and line < anchor.lineno for name, line in bindings):
        return None
    return enum_name


def _scope_bindings(statements: list[ast.stmt]) -> list[_Binding]:
    bindings: list[_Binding] = []

    def visit(node: ast.AST) -> None:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                bindings.append(_Binding(node.name, node.lineno))
                return
            case ast.Import() | ast.ImportFrom():
                bindings.extend(
                    _Binding(alias.asname or alias.name.partition(".")[0], node.lineno)
                    for alias in node.names
                    if alias.name != "*"
                )
                return
            case ast.Name(id=name, ctx=(ast.Store() | ast.Del())):
                bindings.append(_Binding(name, node.lineno))
            case _:
                pass
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in statements:
        visit(statement)
    return bindings


def _simple_annotation_name(annotation: ast.expr | None) -> str | None:
    match annotation:
        case ast.Name(id=name) | ast.Constant(value=str(name)):
            return name
        case _:
            return None


def _silent_enum_wildcard(
    node: ast.Match,
    enum_name: str | None,
    enum_members: dict[str, frozenset[str]],
) -> ast.match_case | None:
    if enum_name is None or len(node.cases) < _MIN_ARMS + 1:
        return None
    last = node.cases[-1]
    if not _is_catch_all(last.pattern):
        return None
    if last.guard is not None or not _is_silent_body(last.body):
        return None
    real_arms = node.cases[:-1]
    if any(case.guard is not None for case in real_arms):
        return None
    if all(_is_assignment_only(case.body) for case in real_arms):
        return None
    declared = enum_members.get(enum_name, frozenset())
    members = [_enum_pattern_members(case.pattern, enum_name, declared) for case in real_arms]
    if any(member_set is None for member_set in members):
        return None
    covered = frozenset(member for member_set in members if member_set is not None for member in member_set)
    return last if len(covered) >= _MIN_ARMS else None


def _is_catch_all(pattern: ast.pattern) -> bool:
    match pattern:
        case ast.MatchAs(pattern=None) | ast.MatchAs(pattern=ast.MatchAs(pattern=None, name=None)):
            return True
        case _:
            return False


def _is_assignment_only(body: list[ast.stmt]) -> bool:
    return all(isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)) for stmt in body)


def _is_silent_body(body: list[ast.stmt]) -> bool:
    if len(body) != 1:
        return False
    statement = body[0]
    if isinstance(statement, (ast.Pass, ast.Continue)):
        return True
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
        return True
    return isinstance(statement, ast.Return) and (
        statement.value is None or (isinstance(statement.value, ast.Constant) and statement.value.value is None)
    )


def _enum_pattern_members(
    pattern: ast.pattern,
    enum_name: str,
    declared: frozenset[str],
) -> frozenset[str] | None:
    match pattern:
        case ast.MatchValue(value=ast.Attribute(value=ast.Name(id=owner), attr=member)) if (
            owner == enum_name and member in declared
        ):
            return frozenset({member})
        case ast.MatchOr(patterns=subpatterns):
            members = [_enum_pattern_members(subpattern, enum_name, declared) for subpattern in subpatterns]
            if any(member_set is None for member_set in members):
                return None
            return frozenset(member for member_set in members if member_set is not None for member in member_set)
        case _:
            return None


def _silent_enum_chain(
    tree: ast.Module,
    head: ast.If,
    enum_members: dict[str, frozenset[str]],
    consumed_elifs: set[int],
    *,
    node_index: NodeIndex | None = None,
) -> str | None:
    local_enums = frozenset(enum_members)
    if not local_enums:
        return None
    first_target: ast.expr | None = None
    enum_name: str | None = None
    covered: set[str] = set()
    arm_bodies: list[list[ast.stmt]] = []
    child_elifs: list[ast.If] = []
    current = head
    while True:
        parsed = _enum_comparison(current.test, enum_members)
        if parsed is None:
            return None
        target = parsed.target
        cls_name = parsed.enum_name
        if first_target is None:
            first_target = target
            enum_name = cls_name
        elif ast.dump(target) != ast.dump(first_target) or cls_name != enum_name:
            return None
        if current is not head:
            child_elifs.append(current)
        covered.update(parsed.members)
        arm_bodies.append(current.body)
        orelse = current.orelse
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            current = orelse[0]
            continue
        break
    if len(covered) < _MIN_ARMS or not orelse or not _is_silent_body(orelse):
        return None
    if all(_is_assignment_only(body) for body in arm_bodies):
        return None
    if enum_name is None or first_target is None:
        return None
    if _annotated_local_enum(tree, first_target, head, local_enums, node_index=node_index) != enum_name:
        return None
    consumed_elifs.update(map(id, child_elifs))
    return enum_name


def _enum_comparison(test: ast.expr, enum_members: dict[str, frozenset[str]]) -> _EnumComparison | None:
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1):
        return None
    left = test.left
    right = test.comparators[0]
    match test.ops[0]:
        case ast.Eq() | ast.Is():
            right_member = _enum_member(right, enum_members)
            left_member = _enum_member(left, enum_members)
            if right_member is not None and left_member is None:
                cls_name, member = right_member
                target = left
            elif left_member is not None and right_member is None:
                cls_name, member = left_member
                target = right
            else:
                return None
            members = frozenset({member})
        case ast.In():
            container = _enum_member_container(right, enum_members)
            if container is None:
                return None
            cls_name, members = container
            target = left
        case _:
            return None
    return _EnumComparison(target, cls_name, members)


def _enum_member(expr: ast.expr, enum_members: dict[str, frozenset[str]]) -> _EnumMember | None:
    match expr:
        case ast.Attribute(value=ast.Name(id=cls_name), attr=member) if member in enum_members.get(
            cls_name, frozenset()
        ):
            return _EnumMember(cls_name, member)
        case _:
            return None


def _enum_member_container(expr: ast.expr, enum_members: dict[str, frozenset[str]]) -> _EnumMemberSet | None:
    if not isinstance(expr, (ast.Tuple, ast.List, ast.Set)) or not expr.elts:
        return None
    resolved = [_enum_member(element, enum_members) for element in expr.elts]
    if any(member is None for member in resolved):
        return None
    owners = {member[0] for member in resolved if member is not None}
    if len(owners) != 1:
        return None
    return _EnumMemberSet(
        owners.pop(),
        frozenset(member.member for member in resolved if member is not None),
    )


def _class_enum_members(classdef: ast.ClassDef) -> frozenset[str]:
    return frozenset(
        target.id
        for statement in classdef.body
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
        and (not isinstance(statement, ast.AnnAssign) or statement.value is not None)
        for target in (statement.targets if isinstance(statement, ast.Assign) else (statement.target,))
        if isinstance(target, ast.Name) and not target.id.startswith("_")
    )
