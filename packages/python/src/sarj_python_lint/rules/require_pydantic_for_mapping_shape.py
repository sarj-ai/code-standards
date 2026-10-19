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
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_TYPING = frozenset({"typing", "typing_extensions"})
_MAPPINGS = frozenset(
    {
        "typing.Dict",
        "typing.Mapping",
        "typing.MutableMapping",
        "collections.abc.Mapping",
        "collections.abc.MutableMapping",
    }
)
_WRAPPERS = frozenset({"Annotated", "Final", "ClassVar", "Required", "NotRequired", "ReadOnly", "Optional"})
_VALIDATORS = frozenset(
    {
        "pydantic.model_validator",
        "pydantic.field_validator",
        "pydantic.functional_validators.model_validator",
        "pydantic.functional_validators.field_validator",
    }
)
_DISCRIMINATORS = frozenset({"pydantic.Discriminator", "pydantic.types.Discriminator"})
_RAW_METADATA = frozenset(
    {
        "pydantic.BeforeValidator",
        "pydantic.WrapValidator",
        "pydantic.functional_validators.BeforeValidator",
        "pydantic.functional_validators.WrapValidator",
    }
)
_MAX_DEPTH = 32
_MAPPING_ARITY = 2
_BAD = (
    "def verified(raw: dict[str, object]) -> bool:\n"
    "    match raw.get('factor_age'):\n"
    "        case [int(), int(age)] if not isinstance(age, bool):\n"
    "            return age >= 0\n"
    "        case _:\n"
    "            return False\n"
)
_GOOD = (
    "from typing import Annotated\n"
    "from pydantic import BaseModel, Field, StrictInt, ValidationError\n"
    "class FactorClaim(BaseModel):\n"
    "    factor_age: tuple[StrictInt, Annotated[StrictInt, Field(ge=0)]]\n"
    "def verified(raw: object) -> bool:\n"
    "    try:\n"
    "        FactorClaim.model_validate(raw)\n"
    "    except ValidationError:\n"
    "        return False\n"
    "    return True\n"
)


