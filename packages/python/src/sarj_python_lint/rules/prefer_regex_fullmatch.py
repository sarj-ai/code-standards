from __future__ import annotations

import ast
from collections import Counter
from pathlib import PurePosixPath
import re
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
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_RE = frozenset({"re"})
_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_BAD = "import re\n\ndef validate(value):\n    if not re.match(r'^[a-z]+$', value):\n        raise ValueError('invalid value')\n"
_GOOD = _BAD.replace("re.match(r'^[a-z]+$'", "re.fullmatch(r'[a-z]+'")


class PreferRegexFullmatch(Rule):
    id: str = "prefer-regex-fullmatch"
    code: str = "SARJ460"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="An anchored regex validation predicate does not require a full-string match.",
        rationale="The regex `$` anchor can match before a final newline, so an anchored match can accept a value that was not fully validated.",
        remediation="Use `re.fullmatch` or the compiled pattern's `fullmatch` method for whole-value validation; review whether a terminal newline is intentionally allowed.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks direct negative match/is-None rejection guards and returns of bool(match), not match, or match is/is-not None. Match-object returns, extraction, search, and compound conditions are excluded.",
            "Patterns must be valid string or bytes literals bounded by `^` or `\\A` and an unescaped outer `$`; top-level alternation, inline extension groups other than noncapturing groups, and flags other than literal zero are excluded.",
            "Only imported standard-library re functions and unique, unconditional module or same-function compile bindings are resolved. Rebinding, import shadowing, escaped regex objects or modules, explicit match positions, tests, and generated files are excluded.",
            "Binding checks are deliberately file-wide, so unrelated same-named locals can suppress findings. Dynamic monkeypatching and interprocedural changes are not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="anchored-rejection",
                title="An end anchor permits a final newline",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/validation.py", _BAD),),
                focus_path=PurePosixPath("app/validation.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="whole-value-rejection",
                title="Validate the entire value",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/validation.py", _GOOD),),
                focus_path=PurePosixPath("app/validation.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "match" not in context.source or context.tree is None or context.generated or is_test_path(context.path):
            return []
        bindings = _binding_counts(context)
        mutated = {
            root
            for node in context.nodes(ast.Attribute)
            if isinstance(node.ctx, (ast.Store, ast.Del)) and (root := _root_name(node)) is not None
        }
        mutated.update(
            node.id for node in context.nodes(ast.Name) if isinstance(node.ctx, ast.Load) and _escapes(context, node)
        )
        compiled = _compiled_patterns(context, bindings, mutated)
        findings: list[Diagnostic] = []
        for guard in context.nodes(ast.If, ast.Return):
            call = _validation_call(guard, context, bindings)
            if call is None or is_suppressed(context.source_lines, call.lineno, self.code):
                continue
            pattern = _match_pattern(context, call, bindings, mutated, compiled)
            if pattern is None or not _whole_value_pattern(pattern):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    message="anchored match is used as a validation predicate, but `$` can accept a final newline; use fullmatch for whole-value validation and review newline handling.",
                    severity=Severity.WARNING,
                )
            )
        return sorted(findings, key=lambda item: (item.line, item.col))


def _validation_call(node: ast.If | ast.Return, context: PythonFileContext, bindings: Counter[str]) -> ast.Call | None:
    if isinstance(node, ast.If):
        return _rejection_call(node)
    match node.value:
        case (
            ast.UnaryOp(op=ast.Not(), operand=ast.Call() as call)
            | ast.Compare(left=ast.Call() as call, ops=[ast.Is() | ast.IsNot()], comparators=[ast.Constant(value=None)])
        ):
            return call
        case ast.Call(func=ast.Name(id="bool"), args=[ast.Call() as call], keywords=[]):
            if context.imports.builtin_is_unshadowed("bool") and bindings["bool"] == 0:
                return call
        case _:
            pass
    return None


def _rejection_call(guard: ast.If) -> ast.Call | None:
    if len(guard.body) != 1 or not isinstance(guard.body[0], ast.Raise):
        return None
    condition = guard.test
    if isinstance(condition, ast.UnaryOp) and isinstance(condition.op, ast.Not):
        return condition.operand if isinstance(condition.operand, ast.Call) else None
    if not isinstance(condition, ast.Compare) or len(condition.ops) != 1:
        return None
    if (
        isinstance(condition.ops[0], ast.Is)
        and isinstance(condition.left, ast.Call)
        and isinstance(condition.comparators[0], ast.Constant)
        and condition.comparators[0].value is None
    ):
        return condition.left
    return None


