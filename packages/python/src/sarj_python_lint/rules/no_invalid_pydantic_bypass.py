from __future__ import annotations

import ast
from dataclasses import dataclass
from itertools import starmap
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, TypeIs, final, override

from sarj_python_lint.json_boundary import is_object_mapping
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
from sarj_python_lint.rules._pydantic_field_contract import (
    FIELD_SOURCES,
    MODEL_SOURCES,
    TYPING_SOURCES,
    direct_models,
    unique_members,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_BUILTINS = frozenset({"str", "int", "float", "bool", "bytes", "complex", "list", "dict", "set", "frozenset", "tuple"})
_GENERICS = frozenset({"list", "dict", "set", "frozenset", "tuple"})
_ALIASES = frozenset({"alias", "validation_alias", "serialization_alias"})
_PASSIVE_CONFIG = frozenset({"frozen", "strict", "validate_default"})
_MODEL_APIS = frozenset({"model_construct", "model_validate", "model_validate_json", "model_validate_strings"})
_MAX_ANNOTATION_DEPTH = 64
_MAX_ANNOTATION_NODES = 1024
_MAX_LITERAL_TEXT = 65536
_UNKNOWN_LITERAL: Final = object()
_PAIR_ARITY = 2


@dataclass(frozen=True, slots=True)
class _Field:
    annotation: ast.expr
    required: bool


@dataclass(frozen=True, slots=True)
class _Model:
    node: ast.ClassDef
    fields: dict[str, _Field]


@final
class NoInvalidPydanticBypass(Rule):
    id = "no-invalid-pydantic-bypass"
    code = "SARJ511"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Do not create a provably invalid model through Pydantic validation bypass APIs.",
        rationale=(
            "model_construct and model_copy(update=...) store supplied values without validation. A contradictory "
            "literal or an omitted required construction field can therefore invalidate a model's declared type "
            "while the permissive bypass signatures still pass static checking."
        ),
        remediation=(
            "Supply values satisfying the model contract and every required field, or validate a complete input "
            "mapping with the normal constructor or model_validate. A model_validate call on an existing model "
            "instance does not necessarily revalidate it; keep trusted bypasses only when their inputs preserve the contract."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only plain, direct, module-level Pydantic BaseModel subclasses with supported built-in and typing field annotations are inspected; hooks, inheritance, class decorators and custom methods are excluded.",
            "Checks explicit None conflicts, closed string Literal domains, and bounded side-effect-free literal values contradicting builtin primitive or container field contracts. Coercible input is not assumed to be validated stored output.",
            "Container literals preserve their actual construction semantics, including last-wins dictionary keys. Unpacking, calls, unhashable literal containers, opaque values, numeric Literal domains, bounds, aliases and custom field types are not inferred. Bool remains an int subtype, and numeric int-to-float/complex assignability is preserved.",
            "model_construct must use explicit keywords; omitted required fields are checked only when no unpacking or positional argument can supply them.",
            "model_copy requires a fresh exact constructor or a stable unescaped local constructor binding, plus a plain literal update dictionary. Arbitrary annotated receivers and overridden methods are excluded.",
            "Field aliases, non-passive model configuration, class or instance mutation and escape, ambiguous namespaces, tests and generated files are excluded.",
            "Direct model field annotations exceeding a bounded depth or node budget exclude the file rather than risking recursive analysis failure. Literal analysis also bounds the value tree and combined string/bytes content to avoid excessive witness work.",
            "Trusted valid construction and copy operations remain legal. No autofix chooses domain values or changes validation behavior.",
        ),
        examples=(
            RuleExample(
                example_id="construct-invalid-tag",
                title="Unchecked construction stores a tag outside the declared vocabulary",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Literal\nfrom pydantic import BaseModel\nclass Job(BaseModel):\n    kind: Literal['queued', 'done']\njob = Job.model_construct(kind='unknown')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="construct-trusted-valid-tag",
                title="Trusted construction still satisfies the declared vocabulary",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Literal\nfrom pydantic import BaseModel\nclass Job(BaseModel):\n    kind: Literal['queued', 'done']\njob = Job.model_construct(kind='queued')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="construct-invalid-list-member",
                scenario="stored-literal-contract",
                title="Unchecked list elements must satisfy the stored field type",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel\nclass Payload(BaseModel):\n    labels: list[str]\npayload = Payload.model_construct(labels=[3])\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="construct-trusted-list-members",
                scenario="stored-literal-contract",
                title="Trusted list elements preserve the field contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel\nclass Payload(BaseModel):\n    labels: list[str]\npayload = Payload.model_construct(labels=['ready'])\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if is_test_path(context.path) or context.generated:
            return []
        signals = context.symbol_source
        if "BaseModel" not in signals or not any(api in signals for api in ("model_construct", "model_copy")):
            return []
        if context.tree is None or not _bounded_model_annotations(context):
            return []
        provenance = context.static_resource_provenance
        models = _models(context, provenance)
        diagnostics: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            target = _bypass_target(call, models, provenance)
            if target is None:
                continue
            model, values, construction = target
            diagnostics.extend(_invalid_values(call, model, values, construction=construction, context=context))
        return [finding for finding in diagnostics if not is_suppressed(context.source_lines, finding.line, self.code)]


def _bounded_model_annotations(context: PythonFileContext) -> bool:
    tree = context.tree
    if tree is None:
        return False
    for model in tree.body:
        if (
            not isinstance(model, ast.ClassDef)
            or len(model.bases) != 1
            or not context.imports.resolves(model.bases[0], sources=MODEL_SOURCES, symbol="BaseModel")
        ):
            continue
        for member in model.body:
            if isinstance(member, ast.AnnAssign) and not _bounded_annotation(member.annotation):
                return False
    return True


def _bounded_annotation(annotation: ast.expr) -> bool:
    pending: list[tuple[ast.AST, int]] = [(annotation, 0)]
    visited = 0
    while pending:
        node, depth = pending.pop()
        visited += 1
        if depth > _MAX_ANNOTATION_DEPTH or visited > _MAX_ANNOTATION_NODES:
            return False
        for child in ast.iter_child_nodes(node):
            if visited + len(pending) >= _MAX_ANNOTATION_NODES:
                return False
            pending.append((child, depth + 1))
    return True


def _models(context: PythonFileContext, provenance: ResourceProvenance) -> dict[ast.ClassDef, _Model]:
    result: dict[ast.ClassDef, _Model] = {}
    for node in direct_models(context):
        if not _stable_class(node, context, provenance) or not _passive_configuration(node, context):
            continue
        fields = _model_fields(node, context)
        if fields is not None:
            result[node] = _Model(node, fields)
    return result


def _model_fields(node: ast.ClassDef, context: PythonFileContext) -> dict[str, _Field] | None:
    unique = unique_members(node)
    if unique & (_MODEL_APIS | {"model_copy", "__copy__", "__deepcopy__"}):
        return None
    fields: dict[str, _Field] = {}
    for member in node.body:
        if not isinstance(member, ast.AnnAssign) or not isinstance(member.target, ast.Name):
            continue
        if member.target.id not in unique or not _safe_annotation(member.annotation, context):
            return None
        if member.target.id.startswith("_") or _typing_wrapper(member.annotation, "ClassVar", context):
            continue
        if member.target.id != "model_config":
            fields[member.target.id] = _Field(member.annotation, _required(member, context))
    return fields


def _stable_class(node: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    if node.name in provenance.mutated or node.name in provenance.external_bindings:
        return False
    return all(
        _safe_class_use(read, context)
        for read in provenance.reads.get(node.name, ())
        if provenance.binding(read.id, read) is node
    )


def _safe_class_use(read: ast.Name, context: PythonFileContext) -> bool:
    parent = context.parents.get(read)
    if isinstance(parent, ast.Call) and parent.func is read:
        return True
    if isinstance(parent, (ast.arg, ast.AnnAssign)) and parent.annotation is read:
        return True
    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)) and parent.returns is read:
        return True
    if isinstance(parent, ast.Attribute) and parent.value is read and parent.attr in _MODEL_APIS:
        owner = context.parents.get(parent)
        return isinstance(owner, ast.Call) and owner.func is parent
    return False


def _passive_configuration(node: ast.ClassDef, context: PythonFileContext) -> bool:
    for member in node.body:
        if not isinstance(member, (ast.Assign, ast.AnnAssign)):
            continue
        targets = member.targets if isinstance(member, ast.Assign) else [member.target]
        if not any(isinstance(target, ast.Name) and target.id == "model_config" for target in targets):
            continue
        options = _configuration_options(member.value, context)
        if options is None or not all(starmap(_passive_option, options)):
            return False
    return all(_safe_field_call(call, context) for call in ast.walk(node) if isinstance(call, ast.Call))


def _configuration_options(
    value: ast.expr | None, context: PythonFileContext
) -> list[tuple[str | None, ast.expr]] | None:
    if isinstance(value, ast.Dict):
        options: list[tuple[str | None, ast.expr]] = [
            (key.value, item)
            for key, item in zip(value.keys, value.values, strict=True)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        ]
        return options if len(options) == len(value.keys) else None
    if (
        isinstance(value, ast.Call)
        and not value.args
        and context.imports.resolves(
            value.func, sources=frozenset({"pydantic", "pydantic.config"}), symbol="ConfigDict"
        )
    ):
        return [(keyword.arg, keyword.value) for keyword in value.keywords]
    return None


def _passive_option(name: str | None, item: ast.expr) -> bool:
    return isinstance(item, ast.Constant) and (
        (name in _PASSIVE_CONFIG and type(item.value) is bool)
        or (name == "extra" and item.value in {"allow", "forbid", "ignore"})
    )


def _safe_field_call(call: ast.Call, context: PythonFileContext) -> bool:
    if context.imports.resolves(call.func, sources=frozenset({"pydantic", "pydantic.config"}), symbol="ConfigDict"):
        return True
    return context.imports.resolves(call.func, sources=FIELD_SOURCES, symbol="Field") and not any(
        keyword.arg in _ALIASES or keyword.arg is None for keyword in call.keywords
    )


def _safe_annotation(annotation: ast.expr, context: PythonFileContext) -> bool:
    if isinstance(annotation, ast.Constant):
        return annotation.value is None or annotation.value is Ellipsis
    if isinstance(annotation, ast.Name):
        return annotation.id in _BUILTINS and context.imports.builtin_is_unshadowed(annotation.id)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _safe_annotation(annotation.left, context) and _safe_annotation(annotation.right, context)
    if not isinstance(annotation, ast.Subscript):
        return False
    return _safe_subscription(annotation, context)


def _safe_subscription(annotation: ast.Subscript, context: PythonFileContext) -> bool:
    members = _members(annotation.slice)
    wrapper = context.imports.resolved_symbol(annotation.value, sources=TYPING_SOURCES)
    if wrapper == "Literal":
        return all(
            isinstance(member, ast.Constant) and isinstance(member.value, (str, int, bool, bytes, type(None)))
            for member in members
        )
    if wrapper == "Annotated":
        return (
            bool(members)
            and _safe_annotation(members[0], context)
            and all(isinstance(member, ast.Call) and _safe_field_call(member, context) for member in members[1:])
        )
    if (
        isinstance(annotation.value, ast.Name)
        and annotation.value.id in _GENERICS
        and context.imports.builtin_is_unshadowed(annotation.value.id)
    ):
        return all(_safe_annotation(member, context) for member in members)
    return wrapper in {"Optional", "Union", "ClassVar"} and all(_safe_annotation(member, context) for member in members)


def _members(node: ast.expr) -> list[ast.expr]:
    return node.elts if isinstance(node, ast.Tuple) else [node]


def _typing_wrapper(node: ast.expr, wrapper: str, context: PythonFileContext) -> bool:
    return isinstance(node, ast.Subscript) and context.imports.resolves(
        node.value, sources=TYPING_SOURCES, symbol=wrapper
    )


def _required(field: ast.AnnAssign, context: PythonFileContext) -> bool:
    calls = _annotated_fields(field.annotation, context)
    bare_default = field.value
    if isinstance(field.value, ast.Call) and context.imports.resolves(
        field.value.func, sources=FIELD_SOURCES, symbol="Field"
    ):
        calls.append(field.value)
        bare_default = None
    default_present = False
    factory_present = False
    for call in calls:
        defaults = [*call.args, *(keyword.value for keyword in call.keywords if keyword.arg == "default")]
        if any(not _ellipsis(value) for value in defaults):
            default_present = True
        for keyword in call.keywords:
            if keyword.arg == "default_factory":
                factory_present = not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
    if bare_default is not None:
        default_present = not _ellipsis(bare_default)
    return not default_present and not factory_present


def _annotated_fields(annotation: ast.expr, context: PythonFileContext) -> list[ast.Call]:
    if not _typing_wrapper(annotation, "Annotated", context) or not isinstance(annotation, ast.Subscript):
        return []
    members = _members(annotation.slice)
    if not members:
        return []
    return [*_annotated_fields(members[0], context), *(item for item in members[1:] if isinstance(item, ast.Call))]


def _ellipsis(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is Ellipsis


def _bypass_target(
    call: ast.Call, models: dict[ast.ClassDef, _Model], provenance: ResourceProvenance
) -> tuple[_Model, dict[str, ast.expr], bool] | None:
    if not isinstance(call.func, ast.Attribute) or call.args:
        return None
    if call.func.attr == "model_construct":
        return _construction_target(call, call.func.value, models, provenance)
    if call.func.attr != "model_copy":
        return None
    return _copy_target(call, call.func.value, models, provenance)


def _construction_target(
    call: ast.Call, receiver: ast.expr, models: dict[ast.ClassDef, _Model], provenance: ResourceProvenance
) -> tuple[_Model, dict[str, ast.expr], bool] | None:
    model = _named_model(receiver, models, provenance)
    if model is None or any(keyword.arg is None for keyword in call.keywords):
        return None
    values = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg is not None}
    return model, values, True


def _copy_target(
    call: ast.Call, receiver: ast.expr, models: dict[ast.ClassDef, _Model], provenance: ResourceProvenance
) -> tuple[_Model, dict[str, ast.expr], bool] | None:
    constructor = _copy_constructor(receiver, call, provenance)
    if not isinstance(constructor, ast.Call):
        return None
    model = _named_model(constructor.func, models, provenance)
    if model is None or any(keyword.arg not in {"update", "deep"} for keyword in call.keywords):
        return None
    updates = [keyword.value for keyword in call.keywords if keyword.arg == "update"]
    if len(updates) != 1 or not isinstance(updates[0], ast.Dict):
        return None
    values = _dict_values(updates[0])
    return None if values is None else (model, values, False)


def _copy_constructor(receiver: ast.expr, call: ast.Call, provenance: ResourceProvenance) -> ast.Call | None:
    if isinstance(receiver, ast.Name):
        return provenance.constructor(receiver, call) if provenance.unescaped(receiver, call) else None
    return receiver if isinstance(receiver, ast.Call) else None


def _named_model(
    expression: ast.expr, models: dict[ast.ClassDef, _Model], provenance: ResourceProvenance
) -> _Model | None:
    if not isinstance(expression, ast.Name):
        return None
    binding = provenance.binding(expression.id, expression)
    return models.get(binding) if isinstance(binding, ast.ClassDef) else None


def _dict_values(node: ast.Dict) -> dict[str, ast.expr] | None:
    result: dict[str, ast.expr] = {}
    for key, value in zip(node.keys, node.values, strict=True):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str) or key.value in result:
            return None
        result[key.value] = value
    return result


def _invalid_values(
    call: ast.Call, model: _Model, values: dict[str, ast.expr], *, construction: bool, context: PythonFileContext
) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    missing = [name for name, field in model.fields.items() if field.required and name not in values]
    if construction and missing:
        findings.append(
            _diagnostic(
                call,
                context,
                f"`{model.node.name}.model_construct` omits required fields {', '.join(f'`{name}`' for name in missing)}; construction bypasses required-field validation and leaves those attributes unset.",
            )
        )
    for name, value in values.items():
        field = model.fields.get(name)
        if field is None:
            continue
        finding = _invalid_field_value(model, name, field.annotation, value, context)
        if finding is not None:
            findings.append(finding)
    return findings


def _invalid_field_value(
    model: _Model, name: str, annotation: ast.expr, value: ast.expr, context: PythonFileContext
) -> Diagnostic | None:
    literal = _literal_value(value)
    if literal is _UNKNOWN_LITERAL:
        return None
    if not _bounded_literal_text(annotation, value):
        return None
    domain = _string_domain(annotation, context)
    if domain is not None and not any(literal == member for member in domain):
        message = f"Unchecked `{name}` is outside `{model.node.name}`'s declared string Literal domain; validate a complete input mapping or supply an admitted value."
    elif literal is None and _excludes_none(annotation, context):
        message = f"Unchecked `{name}=None` contradicts `{model.node.name}`'s non-null field annotation; validate a complete input mapping or supply a non-null value."
    elif _literal_incompatible(annotation, literal, context):
        message = f"Unchecked `{name}` stores a literal incompatible with `{model.node.name}`'s field type; validate a complete input mapping or supply a value satisfying the stored contract."
    else:
        return None
    return _diagnostic(value, context, message)


def _bounded_literal_text(annotation: ast.expr, value: ast.expr) -> bool:
    length = 0
    for expression in (annotation, value):
        for node in ast.walk(expression):
            if isinstance(node, ast.Constant) and isinstance(node.value, str | bytes):
                length += len(node.value)
                if length > _MAX_LITERAL_TEXT:
                    return False
    return True


def _literal_value(node: ast.expr) -> object:
    if not _bounded_annotation(node) or any(isinstance(member, ast.Call) for member in ast.walk(node)):
        return _UNKNOWN_LITERAL
    try:
        return ast.literal_eval(node)  # pyright: ignore[reportAny] -- bounded stdlib literal parser boundary exports object.
    except ValueError, TypeError, SyntaxError, RecursionError:
        return _UNKNOWN_LITERAL


def _literal_incompatible(
    annotation: ast.expr,
    value: object,  # sarj-noqa: SARJ528 -- recursive annotation checks consume native literal values including bytes, complex numbers and sets.
    context: PythonFileContext,
) -> bool:
    if isinstance(annotation, ast.Constant):
        return annotation.value is None and value is not None
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _literal_incompatible(annotation.left, value, context) and _literal_incompatible(
            annotation.right, value, context
        )
    if isinstance(annotation, ast.Name) and annotation.id in _BUILTINS:
        return _builtin_incompatible(annotation.id, value)
    if not isinstance(annotation, ast.Subscript):
        return False
    return _subscript_incompatible(annotation, value, context)


def _subscript_incompatible(
    annotation: ast.Subscript,
    value: object,  # sarj-noqa: SARJ528 -- annotation wrappers recursively refine the unchecked native literal decoder result.
    context: PythonFileContext,
) -> bool:
    members = _members(annotation.slice)
    if _typing_wrapper(annotation, "Annotated", context):
        return bool(members) and _literal_incompatible(members[0], value, context)
    if _typing_wrapper(annotation, "Optional", context):
        return value is not None and _literal_incompatible(annotation.slice, value, context)
    if _typing_wrapper(annotation, "Union", context):
        return bool(members) and all(_literal_incompatible(member, value, context) for member in members)
    domain = _string_domain(annotation, context)
    if domain is not None:
        return not any(value == member for member in domain)
    if isinstance(annotation.value, ast.Name) and annotation.value.id in _GENERICS:
        return _container_incompatible(annotation.value.id, members, value, context)
    return False


def _builtin_incompatible(kind: str, value: object) -> bool:
    match kind:
        case "str":
            return not isinstance(value, str)
        case "bytes":
            return not isinstance(value, bytes)
        case "bool":
            return not isinstance(value, bool)
        case "int":
            return not isinstance(value, int)
        case "float":
            return not isinstance(value, int | float)
        case "complex":
            return not isinstance(value, int | float | complex)
        case "list":
            return not isinstance(value, list)
        case "dict":
            return not isinstance(value, dict)
        case "set":
            return not isinstance(value, set)
        case "frozenset":
            return not isinstance(value, frozenset)
        case "tuple":
            return not isinstance(value, tuple)
        case _:
            return False


def _container_incompatible(
    kind: str,
    members: list[ast.expr],
    value: object,  # sarj-noqa: SARJ528 -- native literal container shape and unchecked members are validated recursively here.
    context: PythonFileContext,
) -> bool:
    if _builtin_incompatible(kind, value):
        return True
    if kind == "dict" and is_object_mapping(value) and len(members) == _PAIR_ARITY:
        return any(
            _literal_incompatible(members[0], key, context) or _literal_incompatible(members[1], item, context)
            for key, item in value.items()
        )
    if _is_literal_items(value):
        if kind == "tuple" and isinstance(value, tuple):
            return _tuple_incompatible(members, value, context)
        if kind in {"list", "set", "frozenset"} and len(members) == 1:
            return any(_literal_incompatible(members[0], item, context) for item in value)
    return False


def _is_literal_items(value: object) -> TypeIs[list[object] | set[object] | frozenset[object] | tuple[object, ...]]:
    return isinstance(value, list | set | frozenset | tuple)


def _tuple_incompatible(
    members: list[ast.expr],
    value: tuple[  # sarj-noqa: SARJ528 -- tuple shape is known; each native literal member still needs its annotation check.
        object, ...
    ],
    context: PythonFileContext,
) -> bool:
    if len(members) == _PAIR_ARITY and _ellipsis(members[1]):
        return any(_literal_incompatible(members[0], item, context) for item in value)
    if any(_ellipsis(member) for member in members):
        return False
    return len(members) != len(value) or any(
        _literal_incompatible(member, item, context) for member, item in zip(members, value, strict=False)
    )


def _string_domain(annotation: ast.expr, context: PythonFileContext) -> frozenset[str | None] | None:
    if isinstance(annotation, ast.Constant) and annotation.value is None:
        return frozenset({None})
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        left = _string_domain(annotation.left, context)
        right = _string_domain(annotation.right, context)
        return None if left is None or right is None else left | right
    if not isinstance(annotation, ast.Subscript):
        return None
    return _subscript_string_domain(annotation, context)


def _subscript_string_domain(annotation: ast.Subscript, context: PythonFileContext) -> frozenset[str | None] | None:
    members = _members(annotation.slice)
    if _typing_wrapper(annotation, "Annotated", context):
        return _string_domain(members[0], context) if members else None
    if _typing_wrapper(annotation, "Optional", context):
        domain = _string_domain(annotation.slice, context)
        return None if domain is None else domain | {None}
    return _literal_string_values(members) if _typing_wrapper(annotation, "Literal", context) else None


def _literal_string_values(members: list[ast.expr]) -> frozenset[str | None] | None:
    if all(
        isinstance(member, ast.Constant) and (isinstance(member.value, str) or member.value is None)
        for member in members
    ):
        return frozenset(
            member.value
            for member in members
            if isinstance(member, ast.Constant) and (isinstance(member.value, str) or member.value is None)
        )
    return None


def _excludes_none(annotation: ast.expr, context: PythonFileContext) -> bool:
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _excludes_none(annotation.left, context) and _excludes_none(annotation.right, context)
    if isinstance(annotation, ast.Name):
        return annotation.id in _BUILTINS and context.imports.builtin_is_unshadowed(annotation.id)
    if not isinstance(annotation, ast.Subscript):
        return False
    if _typing_wrapper(annotation, "Annotated", context):
        members = _members(annotation.slice)
        return bool(members) and _excludes_none(members[0], context)
    if isinstance(annotation.value, ast.Name) and annotation.value.id in _GENERICS:
        return context.imports.builtin_is_unshadowed(annotation.value.id)
    return False


def _diagnostic(node: ast.expr, context: PythonFileContext, message: str) -> Diagnostic:
    return Diagnostic(
        context.path, node.lineno, node.col_offset + 1, NoInvalidPydanticBypass.code, message, severity=Severity.ERROR
    )