@final
class RequirePydanticForMappingShape(Rule):
    id = "require-pydantic-for-mapping-shape"
    code = "SARJ521"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Declare opaque mapping field shapes in Pydantic instead of probing them by hand.",
        rationale=(
            "Fixed-key reads followed by runtime type, shape, or discriminator checks spread a record contract "
            "across control flow. An object/Any/JsonValue mapping does not declare those field contracts."
        ),
        remediation=(
            "Parse the raw object with a named Pydantic BaseModel or RootModel before using typed attributes. "
            "Prefer strict fields, Field bounds, aliases/AliasPath and discriminated unions to handwritten probes. "
            "For an already trusted internal record, declare a precise named record such as TypedDict instead of "
            "parsing it again. Preserve rejection, defaults and fail-closed behavior explicitly; bool is an int subclass."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks literal-string get/subscript reads on parameters or local names annotated as standard string mappings with object, Any or pydantic.JsonValue values. Stable module type aliases, quoted annotations, wrappers and local value aliases are recognized with bounded resolution.",
            "A field must feed builtin isinstance/type checks, literal comparisons, truth tests or a constrained match pattern. Ordinary reads/forwarding, dynamic keys, homogeneous typed maps, imported application aliases, attributes and ambiguous/rebound assignments are excluded.",
            "Import-resolved Pydantic before/wrap decorator or metadata validators and explicitly registered Discriminator callbacks own raw input normalization and are excluded. Stable callback function aliases and simple local callable instances/bound __call__ methods are recognized. Prefer declarative fields before introducing such callbacks.",
            "Callable classes must be unique undecorated local declarations with no bases, class options, custom constructor or descriptor hooks; only an undecorated __call__ method and inert class data are admitted. Imported, inherited, decorated, rebound and directly mutated callback classes/instances abstain.",
            "Parsing helpers in authored tests are checked, but assert-contained test oracles are excluded. Generated/vendor sources and dynamic namespaces are excluded. This is a warning with no automatic rewrite because coercion, missing-field handling and error policy can differ.",
        ),
        examples=(
            RuleExample(
                example_id="manual-mapping-shape",
                title="A match statement parses an opaque field by hand",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/claims.py", _BAD),),
                focus_path=PurePosixPath("app/claims.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-mapping-shape",
                title="Strict fields and bounds declare the accepted shape",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/claims.py", _GOOD),),
                focus_path=PurePosixPath("app/claims.py"),
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
        ):
            return []
        facts = _Facts(context, context.tree)
        if facts.provenance.wildcard or facts.provenance.dynamic_namespace:
            return []
        sources: set[ast.expr] = set()
        for node in context.nodes(ast.Call, ast.Compare, ast.Match, ast.If, ast.While, ast.IfExp, ast.Assert):
            if facts.raw_boundary(node) or _test_assertion(node, context):
                continue
            sources.update(_probe_sources(node, facts))
        return [
            Diagnostic(
                path=context.path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message="Declare this mapping field's type, shape and discriminator in a named Pydantic model; use a precise named record for already trusted internals instead of probing an opaque get/subscript result.",
            )
            for node in sorted(sources, key=lambda source: (source.lineno, source.col_offset))
            if not is_suppressed(context.source_lines, node.lineno, self.code)
        ]


class _Facts:
    def __init__(self, context: PythonFileContext, tree: ast.Module) -> None:
        self.context = context
        self.provenance = ResourceProvenance(context, require_static_namespace=True)
        self.semantics = AnnotationSemantics.from_tree(tree)
        self.imports = {
            node: ImportIndex.from_tree(ast.Module(body=[node], type_ignores=[]))
            for node in context.nodes(ast.Import, ast.ImportFrom)
        }
        self.callbacks = {
            binding
            for call in context.nodes(ast.Call)
            if (qualified := self.qualified(call.func, call)) in _DISCRIMINATORS | _RAW_METADATA
            if (argument := _callback_argument(call, qualified)) is not None
            if (binding := self.callback(argument)) is not None
        }

    def callback(self, node: ast.expr, *, seen: frozenset[ast.AST] = frozenset()) -> ast.AST | None:
        if len(seen) >= _MAX_DEPTH:
            return None
        if isinstance(node, ast.Call):
            return self.callable_method(node, seen=seen)
        if isinstance(node, ast.Attribute) and node.attr == "__call__":
            return self.callable_method(node.value, seen=seen)
        if not isinstance(node, ast.Name) or node.id in self.provenance.mutated | self.provenance.external_bindings:
            return None
        binding = self.provenance.binding(node.id, node)
        if isinstance(binding, ast.FunctionDef | ast.AsyncFunctionDef):
            return binding if not binding.decorator_list else None
        if not isinstance(binding, ast.Name) or binding in seen:
            return None
        value = self.provenance.assignment_value(binding, node)
        return self.callback(value, seen=seen | {binding}) if value is not None else None

    def callable_method(self, node: ast.expr, *, seen: frozenset[ast.AST]) -> ast.FunctionDef | None:
        if len(seen) >= _MAX_DEPTH:
            return None
        if isinstance(node, ast.Name):
            if node.id in self.provenance.mutated | self.provenance.external_bindings:
                return None
            binding = self.provenance.binding(node.id, node)
            if not isinstance(binding, ast.Name) or binding in seen:
                return None
            value = self.provenance.assignment_value(binding, node)
            return self.callable_method(value, seen=seen | {binding}) if value is not None else None
        if not isinstance(node, ast.Call) or node.args or node.keywords or not isinstance(node.func, ast.Name):
            return None
        if node.func.id in self.provenance.mutated | self.provenance.external_bindings:
            return None
        binding = self.provenance.binding(node.func.id, node)
        if not isinstance(binding, ast.ClassDef) or not isinstance(
            self.context.parents.get(binding), ast.Module | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            return None
        return _plain_callable_method(binding)

    def qualified(self, node: ast.expr, at: ast.AST) -> str | None:
        root = node
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name) or root.id in self.provenance.mutated | self.provenance.external_bindings:
            return None
        binding = self.provenance.binding(root.id, at)
        parent = self.context.parents.get(binding) if binding is not None else None
        index = self.imports.get(parent) if isinstance(parent, ast.Import | ast.ImportFrom) else None
        return index.resolved_qualified_name(node) if index is not None else None

    def builtin(self, node: ast.expr, name: str, at: ast.AST) -> bool:
        return (
            self.provenance.builtin_namespace_untouched
            and isinstance(node, ast.Name)
            and node.id == name
            and self.provenance.binding(name, at) is None
        )

    def annotation(self, node: ast.expr, at: ast.AST, *, mapping: bool, depth: int = 0) -> bool:
        if depth >= _MAX_DEPTH:
            return False
        parsed = self.semantics.parse(node)
        if parsed is None:
            return False
        if isinstance(parsed, ast.Name) and parsed.id in self.semantics.aliases:
            return self.alias_annotation(parsed, at, mapping=mapping, depth=depth)
        if isinstance(parsed, ast.BinOp) and isinstance(parsed.op, ast.BitOr):
            return any(
                self.annotation(member, at, mapping=mapping, depth=depth + 1) for member in (parsed.left, parsed.right)
            )
        qualified = self.qualified(parsed, at)
        if not mapping and (
            self.builtin(parsed, "object", at)
            or qualified in {"typing.Any", "typing_extensions.Any", "pydantic.JsonValue"}
        ):
            return True
        if not isinstance(parsed, ast.Subscript):
            return False
        return self.subscription_annotation(parsed, at, mapping=mapping, depth=depth)

    def alias_annotation(self, node: ast.Name, at: ast.AST, *, mapping: bool, depth: int) -> bool:
        binding = self.provenance.binding(node.id, at)
        if not isinstance(binding, ast.Name) or not isinstance(
            self.context.parents.get(binding), ast.TypeAlias | ast.AnnAssign
        ):
            return False
        value = self.semantics.aliases[node.id]
        return self.annotation(value, value, mapping=mapping, depth=depth + 1)

    def subscription_annotation(self, node: ast.Subscript, at: ast.AST, *, mapping: bool, depth: int) -> bool:
        qualified = self.qualified(node.value, at)
        members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        wrapper = qualified.rpartition(".")[-1] if qualified is not None else None
        if qualified is not None and qualified.partition(".")[0] in _TYPING:
            if wrapper in _WRAPPERS and members:
                return self.annotation(members[0], at, mapping=mapping, depth=depth + 1)
            if wrapper == "Union":
                return any(self.annotation(member, at, mapping=mapping, depth=depth + 1) for member in members)
        if not mapping or len(members) != _MAPPING_ARITY:
            return False
        key, value = members
        return (
            (self.builtin(node.value, "dict", at) or qualified in _MAPPINGS)
            and self.builtin(key, "str", at)
            and self.annotation(value, at, mapping=False, depth=depth + 1)
        )

    def mapping(self, node: ast.expr, *, seen: frozenset[ast.AST] = frozenset()) -> bool:
        if not isinstance(node, ast.Name) or len(seen) >= _MAX_DEPTH or node.id in self.provenance.external_bindings:
            return False
        binding = self.provenance.binding(node.id, node)
        if binding is None or binding in seen:
            return False
        if isinstance(binding, ast.arg):
            return binding.annotation is not None and self.annotation(binding.annotation, binding, mapping=True)
        parent = self.context.parents.get(binding)
        if isinstance(parent, ast.AnnAssign) and parent.annotation is not None:
            return self.annotation(parent.annotation, binding, mapping=True)
        value = self.provenance.assignment_value(binding, node) if isinstance(binding, ast.Name) else None
        return value is not None and self.mapping(value, seen=seen | {binding})

    def field(self, node: ast.expr, *, seen: frozenset[ast.AST] = frozenset()) -> ast.expr | None:
        if len(seen) >= _MAX_DEPTH:
            return None
        if isinstance(node, ast.NamedExpr):
            return self.field(node.value, seen=seen)
        if isinstance(node, ast.Name):
            binding = self.provenance.binding(node.id, node)
            if not isinstance(binding, ast.Name) or binding in seen or node.id in self.provenance.external_bindings:
                return None
            value = self.provenance.assignment_value(binding, node)
            return self.field(value, seen=seen | {binding}) if value is not None else None
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Load)
            and _string(node.slice)
            and self.mapping(node.value)
        ):
            return node
        if (receiver := _get_receiver(node)) is not None and self.mapping(receiver):
            return node
        return None

    def raw_boundary(self, node: ast.AST) -> bool:
        current: ast.AST | None = node
        while current is not None:
            if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef) and self.raw_validator(current):
                return True
            current = self.context.parents.get(current)
        return False

    def raw_validator(self, function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        if function in self.callbacks:
            return True
        for decorator in function.decorator_list:
            if not isinstance(decorator, ast.Call) or self.qualified(decorator.func, decorator) not in _VALIDATORS:
                continue
            if any(
                keyword.arg == "mode"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value in {"before", "wrap"}
                for keyword in decorator.keywords
            ):
                return True
        return False


def _string(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _test_assertion(node: ast.AST, context: PythonFileContext) -> bool:
    if not is_test_path(context.path):
        return False
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.Assert):
            return True
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            return False
        current = context.parents.get(current)
    return False


def _get_receiver(node: ast.expr) -> ast.expr | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "get":
        return None
    if len(node.args) not in {1, 2} or node.keywords or not _string(node.args[0]):
        return None
    return node.func.value


def _callback_argument(call: ast.Call, qualified: str | None) -> ast.expr | None:
    if call.args:
        return call.args[0]
    parameter = "discriminator" if qualified in _DISCRIMINATORS else "func"
    return next((keyword.value for keyword in call.keywords if keyword.arg == parameter), None)


def _plain_callable_method(node: ast.ClassDef) -> ast.FunctionDef | None:
    if node.bases or node.keywords or node.decorator_list or node.type_params:
        return None
    method: ast.FunctionDef | None = None
    for statement in node.body:
        match statement:
            case ast.FunctionDef(name="__call__", decorator_list=[]) if method is None:
                method = statement
            case ast.Assign(value=ast.Constant(), targets=targets) if all(
                isinstance(target, ast.Name) and _inert_callable_attribute(target.id) for target in targets
            ):
                continue
            case ast.AnnAssign(target=ast.Name(id=name), value=None | ast.Constant()) if _inert_callable_attribute(
                name
            ):
                continue
            case ast.Pass() | ast.Expr(value=ast.Constant(value=str())):
                continue
            case _:
                return None
    return method


def _inert_callable_attribute(name: str) -> bool:
    return name == "__name__" or not (name.startswith("__") and name.endswith("__"))


def _probe_sources(node: ast.AST, facts: _Facts) -> Iterator[ast.expr]:
    match node:
        case ast.Call(func=func, args=[value, _], keywords=[]) if facts.builtin(func, "isinstance", node):
            if (field := facts.field(value)) is not None:
                yield field
        case ast.Compare():
            yield from _comparison_fields(node, facts)
        case ast.Match(subject=subject, cases=cases):
            for case in cases:
                yield from _match_fields(subject, case.pattern, facts)
        case ast.If(test=test) | ast.While(test=test) | ast.IfExp(test=test) | ast.Assert(test=test):
            yield from _truth_fields(test, facts)
        case _:
            return


def _comparison_fields(node: ast.Compare, facts: _Facts) -> Iterator[ast.expr]:
    operands = [node.left, *node.comparators]
    for value in operands:
        if (
            any(_literal(other) for other in operands if other is not value)
            and (field := facts.field(value)) is not None
        ):
            yield field
        if (field := _type_field(value, facts)) is not None:
            yield field


def _literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) or (
        isinstance(node, ast.Set | ast.List | ast.Tuple) and all(isinstance(item, ast.Constant) for item in node.elts)
    )


