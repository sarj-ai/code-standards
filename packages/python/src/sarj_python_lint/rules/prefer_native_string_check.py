from __future__ import annotations

import ast
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
    is_suppressed,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_PYDANTIC = frozenset({"pydantic", "pydantic.type_adapter"})
_BUILTINS = frozenset({"builtins"})
_PYTEST = frozenset({"pytest"})
_VALIDATION_ERROR = frozenset({"pydantic", "pydantic_core"})
_MODULES = _PYDANTIC | _BUILTINS | _PYTEST | _VALIDATION_ERROR


@dataclass(frozen=True, slots=True)
class _ImportReference:
    index: ImportIndex
    root_key: str


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
            "Scoped import aliases and unescaped unconditional module or local adapter bindings are recognized, including independent functions reusing a name. Conditional, reassigned, indirect or class/comprehension/parameter/global/nonlocal cached bindings are excluded, as are shadowed symbols, wildcard imports and imports with visible mutation or escape.",
            "Only assertion tests are checked: messages and lambda or generator expressions are excluded. Proven pytest.raises(ValidationError) contexts are preserved; other intentional byte-decoding or exception contracts need a local reasoned suppression. No automatic replacement can preserve those contracts.",
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
        provenance = ResourceProvenance(context)
        imports = {
            statement: ImportIndex.from_tree(ast.Module(body=[statement], type_ignores=[]))
            for statement in (*context.nodes(ast.Import), *context.nodes(ast.ImportFrom))
        }
        unsafe_imports = _unsafe_imports(context, provenance, imports)
        uncertain_names = _uncertain_cached_names(context, provenance)
        mutated_bindings = _mutated_cached_bindings(context, provenance)
        findings: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            receiver = _validation_receiver(call)
            if receiver is None:
                continue
            if not _inside_assertion(call, context) or _expects_validation_error(
                call, context, provenance, imports, unsafe_imports
            ):
                continue
            if isinstance(receiver, ast.Name):
                receiver = _cached_constructor(receiver, call, provenance, uncertain_names, mutated_bindings)
            if receiver is None or not _plain_string_adapter(receiver, context, provenance, imports, unsafe_imports):
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
                    message="plain str adapter in an assertion; use isinstance(value, str) with an explicit failure path, or preserve the intentional Pydantic contract explicitly",
                )
            )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _cached_constructor(
    receiver: ast.Name,
    at: ast.Call,
    provenance: ResourceProvenance,
    uncertain_names: set[str],
    mutated_bindings: set[ast.AST | None],
) -> ast.Call | None:
    if (
        receiver.id in uncertain_names
        or provenance.binding(receiver.id, at) in mutated_bindings
        or not provenance.unescaped(receiver, at)
    ):
        return None
    return provenance.constructor(receiver, at)


def _validation_receiver(call: ast.Call) -> ast.expr | None:
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "validate_python"
        and len(call.args) == 1
        and not call.keywords
        and not isinstance(call.args[0], ast.Starred)
    ):
        return call.func.value
    return None


def _uncertain_cached_names(context: PythonFileContext, provenance: ResourceProvenance) -> set[str]:
    uncertain_names = _nonlocal_names(context)
    uncertain_names.update(
        name
        for scope, bindings in provenance.bindings.items()
        if isinstance(scope, ast.ClassDef | ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp)
        for name in bindings
    )
    uncertain_names.update(argument.arg for argument in context.nodes(ast.arg))
    return uncertain_names


def _mutated_cached_bindings(context: PythonFileContext, provenance: ResourceProvenance) -> set[ast.AST | None]:
    return {
        provenance.binding(call.func.value.id, call)
        for call in context.nodes(ast.Call)
        if isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.attr in {"__init__", "__setattr__", "__delattr__"}
    }


def _plain_string_adapter(
    node: ast.expr,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    imports: dict[ast.Import | ast.ImportFrom, ImportIndex],
    unsafe_imports: set[str],
) -> bool:
    if not isinstance(node, ast.Call):
        return False
    function = node.func.value if isinstance(node.func, ast.Subscript) else node.func
    if not _resolves(function, context, provenance, imports, unsafe_imports, sources=_PYDANTIC, symbol="TypeAdapter"):
        return False
    value = _single_value(node, "type")
    if value is None:
        return False
    return (
        isinstance(value, ast.Name)
        and value.id == "str"
        and context.imports.builtin_is_unshadowed("str")
        and _lexical_binding("str", value, provenance) is None
        and "builtins" not in unsafe_imports
        and "builtins.str" not in unsafe_imports
    ) or _resolves(value, context, provenance, imports, unsafe_imports, sources=_BUILTINS, symbol="str")


