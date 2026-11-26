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
)
from sarj_python_lint.rules._comments import comment_line_numbers
from sarj_python_lint.rules.prefer_match_type_dispatch import none_disjoint_class_references
from sarj_python_lint.rules.prefer_walrus_awaited_none_guard import none_guard_candidates, none_guard_message


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_BINARY_CASES = 2
_MATCH_PYTHON = (3, 10)
_WALRUS_PYTHON = (3, 8)


@final
class PreferMatchNoneCheck(Rule):
    id = "prefer-match-none-check"
    code = "SARJ589"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Handle present values before an unconditional None arm in optional-value matches.",
        rationale=(
            "A presence check expresses a binary choice directly. For structural dispatch, leading with the "
            "concrete cases shows what each value does, and a later None arm handles absence."
        ),
        remediation=(
            "Move the unconditional `case None:` below the concrete value cases while keeping a final catchall "
            "last. When absence exits early or the present arm is `pass`, use a guard clause such as "
            "`if (value := lookup()) is None: raise ...`; when absence is `pass`, use `if (value := lookup()) is not None:`. "
            "Otherwise prefer `if value is not None:` with an `else` for absence."
        ),
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.SAFE,
        aliases=("prefer-walrus-none-guard",),
        limitations=(
            "Case order is an error only when the later patterns can be proved disjoint from None. Literal, sequence, mapping, unshadowed builtin, ordinary local class and standard AST node patterns are recognized. Unresolved class or value references, guarded None, overlapping alternatives and observable comparisons are excluded. A final unconditional wildcard or capture keeps its position.",
            "A two-arm match that handles None then accepts the remaining values is a binary presence check. A bare capture or wildcard guarded by a direct identity check against the matched name also proves presence. Preserve any capture that is observed after the match or in its absence branch. Case ordering and capture preservation require manual changes.",
            "A compact synchronous lookup immediately returned or raised under an is-not-None guard still receives a warning and a safe inline-binding fix. SARJ432 owns awaited lookups and SARJ081 owns regex lookups. Stubs, generated code and syntax unsupported by the declared Python target are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="absence-before-concrete-case",
                scenario="case-order",
                title="An unconditional None case precedes a concrete variant",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def render(value):\n"
                        "    match value:\n"
                        "        case None: return 'missing'\n"
                        "        case str() as text: return text.upper()\n"
                        "        case _: return 'other'\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="concrete-before-absence",
                scenario="case-order",
                title="Concrete variants precede None and the fallback stays last",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def render(value):\n"
                        "    match value:\n"
                        "        case str() as text: return text.upper()\n"
                        "        case None: return 'missing'\n"
                        "        case _: return 'other'\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="binary-presence",
                scenario="binary-presence",
                title="A binary None match can use an explicit identity check",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def render(value):\n"
                        "    match value:\n"
                        "        case None: return 'missing'\n"
                        "        case _: return str(value)\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="positive-identity-check",
                scenario="binary-presence",
                title="An explicit identity check handles present and absent values",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def render(value):\n"
                        "    if value is not None:\n"
                        "        return str(value)\n"
                        "    return 'missing'\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="consumed-lookup-binding",
                scenario="lookup-binding",
                title="A lookup returned under `is not None` is bound in its guard",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def label(labels, key):\n"
                        "    found = labels.get(key)\n"
                        "    if found is not None:\n"
                        "        return found.title()\n"
                        "    return 'unknown'\n",
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "service.py",
                        "def label(labels, key):\n"
                        "    if (found := labels.get(key)) is not None:\n"
                        "        return found.title()\n"
                        "    return 'unknown'\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="inline-lookup-binding",
                scenario="lookup-binding",
                title="A lookup is evaluated once in the guard that consumes it",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def label(labels, key):\n"
                        "    if (found := labels.get(key)) is not None:\n"
                        "        return found.title()\n"
                        "    return 'unknown'\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        tree = context.tree
        if path.suffix == ".pyi" or context.generated or tree is None or "None" not in context.source:
            return []
        target = context.session.python_target
        diagnostics: list[Diagnostic] = []
        if not target.has_declared_support_before(path, _WALRUS_PYTHON):
            diagnostics.extend(
                Diagnostic(
                    path=path,
                    line=candidate.assignment.lineno,
                    col=candidate.assignment.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=none_guard_message(candidate, "a lookup"),
                )
                for candidate in none_guard_candidates(
                    context, self.code, comment_line_numbers(context.source), awaited=False
                )
                if candidate.is_not_none
            )
        if "match" in context.source and not target.has_declared_support_before(path, _MATCH_PYTHON):
            diagnostics.extend(self._order_findings(context))
        return sorted(diagnostics, key=lambda item: (item.line, item.col))

    def _order_findings(self, context: PythonFileContext) -> Iterator[Diagnostic]:
        candidates = [
            (statement, cases) for statement in context.nodes(ast.Match) if (cases := _none_before_values(statement))
        ]
        proven = none_disjoint_class_references(
            context,
            {
                atom.cls
                for _, cases in candidates
                for case in cases[1:]
                for atom in _alternatives(case.pattern)
                if isinstance(atom, ast.MatchClass)
            },
        )
        for statement, cases in candidates:
            message = _order_message(statement, cases, proven)
            if message is not None:
                absent = cases[0].pattern
                yield Diagnostic(context.path, absent.lineno, absent.col_offset + 1, self.code, message)


def _none_before_values(statement: ast.Match) -> list[ast.match_case]:
    for index, case in enumerate(statement.cases[:-1]):
        if not (case.guard is None and isinstance(case.pattern, ast.MatchSingleton) and case.pattern.value is None):
            continue
        candidates = statement.cases[index:]
        if len(statement.cases) > _BINARY_CASES and _catchall(candidates[-1]):
            candidates = candidates[:-1]
        if len(candidates) > 1:
            return candidates
    return []


def _catchall(case: ast.match_case) -> bool:
    return case.guard is None and isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None


def _alternatives(pattern: ast.pattern) -> Iterator[ast.pattern]:
    match pattern:
        case ast.MatchOr(patterns=members):
            for member in members:
                yield from _alternatives(member)
        case ast.MatchAs(pattern=ast.pattern() as inner):
            yield from _alternatives(inner)
        case _:
            yield pattern


def _order_message(statement: ast.Match, cases: list[ast.match_case], proven: frozenset[ast.expr]) -> str | None:
    absent, *following = cases
    if len(statement.cases) == _BINARY_CASES and (
        _catchall(following[0]) or _guards_presence(following[0], statement.subject, bind_on_present=True)
    ):
        message = _binary_message(absent, following[0])
        if isinstance(capture := following[0].pattern, ast.MatchAs) and capture.name is not None:
            return f"{message} Preserve the binding of `{capture.name}` on the present path."
        return message
    if all(
        (statement.cases[0] is absent and _guards_presence(case, statement.subject))
        or all(_disjoint_from_none(atom, proven) for atom in _alternatives(case.pattern))
        for case in following
    ):
        return "Place the present value arms before `case None:`. Keep their relative order, any capture bindings and the final catchall."
    return None


def _binary_message(absent: ast.match_case, present: ast.match_case) -> str:
    match absent.body[-1], present.body:
        case ast.Return() | ast.Raise() | ast.Continue() | ast.Break(), _:
            return (
                "Use a guard clause, `if (value := ...) is None:` followed by the exit, then continue "
                "with the present value. Do not use `case None:` for an early exit."
            )
        case _, [ast.Pass()]:
            return "Use `if (value := ...) is None:` for the absence branch, without `else:`."
        case ast.Pass(), _:
            return "Use `if (value := ...) is not None:` for the present branch, without `else:`."
        case _:
            return (
                "Use `if value is not None:` for the present case and `else:` for absence. "
                "Bind a lookup once with a walrus when needed."
            )


def _guards_presence(case: ast.match_case, subject: ast.expr, *, bind_on_present: bool = False) -> bool:
    match case.pattern, case.guard:
        case (
            ast.MatchAs(pattern=None, name=captured),
            ast.Compare(left=ast.Name(id=checked), ops=[ast.IsNot()], comparators=[ast.Constant(value=None)]),
        ):
            pass
        case _:
            return False
    if bind_on_present and captured == checked:
        return True
    match subject:
        case ast.Name(id=name):
            return name == checked and captured in {None, checked}
        case _:
            return False


def _disjoint_from_none(pattern: ast.pattern, proven: frozenset[ast.expr]) -> bool:
    match pattern:
        case (
            ast.MatchSingleton(value=True | False)
            | ast.MatchSequence()
            | ast.MatchMapping()
            | ast.MatchValue(value=ast.Constant() | ast.UnaryOp() | ast.BinOp())
        ):
            return True
        case ast.MatchClass(cls=reference):
            return reference in proven
        case _:
            return False
