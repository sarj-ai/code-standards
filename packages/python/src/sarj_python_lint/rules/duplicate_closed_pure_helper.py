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
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._closed_helpers import call_matches, closed_references, direct_call, executable_body
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_HELPER = "def _space(match: re.Match[str]) -> str:\n    full = match.group(0)\n    digits = match.group(1)\n    spaced = ' '.join(digits)\n    return full.replace(digits, spaced)\n"
_BAD = (
    "import re\nFIRST = re.compile(r'item (\\d+)')\nSECOND = re.compile(r'code (\\d+)')\n"
    + _HELPER
    + _HELPER.replace("_space", "_spread")
    + "FIRST.sub(_space, text)\nSECOND.sub(_spread, text)\n"
)
_GOOD = (
    "import re\nFIRST = re.compile(r'item (\\d+)')\nSECOND = re.compile(r'code (\\d+)')\n"
    + _HELPER
    + "FIRST.sub(_space, text)\nSECOND.sub(_space, text)\n"
)
_PATTERN_METHODS = frozenset({"sub", "subn", "match", "fullmatch", "search", "findall", "finditer", "split"})
_SUB_REQUIRED_ARGUMENTS = 2


@final
class DuplicateClosedPureHelper(Rule):
    id = "duplicate-closed-pure-helper"
    code = "SARJ489"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Closed private helpers repeat one proven native regex/string transformation.",
        rationale="Identical private transformations duplicate maintained behavior even when different caller patterns choose the domains in which they run.",
        remediation="Reuse one existing transformation while keeping each caller's pattern, order and examples. Preserve documented independent versioning or patch contracts explicitly.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only undecorated private module-level functions in one authored source file with identical signatures and executable ASTs are compared; no cross-file extraction is suggested.",
            "The supported pure grammar is one re.Match[str] parameter, straight-line local assignments, immutable literals, native Match.group, str.join and str.replace, and a str result. Defaults and unknown calls are excluded.",
            "Every reference must be a known direct call or the first replacement argument to Pattern.sub on a stable, unescaped native re.compile binding with a string pattern.",
            "Escapes, aliases, reflection, rebinding, exports, patch strings, decorators and generated/vendor paths are excluded. Distinct domain docstrings alone do not create runtime behavior; retain useful examples at the surviving owner. No autofix.",
        ),
        examples=tuple(
            RuleExample(
                example_id=name,
                title=title,
                outcome=outcome,
                files=(ExampleFile.python("app/formatters.py", source),),
                focus_path=PurePosixPath("app/formatters.py"),
                expected_count=count,
                public=True,
            )
            for name, title, outcome, source, count in (
                (
                    "duplicate-native-transformation",
                    "Different patterns use identical closed callbacks",
                    ExampleOutcome.MATCH,
                    _BAD,
                    1,
                ),
                (
                    "shared-existing-transformation",
                    "Patterns retain their choices and share one transformation",
                    ExampleOutcome.NO_MATCH,
                    _GOOD,
                    0,
                ),
            )
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        tree = context.tree
        if context.generated or tree is None or ".group" not in context.symbol_source:
            return []
        provenance = ResourceProvenance(context)
        owners: dict[str, ast.FunctionDef] = {}
        findings: list[Diagnostic] = []
        for function in tree.body:
            if (
                not isinstance(function, ast.FunctionDef)
                or function.returns is None
                or not _pure_body(function, context)
            ):
                continue
            references = closed_references(context, function, provenance)
            if references is None or any(
                not _known_reference(reference, function, context, provenance) for reference in references
            ):
                continue
            key = (
                ast.dump(function.args)
                + ast.dump(function.returns)
                + ast.dump(ast.Module(body=executable_body(function), type_ignores=[]))
            )
            if key not in owners:
                owners[key] = function
            elif not is_suppressed(context.source_lines, function.lineno, self.code):
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=function.lineno,
                        col=function.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=f"`{function.name}` repeats the closed native transformation in `{owners[key].name}`; reuse that helper while preserving caller patterns, useful examples, and intentional independent contracts.",
                    )
                )
        return findings