def _single_value(call: ast.Call, keyword: str) -> ast.expr | None:
    if len(call.args) == 1 and not call.keywords and not isinstance(call.args[0], ast.Starred):
        return call.args[0]
    if not call.args and len(call.keywords) == 1 and call.keywords[0].arg == keyword:
        return call.keywords[0].value
    return None


def _resolves(
    node: ast.expr,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    imports: dict[ast.Import | ast.ImportFrom, ImportIndex],
    unsafe_imports: set[str],
    *,
    sources: frozenset[str],
    symbol: str,
) -> bool:
    reference = _import_reference(node, context, provenance, imports)
    if reference is None or provenance.wildcard:
        return False
    index = reference.index
    root_key = reference.root_key
    qualified = index.resolved_qualified_name(node)
    return (
        qualified is not None
        and root_key not in unsafe_imports
        and (root_key not in _MODULES or qualified.rsplit(".", 1)[0] not in unsafe_imports)
        and _import_key(*qualified.rsplit(".", 1)) not in unsafe_imports
        and index.resolves(node, sources=sources, symbol=symbol)
    )


def _lexical_binding(name: str, at: ast.AST, provenance: ResourceProvenance) -> ast.AST | None:
    initial = scope = provenance.scope(at)
    while scope is not None:
        if (scope is initial or not isinstance(scope, ast.ClassDef)) and (
            nodes := provenance.bindings.get(scope, {}).get(name)
        ):
            return nodes[0] if len(nodes) == 1 else None
        scope = provenance.scope(scope)
    return None


def _import_key(module: str, symbol: str | None) -> str:
    if symbol == "TypeAdapter" and module in _PYDANTIC:
        return f"pydantic.{symbol}"
    if symbol == "ValidationError" and module in _VALIDATION_ERROR:
        return f"pydantic_core.{symbol}"
    return f"{module}.{symbol}" if symbol is not None else module


def _import_reference(
    node: ast.expr,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    imports: dict[ast.Import | ast.ImportFrom, ImportIndex],
) -> _ImportReference | None:
    root = node
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return None
    binding = _lexical_binding(root.id, node, provenance)
    owner = context.parents.get(binding) if isinstance(binding, ast.alias) else None
    index = imports.get(owner) if isinstance(owner, ast.Import | ast.ImportFrom) else None
    target = index.bindings.get(root.id) if index is not None else None
    if index is None or target is None:
        return None
    return _ImportReference(index, _import_key(target.module, target.symbol))


def _reference_key(
    node: ast.expr,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    imports: dict[ast.Import | ast.ImportFrom, ImportIndex],
) -> str | None:
    reference = _import_reference(node, context, provenance, imports)
    if reference is None:
        return None
    index = reference.index
    root_key = reference.root_key
    if qualified := index.resolved_qualified_name(node):
        return qualified if qualified in _MODULES else _import_key(*qualified.rsplit(".", 1))
    return root_key


def _unsafe_imports(
    context: PythonFileContext,
    provenance: ResourceProvenance,
    imports: dict[ast.Import | ast.ImportFrom, ImportIndex],
) -> set[str]:
    unsafe = _mutated_imports(context, provenance, imports)
    for read in (*context.nodes(ast.Name), *context.nodes(ast.Attribute)):
        if not isinstance(read.ctx, ast.Load):
            continue
        key = _reference_key(read, context, provenance, imports)
        if key is None or not _import_escapes(read, key, context, provenance, imports):
            continue
        unsafe.add(key)
        if key in _PYDANTIC:
            unsafe.add("pydantic.TypeAdapter")
        if key in _VALIDATION_ERROR:
            unsafe.add("pydantic_core.ValidationError")
        if key == "pytest":
            unsafe.add("pytest.raises")
    return unsafe


def _mutated_imports(
    context: PythonFileContext,
    provenance: ResourceProvenance,
    imports: dict[ast.Import | ast.ImportFrom, ImportIndex],
) -> set[str]:
    unsafe = _rebound_imports(context, imports)
    for attribute in context.nodes(ast.Attribute):
        if (isinstance(attribute.ctx, ast.Store | ast.Del) or attribute.attr == "__dict__") and (
            key := _reference_key(attribute.value, context, provenance, imports)
        ) is not None:
            _mark_unsafe_import(key, attribute, context, imports, unsafe)
    for call in context.nodes(ast.Call):
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr in {"__setattr__", "__delattr__"}
            and (key := _reference_key(call.func.value, context, provenance, imports)) is not None
        ):
            _mark_unsafe_import(key, call, context, imports, unsafe)
        if (
            call.args
            and _builtin_mutation(call, context, provenance, imports)
            and (key := _reference_key(call.args[0], context, provenance, imports)) is not None
        ):
            _mark_unsafe_import(key, call, context, imports, unsafe)
    return unsafe


