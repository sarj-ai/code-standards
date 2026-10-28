from __future__ import annotations

import ast
from dataclasses import dataclass
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
    is_suppressed,
)
from sarj_python_lint.rules._data_union_discriminator import data_union_diagnostics
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._pydantic_field_contract import (
    DECORATOR_SOURCES,
    FIELD_SOURCES,
    TYPING_SOURCES,
    direct_models,
    unique_members,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_PAIR_ARITY = 2
_BUILTIN_SOURCES = frozenset({"builtins"})
_INHABITED_SCALARS = frozenset({"str", "int", "float", "bool", "bytes", "complex"})
_EMPTY_CONTAINERS = frozenset({"list", "dict", "set", "frozenset", "tuple"})
_MAX_REGIONS = 32
_MAX_CONDITIONS = 128
_MAX_CONDITION_DEPTH = 32
_MAX_VALIDATOR_NODES = 2048
_PASSIVE_FIELD_OPTIONS = frozenset(
    {
        "default",
        "default_factory",
        "alias",
        "validation_alias",
        "serialization_alias",
        "title",
        "description",
        "examples",
        "exclude",
        "repr",
    }
)
_VALIDATION_APIS = frozenset({"model_validate", "model_validate_json", "model_validate_strings", "model_construct"})

type _Tag = str | int | bool | None


@dataclass(frozen=True, slots=True)
class _Requirement:
    guard: ast.If
    tag: str
    value: _Tag
    payload: str


@dataclass(frozen=True, slots=True)
class _Region:
    tags: dict[str, frozenset[_Tag]]
    missing: frozenset[str] = frozenset()
    present: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class _Path:
    statements: list[ast.stmt]
    regions: list[_Region]
    guard: ast.If | None = None


@final
class PreferDiscriminatedModelUnion(Rule):
    id = "prefer-discriminated-model-union"
    code = "SARJ510"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Give data unions explicit Literal discriminators and express tag-dependent payloads as variants.",
        rationale=(
            "An explicit shared tag identifies data variants and supports field-based narrowing. "
            "A nullable field remains statically nullable even when an after validator requires it for a literal "
            "tag. A union of models with distinct Literal tags carries that dependency in the type and supports "
            "safe narrowing without repeating runtime guards."
        ),
        remediation=(
            "Give every data variant a common field with disjoint Literal values. For dataclasses, "
            "field(default=..., init=False) can preserve existing constructor calls; review serialized contracts. "
            "Consider a discriminated union of model variants. Make the payload non-nullable only in variants "
            "proven to reject None, and preserve every other accepted field combination, defaults, aliases and wire shape. "
            "Independent optional fields can remain optional within each variant."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Declared module-level unions of at least two source-visible direct dataclasses, Pydantic BaseModels or TypedDicts require a shared disjoint Literal field. PEP 604, typing Union, Optional, Annotated, forward references and bounded local aliases are supported; a None branch is allowed.",
            "The explicit-tag policy is a modeling preference: nominal variants already support isinstance narrowing. Scalar/container unions, inline annotations, generic or inherited variants, behavior classes, unresolved variants and dynamic or ambiguous namespaces are excluded. Imported tag aliases are not resolved; an explicit literal field paired with an unresolved imported or local class domain abstains, as do opaque explicit Literal domains. Qualified imported domains and unsupported computed aliases remain uncertain rather than proving a missing tag.",
            "String, bytes, integer, Boolean and None tag values are supported. Boolean and integer Literal values retain their distinct static types; use identity checks when equality would conflate their runtime values. A bounded hierarchy of shared literal fields may distinguish nested groups; overlapping tags without a further discriminator still fail. Nested Literal domains and transparent Final, ReadOnly, Annotated and local alias wrappers are supported. TypedDict tags must be required; dataclass ClassVar tags must have a value. Direct import-proven InitVar annotations without defaults are constructor inputs rather than instance tags; quoted, wrapped, locally aliased or defaulted InitVar forms remain uncertain. Import-proven typing final decorators preserve record recognition. Explicit Pydantic callable Discriminators, bounded stable reusable metadata, single-value plain local class namespaces, literal immutable tuple projections and imported pydantic.types constructors are respected; source-proven string field names, including local bindings and concatenation, still need Literal fields. Source-proven string discriminator writes through stable aliases invalidate callable coverage; opaque mutation, helper escapes and excessive alias graphs abstain. Module bindings are independent of unrelated local parameters and their attribute writes; class annotation shadows and global rebinding remain excluded. Other runtime configuration and default correctness remain separate contracts. No automatic field addition is safe for every constructor or serializer.",
            "For nullable-field dependencies, only stable direct module-level import-proven Pydantic BaseModel subclasses with pure direct after model validators are inspected.",
            "Bounded paths may contain finite tag comparisons or literal-container membership, None identity tests, Boolean combinations, nested guards and returns of the same instance. Every rejection region must prove one tag-dependent nullable-field requirement; joint missing-field or independent-tag-axis conditions abstain.",
            "Tags must use imported Literal domains, optionally composed through direct unions, with at least two distinct homogeneous string, integer or Boolean values, optionally including an explicit None state. Mixed primitive families, bool/int equality collisions, open or computed tags abstain. Payloads must explicitly include None in a union, imported Union or Optional.",
            "Every non-null payload member must have a source-proven inhabited built-in scalar or container type; opaque aliases, custom types and None-only or bottom-type unions are excluded.",
            "A field required by every admitted tag value is a common field constraint rather than evidence for a discriminated union and is excluded.",
            "Unsupported Field validation constraints cannot prove non-null payload inhabitance; defaults, aliases and passive metadata remain eligible. Literal exception messages or local assignments of those messages are supported with import-proven builtin rejection types.",
            "Opaque helpers, effectful validators, inherited models, model mutation or escape, ambiguous namespaces, tests and generated files are excluded. The analyzer bounds validator nodes, Boolean depth, paths and rejection regions; complex forms abstain.",
            "This error requires explicit data modeling; it does not require absent payloads in other variants or change external compatibility automatically.",
        ),
        examples=(
            RuleExample(
                example_id="literal-tag-dependent-payload",
                title="An after validator encodes a field dependency that its type cannot express",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Literal, Self\nfrom pydantic import BaseModel, model_validator\n"
                        "class Delivery(BaseModel):\n    kind: Literal['email', 'pickup']\n    address: str | None = None\n"
                        "    @model_validator(mode='after')\n    def validate_address(self) -> Self:\n"
                        "        if self.kind == 'email' and self.address is None:\n"
                        "            raise ValueError('Email requires an address')\n        return self\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="variants-preserve-other-accepted-states",
                title="Only the email variant requires an address; pickup preserves its optional address",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Annotated, Literal\nfrom pydantic import BaseModel, Field\n"
                        "class EmailDelivery(BaseModel):\n    kind: Literal['email']\n    address: str\n"
                        "class PickupDelivery(BaseModel):\n    kind: Literal['pickup']\n    address: str | None = None\n"
                        "type Delivery = Annotated[EmailDelivery | PickupDelivery, Field(discriminator='kind')]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="untagged-data-variants",
                scenario="explicit-data-discriminator",
                title="Data variants lack a common explicit tag",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/access.py",
                        "from dataclasses import dataclass\n"
                        "@dataclass(frozen=True, slots=True)\nclass TeamAccess:\n    team_id: str\n"
                        "@dataclass(frozen=True, slots=True)\nclass GlobalAccess:\n    group: str\n"
                        "type Access = TeamAccess | GlobalAccess\n",
                    ),
                ),
                focus_path=PurePosixPath("app/access.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="literal-tags-preserve-constructor-calls",
                scenario="explicit-data-discriminator",
                title="Explicit tags preserve positional constructor calls with init=False",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/access.py",
                        "from dataclasses import dataclass, field\nfrom typing import Literal\n"
                        "@dataclass(frozen=True, slots=True)\nclass TeamAccess:\n"
                        "    scope: Literal['team'] = field(default='team', init=False)\n    team_id: str\n"
                        "@dataclass(frozen=True, slots=True)\nclass GlobalAccess:\n"
                        "    scope: Literal['global'] = field(default='global', init=False)\n    group: str\n"
                        "type Access = TeamAccess | GlobalAccess\n",
                    ),
                ),
                focus_path=PurePosixPath("app/access.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if is_test_path(context.path):
            return []
        diagnostics = data_union_diagnostics(context, self.code)
        if "None" not in context.symbol_source or "model_validator" not in context.symbol_source:
            return diagnostics
        provenance = context.static_resource_provenance
        for model in direct_models(context, methods=True):
            if not _stable_model(model, context, provenance):
                continue
            requirements = _model_requirements(model, context)
            if not requirements:
                continue
            first = requirements[0]
            if is_suppressed(context.source_lines, first.guard.lineno, self.code):
                continue
            diagnostics.append(
                Diagnostic(
                    context.path,
                    first.guard.lineno,
                    first.guard.col_offset + 1,
                    self.code,
                    f"`{model.name}` requires nullable `{first.payload}` when `{first.tag}` is {first.value!r}. "
                    "Consider a discriminated model union with that payload non-nullable in the matching variant; "
                    "preserve every other accepted combination and the external contract.",
                    severity=Severity.ERROR,
                )
            )
        return diagnostics


def _model_requirements(model: ast.ClassDef, context: PythonFileContext) -> list[_Requirement]:
    methods = [member for member in model.body if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not methods or any(not isinstance(method, ast.FunctionDef) for method in methods):
        return []
    unique = unique_members(model)
    if any(method.name not in unique for method in methods):
        return []
    fields = {
        member.target.id: member.annotation
        for member in model.body
        if isinstance(member, ast.AnnAssign)
        and isinstance(member.target, ast.Name)
        and member.target.id in unique
        and not member.target.id.startswith("_")
        and _passive_field(member, context)
    }
    requirements: list[_Requirement] = []
    for validator in methods:
        if not isinstance(validator, ast.FunctionDef):
            return []
        instance = _validator_instance(validator, context)
        if instance is None:
            return []
        admitted = _validator_requirements(validator, fields, instance, context)
        if admitted is None:
            return []
        requirements.extend(admitted)
    return _variant_specific_requirements(requirements, fields, context)


def _passive_field(member: ast.AnnAssign, context: PythonFileContext) -> bool:
    value = member.value
    if not isinstance(value, ast.Call):
        return True
    return (
        context.imports.resolves(value.func, sources=FIELD_SOURCES, symbol="Field")
        and len(value.args) <= 1
        and all(keyword.arg in _PASSIVE_FIELD_OPTIONS for keyword in value.keywords)
    )


def _stable_model(model: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    if (
        model.name in provenance.mutated
        or model.name in provenance.external_bindings
        or len(provenance.bindings[context.tree].get(model.name, ())) != 1
    ):
        return False
    return all(
        _stable_model_read(read, context)
        for read in provenance.reads.get(model.name, ())
        if provenance.binding(read.id, read) is model
    )


def _stable_model_read(read: ast.Name, context: PythonFileContext) -> bool:
    parent = context.parents.get(read)
    if isinstance(parent, ast.Call) and parent.func is read:
        return True
    if isinstance(parent, ast.Attribute) and parent.value is read and parent.attr in _VALIDATION_APIS:
        call = context.parents.get(parent)
        return isinstance(call, ast.Call) and call.func is parent
    node: ast.AST = read
    while isinstance(parent, (ast.Subscript, ast.BinOp, ast.Tuple)):
        node = parent
        parent = context.parents.get(parent)
    match parent:
        case ast.arg() | ast.AnnAssign():
            return parent.annotation is node
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            return parent.returns is node
        case _:
            pass
    return isinstance(parent, ast.TypeAlias) and parent.value is node


def _variant_specific_requirements(
    requirements: list[_Requirement], fields: dict[str, ast.expr], context: PythonFileContext
) -> list[_Requirement]:
    required_tags: dict[tuple[str, str], set[_Tag]] = {}
    for requirement in requirements:
        required_tags.setdefault((requirement.tag, requirement.payload), set()).add(requirement.value)
    return [
        requirement
        for requirement in requirements
        if required_tags[requirement.tag, requirement.payload] < _literal_tags(fields[requirement.tag], context)
    ]


def _validator_instance(validator: ast.FunctionDef, context: PythonFileContext) -> str | None:
    arguments = validator.args
    positional = [*arguments.posonlyargs, *arguments.args]
    if len(positional) != 1 or len(validator.decorator_list) != 1 or positional[0].arg == "cls":
        return None
    if arguments.vararg is not None or arguments.kwarg is not None or arguments.kwonlyargs or arguments.defaults:
        return None
    decorator = validator.decorator_list[0]
    match decorator:
        case ast.Call(args=[], keywords=[ast.keyword(arg="mode", value=ast.Constant(value="after"))]):
            if context.imports.resolves(decorator.func, sources=DECORATOR_SOURCES, symbol="model_validator"):
                return positional[0].arg
        case _:
            pass
    return None


def _validator_requirements(
    validator: ast.FunctionDef, fields: dict[str, ast.expr], instance: str, context: PythonFileContext
) -> list[_Requirement] | None:
    if any(index >= _MAX_VALIDATOR_NODES for index, _node in enumerate(ast.walk(validator))):
        return None
    body = validator.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    pending = [_Path(body, [_Region({})])]
    requirements: list[_Requirement] = []
    visited = 0
    while pending:
        path = pending.pop()
        visited += 1
        if visited > _MAX_CONDITIONS or len(pending) > _MAX_REGIONS or not path.statements:
            return None
        result = _advance_path(path, fields, instance, context)
        if result is None:
            return None
        paths, found = result
        pending.extend(paths)
        requirements.extend(found)
    return requirements


def _advance_path(
    path: _Path, fields: dict[str, ast.expr], instance: str, context: PythonFileContext
) -> tuple[list[_Path], list[_Requirement]] | None:
    first, *remaining = path.statements
    if isinstance(first, ast.Return) and _is_instance(first.value, instance):
        return [], []
    rejection = path.statements[:2] if isinstance(first, ast.Assign) else [first]
    if _rejection_body(rejection, context):
        found = _region_requirements(path.regions, path.guard)
        return ([], found) if found is not None else None
    if not isinstance(first, ast.If):
        return None
    if first.orelse or not _rejection_body(first.body, context):
        branches = _branch_paths(first, remaining, path, fields, instance, context=context)
        return (branches, []) if branches is not None else None
    condition = _condition_regions(first.test, fields, instance, context, truth=True)
    combined = _combine_regions(path.regions, condition) if condition is not None else None
    found = _region_requirements(combined, path.guard or first) if combined is not None else None
    return ([_Path(remaining, path.regions, path.guard)], found) if found is not None else None


def _branch_paths(
    guard: ast.If,
    remaining: list[ast.stmt],
    path: _Path,
    fields: dict[str, ast.expr],
    instance: str,
    *,
    context: PythonFileContext,
) -> list[_Path] | None:
    pending: list[_Path] = []
    for truth, branch in ((True, guard.body), (False, guard.orelse)):
        condition = _condition_regions(guard.test, fields, instance, context, truth=truth)
        combined = _combine_regions(path.regions, condition) if condition is not None else None
        if combined is None:
            return None
        if combined:
            pending.append(_Path([*branch, *remaining], combined, path.guard or guard))
    return pending


def _region_requirements(regions: list[_Region], guard: ast.If | None) -> list[_Requirement] | None:
    requirements: list[_Requirement] = []
    for region in regions:
        if guard is None or len(region.tags) != 1 or len(region.missing) != 1 or region.present:
            return None
        tag, values = next(iter(region.tags.items()))
        payload = next(iter(region.missing))
        if tag == payload:
            return None
        requirements.extend(_Requirement(guard, tag, value, payload) for value in sorted(values, key=repr))
    return requirements


def _condition_regions(
    node: ast.expr,
    fields: dict[str, ast.expr],
    instance: str,
    context: PythonFileContext,
    *,
    truth: bool,
    depth: int = 0,
) -> list[_Region] | None:
    if depth > _MAX_CONDITION_DEPTH:
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _condition_regions(node.operand, fields, instance, context, truth=not truth, depth=depth + 1)
    if not isinstance(node, ast.BoolOp):
        return _comparison_regions(node, fields, instance, context, truth=truth)
    conjunction = isinstance(node.op, ast.And) is truth
    result: list[_Region] = [_Region({})] if conjunction else []
    if len(node.values) > _MAX_CONDITIONS:
        return None
    for value in node.values:
        members = _condition_regions(value, fields, instance, context, truth=truth, depth=depth + 1)
        if members is None:
            return None
        combined = _combine_regions(result, members) if conjunction else [*result, *members]
        if combined is None or len(combined) > _MAX_REGIONS:
            return None
        result = combined
    return result


def _combine_regions(left: list[_Region], right: list[_Region]) -> list[_Region] | None:
    if len(left) * len(right) > _MAX_REGIONS:
        return None
    combined: list[_Region] = []
    for one in left:
        for other in right:
            tags = dict(one.tags)
            for tag, values in other.tags.items():
                tags[tag] = tags[tag] & values if tag in tags else values
            missing, present = one.missing | other.missing, one.present | other.present
            if all(tags.values()) and missing.isdisjoint(present):
                combined.append(_Region(tags, missing, present))
    return combined


def _comparison_regions(
    node: ast.expr, fields: dict[str, ast.expr], instance: str, context: PythonFileContext, *, truth: bool
) -> list[_Region] | None:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return None
    operator = node.ops[0]
    for attribute, value in ((node.left, node.comparators[0]), (node.comparators[0], node.left)):
        field = _instance_field(attribute, instance)
        if field is None or field not in fields:
            continue
        if _is_none(value) and isinstance(operator, (ast.Is, ast.IsNot)) and _nullable(fields[field], context):
            return [_none_region(field, absent=isinstance(operator, ast.Is) is truth)]
        domain = _literal_tags(fields[field], context)
        selected = _selected_tags(value, operator, domain, reversed_operands=attribute is not node.left)
        if selected is not None:
            values = selected if truth else domain - selected
            return [_Region({field: values})] if values else []
    return None


def _none_region(field: str, *, absent: bool) -> _Region:
    return _Region({}, missing=frozenset({field})) if absent else _Region({}, present=frozenset({field}))


def _selected_tags(
    node: ast.expr, operator: ast.cmpop, domain: frozenset[_Tag], *, reversed_operands: bool
) -> frozenset[_Tag] | None:
    if not domain:
        return None
    if isinstance(operator, (ast.In, ast.NotIn)) and not reversed_operands:
        if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return None
        literals = [_tag_value(member) for member in node.elts]
    elif isinstance(operator, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)):
        literal = _tag_value(node)
        if (
            literal
            and isinstance(operator, (ast.Is, ast.IsNot))
            and not (literal[0] is None or isinstance(literal[0], bool))
        ):
            return None
        literals = [literal]
    else:
        return None
    if any(not literal for literal in literals):
        return None
    selected = frozenset(literal[0] for literal in literals)
    if any(not _tag_in_domain(value, domain) for value in selected):
        return None
    return domain - selected if isinstance(operator, (ast.NotEq, ast.NotIn, ast.IsNot)) else selected


def _tag_in_domain(value: _Tag, domain: frozenset[_Tag]) -> bool:
    return any(value == member and type(value) is type(member) for member in domain)


def _instance_field(node: ast.expr, instance: str) -> str | None:
    return node.attr if isinstance(node, ast.Attribute) and _is_instance(node.value, instance) else None


def _is_instance(node: ast.expr | None, instance: str) -> bool:
    return isinstance(node, ast.Name) and node.id == instance


def _literal_tags(annotation: ast.expr, context: PythonFileContext) -> frozenset[_Tag]:
    values: list[ast.expr] = []
    for member in _union_members(annotation, context):
        if not isinstance(member, ast.Subscript) or not context.imports.resolves(
            member.value, sources=TYPING_SOURCES, symbol="Literal"
        ):
            return frozenset()
        values.extend(member.slice.elts if isinstance(member.slice, ast.Tuple) else [member.slice])
        if len(values) > _MAX_CONDITIONS:
            return frozenset()
    literals = [_tag_value(value) for value in values]
    tags = frozenset(literal[0] for literal in literals if literal)
    return (
        tags
        if len(tags) > 1 and len(tags) == len(values) and len({type(value) for value in tags if value is not None}) <= 1
        else frozenset()
    )


def _tag_value(node: ast.expr) -> tuple[_Tag, ...]:
    if isinstance(node, ast.Constant) and (node.value is None or isinstance(node.value, (str, int))):
        return (node.value,)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) is int
    ):
        return (-node.operand.value,)
    return ()