def _pure_body(function: ast.FunctionDef, context: PythonFileContext) -> bool:
    arguments = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
    if (
        len(arguments) != 1
        or function.args.defaults
        or any(function.args.kw_defaults)
        or not isinstance(function.returns, ast.Name)
    ):
        return False
    if function.returns.id != "str" or not context.imports.builtin_is_unshadowed("str"):
        return False
    annotation = arguments[0].annotation
    if (
        not isinstance(annotation, ast.Subscript)
        or context.imports.resolved_qualified_name(annotation.value) != "re.Match"
        or not isinstance(annotation.slice, ast.Name)
        or annotation.slice.id != "str"
    ):
        return False
    types = {arguments[0].arg: "match"}
    body = executable_body(function)
    if not body or not isinstance(body[-1], ast.Return):
        return False
    for statement in body[:-1]:
        if (
            not isinstance(statement, ast.Assign)
            or len(statement.targets) != 1
            or not isinstance(statement.targets[0], ast.Name)
        ):
            return False
        name = statement.targets[0].id
        kind = _native_type(statement.value, types)
        if name in types or kind is None:
            return False
        types[name] = kind
    return body[-1].value is not None and _native_type(body[-1].value, types) == "str"


def _native_type(expression: ast.expr, types: dict[str, str]) -> str | None:
    if isinstance(expression, ast.Name):
        return types.get(expression.id)
    if isinstance(expression, ast.Constant):
        return "str" if isinstance(expression.value, str) else "int" if type(expression.value) is int else None
    if not isinstance(expression, ast.Call) or expression.keywords or not isinstance(expression.func, ast.Attribute):
        return None
    receiver = _native_type(expression.func.value, types)
    arguments = [_native_type(argument, types) for argument in expression.args]
    if receiver == "match" and expression.func.attr == "group" and arguments == ["int"]:
        return "str"
    if receiver == "str" and (
        (expression.func.attr == "join" and arguments == ["str"])
        or (expression.func.attr == "replace" and arguments in (["str", "str"], ["str", "str", "int"]))
    ):
        return "str"
    return None


def _known_reference(
    reference: ast.Name, function: ast.FunctionDef, context: PythonFileContext, provenance: ResourceProvenance
) -> bool:
    call = direct_call(reference, context)
    if call is not None:
        return call_matches(function, call)
    parent = context.parents.get(reference)
    if (
        not isinstance(parent, ast.Call)
        or len(parent.args) < _SUB_REQUIRED_ARGUMENTS
        or parent.args[0] is not reference
        or not isinstance(parent.func, ast.Attribute)
        or parent.func.attr != "sub"
    ):
        return False
    return (
        isinstance(parent.func.value, ast.Name)
        and _native_pattern(parent.func.value, context, provenance)
        and not any(isinstance(argument, ast.Starred) for argument in parent.args)
        and not any(keyword.arg is None for keyword in parent.keywords)
    )


def _native_pattern(receiver: ast.Name, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    constructor = provenance.constructor(receiver, receiver)
    binding = provenance.binding(receiver.id, receiver)
    if (
        constructor is None
        or binding is None
        or not provenance.imported(constructor.func, "re.compile")
        or not constructor.args
    ):
        return False
    if not _string_pattern(constructor.args[0], provenance, frozenset()) or any(
        isinstance(node.value, str)
        and (receiver.id in node.value.split(".") or node.value in {"re.compile", "re.Match", "re.Pattern"})
        for node in context.nodes(ast.Constant)
    ):
        return False
    declaration = context.parents.get(binding)
    if declaration is None or context.parents.get(declaration) is not context.tree or receiver.id in provenance.mutated:
        return False
    for read in provenance.reads.get(receiver.id, ()):
        attribute = context.parents.get(read)
        use = context.parents.get(attribute) if attribute is not None else None
        if (
            provenance.binding(read.id, read) is not binding
            or not isinstance(attribute, ast.Attribute)
            or attribute.attr not in _PATTERN_METHODS
            or not isinstance(use, ast.Call)
            or use.func is not attribute
        ):
            return False
    return True


def _string_pattern(expression: ast.expr, provenance: ResourceProvenance, seen: frozenset[str]) -> bool:
    if isinstance(expression, ast.Constant):
        return isinstance(expression.value, str)
    if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Add):
        return _string_pattern(expression.left, provenance, seen) and _string_pattern(
            expression.right, provenance, seen
        )
    if not isinstance(expression, ast.Name) or expression.id in seen:
        return False
    binding = provenance.binding(expression.id, expression)
    if not isinstance(binding, ast.Name):
        return False
    statement = provenance.context.parents.get(binding)
    if statement is None or provenance.context.parents.get(statement) is not provenance.context.tree:
        return False
    value = provenance.assignment_value(binding, expression)
    return value is not None and _string_pattern(value, provenance, seen | {expression.id})
