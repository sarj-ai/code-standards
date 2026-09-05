from __future__ import annotations

import ast
from collections import Counter
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
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


type _Literal = str | bytes | int | float
_MIN_TESTS = 2


@final
class PreferMatchValueDispatch(Rule):
    id: str = "prefer-match-value-dispatch"
    code: str = "SARJ439"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Prefer match/case for repeated equality dispatch with a fallback.",
        rationale="A single dispatch subject makes distinct value cases and their fallback easier to review.",
        remediation=(
            "Consider match/case while preserving fallback and constant semantics; use literal or dotted value "
            "patterns, never bare constant names that capture instead of compare."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only two or more equality tests on the same left-hand name or attribute chain, followed by else, are checked.",
            "Cases must be distinct string, bytes, or numeric literals, or singly bound module constants containing them; shadowed constants and singleton values are excluded.",
            "This is a readability suggestion, not proof of exhaustiveness or a safe automatic rewrite: attributes can have side effects and match evaluates its subject once.",
        ),
        examples=(
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
                public=True,
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
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        constants = _module_constants(tree)
        lines = source.splitlines()
        continuations: set[int] = set()
        findings: list[Diagnostic] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If) or id(node) in continuations:
                continue
            branches = [node]
            current = node
            while len(current.orelse) == 1:
                child = current.orelse[0]
                if not isinstance(child, ast.If) or not lines[child.lineno - 1].lstrip().startswith("elif"):
                    break
                continuations.add(id(child))
                branches.append(child)
                current = child
            if len(branches) < _MIN_TESTS or not current.orelse:
                continue
            subject = _dispatch_subject(branches, constants)
            if subject is not None:
                findings.append(
                    Diagnostic(
                        path=path,
                        line=node.lineno,
                        col=node.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=(
                            f"Repeated equality dispatch on '{subject}' with a fallback — consider match/case; "
                            "preserve fallback and constant semantics, and review repeated attribute evaluation."
                        ),
                    )
                )
        return findings


def _module_constants(tree: ast.Module) -> dict[str, _Literal]:
    bindings: Counter[str] = Counter()
    for node in ast.walk(tree):
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
