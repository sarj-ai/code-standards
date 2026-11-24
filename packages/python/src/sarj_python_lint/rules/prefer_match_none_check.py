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
from sarj_python_lint.rules._ast_index import statement_blocks
from sarj_python_lint.rules._comments import comment_line_numbers
from sarj_python_lint.rules.prefer_walrus_awaited_none_guard import (
    PreferWalrusAwaitedNoneGuard,
    name_flow,
    none_guard_candidates,
    none_guard_message,
)


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_MATCH_PYTHON = (3, 10)
_WALRUS_PYTHON = (3, 8)


@final
class PreferMatchNoneCheck(Rule):
    id = "prefer-match-none-check"
    code = "SARJ589"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Prefer match/case for a None check that selects a value or guards later use of a name.",
        rationale=(
            "A conditional expression or early-exit guard on `is None` hides a two-way decision in an operator or "
            "splits it across statements. `match value: case None: ... case _: ...` names both outcomes, keeps "
            "the absent case first and lets the type checker narrow `value` in each arm."
        ),
        remediation=(
            "Rewrite `return use(value) if value is not None else None` as `match value:` with `case None: return "
            "None` and `case _: return use(value)`. Rewrite `if (value := lookup()) is None: return` (or a plain "
            "`if value is None: return`) followed by code that uses `value` as `match value := lookup():` with the "
            "early exit under `case None:` and the remaining code under `case _:`. When a split lookup is "
            "immediately returned or raised under `is not None`, bind it in the guard as "
            "`if (value := lookup()) is not None:`."
        ),
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.SAFE,
        aliases=("prefer-walrus-none-guard",),
        limitations=(
            "A conditional expression is reported only when it is the whole value of a return statement or an assignment and its test is exactly `subject is None` or `subject is not None`, where the subject is a name, an attribute chain or an assignment expression. Conditional expressions in call arguments, default arguments, comprehensions, lambdas, containers, f-strings, boolean operands and nested positions are excluded because no match statement fits there.",
            "The default-value idiom `value if value is not None else default` (or `default if value is None else value`), where the non-None arm is the subject itself, is excluded.",
            "A guard is reported when an `if` without else tests exactly `name is None` or `(name := expr) is None`, its body ends in return, raise or continue, and a later statement in the same block reads the name before rebinding it. Truthiness, `== None`, compound conditions, attribute or subscript subjects, guards with else branches and guards without a later use are excluded.",
            "Awaited lookups split from their `is None` guard are reported by SARJ432 at the assignment, so this rule does not report the guard twice. `isinstance` conditional expressions and single-branch `isinstance` dispatch belong to SARJ080.",
            "A one-line synchronous call assigned to a single name and immediately returned or raised under an `is not None` guard, with no later use, is reported at the assignment and safely fixed into `if (name := call()) is not None:`. Regex search/match/fullmatch lookups belong to SARJ081.",
            "Match recommendations have no automatic fix because the code after a guard moves under `case _:`. Generated and stub files are excluded, and declared support for Python before 3.10 (3.8 for the inline binding) suppresses the corresponding findings.",
        ),
        examples=(
            RuleExample(
                example_id="conditional-none-return",
                scenario="conditional-expression",
                title="A returned conditional expression hides the None decision in an operator",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "audio.py",
                        "class Audio:\n"
                        "    def frames(self, key):\n"
                        "        pcm = self._pcm.get(key)\n"
                        "        return self._frames(pcm) if pcm is not None else None\n",
                    ),
                ),
                focus_path=PurePosixPath("audio.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="conditional-none-match",
                scenario="conditional-expression",
                title="Both outcomes are match arms",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "audio.py",
                        "class Audio:\n"
                        "    def frames(self, key):\n"
                        "        match pcm := self._pcm.get(key):\n"
                        "            case None:\n"
                        "                return None\n"
                        "            case _:\n"
                        "                return self._frames(pcm)\n",
                    ),
                ),
                focus_path=PurePosixPath("audio.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="none-guard-before-use",
                scenario="none-guard",
                title="An early None exit guards the code that uses the name",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "voice.py",
                        "def voice_settings(session):\n"
                        "    models = session.userdata.model_config\n"
                        "    if models is None:\n"
                        "        return None\n"
                        "    return models.tts\n",
                    ),
                ),
                focus_path=PurePosixPath("voice.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="none-guard-match",
                scenario="none-guard",
                title="The guarded name is the match subject",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "voice.py",
                        "def voice_settings(session):\n"
                        "    match models := session.userdata.model_config:\n"
                        "        case None:\n"
                        "            return None\n"
                        "        case _:\n"
                        "            return models.tts\n",
                    ),
                ),
                focus_path=PurePosixPath("voice.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="default-value-idioms",
                title="Default-value idioms and call arguments stay inline",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "client.py",
                        "def connect(timeout=None, retries=None):\n"
                        "    timeout = timeout if timeout is not None else 30\n"
                        "    return open_client(retries=retries if retries is not None else 3, timeout=timeout)\n",
                    ),
                ),
                focus_path=PurePosixPath("client.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="consumed-lookup-binding",
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
        if not target.has_declared_support_before(path, _MATCH_PYTHON):
            diagnostics.extend(self._conditional_findings(context))
            diagnostics.extend(self._guard_findings(context, tree))
        return sorted(diagnostics, key=lambda item: (item.line, item.col))

    def _conditional_findings(self, context: PythonFileContext) -> Iterator[Diagnostic]:
        for statement in context.nodes(ast.Return, ast.Assign, ast.AnnAssign):
            value = statement.value
            if isinstance(value, ast.IfExp) and (subject := _conditional_subject(value, context.source)) is not None:
                yield self._diagnostic(
                    context,
                    value,
                    f"Use `match {subject}:` with `case None:` and `case _:` arms instead of this None "
                    "conditional expression",
                )

    def _guard_findings(self, context: PythonFileContext, tree: ast.Module) -> Iterator[Diagnostic]:
        owned = {
            candidate.guard
            for candidate in none_guard_candidates(
                context,
                PreferWalrusAwaitedNoneGuard.code,
                comment_line_numbers(context.source),
                awaited=True,
            )
            if not candidate.is_not_none
        }
        owners = [tree, *context.nodes(ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)]
        for block in (block for owner in owners for block in statement_blocks(owner.body)):
            for index, guard in enumerate(block):
                if guard in owned or (header := _used_guard_header(block, index, context.source)) is None:
                    continue
                name, subject = header
                yield self._diagnostic(
                    context,
                    guard,
                    f"Use `match {subject}:` with `case None:` for this early exit and `case _:` for the code "
                    f"that uses `{name}`",
                )

    def _diagnostic(self, context: PythonFileContext, node: ast.expr | ast.stmt, message: str) -> Diagnostic:
        return Diagnostic(
            path=context.path,
            line=node.lineno,
            col=node.col_offset + 1,
            code=self.code,
            severity=Severity.WARNING,
            message=message,
        )


def _is_none_test(test: ast.expr) -> tuple[ast.expr, bool] | None:
    match test:
        case ast.Compare(left=subject, ops=[ast.Is() | ast.IsNot() as operator], comparators=[ast.Constant(None)]):
            return subject, isinstance(operator, ast.IsNot)
        case _:
            return None


def _conditional_subject(value: ast.IfExp, source: str) -> str | None:
    if (test := _is_none_test(value.test)) is None:
        return None
    subject, is_not_none = test
    present = value.body if is_not_none else value.orelse
    match subject:
        case ast.NamedExpr(target=ast.Name(id=name)):
            if isinstance(present, ast.Name) and present.id == name:
                return None
        case ast.Name() | ast.Attribute() if _is_attribute_chain(subject):
            if ast.dump(present) == ast.dump(subject):
                return None
        case _:
            return None
    return ast.get_source_segment(source, subject)


def _is_attribute_chain(node: ast.expr) -> bool:
    match node:
        case ast.Name():
            return True
        case ast.Attribute(value=owner):
            return _is_attribute_chain(owner)
        case _:
            return False


def _used_guard_header(block: list[ast.stmt], index: int, source: str) -> tuple[str, str] | None:
    guard = block[index]
    if not isinstance(guard, ast.If):
        return None
    header = _guard_header(guard, block[index - 1] if index else None, source)
    if header is None or name_flow(block[index + 1 :], header[0]) != "loaded":
        return None
    return header


def _guard_header(guard: ast.If, previous: ast.stmt | None, source: str) -> tuple[str, str] | None:
    if guard.orelse or not isinstance(guard.body[-1], ast.Return | ast.Raise | ast.Continue):
        return None
    match _is_none_test(guard.test):
        case ast.NamedExpr(target=ast.Name(id=name), value=value), False:
            return name, _binding(name, value, source)
        case ast.Name(id=name), False:
            match previous:
                case ast.Assign(targets=[ast.Name(id=target)], value=value) if target == name:
                    return name, _binding(name, value, source)
                case _:
                    return name, name
        case _:
            return None


def _binding(name: str, value: ast.expr, source: str) -> str:
    expression = ast.get_source_segment(source, value)
    if expression is None or "\n" in expression:
        return f"{name} := ..."
    return f"{name} := {expression}"
