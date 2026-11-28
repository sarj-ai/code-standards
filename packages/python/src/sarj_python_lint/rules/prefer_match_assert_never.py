from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import cache
from itertools import chain
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._declared_contracts import DeclaredContracts, written_attribute_roots
from sarj_python_lint.rules._enum_declarations import class_enum_members, stdlib_enum_base
from sarj_python_lint.rules._finite_literal_dispatch import rejecting_body
from sarj_python_lint.rules._suite_flow import previous_statements
from sarj_python_lint.rules._suppression_comments import scan_comments_or_none


if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from sarj_python_lint.rules._declared_contracts import DeclaredClass
    from sarj_python_lint.rules._imports import ImportIndex
    from sarj_python_lint.rules._project_index import SourceUnit


_MIN_ARMS = 2

_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum", "ReprEnum"})
_ARGUMENT_IGNORE = re.compile(r"^(?:type|pyright):\s*ignore\b(?:\[([^\]]*)\])?")
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})


class _EnumDomain(NamedTuple):
    declaration: ast.ClassDef
    members: frozenset[str]


class _EnumCoverage(NamedTuple):
    domain: _EnumDomain
    covered: frozenset[str]


class _EnumComparison(NamedTuple):
    target: ast.expr
    coverage: _EnumCoverage


@dataclass(frozen=True, slots=True)
class _EnumChain:
    target: ast.expr
    coverage: _EnumCoverage
    branches: list[ast.If]


class _Binding(NamedTuple):
    name: str
    line: int


type _EnumLookup = Callable[[ast.expr], _EnumDomain | None]