def _rebound_imports(
    context: PythonFileContext,
    imports: dict[ast.Import | ast.ImportFrom, ImportIndex],
) -> set[str]:
    uncertain_names = _nonlocal_names(context)
    return {
        _import_key(target.module, target.symbol)
        for index in imports.values()
        for name, target in index.bindings.items()
        if name in uncertain_names
    }


def _nonlocal_names(context: PythonFileContext) -> set[str]:
    return {
        name for statement in (*context.nodes(ast.Global), *context.nodes(ast.Nonlocal)) for name in statement.names
    }


def _import_escapes(
    read: ast.expr,
    key: str,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    imports: dict[ast.Import | ast.ImportFrom, ImportIndex],
) -> bool:
    parent = context.parents.get(read)
    if key == "pydantic.TypeAdapter":
        return not (
            isinstance(parent, ast.Attribute)
            or (isinstance(parent, ast.Subscript) and parent.value is read)
            or (isinstance(parent, ast.Call) and parent.func is read)
            or (isinstance(parent, ast.AnnAssign) and parent.annotation is read)
        )
    if key not in _MODULES or isinstance(parent, ast.Attribute | ast.ExceptHandler):
        return False
    return not (
        isinstance(parent, ast.Call)
        and (parent.func is read or _builtin_mutation(parent, context, provenance, imports))
    )


def _builtin_mutation(
    call: ast.Call,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    imports: dict[ast.Import | ast.ImportFrom, ImportIndex],
) -> bool:
    return (
        isinstance(call.func, ast.Name)
        and call.func.id in {"setattr", "delattr"}
        and context.imports.builtin_is_unshadowed(call.func.id)
        and _lexical_binding(call.func.id, call.func, provenance) is None
    ) or _reference_key(call.func, context, provenance, imports) in {
        "builtins.setattr",
        "builtins.delattr",
    }


def _mark_unsafe_import(
    key: str,
    at: ast.AST,
    context: PythonFileContext,
    imports: dict[ast.Import | ast.ImportFrom, ImportIndex],
    unsafe: set[str],
) -> None:
    unsafe.add(key)
    if key not in _MODULES:
        return
    for statement, index in imports.items():
        if isinstance(context.parents.get(statement), ast.Module) and (statement.lineno, statement.col_offset) < (
            getattr(at, "lineno", 0),
            getattr(at, "col_offset", 0),
        ):
            continue
        unsafe.update(
            _import_key(target.module, target.symbol)
            for target in index.bindings.values()
            if target.symbol is not None and target.module == key
        )


def _inside_assertion(call: ast.Call, context: PythonFileContext) -> bool:
    child: ast.AST = call
    parent = context.parents.get(call)
    while parent is not None:
        if isinstance(parent, ast.Assert):
            return child is parent.test
        if isinstance(parent, (ast.Lambda, ast.GeneratorExp, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return False
        child = parent
        parent = context.parents.get(parent)
    return False


def _expects_validation_error(
    call: ast.Call,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    imports: dict[ast.Import | ast.ImportFrom, ImportIndex],
    unsafe_imports: set[str],
) -> bool:
    parent = context.parents.get(call)
    while parent is not None and not isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
        if isinstance(parent, ast.With | ast.AsyncWith) and any(
            _raises_validation_error(item.context_expr, context, provenance, imports, unsafe_imports)
            for item in parent.items
        ):
            return True
        parent = context.parents.get(parent)
    return False


def _raises_validation_error(
    value: ast.expr,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    imports: dict[ast.Import | ast.ImportFrom, ImportIndex],
    unsafe_imports: set[str],
) -> bool:
    if (
        not isinstance(value, ast.Call)
        or len(value.args) > 1
        or not _resolves(value.func, context, provenance, imports, unsafe_imports, sources=_PYTEST, symbol="raises")
    ):
        return False
    expected = (
        value.args[0]
        if value.args
        else next((keyword.value for keyword in value.keywords if keyword.arg == "expected_exception"), None)
    )
    if expected is None:
        return False
    types = expected.elts if isinstance(expected, ast.Tuple) else (expected,)
    return any(
        _resolves(
            item, context, provenance, imports, unsafe_imports, sources=_VALIDATION_ERROR, symbol="ValidationError"
        )
        for item in types
    )
