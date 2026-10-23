from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
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
    Severity,
)
from sarj_python_lint.rules._ast_index import walk as walk_ast


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


type _Literal = str | bytes | int | float
_MIN_TESTS = 2
_MIN_EXPANDED_ARMS = 3
_GUARDED_TEST_PARTS = 2
_MIN_GROUP_VALUES = 2
_MAX_GROUP_VALUES = 6


@final
class PreferMatchValueDispatch(Rule):
    id: str = "prefer-match-value-dispatch"
    code: str = "SARJ439"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Prefer match/case for repeated dispatch on one value with a fallback.",
        rationale="A single dispatch subject makes distinct value cases and their fallback easier to review.",
        remediation=(
            "Consider match/case while preserving fallback and constant semantics; use literal or dotted value "
            "patterns, never bare constant names that capture instead of compare. Review membership versus equality, "
            "subject evaluation, and guard order before rewriting."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "ERROR is limited to direct literal equality ladders on an unrebound local parameter, without visible namespace access, in a project with a proven minimum Python version of 3.10. All other supported ladders remain WARNING; no autofix is offered.",
            "Equality-only ladders require two or more tests on the same left-hand name or attribute chain, followed by else.",
            "Cases must be distinct string, bytes, or numeric literals, or singly bound module constants containing them; shadowed constants and singleton values are excluded.",
            "This is a readability suggestion, not proof of exhaustiveness or a safe automatic rewrite: attributes can have side effects and match evaluates its subject once.",
            "Grouped or guarded ladders and terminal sibling branches require three distinct arms on a bare name; only the last arm may have a selector-first guard.",
            "Groups contain two to six distinct string literals in a tuple, list, or set. Set hashing and custom equality can differ from pattern matching; no runtime string type is inferred.",
            "Declared support for Python before 3.10 suppresses this recommendation when proven by the nearest project metadata or exact installed-distribution ownership. Missing or ambiguous target metadata retains advisory behavior; it does not prove a modern target.",
        ),
        examples=(
            RuleExample(
                example_id="stable-literal-parameter",
                title="Dispatch a stable parameter through literal cases",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile(PurePosixPath("pyproject.toml"), "[project]\nrequires-python = '>=3.10'\n"),
                    ExampleFile.python(
                        "app/parse.py",
                        "def parse(kind):\n    if kind == 'json': return json_parser()\n    elif kind == 'yaml': return yaml_parser()\n    else: return fallback()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/parse.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="grouped-terminal-suffix-dispatch",
                scenario="grouped-terminal-dispatch",
                title="Group terminal format dispatch under one subject",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/formats.py",
                        "def parse_config(suffix: str, source: str, jsonc_is_valid: bool):\n"
                        "    if suffix in {'.yaml', '.yml'}:\n"
                        "        return ('yaml', source)\n"
                        "    if suffix == '.toml':\n"
                        "        return ('toml', source)\n"
                        "    if suffix == '.jsonc' and jsonc_is_valid:\n"
                        "        return ('jsonc', source)\n"
                        "    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/formats.py"),
                expected_count=1,
                public=False,
            ),
            RuleExample(
                example_id="grouped-suffix-match-with-guard",
                scenario="grouped-terminal-dispatch",
                title="Retain grouped alternatives, the guard, and the fallback",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/formats.py",
                        "def parse_config(suffix: str, source: str, jsonc_is_valid: bool):\n"
                        "    match suffix:\n"
                        "        case '.yaml' | '.yml':\n"
                        "            return ('yaml', source)\n"
                        "        case '.toml':\n"
                        "            return ('toml', source)\n"
                        "        case '.jsonc' if jsonc_is_valid:\n"
                        "            return ('jsonc', source)\n"
                        "        case _:\n"
                        "            return None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/formats.py"),
                expected_count=0,
                public=False,
            ),
            RuleExample(
                example_id="named-file-dispatch",
                title="Make repeated filename dispatch explicit",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/migrate.py",
                        "_ESLINT_SUPPRESSIONS = 'eslint.json'\n"
                        "_RATCHET_SUPPRESSIONS = 'ratchet.json'\n"
                        "def migrate(path):\n"
                        "    if path.name == _ESLINT_SUPPRESSIONS:\n"
                        "        migrated = rewrite_eslint(path)\n"
                        "    elif path.name == _RATCHET_SUPPRESSIONS:\n"
                        "        migrated = rewrite_ratchet(path)\n"
                        "    else:\n"
                        "        migrated = rewrite(path)\n"
                        "    return migrated\n",
                    ),
                ),
                focus_path=PurePosixPath("app/migrate.py"),
                expected_count=1,
                public=False,
            ),
            RuleExample(
                example_id="literal-match-dispatch",
                title="Use value cases and retain the fallback",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/migrate.py",
                        "def migrate(path):\n"
                        "    match path.name:\n"
                        "        case 'eslint.json':\n"
                        "            return rewrite_eslint(path)\n"
                        "        case 'ratchet.json':\n"
                        "            return rewrite_ratchet(path)\n"
                        "        case _:\n"
                        "            return rewrite(path)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/migrate.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        findings: list[Diagnostic] = []
        candidates = _candidate_dispatches(context, tree)
        if candidates and context.session.python_target.has_declared_support_before(path, (3, 10)):
            return []
        provenance = context.static_resource_provenance if candidates else None
        for node, subject in sorted(candidates, key=lambda candidate: candidate[0].lineno):
            findings.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=(
                        Severity.ERROR
                        if provenance is not None and _blocking_literal_dispatch(context, node, provenance)
                        else Severity.WARNING
                    ),
                    message=(
                        f"Repeated value dispatch on '{subject}' with a fallback — consider match/case; "
                        "preserve fallback and constant semantics, and review repeated attribute evaluation, "
                        "membership versus equality, and guard order."
                    ),
                )
            )
        return findings