@final
class PreferMatchAssertNever(ProjectRule):
    id: str = "prefer-match-assert-never"
    code: str = "SARJ032"
    documentation = RuleDocumentation(
        summary="Typed enum dispatch must not silently ignore unhandled members.",
        rationale=(
            "A wildcard or else branch can hide missing enum members and let newly added members inherit default behavior. "
            "Suppressing the argument-type error at assert_never also disables its static exhaustiveness guarantee."
        ),
        remediation=(
            "Handle enum members explicitly and group those that share a default. "
            "For an exhausted type, bind the catch-all value and pass it to `typing.assert_never`; "
            "raise an explicit exception when static exhaustiveness is unavailable. Narrow the accepted type or "
            "handle missing variants instead of suppressing assert_never's argument check."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes remove only an exact single argument-type ignore from an existing terminal assert_never call after every member of a canonical local StrEnum is already handled by terminating identity branches. Missing members, other suppressions, reasons, aliases, guarded branches and dynamic domains remain manual.",
            "The no-op error requires a parameter annotated with a local enum. The defaulting check handles match and if/elif dispatch on names and one-level attributes, including enums resolved through direct first-party imports or one re-export.",
            "The defaulting check requires a direct standard enum base and distinct literal string or integer members. It skips guarded arms, generated files, and dynamic or unresolved enum domains.",
            "The defaulting check skips a local whose only bindings are assignments of a proper enum subset in the immediately preceding match.",
            "Independently warns on import-proven assert_never calls with a trailing blanket or argument-type ignore; module-wide disables are not analyzed.",
        ),
        examples=(
            RuleExample(
                example_id="safe-exhaustive-ignore-removal",
                title="Remove an already unnecessary exhaustiveness suppression",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/dispatch.py",
                        "from enum import StrEnum\nfrom typing import assert_never\n"
                        "class Status(StrEnum):\n    READY = 'ready'\n    DONE = 'done'\n"
                        "def label(status: Status) -> str:\n"
                        "    if status is Status.READY:\n        return 'Ready'\n"
                        "    if status is Status.DONE:\n        return 'Done'\n"
                        "    assert_never(status)  # type: ignore[arg-type]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/dispatch.py"),
                expected_count=1,
                fixed_files=(
                    ExampleFile.python(
                        "app/dispatch.py",
                        "from enum import StrEnum\nfrom typing import assert_never\n"
                        "class Status(StrEnum):\n    READY = 'ready'\n    DONE = 'done'\n"
                        "def label(status: Status) -> str:\n"
                        "    if status is Status.READY:\n        return 'Ready'\n"
                        "    if status is Status.DONE:\n        return 'Done'\n"
                        "    assert_never(status)  \n",
                    ),
                ),
            ),
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
                example_id="defaulting-enum-wildcard",
                scenario="explicit-enum-default",
                title="An enum wildcard hides the members that share a default",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "dispatch.py",
                        'from enum import StrEnum\n\nclass Job(StrEnum):\n    CALLER_EXPERIENCE = "caller_experience"\n    JUDGE = "judge"\n    TRANSCRIPT = "transcript"\n    REPORT = "report"\n\ndef max_output_tokens(job: Job) -> int:\n    match job:\n        case Job.CALLER_EXPERIENCE:\n            return 4_000\n        case Job.JUDGE:\n            return 8_000\n        case _:\n            return 2_000\n',
                    ),
                ),
                focus_path=PurePosixPath("dispatch.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-enum-default",
                scenario="explicit-enum-default",
                title="Group enum members that share a default",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "dispatch.py",
                        'from enum import StrEnum\nfrom typing import assert_never\n\nclass Job(StrEnum):\n    CALLER_EXPERIENCE = "caller_experience"\n    JUDGE = "judge"\n    TRANSCRIPT = "transcript"\n    REPORT = "report"\n\ndef max_output_tokens(job: Job) -> int:\n    match job:\n        case Job.CALLER_EXPERIENCE:\n            return 4_000\n        case Job.JUDGE:\n            return 8_000\n        case Job.TRANSCRIPT | Job.REPORT:\n            return 2_000\n        case _ as unreachable:\n            assert_never(unreachable)\n',
                    ),
                ),
                focus_path=PurePosixPath("dispatch.py"),
                expected_count=0,
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
        if context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        local_domains = _legacy_enum_domains(context, tree)
        local_enums = frozenset(local_domains)

        def local_enum(expression: ast.expr) -> _EnumDomain | None:
            return local_domains.get(expression.id) if isinstance(expression, ast.Name) else None

        @cache
        def contracts() -> DeclaredContracts:
            return DeclaredContracts(context)

        def closed_enum(expression: ast.expr) -> _EnumDomain | None:
            return _closed_enum(expression, contracts())

        diags = _suppressed_exhaustiveness_calls(context, self.code)
        consumed_elifs: set[int] = set()
        for node in context.nodes(ast.Match, ast.If):
            if id(node) in consumed_elifs:
                continue
            finding = _silent_dispatch_error(
                node, context, local_enums, local_enum, consumed_elifs=consumed_elifs, code=self.code
            ) or _defaulting_error(node, context, closed_enum, self.code)
            if finding is not None:
                diags.append(finding)
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _silent_dispatch_error(
    node: ast.Match | ast.If,
    context: PythonFileContext,
    local_enums: frozenset[str],
    lookup: _EnumLookup,
    *,
    consumed_elifs: set[int],
    code: str,
) -> Diagnostic | None:
    if not local_enums:
        return None
    if isinstance(node, ast.Match):
        enum_name = _annotated_local_enum(context, node.subject, node, local_enums)
        wildcard = _silent_enum_wildcard(node, enum_name, lookup)
        if wildcard is None:
            return None
        anchor = wildcard.pattern
        message = (
            f"typed `{enum_name}` match has a no-op catch-all — an unhandled member "
            "is silently ignored; bind it and call `assert_never`, or raise."
        )
    else:
        enum_name = _silent_enum_chain(context, node, local_enums, lookup, consumed_elifs)
        if enum_name is None:
            return None
        anchor = node
        message = (
            f"typed `{enum_name}` if/elif dispatch has a no-op `else` — an unhandled "
            "member is silently ignored; prefer match/case with `assert_never`, or raise."
        )
    return Diagnostic(
        path=context.path,
        line=anchor.lineno,
        col=anchor.col_offset + 1,
        code=code,
        severity=Severity.ERROR,
        message=message,
    )


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
        if any(context.suppressions.is_suppressed(line, code) for line in call_lines):
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
    return codes is None or not {"reportArgumentType", "arg-type"}.isdisjoint(code.strip() for code in codes.split(","))


def _legacy_enum_domains(context: PythonFileContext, tree: ast.Module) -> dict[str, _EnumDomain]:
    return {
        node.name: _EnumDomain(node, class_enum_members(node))
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(_is_enum_base(base, context.imports) for base in node.bases)
        and sum(bound == node.name for bound, _ in _scope_bindings(tree.body)) == 1
    }


def _is_enum_base(base: ast.expr, imports: ImportIndex) -> bool:
    return stdlib_enum_base(base, imports) in _ENUM_BASES


def _annotated_local_enum(
    context: PythonFileContext,
    subject: ast.expr,
    anchor: ast.stmt,
    local_enums: frozenset[str],
) -> str | None:
    if not isinstance(subject, ast.Name):
        return None
    scopes = [
        scope
        for scope in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef)
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
    lookup: _EnumLookup,
) -> ast.match_case | None:
    if enum_name is None or len(node.cases) < _MIN_ARMS + 1:
        return None
    last = node.cases[-1]
    if not _is_silent_body(last.body) or all(_is_assignment_only(case.body) for case in node.cases[:-1]):
        return None
    coverage = _match_coverage(node, lookup)
    if coverage is not None and coverage.domain.declaration.name == enum_name and len(coverage.covered) >= _MIN_ARMS:
        return last
    return None