def _binding_counts(context: PythonFileContext) -> Counter[str]:
    result: Counter[str] = Counter()
    for node in context.nodes(ast.AST):
        match node:
            case (
                ast.Name(id=name, ctx=(ast.Store() | ast.Del()))
                | ast.arg(arg=name)
                | ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ):
                result[name] += 1
            case ast.alias(name=name, asname=alias):
                result[alias or name.partition(".")[0]] += 1
            case (
                ast.ExceptHandler(name=str(name))
                | ast.MatchAs(name=str(name))
                | ast.MatchStar(name=str(name))
                | ast.MatchMapping(rest=str(name))
            ):
                result[name] += 1
            case _:
                pass
    return result


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _escapes(context: PythonFileContext, node: ast.Name) -> bool:
    parent = context.parents.get(node)
    if isinstance(parent, ast.Attribute) and parent.value is node:
        return False
    return not (isinstance(parent, ast.Call) and parent.func is node)


def _resolves(
    context: PythonFileContext, node: ast.expr, symbol: str, bindings: Counter[str], mutated: set[str]
) -> bool:
    root = _root_name(node)
    return (
        root is not None
        and bindings[root] == 1
        and root not in mutated
        and context.imports.resolves(node, sources=_RE, symbol=symbol)
    )


def _literal_pattern(call: ast.Call, *, compile_call: bool) -> str | bytes | None:
    names = ("pattern", "flags") if compile_call else ("pattern", "string", "flags")
    if len(call.args) > len(names) or any(isinstance(argument, ast.Starred) for argument in call.args):
        return None
    arguments: dict[str, ast.expr] = dict(zip(names, call.args, strict=False))
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg not in names or keyword.arg in arguments:
            return None
        arguments[keyword.arg] = keyword.value
    required = {"pattern"} if compile_call else {"pattern", "string"}
    if not required <= arguments.keys():
        return None
    flags = arguments.get("flags")
    if flags is not None and not (isinstance(flags, ast.Constant) and type(flags.value) is int and flags.value == 0):
        return None
    pattern = arguments["pattern"]
    return pattern.value if isinstance(pattern, ast.Constant) and isinstance(pattern.value, (str, bytes)) else None


def _compiled_patterns(
    context: PythonFileContext, bindings: Counter[str], mutated: set[str]
) -> dict[str, tuple[ast.AST, ast.expr, str | bytes]]:
    patterns: dict[str, tuple[ast.AST, ast.expr, str | bytes]] = {}
    for node in context.nodes(ast.Assign, ast.AnnAssign):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        else:
            continue
        owner = context.parents.get(node)
        if not isinstance(owner, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if (
            not isinstance(target, ast.Name)
            or bindings[target.id] != 1
            or target.id in mutated
            or not isinstance(value, ast.Call)
            or not _resolves(context, value.func, "compile", bindings, mutated)
        ):
            continue
        pattern = _literal_pattern(value, compile_call=True)
        if pattern is not None:
            patterns[target.id] = owner, target, pattern
    return patterns


def _match_pattern(
    context: PythonFileContext,
    call: ast.Call,
    bindings: Counter[str],
    mutated: set[str],
    compiled: dict[str, tuple[ast.AST, ast.expr, str | bytes]],
) -> str | bytes | None:
    if _resolves(context, call.func, "match", bindings, mutated):
        return _literal_pattern(call, compile_call=False)
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "match" or len(call.args) != 1 or call.keywords:
        return None
    receiver = call.func.value
    if isinstance(receiver, ast.Call) and _resolves(context, receiver.func, "compile", bindings, mutated):
        return _literal_pattern(receiver, compile_call=True)
    if not isinstance(receiver, ast.Name) or receiver.id not in compiled:
        return None
    owner, target, pattern = compiled[receiver.id]
    if target.lineno >= call.lineno or (not isinstance(owner, ast.Module) and owner is not _scope(context, call)):
        return None
    return pattern


def _scope(context: PythonFileContext, node: ast.AST) -> ast.AST | None:
    parent = context.parents.get(node)
    while parent is not None and not isinstance(parent, _SCOPES):
        parent = context.parents.get(parent)
    return parent


def _whole_value_pattern(pattern: str | bytes) -> bool:
    text = pattern.decode("latin1") if isinstance(pattern, bytes) else pattern
    if not text.startswith(("^", r"\A")) or not text.endswith("$"):
        return False
    try:
        re.compile(pattern)
    except re.PatternError, OverflowError, RecursionError:
        return False
    depth = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            index = _class_end(text, index) + 1
            continue
        if char == "(":
            if text[index : index + 2] == "(?" and text[index : index + 3] != "(?:":
                return False
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "|" and depth == 0:
            return False
        elif char == "$" and index == len(text) - 1:
            return depth == 0
        index += 1
    return False


def _class_end(text: str, start: int) -> int:
    index = start + 1
    if text[index] == "^":
        index += 1
    if text[index] == "]":
        index += 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "]":
            return index
        index += 1
    return len(text)
