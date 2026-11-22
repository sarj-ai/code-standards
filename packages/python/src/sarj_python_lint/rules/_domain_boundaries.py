from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sarj_python_lint.rules._annotation_origins import AnnotationOrigins, ResolvedAnnotation


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MAX_ALIAS_DEPTH = 32
_NEWTYPE_ARGUMENTS = 2
_TYPING = frozenset({"typing", "typing_extensions"})
_PRIMITIVES = frozenset({"str", "int", "float", "bool", "bytes"})
_ENUMS = frozenset({"enum.Enum", "enum.StrEnum", "enum.IntEnum"})
_WRAPPERS = frozenset(f"{module}.{name}" for module in _TYPING for name in ("Optional", "Annotated"))
_LITERALS = frozenset(f"{module}.Literal" for module in _TYPING)
_NEW_TYPES = frozenset(f"{module}.NewType" for module in _TYPING)
type Function = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True, slots=True)
class DomainType:
    name: str
    carrier: str
    declaration: ast.AST


class DomainBoundaries:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.origins = AnnotationOrigins(context)
        self.provenance = self.origins.provenance
        self.arguments = {
            argument: function
            for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef)
            for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        }
        self.required: dict[ast.arg, set[DomainType]] = {}
        if any(marker in context.symbol_source for marker in ("Literal", "NewType", "Enum", "BaseModel", "RootModel")):
            self._collect_relations()

    def primitive(self, annotation: ast.expr | None, *, depth: int = 0) -> str | None:
        member = self._annotation_member(annotation)
        if member is None or depth >= _MAX_ALIAS_DEPTH:
            return None
        qualified = self.origins.qualified(member.expression, member.at)
        for name in _PRIMITIVES:
            if self.origins.builtin(member.expression, name, member.at) or qualified == f"builtins.{name}":
                return name
        if not isinstance(member.expression, ast.Name):
            return None
        value = self._assignment_value(self.origins.binding(member.expression.id, member.at))
        return self.primitive(value, depth=depth + 1) if value is not None else None

    def domain(self, annotation: ast.expr | None, *, depth: int = 0) -> DomainType | None:
        member = self._annotation_member(annotation)
        if member is None or depth >= _MAX_ALIAS_DEPTH or not isinstance(member.expression, ast.Name):
            return None
        if self.origins.shadowed(member.expression.id, member.at):
            return None
        binding = self.origins.binding(member.expression.id, member.at)
        if isinstance(binding, ast.ClassDef):
            carrier = self._enum_carrier(binding)
            return DomainType(binding.name, carrier, binding) if carrier is not None else None
        value = self._assignment_value(binding)
        if value is None or not isinstance(binding, ast.Name):
            return None
        match value:
            case ast.Subscript() if self.origins.qualified(value.value, value) in _LITERALS:
                carrier = _literal_carrier(value)
            case ast.Call() if self.origins.qualified(value.func, value) in _NEW_TYPES:
                carrier = self._newtype_carrier(value, binding.id)
            case _:
                return self.domain(value, depth=depth + 1)
        return DomainType(binding.id, carrier, binding) if carrier is not None else None

    def expression_domain(self, expression: ast.expr) -> DomainType | None:
        return self.domain(self._value_annotation(expression))

    def has_domain_guard(self, expression: ast.expr) -> bool:
        return any(
            self.expression_domain(node) is not None
            or (isinstance(node, ast.Attribute) and self._validated_attribute(node))
            for node in ast.walk(expression)
            if isinstance(node, ast.Name | ast.Attribute)
        )

    def _annotation_member(self, annotation: ast.expr | None) -> ResolvedAnnotation | None:
        if annotation is None:
            return None
        current = annotation
        for _ in range(_MAX_ALIAS_DEPTH):
            parsed = self.context.annotation_semantics.parse(current)
            match parsed:
                case (
                    ast.BinOp(left=ast.Constant(value=None), op=ast.BitOr(), right=other)
                    | ast.BinOp(left=other, op=ast.BitOr(), right=ast.Constant(value=None))
                ):
                    current = other
                case ast.Subscript(value=wrapper, slice=inner) if (
                    self.origins.qualified(wrapper, annotation) in _WRAPPERS
                ):
                    if isinstance(inner, ast.Tuple):
                        if not inner.elts:
                            return None
                        current = inner.elts[0]
                    else:
                        current = inner
                case None:
                    return None
                case _:
                    return ResolvedAnnotation(parsed, annotation)
        return None

    def _assignment_value(self, binding: ast.AST | None) -> ast.expr | None:
        if not isinstance(binding, ast.Name):
            return None
        parent = self.context.parents.get(binding)
        match parent:
            case ast.Assign(targets=[target], value=value) if target is binding:
                return value
            case ast.AnnAssign(value=value) | ast.TypeAlias(value=value, type_params=[]):
                return value
            case _:
                return None

    def _enum_carrier(self, declaration: ast.ClassDef) -> str | None:
        if not any(self.origins.qualified(base, declaration) in _ENUMS for base in declaration.bases):
            return None
        members = [
            statement.value
            for statement in declaration.body
            if isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and not statement.targets[0].id.startswith("_")
        ]
        return _constant_carrier(members)

    def _newtype_carrier(self, call: ast.Call, name: str) -> str | None:
        if len(call.args) != _NEWTYPE_ARGUMENTS or call.keywords:
            return None
        if not isinstance(call.args[0], ast.Constant) or call.args[0].value != name:
            return None
        return self.primitive(call.args[1])

    def _value_annotation(self, value: ast.expr) -> ast.expr | None:
        match value:
            case ast.Name():
                binding = self.origins.binding(value.id, value)
                if isinstance(binding, ast.arg):
                    return binding.annotation
                parent = self.context.parents.get(binding) if binding is not None else None
                return parent.annotation if isinstance(parent, ast.AnnAssign) else None
            case ast.Attribute():
                owner = self._record_class(value.value)
                if owner is None:
                    return None
                fields = [
                    item.annotation
                    for item in owner.body
                    if isinstance(item, ast.AnnAssign)
                    and isinstance(item.target, ast.Name)
                    and item.target.id == value.attr
                ]
                return fields[0] if len(fields) == 1 else None
            case _:
                return None

    def _record_class(self, value: ast.expr) -> ast.ClassDef | None:
        annotation = self._annotation_member(self._value_annotation(value))
        if annotation is None or not isinstance(annotation.expression, ast.Name):
            return None
        owner = self.origins.binding(annotation.expression.id, annotation.at)
        return owner if isinstance(owner, ast.ClassDef) else None

    def _validated_attribute(self, expression: ast.Attribute) -> bool:
        if expression.attr.startswith("_"):
            return False
        owner = self._record_class(expression.value) or self._method_class(expression.value)
        seen: set[ast.ClassDef] = set()
        field_proven: bool | None = None
        while owner is not None and owner not in seen:
            seen.add(owner)
            if field_proven is None:
                field_proven = self._model_field(owner, expression.attr)
            bases = {
                self.origins.qualified(base.value if isinstance(base, ast.Subscript) else base, owner)
                for base in owner.bases
            }
            if not bases.isdisjoint({"pydantic.BaseModel", "pydantic.RootModel", "pydantic.main.BaseModel"}):
                return field_proven or ("pydantic.RootModel" in bases and expression.attr == "root")
            inherited = (
                self.origins.binding(owner.bases[0].id, owner)
                if len(owner.bases) == 1 and isinstance(owner.bases[0], ast.Name)
                else None
            )
            owner = inherited if isinstance(inherited, ast.ClassDef) else None
        return False

    def _model_field(self, owner: ast.ClassDef, name: str) -> bool | None:
        fields = [
            statement.annotation
            for statement in owner.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
        ]
        if not fields:
            return None
        if len(fields) != 1:
            return False
        annotation = self._annotation_member(fields[0])
        if annotation is None:
            return False
        return not (
            isinstance(annotation.expression, ast.Subscript)
            and self.origins.qualified(annotation.expression.value, annotation.at)
            in {"typing.ClassVar", "typing_extensions.ClassVar"}
        )

    def _method_class(self, value: ast.expr) -> ast.ClassDef | None:
        if not isinstance(value, ast.Name):
            return None
        argument = self.origins.binding(value.id, value)
        function = self.arguments.get(argument) if isinstance(argument, ast.arg) else None
        if function is None or function.decorator_list:
            return None
        positional = [*function.args.posonlyargs, *function.args.args]
        if not positional or positional[0] is not argument:
            return None
        owner = self.context.parents.get(function)
        return owner if isinstance(owner, ast.ClassDef) else None

    def _collect_relations(self) -> None:
        if self.provenance.wildcard or self.provenance.dynamic_namespace:
            return
        self._collect_guards()
        edges = self._call_edges()
        pending = list(self.required)
        while pending:
            target = pending.pop()
            for source in edges.get(target, ()):
                domains = {
                    domain for domain in self.required[target] if self.primitive(source.annotation) == domain.carrier
                }
                previous = self.required.get(source, set())
                if domains - previous:
                    self.required[source] = previous | domains
                    pending.append(source)

    def _collect_guards(self) -> None:
        for comparison in self.context.nodes(ast.Compare):
            function = self._function(comparison)
            if function is None or not self._rejecting_guard(comparison):
                continue
            for left, right, operator in zip(
                [comparison.left, *comparison.comparators[:-1]], comparison.comparators, comparison.ops, strict=True
            ):
                if isinstance(operator, ast.Eq | ast.NotEq):
                    self._relate_guard(left, right, function)
                    self._relate_guard(right, left, function)

    def _rejecting_guard(self, comparison: ast.Compare) -> bool:
        guard = self.context.parents.get(comparison)
        while isinstance(guard, ast.BoolOp | ast.UnaryOp):
            guard = self.context.parents.get(guard)
        return isinstance(guard, ast.If) and any(
            isinstance(statement, ast.Raise) for statement in [*guard.body, *guard.orelse]
        )

    def _relate_guard(self, raw: ast.expr, typed: ast.expr, function: Function) -> None:
        if not isinstance(raw, ast.Name) or not isinstance(typed, ast.Attribute) or raw.id != typed.attr:
            return
        argument = self._raw_argument(raw, function)
        domain = self.expression_domain(typed)
        if argument is not None and domain is not None and self.primitive(argument.annotation) == domain.carrier:
            self.required.setdefault(argument, set()).add(domain)

    def _call_edges(self) -> dict[ast.arg, set[ast.arg]]:
        edges: dict[ast.arg, set[ast.arg]] = {}
        for call in self.context.nodes(ast.Call):
            function = self._function(call)
            if function is None:
                continue
            for parameter, expression in self._call_arguments(call).items():
                raw = self._raw_argument(expression, function)
                if raw is None:
                    continue
                domain = self.domain(parameter.annotation)
                if domain is not None and self.primitive(raw.annotation) == domain.carrier:
                    self.required.setdefault(raw, set()).add(domain)
                edges.setdefault(parameter, set()).add(raw)
        return edges

    def _call_arguments(self, call: ast.Call) -> dict[ast.arg, ast.expr]:
        if not isinstance(call.func, ast.Name):
            return {}
        callee = self.origins.binding(call.func.id, call)
        if not isinstance(callee, ast.FunctionDef | ast.AsyncFunctionDef) or callee.decorator_list:
            return {}
        if any(isinstance(argument, ast.Starred) for argument in call.args) or any(
            keyword.arg is None for keyword in call.keywords
        ):
            return {}
        positional = [*callee.args.posonlyargs, *callee.args.args]
        if len(call.args) > len(positional):
            return {}
        result = dict(zip(positional, call.args, strict=False))
        by_name = {parameter.arg: parameter for parameter in [*positional, *callee.args.kwonlyargs]}
        for keyword in call.keywords:
            parameter = by_name.get(keyword.arg) if keyword.arg is not None else None
            if parameter is None or parameter in result or parameter in callee.args.posonlyargs:
                return {}
            result[parameter] = keyword.value
        return result

    def _raw_argument(self, expression: ast.expr, function: Function) -> ast.arg | None:
        if not isinstance(expression, ast.Name) or self.domain(function.returns) is not None:
            return None
        binding = self.origins.binding(expression.id, expression)
        return (
            binding
            if isinstance(binding, ast.arg)
            and self.arguments.get(binding) is function
            and self.primitive(binding.annotation) is not None
            else None
        )

    def _function(self, node: ast.AST) -> Function | None:
        current = self.context.parents.get(node)
        while current is not None:
            match current:
                case ast.FunctionDef() | ast.AsyncFunctionDef():
                    return current
                case ast.Lambda():
                    return None
                case _:
                    current = self.context.parents.get(current)
        return None


def _literal_carrier(value: ast.Subscript) -> str | None:
    members = value.slice.elts if isinstance(value.slice, ast.Tuple) else [value.slice]
    return _constant_carrier(members)


def _constant_carrier(members: list[ast.expr]) -> str | None:
    values = [member.value for member in members if isinstance(member, ast.Constant)]
    if len(values) != len(members) or not values:
        return None
    carriers = {type(value).__name__ for value in values}
    return next(iter(carriers)) if len(carriers) == 1 and carriers <= _PRIMITIVES else None