def _nullable(annotation: ast.expr, context: PythonFileContext) -> bool:
    members = _union_members(annotation, context)
    non_null = [member for member in members if not _is_none(member)]
    return (
        len(non_null) < len(members)
        and bool(non_null)
        and all(_non_none_witness(member, context) for member in non_null)
    )


def _union_members(annotation: ast.expr, context: PythonFileContext) -> list[ast.expr]:
    members: list[ast.expr] = []
    pending = [annotation]
    while pending:
        member = pending.pop()
        if isinstance(member, ast.Subscript) and context.imports.resolves(
            member.value, sources=TYPING_SOURCES, symbol="Optional"
        ):
            if isinstance(member.slice, ast.Tuple):
                members.append(member)
            else:
                members.append(ast.Constant(value=None))
                pending.append(member.slice)
        elif isinstance(member, ast.BinOp) and isinstance(member.op, ast.BitOr):
            pending.extend((member.right, member.left))
        elif isinstance(member, ast.Subscript) and context.imports.resolves(
            member.value, sources=TYPING_SOURCES, symbol="Union"
        ):
            pending.extend(member.slice.elts if isinstance(member.slice, ast.Tuple) else [member.slice])
        else:
            members.append(member)
    return members


def _non_none_witness(annotation: ast.expr, context: PythonFileContext, *, depth: int = 0) -> bool:
    if depth > _MAX_CONDITION_DEPTH:
        return False
    if isinstance(annotation, ast.Subscript):
        builtin = _builtin_type(annotation.value, context)
        if builtin not in _EMPTY_CONTAINERS:
            return False
        if builtin != "tuple":
            return True
        arguments = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return (
            not arguments
            or (
                len(arguments) == _PAIR_ARITY
                and isinstance(arguments[-1], ast.Constant)
                and arguments[-1].value is Ellipsis
            )
            or all(
                _is_none(argument) or _non_none_witness(argument, context, depth=depth + 1) for argument in arguments
            )
        )
    return _builtin_type(annotation, context) in _INHABITED_SCALARS | _EMPTY_CONTAINERS


def _builtin_type(annotation: ast.expr, context: PythonFileContext) -> str | None:
    if isinstance(annotation, ast.Name) and context.imports.builtin_is_unshadowed(annotation.id):
        return annotation.id
    return context.imports.resolved_symbol(annotation, sources=_BUILTIN_SOURCES)


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _rejection_body(body: list[ast.stmt], context: PythonFileContext) -> bool:
    if len(body) == 1:
        return _rejection(body[0], context)
    match body:
        case [ast.Assign(targets=[ast.Name(id=message)], value=ast.Constant(value=str())), rejection]:
            return _rejection(rejection, context, message=message)
        case _:
            return False


def _rejection(statement: ast.stmt, context: PythonFileContext, *, message: str | None = None) -> bool:
    return (
        isinstance(statement, ast.Raise)
        and statement.cause is None
        and isinstance(statement.exc, ast.Call)
        and _builtin_type(statement.exc.func, context) in {"ValueError", "AssertionError"}
        and not statement.exc.keywords
        and all(
            isinstance(argument, ast.Constant) or (message is not None and _is_instance(argument, message))
            for argument in statement.exc.args
        )
    )