def _match_coverage(node: ast.Match, lookup: _EnumLookup) -> _EnumCoverage | None:
    if not _is_catch_all(node.cases[-1].pattern) or any(case.guard is not None for case in node.cases):
        return None
    return _enum_member_set(chain.from_iterable(_pattern_values(case.pattern) for case in node.cases[:-1]), lookup)


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


def _pattern_values(pattern: ast.pattern) -> Iterator[ast.expr | None]:
    match pattern:
        case ast.MatchValue(value=value):
            yield value
        case ast.MatchOr(patterns=subpatterns):
            for subpattern in subpatterns:
                yield from _pattern_values(subpattern)
        case _:
            yield None


def _silent_enum_chain(
    context: PythonFileContext,
    head: ast.If,
    local_enums: frozenset[str],
    lookup: _EnumLookup,
    consumed_elifs: set[int],
) -> str | None:
    parsed = _enum_chain(head, lookup)
    if parsed is None:
        return None
    if len(parsed.coverage.covered) < _MIN_ARMS or not _is_silent_body(parsed.branches[-1].orelse):
        return None
    if all(_is_assignment_only(branch.body) for branch in parsed.branches):
        return None
    enum_name = parsed.coverage.domain.declaration.name
    if _annotated_local_enum(context, parsed.target, head, local_enums) != enum_name:
        return None
    consumed_elifs.update(id(branch) for branch in parsed.branches[1:])
    return enum_name


def _enum_chain(head: ast.If, lookup: _EnumLookup, *, elif_only: bool = False) -> _EnumChain | None:
    first = _enum_comparison(head.test, lookup)
    if first is None:
        return None
    domain = first.coverage.domain
    target = ast.dump(first.target)
    branches = [head]
    covered = set(first.coverage.covered)
    while len(branches[-1].orelse) == 1:
        child = branches[-1].orelse[0]
        if not isinstance(child, ast.If) or (elif_only and child.col_offset != head.col_offset):
            break
        parsed = _enum_comparison(child.test, lookup)
        if parsed is None or parsed.coverage.domain != domain or ast.dump(parsed.target) != target:
            return None
        branches.append(child)
        covered.update(parsed.coverage.covered)
    return _EnumChain(first.target, _EnumCoverage(domain, frozenset(covered)), branches)


def _defaulting_error(
    node: ast.Match | ast.If, context: PythonFileContext, lookup: _EnumLookup, code: str
) -> Diagnostic | None:
    if isinstance(node, ast.Match):
        last = node.cases[-1]
        subject = node.subject
        body, anchor = last.body, last.pattern
        coverage = _match_coverage(node, lookup)
    else:
        if not _starts_elif_chain(node, context):
            return None
        parsed = _enum_chain(node, lookup, elif_only=True)
        if parsed is None:
            return None
        subject, coverage = parsed.target, parsed.coverage
        body, anchor = parsed.branches[-1].orelse, node
    if coverage is None or not body:
        return None
    match subject:
        case ast.Name() | ast.Attribute(value=ast.Name()):
            pass
        case _:
            return None
    missing = coverage.domain.members - coverage.covered
    if not missing or (
        isinstance(subject, ast.Name)
        and context.parents.get(coverage.domain.declaration) is context.tree
        and _is_silent_body(body)
    ):
        return None
    if rejecting_body(body, node, context) is not False or _assigns_enum_subset(
        node, subject, coverage, context, lookup
    ):
        return None
    enum_name = coverage.domain.declaration.name
    members = ", ".join(f"`{enum_name}.{member}`" for member in sorted(missing))
    remedy = "Add an explicit arm for it." if len(missing) == 1 else "Group them in an explicit arm."
    return Diagnostic(
        path=context.path,
        line=anchor.lineno,
        col=anchor.col_offset + 1,
        code=code,
        severity=Severity.ERROR,
        message=f"Enum dispatch routes {members} through the catch-all. {remedy}",
    )


def _assigns_enum_subset(
    node: ast.stmt, subject: ast.expr, coverage: _EnumCoverage, context: PythonFileContext, lookup: _EnumLookup
) -> bool:
    scope = context.parents.get(node)
    if not isinstance(subject, ast.Name) or not isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        return False
    match previous_statements(node, scope):
        case [*_, ast.Match(cases=cases)]:
            pass
        case _:
            return False
    targets: list[ast.Name] = []
    values: list[ast.expr] = []
    for case in cases:
        match case.body:
            case [ast.Assign(targets=[ast.Name() as target], value=value)] if target.id == subject.id:
                targets.append(target)
            case _:
                return False
        match value:
            case ast.IfExp(body=when_true, orelse=when_false):
                values.extend((when_true, when_false))
            case _:
                values.append(value)
    if set(context.runtime_bindings.lookup(scope, subject.id) or ()) != set(targets):
        return False
    assigned = _enum_member_set(values, lookup)
    return assigned is not None and assigned.domain == coverage.domain and assigned.covered < coverage.domain.members


