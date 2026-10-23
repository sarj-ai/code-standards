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
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
from sarj_python_lint.rules._resource_provenance import ResourceProvenance, import_name_for_binding


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_TYPING = ("typing", "typing_extensions")
_MODEL_BASES = ("pydantic.BaseModel", "pydantic.main.BaseModel")
_MAPPINGS = (
    "collections.abc.Mapping",
    "collections.abc.MutableMapping",
    "typing.Mapping",
    "typing.MutableMapping",
)
_PAIR = 2
_MAX_SELECTOR_ALIAS_DEPTH = 16
_MODEL = "from pydantic import BaseModel\nclass Route(BaseModel):\n    destination: str\n"
_BAD = (
    _MODEL
    + """
def _field(route: object, name: str) -> object:
    if isinstance(route, Route):
        return getattr(route, name)
    if isinstance(route, dict):
        return route.get(name)
    return None
def destination(raw: object) -> object:
    return _field(raw, 'destination')
"""
)
_GOOD = (
    _MODEL
    + """
def destination(raw: object) -> str:
    route = Route.model_validate(raw)
    return route.destination
"""
)


@final
class NoDualShapeModelFieldReader(Rule):
    id = "no-dual-shape-model-field-reader"
    code = "SARJ522"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Normalize a known model instead of reading its fields through a model-or-dict accessor.",
        rationale=(
            "A string-selected object return discards the model's field types and duplicates the raw and validated "
            "representations at every read. Literal field names at all local callers prove this is a fixed record API."
        ),
        remediation=(
            "Normalize raw input once with the named model's model_validate, then use typed attributes. Preserve "
            "missing-field, coercion, default and validation-error behavior; before validators still own raw input."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks stable private module functions with two parameters, an object/Any input and return, and a string field selector in either parameter order. The body must consist of a known local Pydantic model getattr branch, a builtin dict or import-proven standard Mapping get/subscript branch and a None fallback. Import-proven typing casts are transparent.",
            "Every visible use must be a direct call with a declared model field selected by a literal or a bounded chain of dominating single-assignment constants. Dynamic selectors, escaped/public helpers, imported/inherited models, custom attribute hooks, shadowed builtins and ambiguous or rebound bindings abstain. No application modules are imported.",
            "Opaque values, arbitrary dictionaries and generic reflection alone are valid. Raw Pydantic validators are not prohibited, but extracting this closed dual-shape reader does not make its erased field contract typed.",
            "Authored tests are checked; generated/vendor code is excluded. This is a warning without an autofix because normalization can change rejection, coercion, default generation and error timing.",
        ),
        examples=(
            RuleExample(
                example_id="model-or-dict-reader",
                title="A fixed model field is hidden behind a string-selected object return",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/routes.py", _BAD),),
                focus_path=PurePosixPath("app/routes.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="normalized-model",
                title="Normalize the input and read the typed field",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/routes.py", _GOOD),),
                focus_path=PurePosixPath("app/routes.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.tree is None
            or context.generated
            or not {"vendor", "vendored", "third_party"}.isdisjoint(context.path.parts)
            or "getattr" not in context.symbol_source
        ):
            return []
        provenance = context.static_resource_provenance
        if provenance.wildcard or provenance.dynamic_namespace or not provenance.builtin_namespace_untouched:
            return []
        findings: list[Diagnostic] = []
        for function in context.tree.body:
            if not isinstance(function, ast.FunctionDef) or not _reader_signature(function, provenance):
                continue
            model = _reader_model(function, context, provenance)
            if model is None or not _fixed_field_calls(function, model, context, provenance):
                continue
            if is_suppressed(context.source_lines, function.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    function.lineno,
                    function.col_offset + 1,
                    self.code,
                    f"Normalize input once with {model.name}.model_validate(...) and read typed attributes instead "
                    "of projecting the same known fields through model getattr and mapping lookup branches.",
                    severity=Severity.WARNING,
                )
            )
        return findings


def _reader_signature(function: ast.FunctionDef, provenance: ResourceProvenance) -> bool:
    return (
        function.name.startswith("_")
        and not function.decorator_list
        and not function.type_params
        and _reader_parameters(function, provenance) is not None
        and function.args.vararg is None
        and function.args.kwarg is None
        and not function.args.defaults
        and not any(function.args.kw_defaults)
        and provenance.binding(function.name, function) is function
        and _opaque(function.returns, provenance)
    )


def _reader_parameters(function: ast.FunctionDef, provenance: ResourceProvenance) -> tuple[ast.arg, ast.arg] | None:
    arguments = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    if len(arguments) != _PAIR:
        return None
    values = [argument for argument in arguments if _opaque(argument.annotation, provenance)]
    keys = [
        argument
        for argument in arguments
        if _builtin(AnnotationSemantics.parse(argument.annotation), "str", provenance)
    ]
    return (values[0], keys[0]) if len(values) == len(keys) == 1 else None


def _opaque(annotation: ast.expr | None, provenance: ResourceProvenance) -> bool:
    node = AnnotationSemantics.parse(annotation)
    return _builtin(node, "object", provenance) or (
        node is not None and any(_imported(node, f"{module}.Any", provenance) for module in _TYPING)
    )


def _builtin(node: ast.expr | None, name: str, provenance: ResourceProvenance) -> bool:
    return (
        isinstance(node, ast.Name)
        and node.id == name
        and provenance.context.module_imports.builtin_is_unshadowed(name)
        and provenance.binding(name, node) is None
    )


def _imported(node: ast.expr, qualified: str, provenance: ResourceProvenance, *, at: ast.AST | None = None) -> bool:
    root = node
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name) or root.id in provenance.mutated | provenance.external_bindings:
        return False
    binding = provenance.binding(root.id, node if at is None else at)
    if not isinstance(binding, ast.alias):
        return False
    return import_name_for_binding(node, binding, provenance.context.parents.get(binding)) == qualified


def _reader_model(
    function: ast.FunctionDef, context: PythonFileContext, provenance: ResourceProvenance
) -> ast.ClassDef | None:
    parameters = _reader_parameters(function, provenance)
    if parameters is None:
        return None
    value, key = parameters
    arms = _reader_arms(function.body)
    if len(arms) != _PAIR:
        return None
    model: ast.ClassDef | None = None
    mapping = False
    for branch in arms:
        guard = branch.test
        if not (
            isinstance(guard, ast.Call)
            and _builtin(guard.func, "isinstance", provenance)
            and len(guard.args) == _PAIR
            and not guard.keywords
            and _parameter(guard.args[0], value, provenance)
            and len(branch.body) == 1
            and isinstance(branch.body[0], ast.Return)
            and branch.body[0].value is not None
        ):
            return None
        result = _without_cast(branch.body[0].value, provenance)
        target = guard.args[1]
        if _builtin(target, "dict", provenance) or any(_imported(target, kind, provenance) for kind in _MAPPINGS):
            mapping = _mapping_read(result, value, key, provenance)
        elif _attribute_read(result, value, key, provenance):
            model = _local_model(target, context, provenance)
        else:
            return None
    return model if mapping else None


def _reader_arms(body: list[ast.stmt]) -> list[ast.If]:
    statements = list(body)
    if statements and isinstance(statements[0], ast.Expr) and isinstance(statements[0].value, ast.Constant):
        statements = statements[1:]
    branches: list[ast.If] = []
    while statements:
        branch = statements[0]
        if not isinstance(branch, ast.If):
            break
        branches.append(branch)
        statements = [*branch.orelse, *statements[1:]]
    if len(statements) == 1 and isinstance(statements[0], ast.Return) and _none(statements[0].value):
        return branches
    return []


def _none(node: ast.expr | None) -> bool:
    return node is None or (isinstance(node, ast.Constant) and node.value is None)


def _parameter(node: ast.expr, parameter: ast.arg, provenance: ResourceProvenance) -> bool:
    return isinstance(node, ast.Name) and node.id == parameter.arg and provenance.binding(node.id, node) is parameter


def _without_cast(node: ast.expr, provenance: ResourceProvenance) -> ast.expr:
    if (
        isinstance(node, ast.Call)
        and len(node.args) == _PAIR
        and not node.keywords
        and any(_imported(node.func, f"{module}.cast", provenance) for module in _TYPING)
    ):
        return node.args[1]
    return node


def _attribute_read(node: ast.expr, value: ast.arg, key: ast.arg, provenance: ResourceProvenance) -> bool:
    return (
        isinstance(node, ast.Call)
        and _builtin(node.func, "getattr", provenance)
        and len(node.args) in {_PAIR, _PAIR + 1}
        and not node.keywords
        and _parameter(node.args[0], value, provenance)
        and _parameter(node.args[1], key, provenance)
        and (len(node.args) == _PAIR or _none(node.args[_PAIR]))
    )


def _mapping_read(node: ast.expr, value: ast.arg, key: ast.arg, provenance: ResourceProvenance) -> bool:
    if isinstance(node, ast.Subscript):
        return _parameter(_without_cast(node.value, provenance), value, provenance) and _parameter(
            node.slice, key, provenance
        )
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and _parameter(_without_cast(node.func.value, provenance), value, provenance)
        and len(node.args) in {1, _PAIR}
        and not node.keywords
        and _parameter(node.args[0], key, provenance)
        and (len(node.args) == 1 or _none(node.args[1]))
    )


