from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
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
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_EFFECT = re.compile(
    r"^(?:append|extend|insert|add|emit|publish|send|record|track|capture|update|set|put|write|enqueue|create"
    r"|delete|remove)"
)
_LOGGER_RECEIVERS = ("logger", "self.logger", "log")


def _example(*, example_id: str, title: str, source: str, matches: bool, public: bool = True) -> RuleExample:
    return RuleExample(
        example_id=example_id,
        title=title,
        outcome=ExampleOutcome.MATCH if matches else ExampleOutcome.NO_MATCH,
        files=(ExampleFile.python("app/agent.py", source),),
        focus_path=PurePosixPath("app/agent.py"),
        expected_count=1 if matches else 0,
        public=public,
    )


@final
class NoSideEffectBeforeNoopGuard(Rule):
    id = "no-side-effect-before-noop-guard"
    code = "SARJ596"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Check no-op guards before performing side effects",
        rationale=(
            "An early return that rejects a repeated or invalid input runs after the function has already recorded, "
            "emitted or written something. The rejected call still leaves that trace, such as a tool call appended "
            "to conversation history for a language switch that never happened."
        ),
        remediation="Move the guard above the first side effect so a rejected call returns before changing any state.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Scans a function's top-level statements and the body of top-level `try` blocks. The side effect is "
                "the first non-`if` statement calling a method named like append, insert, emit, send, record, "
                "update, write or delete on an attribute such as `self.history`; logger receivers and bare local or "
                "parameter names, such as a visited set, are ignored."
            ),
            (
                "The guard is a later `if` without `else` that ends in `return` and tests one `==`, `in`, `not in` "
                "or `is` comparison mentioning a parameter. Guards that call functions or use `:=` are ignored "
                "because they may depend on the side effect."
            ),
            "Tests and generated code are excluded.",
        ),
        examples=(
            _example(
                example_id="effect-before-guard",
                title="History is recorded before the repeated-language guard returns",
                source=(
                    "async def switch_language(self, target: Language) -> str:\n"
                    "    self.history.insert(make_tool_call(target))\n"
                    "    try:\n"
                    "        if target == self.current_language:\n"
                    "            return 'Already speaking it'\n"
                    "        return await self.switch(target)\n"
                    "    finally:\n"
                    "        self.flush()\n"
                ),
                matches=True,
            ),
            _example(
                example_id="guard-before-effect",
                title="The guard returns before history is recorded",
                source=(
                    "async def switch_language(self, target: Language) -> str:\n"
                    "    if target == self.current_language:\n"
                    "        return 'Already speaking it'\n"
                    "    self.history.insert(make_tool_call(target))\n"
                    "    return await self.switch(target)\n"
                ),
                matches=False,
            ),
            _example(
                example_id="guard-reads-state",
                title="A guard that reads fresh state may depend on the earlier write",
                source=(
                    "async def refresh(self, key: str) -> None:\n"
                    "    await self.store.update(key)\n"
                    "    if (latest := await self.store.get(key)) is None:\n"
                    "        return\n"
                    "    self.publish(latest)\n"
                ),
                matches=False,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if is_test_path(context.path) or context.generated or context.tree is None:
            return []
        return [
            Diagnostic(
                path=context.path,
                line=guard.lineno,
                col=guard.col_offset + 1,
                code=self.code,
                message="Move this no-op guard before the side effect above so a rejected or repeated call records nothing.",
                severity=Severity.WARNING,
            )
            for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef)
            if (guard := _late_guard(function)) is not None
        ]


def _late_guard(function: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.If | None:
    arguments = function.args
    parameters = {argument.arg for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)} - {
        "self",
        "cls",
    }
    has_effect = False
    for statement in _statements(function.body):
        match statement:
            case ast.If() if has_effect and _is_noop_guard(statement, parameters):
                return statement
            case ast.If() | ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                pass
            case _ if not has_effect:
                has_effect = _has_effect_call(statement)
            case _:
                pass
    return None


def _statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    for statement in body:
        match statement:
            case ast.Try(body=inner) | ast.TryStar(body=inner):
                yield from _statements(inner)
            case _:
                yield statement


def _has_effect_call(statement: ast.stmt) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and not isinstance(node.func.value, ast.Name)
        and _EFFECT.match(node.func.attr) is not None
        and not ast.unparse(node.func.value).startswith(_LOGGER_RECEIVERS)
        for node in ast.walk(statement)
    )


def _is_noop_guard(statement: ast.If, parameters: set[str]) -> bool:
    match statement:
        case ast.If(
            test=ast.Compare(ops=[ast.Eq() | ast.In() | ast.NotIn() | ast.Is()]) as test,
            body=[*_, ast.Return()],
            orelse=[],
        ):
            nodes = list(ast.walk(test))
            return not any(isinstance(node, ast.Call | ast.NamedExpr) for node in nodes) and any(
                isinstance(node, ast.Name) and node.id in parameters for node in nodes
            )
        case _:
            return False