def _starts_elif_chain(node: ast.If, context: PythonFileContext) -> bool:
    match node.orelse:
        case [ast.If(col_offset=column)] if column == node.col_offset:
            pass
        case _:
            return False
    parent = context.parents.get(node)
    return not (isinstance(parent, ast.If) and parent.orelse == [node] and parent.col_offset == node.col_offset)


def _closed_enum(expression: ast.expr, contracts: DeclaredContracts) -> _EnumDomain | None:
    context = contracts.context
    match expression:
        case (ast.Name() as root) | ast.Attribute(value=ast.Name() as root):
            pass
        case _:
            return None
    unit = contracts.unit
    if unit is None or context.has_wildcard_import:
        return None
    symbol = contracts.project.resolve(unit, expression)
    if symbol is None or (provider := contracts.project.source_unit(symbol.module)) is None:
        return None
    binding = context.static_resource_provenance.runtime_binding(root.id, root)
    parent = context.parents.get(binding) if binding is not None else None
    if isinstance(binding, ast.alias) and parent is not None:
        parent = context.parents.get(parent)
    if parent is not context.tree:
        return None
    declared = contracts.class_type(expression) or _reexported_class(contracts, provider, symbol.name)
    if declared is None or (tree := declared.unit.tree) is None:
        return None
    enum = declared.declaration
    if enum.name in written_attribute_roots(tree) or len(enum.bases) != 1:
        return None
    base = stdlib_enum_base(enum.bases[0], contracts.imports_for(declared.unit))
    if base not in {"Enum", "StrEnum", "IntEnum"}:
        return None
    members = _literal_members(enum, base)
    return _EnumDomain(enum, members) if members else None


def _reexported_class(contracts: DeclaredContracts, provider: SourceUnit, name: str) -> DeclaredClass | None:
    context = PythonFileContext(provider.path, provider.source, contracts.context.session)
    if context.tree is None or context.has_wildcard_import:
        return None
    match context.binding_inventory.bindings.get(context.tree, {}).get(name, ()):
        case [ast.alias() as binding]:
            statement = context.parents.get(binding)
            if isinstance(statement, ast.ImportFrom) and context.parents.get(statement) is context.tree:
                return contracts.class_type(ast.Name(id=name, ctx=ast.Load()), provider)
        case _:
            pass
    return None


def _literal_members(declaration: ast.ClassDef, base: str) -> frozenset[str]:
    members: set[str] = set()
    values: set[str | int] = set()
    for statement in declaration.body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=ast.Constant(value=str() | int() as value))
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.Constant(value=str() | int() as value))
            ):
                if name.startswith("_") or name in members or value in values:
                    return frozenset()
                if (base == "StrEnum" and not isinstance(value, str)) or (
                    base == "IntEnum" and not isinstance(value, int)
                ):
                    return frozenset()
                members.add(name)
                values.add(value)
            case ast.Expr(value=ast.Constant(value=str())) | ast.AnnAssign(target=ast.Name(), value=None):
                continue
            case _:
                return frozenset()
    return frozenset(members)


def _enum_comparison(test: ast.expr, lookup: _EnumLookup) -> _EnumComparison | None:
    match test:
        case ast.Compare(left=left, ops=[ast.Eq() | ast.Is()], comparators=[right]):
            right_member = _enum_member_set((right,), lookup)
            left_member = _enum_member_set((left,), lookup)
            if right_member is not None and left_member is None:
                return _EnumComparison(left, right_member)
            if left_member is not None and right_member is None:
                return _EnumComparison(right, left_member)
        case ast.Compare(
            left=left, ops=[ast.In()], comparators=[ast.Tuple(elts=elts) | ast.List(elts=elts) | ast.Set(elts=elts)]
        ):
            if (members := _enum_member_set(elts, lookup)) is not None:
                return _EnumComparison(left, members)
        case _:
            pass
    return None


def _enum_member_set(expressions: Iterable[ast.expr | None], lookup: _EnumLookup) -> _EnumCoverage | None:
    domain: _EnumDomain | None = None
    covered: set[str] = set()
    for expression in expressions:
        if not isinstance(expression, ast.Attribute):
            return None
        owner = lookup(expression.value)
        if owner is None or expression.attr not in owner.members or (domain is not None and owner != domain):
            return None
        domain = owner
        covered.add(expression.attr)
    return _EnumCoverage(domain, frozenset(covered)) if domain is not None else None
