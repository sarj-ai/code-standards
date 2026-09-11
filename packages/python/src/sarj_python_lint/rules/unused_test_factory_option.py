from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, TypeGuard, final

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
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MIN_INVARIANT_CALLS = 2

_REFLECTION = frozenset({"globals", "locals", "vars", "eval", "exec", "getattr", "__import__", "__all__"})


@final
class UnusedTestFactoryOption(Rule):
    id = "unused-test-factory-option"
    code = "SARJ443"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="A private test factory exposes a literal option that visible callers never vary.",
        rationale="Unused customization obscures the values that actually distinguish test scenarios.",
        remediation="Keep the value in the factory's construction instead of exposing an unused option; retain it if external callers need it.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only module-level private _make_ and _build_ helpers consisting of a single return call are considered.",
            "Only literal defaults with direct, unambiguous calls in this file are reported. Explicit options require at least two calls with the same effective literal value. Decorators, rebinding, callable escapes, reflection, and argument unpacking exclude the helper.",
            "Cross-module callers cannot be proven absent. Shared helpers require an exact suppression; this advisory never autofixes signatures or changes default evaluation timing.",
        ),
        examples=(
            RuleExample(
                example_id="invariant-size-option",
                title="Repeated calls never vary the option",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_widget.py",
                        "def _make_widget(*, size=3):\n    return Widget(size=size)\n\n_make_widget()\n_make_widget(size=3)\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_widget.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="exercised-size-option",
                title="Keep customization that a caller exercises",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_widget.py",
                        "def _make_widget(*, size=3):\n    return Widget(size=size)\n\ndef test_widget():\n    assert _make_widget(size=4)\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_widget.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source) or not ("_make_" in source or "_build_" in source):
            return []
        tree = parse_or_none(path, source)
        if tree is None or (
            any(node.id in _REFLECTION for node in nodes(tree, ast.Name))
            or any(node.attr in _REFLECTION or node.attr == "__dict__" for node in nodes(tree, ast.Attribute))
            or any(node.name in _REFLECTION or node.name == "*" for node in nodes(tree, ast.alias))
        ):
            return []
        lines = source.splitlines()
        findings: list[Diagnostic] = []
        for function in tree.body:
            if not _is_factory(function):
                continue
            calls = _direct_calls(tree, function)
            if not calls:
                continue
            bound = _bound_calls(function, calls)
            if bound is None:
                continue
            supplied = {name for arguments in bound for name in arguments}
            positional = [*function.args.posonlyargs, *function.args.args]
            defaults = [
                *zip(positional[len(positional) - len(function.args.defaults) :], function.args.defaults, strict=True),
                *zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True),
            ]
            used = {node.id for node in nodes(function, ast.Name) if isinstance(node.ctx, ast.Load)}
            for argument, default in defaults:
                if argument.arg not in used or not isinstance(default, ast.Constant):
                    continue
                if default.value is not None and not isinstance(default.value, (str, bytes, int, float)):
                    continue
                explicitly_supplied = argument.arg in supplied
                if explicitly_supplied:
                    values = [arguments.get(argument.arg, default) for arguments in bound]
                    if len(values) < _MIN_INVARIANT_CALLS or any(
                        not isinstance(value, ast.Constant) or ast.dump(value) != ast.dump(values[0])
                        for value in values
                    ):
                        continue
                if is_suppressed(lines, argument.lineno, self.code):
                    continue
                findings.append(
                    Diagnostic(
                        path=path,
                        line=argument.lineno,
                        col=argument.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=(
                            f"Direct callers in this file always use the same literal for `{function.name}.{argument.arg}`; "
                            "consider keeping that value in the factory instead of repeating an invariant option. Retain it if external callers need it."
                            if explicitly_supplied
                            else f"No direct caller in this file supplies `{function.name}.{argument.arg}`; keep its literal value in the factory instead of exposing an unused option. Retain it if external callers need it."
                        ),
                    )
                )
        return sorted(findings, key=lambda item: (item.line, item.col))


def _is_factory(node: ast.stmt) -> TypeGuard[ast.FunctionDef]:
    return (
        isinstance(node, ast.FunctionDef)
        and node.name.startswith(("_make_", "_build_"))
        and not node.decorator_list
        and node.args.vararg is None
        and node.args.kwarg is None
        and len(node.body) == 1
        and isinstance(node.body[0], ast.Return)
        and isinstance(node.body[0].value, ast.Call)
    )


def _direct_calls(tree: ast.Module, function: ast.FunctionDef) -> list[ast.Call]:
    name = function.name
    if sum(node.name == name for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) != 1:
        return []
    if any(node.arg == name for node in nodes(tree, ast.arg)):
        return []
    if any((node.asname or node.name.split(".")[0]) == name for node in nodes(tree, ast.alias)):
        return []
    if any(node.attr == name for node in nodes(tree, ast.Attribute)):
        return []
    if any(node.value == name for node in nodes(tree, ast.Constant)):
        return []
    if any(node.name == name for node in nodes(tree, ast.MatchAs, ast.MatchStar, ast.ExceptHandler)):
        return []
    if any(node.rest == name for node in nodes(tree, ast.MatchMapping)):
        return []
    references = [node for node in nodes(tree, ast.Name) if node.id == name]
    calls = [node for node in nodes(tree, ast.Call) if isinstance(node.func, ast.Name) and node.func.id == name]
    if not calls or len(references) != len(calls) or any(not isinstance(node.ctx, ast.Load) for node in references):
        return []
    if any(
        any(isinstance(arg, ast.Starred) for arg in call.args) or any(kw.arg is None for kw in call.keywords)
        for call in calls
    ):
        return []
    if any(function.lineno <= call.lineno <= (function.end_lineno or function.lineno) for call in calls):
        return []
    return calls


def _bound_calls(function: ast.FunctionDef, calls: list[ast.Call]) -> list[dict[str, ast.expr]] | None:
    positional = [*function.args.posonlyargs, *function.args.args]
    keywords = {arg.arg for arg in (*function.args.args, *function.args.kwonlyargs)}
    required = {arg.arg for arg in positional[: len(positional) - len(function.args.defaults)]}
    required.update(
        arg.arg
        for arg, default in zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True)
        if default is None
    )
    bound: list[dict[str, ast.expr]] = []
    for call in calls:
        if len(call.args) > len(positional):
            return None
        arguments = {arg.arg: value for arg, value in zip(positional[: len(call.args)], call.args, strict=True)}
        for keyword in call.keywords:
            if keyword.arg not in keywords or keyword.arg in arguments:
                return None
            arguments[keyword.arg] = keyword.value
        if not required <= arguments.keys():
            return None
        bound.append(arguments)
    return bound