def _local_model(target: ast.expr, context: PythonFileContext, provenance: ResourceProvenance) -> ast.ClassDef | None:
    if not isinstance(target, ast.Name):
        return None
    model = provenance.binding(target.id, target)
    if not (
        isinstance(model, ast.ClassDef)
        and context.parents.get(model) is context.tree
        and len(model.bases) == 1
        and not model.decorator_list
        and not model.keywords
        and not model.type_params
        and target.id not in provenance.mutated
        and any(_imported(model.bases[0], base, provenance) for base in _MODEL_BASES)
    ):
        return None
    if any(
        isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
        and member.name in {"__getattr__", "__getattribute__"}
        for member in model.body
    ):
        return None
    return model


def _fixed_field_calls(
    function: ast.FunctionDef, model: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance
) -> bool:
    parameters = _reader_parameters(function, provenance)
    if parameters is None:
        return False
    fields = {
        member.target.id
        for member in model.body
        if isinstance(member, ast.AnnAssign)
        and isinstance(member.target, ast.Name)
        and not member.target.id.startswith("_")
        and member.target.id != "model_config"
        and not _class_variable(member.annotation, provenance)
    }
    calls = 0
    for reference in provenance.reads.get(function.name, ()):
        if provenance.binding(reference.id, reference) is not function:
            continue
        call = context.parents.get(reference)
        if not isinstance(call, ast.Call) or call.func is not reference:
            return False
        key = _call_key(call, function, parameters[1].arg)
        literal = _literal_key(key, provenance)
        if literal is None or literal not in fields:
            return False
        calls += 1
    return calls > 0