def _candidate_dispatches(context: PythonFileContext, tree: ast.Module) -> list[tuple[ast.If, str]]:
    constants = _module_constants(tree, node_index=context.node_index)
    continuations: set[int] = set()
    candidates: list[tuple[ast.If, str]] = []
    for node in context.nodes(ast.If):
        if id(node) in continuations:
            continue
        chain = _elif_chain(node, context.source_lines, continuations)
        if len(chain.branches) < _MIN_TESTS or not chain.last.orelse:
            continue
        subject = _dispatch_subject(chain.branches, constants)
        if subject is None:
            subject = _expanded_dispatch_subject(chain.branches, constants)
        if subject is not None:
            candidates.append((node, subject))
    for branches in _terminal_sibling_dispatches(tree, node_index=context.node_index):
        subject = _expanded_dispatch_subject(branches, constants)
        if subject is not None:
            candidates.append((branches[0], subject))
    return candidates


def _blocking_literal_dispatch(context: PythonFileContext, node: ast.If, provenance: ResourceProvenance) -> bool:
    if context.dynamic_namespace or not context.session.python_target.has_declared_minimum(context.path, (3, 10)):
        return False
    chain = _elif_chain(node, context.source_lines, set())
    if not chain.last.orelse:
        return False
    subject: str | None = None
    for branch in chain.branches:
        test = branch.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
        ):
            return False
        if subject is not None and subject != test.left.id:
            return False
        subject = test.left.id
        binding = provenance.binding(subject, test.left)
        owner = provenance.scope(test)
        if (
            subject in provenance.external_bindings
            or not isinstance(binding, ast.arg)
            or not isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef)
            or provenance.scope(binding) is not owner
        ):
            return False
    return len(chain.branches) >= _MIN_TESTS


def _terminal_sibling_dispatches(tree: ast.Module, *, node_index: NodeIndex | None = None) -> list[list[ast.If]]:
    candidates: list[list[ast.If]] = []
    for node in walk_ast(tree, index=node_index):
        for field in _statement_lists(node):
            _collect_terminal_siblings(field, candidates)
    return candidates


def _statement_lists(node: ast.AST) -> tuple[list[ast.stmt], ...]:
    match node:
        case (
            ast.Module()
            | ast.FunctionDef()
            | ast.AsyncFunctionDef()
            | ast.ClassDef()
            | ast.With()
            | ast.AsyncWith()
            | ast.ExceptHandler()
            | ast.match_case()
        ):
            return (node.body,)
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            return node.body, node.orelse
        case ast.Try() | ast.TryStar():
            return node.body, node.orelse, node.finalbody
        case _:
            return ()


def _expanded_dispatch_subject(branches: list[ast.If], constants: dict[str, _Literal]) -> str | None:
    if len(branches) < _MIN_EXPANDED_ARMS:
        return None
    subject: str | None = None
    values: set[_Literal] = set()
    bodies: set[tuple[str, ...]] = set()
    for index, branch in enumerate(branches):
        body = tuple(ast.dump(statement) for statement in branch.body)
        if body in bodies:
            return None
        bodies.add(body)
        selector = _guarded_selector(branch.test, is_last=index == len(branches) - 1)
        if selector is None:
            return None
        parsed = _expanded_selector(selector, constants)
        if parsed is None:
            return None
        candidate, alternatives = parsed
        if (
            candidate in constants
            or (subject is not None and candidate != subject)
            or values.intersection(alternatives)
        ):
            return None
        subject = candidate
        values.update(alternatives)
    return subject