def _type_field(node: ast.expr, facts: _Facts) -> ast.expr | None:
    if not isinstance(node, ast.Call) or len(node.args) != 1 or node.keywords:
        return None
    return facts.field(node.args[0]) if facts.builtin(node.func, "type", node) else None


def _truth_fields(node: ast.expr, facts: _Facts) -> Iterator[ast.expr]:
    if (field := facts.field(node)) is not None:
        yield field
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        yield from _truth_fields(node.operand, facts)
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from _truth_fields(value, facts)


def _match_fields(subject: ast.expr, pattern: ast.pattern, facts: _Facts) -> Iterator[ast.expr]:
    if isinstance(pattern, ast.MatchAs):
        if pattern.pattern is not None:
            yield from _match_fields(subject, pattern.pattern, facts)
    elif isinstance(pattern, ast.MatchOr):
        for member in pattern.patterns:
            yield from _match_fields(subject, member, facts)
    elif isinstance(subject, ast.Tuple | ast.List) and isinstance(pattern, ast.MatchSequence):
        if len(subject.elts) == len(pattern.patterns):
            for value, member in zip(subject.elts, pattern.patterns, strict=True):
                yield from _match_fields(value, member, facts)
    elif not isinstance(pattern, ast.MatchStar) and (field := facts.field(subject)) is not None:
        yield field