def _class_variable(annotation: ast.expr, provenance: ResourceProvenance) -> bool:
    parsed = AnnotationSemantics.parse(annotation)
    if parsed is None:
        return True
    return any(
        isinstance(node, ast.Subscript)
        and any(_imported(node.value, f"{module}.ClassVar", provenance, at=annotation) for module in _TYPING)
        for node in ast.walk(parsed)
    )


def _literal_key(node: ast.expr | None, provenance: ResourceProvenance, *, depth: int = 0) -> str | None:
    if depth >= _MAX_SELECTOR_ALIAS_DEPTH:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.Name) or node.id in provenance.external_bindings:
        return None
    binding = provenance.binding(node.id, node)
    if not isinstance(binding, ast.Name):
        return None
    value = provenance.assignment_value(binding, node)
    return _literal_key(value, provenance, depth=depth + 1) if value is not None else None


def _call_key(call: ast.Call, function: ast.FunctionDef, key_name: str) -> ast.expr | None:
    positional = (*function.args.posonlyargs, *function.args.args)
    parameters = (*positional, *function.args.kwonlyargs)
    if len(call.args) > len(positional) or any(isinstance(argument, ast.Starred) for argument in call.args):
        return None
    bound = {parameter.arg: argument for parameter, argument in zip(positional, call.args, strict=False)}
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg in bound or keyword.arg in {arg.arg for arg in function.args.posonlyargs}:
            return None
        bound[keyword.arg] = keyword.value
    if set(bound) != {parameter.arg for parameter in parameters}:
        return None
    return bound.get(key_name)
