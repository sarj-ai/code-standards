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
    is_suppressed,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_PYDANTIC = frozenset({"pydantic"})
_BUILTINS = frozenset({"builtins"})


@final
class PreferNativeStringCheck(Rule):
    id = "prefer-native-string-check"
    code = "SARJ480"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use native string assertions instead of unconstrained Pydantic coercion.",
        rationale="An unconstrained TypeAdapter(str).validate_python(...) obscures a simple string check and can decode bytes instead of rejecting them.",
        remediation="Use isinstance(value, str) and the appropriate failure path; in tests, assert the type. Keep structured validation at the model or JSON boundary. Preserve intentional coercion or ValidationError contracts explicitly.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only plain built-in str adapters used by validate_python inside an assertion without validation options are reported. Configured adapters, constrained types, unions, models, containers, other scalar types and JSON/serialization operations are excluded.",
            "Import aliases and uniquely assigned unconditional module-level adapter bindings are recognized. Local, conditional, reassigned, imported and indirect adapter values are not resolved; shadowed symbols are conservatively excluded.",
            "Generated and vendored code are excluded. Intentional ValidationError or byte-decoding contracts need a local reasoned suppression; no automatic replacement can preserve those contracts.",
        ),
        examples=(
            RuleExample(
                example_id="adapter-for-string-check",
                title="A string assertion unnecessarily constructs a schema validator",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_receipt.py",
                        'from pydantic import TypeAdapter\ndef test_receipt():\n    assert TypeAdapter(str).validate_python(receipt["id"]) == "abc"\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_receipt.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="native-string-assertion",
                title="A native assertion rejects unexpected types and narrows the value",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_receipt.py",
                        'def test_receipt():\n    value = receipt["id"]\n    assert isinstance(value, str)\n    assert value == "abc"\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_receipt.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.generated
            or not {"vendor", "vendored", "third_party"}.isdisjoint(context.path.parts)
            or "validate_python" not in context.source
            or context.tree is None
        ):
            return []
        adapters = _module_adapters(context)
        findings: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            if not isinstance(call.func, ast.Attribute) or call.func.attr != "validate_python" or call.keywords:
                continue
            if not _inside_assertion(call, context):
                continue
            receiver = call.func.value
            if not (
                _plain_string_adapter(receiver, context) or (isinstance(receiver, ast.Name) and receiver.id in adapters)
            ):
                continue
            if is_suppressed(context.source_lines, call.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message="plain str adapter used only to validate a Python value; use isinstance(value, str) with an explicit failure path, or preserve the intentional Pydantic contract explicitly",
                )
            )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _plain_string_adapter(node: ast.expr, context: PythonFileContext) -> bool:
    if not isinstance(node, ast.Call):
        return False
    function = node.func.value if isinstance(node.func, ast.Subscript) else node.func
    if not context.imports.resolves(function, sources=_PYDANTIC, symbol="TypeAdapter"):
        return False
    if len(node.args) == 1 and not node.keywords:
        value = node.args[0]
    elif not node.args and len(node.keywords) == 1 and node.keywords[0].arg == "type":
        value = node.keywords[0].value
    else:
        return False
    return (
        isinstance(value, ast.Name) and value.id == "str" and context.imports.builtin_is_unshadowed("str")
    ) or context.imports.resolves(value, sources=_BUILTINS, symbol="str")


def _module_adapters(context: PythonFileContext) -> frozenset[str]:
    tree = context.tree
    if tree is None:
        return frozenset()
    bindings = _binding_counts(context)
    names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        else:
            continue
        if isinstance(target, ast.Name) and bindings[target.id] == 1 and _plain_string_adapter(value, context):
            names.add(target.id)
    return frozenset(names)


def _binding_counts(context: PythonFileContext) -> Counter[str]:
    bindings = Counter(node.id for node in context.nodes(ast.Name) if isinstance(node.ctx, ast.Store | ast.Del))
    bindings.update(argument.arg for argument in context.nodes(ast.arg))
    bindings.update(alias.asname or alias.name.split(".")[0] for alias in context.nodes(ast.alias))
    bindings.update(node.name for node in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    bindings.update(node.name for node in context.nodes(ast.ExceptHandler) if node.name is not None)
    bindings.update(node.name for node in context.nodes(ast.MatchAs, ast.MatchStar) if node.name is not None)
    bindings.update(node.rest for node in context.nodes(ast.MatchMapping) if node.rest is not None)
    return bindings


def _inside_assertion(call: ast.Call, context: PythonFileContext) -> bool:
    parent = context.parents.get(call)
    while parent is not None:
        if isinstance(parent, ast.Assert):
            return True
        if isinstance(parent, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return False
        parent = context.parents.get(parent)
    return False