def _expanded_selector(expression: ast.expr, constants: dict[str, _Literal]) -> tuple[str, set[_Literal]] | None:
    match expression:
        case ast.Compare(left=ast.Name(id=name), ops=[ast.Eq()], comparators=[right]):
            value = constants.get(right.id) if isinstance(right, ast.Name) else _literal(right)
            return (name, {value}) if value is not None else None
        case ast.Compare(
            left=ast.Name(id=name),
            ops=[ast.In()],
            comparators=[ast.Tuple(elts=items) | ast.List(elts=items) | ast.Set(elts=items)],
        ):
            if not _MIN_GROUP_VALUES <= len(items) <= _MAX_GROUP_VALUES:
                return None
            values: set[_Literal] = set()
            for item in items:
                if not isinstance(item, ast.Constant) or not isinstance(item.value, str) or item.value in values:
                    return None
                values.add(item.value)
            return name, values
        case _:
            return None


def _module_constants(tree: ast.Module, *, node_index: NodeIndex | None = None) -> dict[str, _Literal]:
    bindings: Counter[str] = Counter()
    for node in walk_ast(tree, index=node_index):
        match node:
            case (
                ast.Name(id=name, ctx=ast.Store() | ast.Del())
                | ast.arg(arg=name)
                | ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
                | ast.TypeVar(name=name)
                | ast.ParamSpec(name=name)
                | ast.TypeVarTuple(name=name)
            ):
                bindings[name] += 1
            case ast.alias(name=name, asname=alias):
                if name == "*":
                    return {}
                bindings[alias or name.partition(".")[0]] += 1
            case (
                ast.ExceptHandler(name=name)
                | ast.MatchAs(name=name)
                | ast.MatchStar(name=name)
                | ast.MatchMapping(rest=name)
            ):
                if name is not None:
                    bindings[name] += 1
            case ast.Global(names=names) | ast.Nonlocal(names=names):
                bindings.update(names)
            case _:
                pass
    constants: dict[str, _Literal] = {}
    for statement in tree.body:
        match statement:
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                literal = _literal(value)
            case ast.AnnAssign(target=ast.Name(id=name), value=value) if value is not None:
                literal = _literal(value)
            case _:
                continue
        if literal is not None and bindings[name] == 1:
            constants[name] = literal
    return constants


def _literal(expression: ast.expr) -> _Literal | None:
    match expression:
        case ast.Constant(value=value) if isinstance(value, (str, bytes, int, float)) and not isinstance(value, bool):
            return value
        case ast.UnaryOp(op=ast.USub() | ast.UAdd(), operand=ast.Constant(value=value)) if isinstance(
            value, (int, float)
        ) and not isinstance(value, bool):
            return -value if isinstance(expression.op, ast.USub) else value
        case _:
            return None


def _dispatch_subject(branches: list[ast.If], constants: dict[str, _Literal]) -> str | None:
    subject: str | None = None
    values: set[_Literal] = set()
    bodies: set[tuple[str, ...]] = set()
    for branch in branches:
        body = tuple(ast.dump(statement) for statement in branch.body)
        if body in bodies:
            return None
        bodies.add(body)
        match branch.test:
            case ast.Compare(left=left, ops=[ast.Eq()], comparators=[right]):
                candidate = _subject(left)
                value = constants.get(right.id) if isinstance(right, ast.Name) else _literal(right)
            case _:
                return None
        if candidate is None or candidate.partition(".")[0] in constants or value is None or value in values:
            return None
        if subject is not None and candidate != subject:
            return None
        subject = candidate
        values.add(value)
    return subject


def _subject(expression: ast.expr) -> str | None:
    match expression:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attribute):
            parent = _subject(value)
            return f"{parent}.{attribute}" if parent is not None else None
        case _:
            return None


@dataclass(frozen=True, slots=True)
class _ElifChain:
    branches: list[ast.If]
    last: ast.If


def _elif_chain(node: ast.If, lines: list[str], continuations: set[int]) -> _ElifChain:
    branches = [node]
    current = node
    while len(current.orelse) == 1:
        child = current.orelse[0]
        if not isinstance(child, ast.If) or not lines[child.lineno - 1].lstrip().startswith("elif"):
            break
        continuations.add(id(child))
        branches.append(child)
        current = child
    return _ElifChain(branches=branches, last=current)


def _collect_terminal_siblings(field: list[ast.stmt], candidates: list[list[ast.If]]) -> None:
    branches: list[ast.If] = []
    for statement in field:
        if isinstance(statement, ast.If) and not statement.orelse:
            branches.append(statement)
            continue
        if (
            len(branches) >= _MIN_EXPANDED_ARMS
            and isinstance(statement, (ast.Return, ast.Raise))
            and all(branch.body and isinstance(branch.body[-1], (ast.Return, ast.Raise)) for branch in branches)
        ):
            candidates.append(branches)
        branches = []


def _guarded_selector(selector: ast.expr, *, is_last: bool) -> ast.expr | None:
    if isinstance(selector, ast.BoolOp) and isinstance(selector.op, ast.And):
        if not is_last or len(selector.values) != _GUARDED_TEST_PARTS:
            return None
        if any(
            isinstance(node, (ast.NamedExpr, ast.Await, ast.Yield, ast.YieldFrom))
            for node in walk_ast(selector.values[1])
        ):
            return None
        selector = selector.values[0]
    return selector
