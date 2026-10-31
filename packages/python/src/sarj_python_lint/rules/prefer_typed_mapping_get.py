from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
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
from sarj_python_lint.rules._local_source import LocalSourceFacts
from sarj_python_lint.rules.require_pydantic_for_mapping_shape import MappingShapeFacts


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext

_UNTYPED = frozenset(
    {
        "typing.Any",
        "typing_extensions.Any",
        "typing.Dict",
        "typing.Mapping",
        "typing.MutableMapping",
        "collections.abc.Mapping",
        "collections.abc.MutableMapping",
    }
)
_JSON_PARSERS = frozenset({"json.load", "json.loads"})
_MAX_DEPTH = 32
_MAX_RETURN_PROOFS = 512
_BAD = "def service_name(state: dict[str, object]):\n    return state.get('name')\n"
_GOOD = "from typing import TypedDict\nclass State(TypedDict):\n    name: str\ndef service_name(state: State) -> str | None:\n    return state.get('name')\n"


@final
class PreferTypedMappingGet(Rule):
    id = "prefer-typed-mapping-get"
    code = "SARJ535"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Read named fields from typed records instead of schema-free mappings.",
        rationale="A get call on an Any/object-valued mapping or unchecked decoded JSON does not declare the field's type or distinguish a misspelled field from missing data. A default can conceal that gap.",
        remediation="Validate external data into a named Pydantic model before reading its attributes. For trusted internal records, declare a TypedDict or another precise record. Preserve legitimate get calls on typed mappings, optional TypedDict fields and validated normalization callbacks.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks get calls on string mappings annotated with object, Any or JsonValue values, bare standard dict/Mapping annotations, explicit Any/object receivers and import-proven json.load/loads results. Source-visible undecorated local or imported function returns, stable aliases, relative imports, reexports, projections and chained gets retain raw provenance through bounded resolution. Unannotated helpers are followed when every return is proven schema-free; precise return annotations retain their contract.",
            "Precise mappings and TypedDicts, arbitrary unannotated parameters, application methods named get, unresolved external return types, ambiguous assignments and custom JSON object hooks abstain. Imported helpers are parsed without executing them, using a bounded per-file resolver that shares captured source inputs; dynamic or mutated namespaces, decorated functions and recursive or unresolved returns abstain. This syntax analysis does not replace the type checker.",
            "Registered Pydantic raw normalization callbacks retain their validation boundary. Generated/vendor sources and wildcard or dynamic namespaces are excluded. No automatic rewrite because validation, defaults, missing keys and error handling can change behavior.",
            "Existing mapping-shape and external-boundary diagnostics take precedence at the same read when selected together; selecting this rule alone still reports it.",
            "Chained reads with the same starting position produce one actionable warning for their raw receiver.",
        ),
        examples=(
            RuleExample(
                example_id="opaque-get",
                title="The field has no declared type",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/state.py", _BAD),),
                focus_path=PurePosixPath("app/state.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-get",
                title="TypedDict retains the field contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/state.py", _GOOD),),
                focus_path=PurePosixPath("app/state.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="unchecked-json",
                scenario="decoded-json",
                title="Decoded JSON still needs validation",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/state.py",
                        "import json\ndef name(text: str):\n    state = json.loads(text)\n    return state.get('name')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/state.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="validated-json",
                scenario="decoded-json",
                title="Validate JSON before reading its fields",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/state.py",
                        "from pydantic import BaseModel\nclass State(BaseModel):\n    name: str\ndef name(text: str) -> str:\n    return State.model_validate_json(text).name\n",
                    ),
                ),
                focus_path=PurePosixPath("app/state.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="imported-parser-contract",
                scenario="imported-return",
                title="Imported parsing helpers keep their raw mapping contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python("app/__init__.py", "# package\n"),
                    ExampleFile.python(
                        "app/parser.py",
                        "import json\ndef parse(text: str) -> dict[str, object]:\n    return json.loads(text)\n",
                    ),
                    ExampleFile.python(
                        "app/state.py",
                        "from .parser import parse\ndef name(text: str):\n    return parse(text).get('name')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/state.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="imported-validated-model",
                scenario="imported-return",
                title="An imported parser validates a named model",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/__init__.py", "# package\n"),
                    ExampleFile.python(
                        "app/parser.py",
                        "from pydantic import BaseModel\nclass State(BaseModel):\n    labels: dict[str, str]\n"
                        "def parse(text: str) -> State:\n    return State.model_validate_json(text)\n",
                    ),
                    ExampleFile.python(
                        "app/state.py",
                        "from .parser import parse\ndef name(text: str):\n    return parse(text).labels.get('name')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/state.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or "get" not in context.symbol_source:
            return []
        facts = MappingShapeFacts(context)
        if facts.provenance.wildcard or facts.provenance.dynamic_namespace:
            return []
        contracts = _ReturnContracts(facts)
        findings = [
            Diagnostic(
                context.path,
                call.lineno,
                call.col_offset + 1,
                self.code,
                "Validate this schema-free mapping into a named model or use a precise internal record before reading fields with get.",
                severity=Severity.WARNING,
            )
            for call in context.nodes(ast.Call)
            if isinstance(call.func, ast.Attribute)
            and call.func.attr == "get"
            and not facts.raw_boundary(call)
            and _untyped_receiver(call.func.value, facts, contracts)
            and not is_suppressed(context.source_lines, call.lineno, self.code)
        ]
        return list({(finding.line, finding.col): finding for finding in findings}.values())


@dataclass(frozen=True, slots=True)
class _FunctionReturn:
    owner: MappingShapeFacts
    definition: ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True, slots=True)
class _ImportLocation:
    module: str
    level: int
    name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _ReturnProofKey:
    owner_path: Path
    definition: ast.FunctionDef | ast.AsyncFunctionDef
    seen: frozenset[ast.AST]


class _ReturnContracts:
    def __init__(self, facts: MappingShapeFacts) -> None:
        self.owners = {facts.context.path: facts}
        # Return lookups must leave other rules enough budget to resolve their validators.
        self.local_source = LocalSourceFacts(source_inputs=facts.context.session.source_inputs)
        self._return_proofs: dict[_ReturnProofKey, bool] = {}
        self._return_nodes: dict[Path, dict[ast.FunctionDef | ast.AsyncFunctionDef, tuple[ast.Return, ...]]] = {}

    def returned_mapping(
        self, owner: MappingShapeFacts, function: ast.FunctionDef | ast.AsyncFunctionDef, seen: frozenset[ast.AST]
    ) -> bool:
        key = _ReturnProofKey(owner_path=owner.context.path, definition=function, seen=seen)
        cached = self._return_proofs.get(key)
        if cached is not None:
            return cached
        returned = self.return_nodes(owner, function)
        result = bool(returned) and all(
            node.value is not None and _untyped_receiver(node.value, owner, self, seen=seen | {function})
            for node in returned
        )
        if len(self._return_proofs) < _MAX_RETURN_PROOFS:
            self._return_proofs[key] = result
        return result

    def return_nodes(
        self, owner: MappingShapeFacts, function: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> tuple[ast.Return, ...]:
        path = owner.context.path
        if path not in self._return_nodes:
            grouped: dict[ast.FunctionDef | ast.AsyncFunctionDef, list[ast.Return]] = {}
            for node in owner.context.nodes(ast.Return):
                scope = owner.provenance.scope(node)
                if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
                    grouped.setdefault(scope, []).append(node)
            self._return_nodes[path] = {scope: tuple(nodes) for scope, nodes in grouped.items()}
        return self._return_nodes[path].get(function, ())

    def function(
        self, expression: ast.expr, facts: MappingShapeFacts, seen: frozenset[ast.AST]
    ) -> _FunctionReturn | None:
        if len(seen) >= _MAX_DEPTH or facts.provenance.wildcard or facts.provenance.dynamic_namespace:
            return None
        attributes: list[str] = []
        root = expression
        while isinstance(root, ast.Attribute):
            attributes.append(root.attr)
            root = root.value
        if (
            not isinstance(root, ast.Name)
            or facts.shadowed(root.id, expression)
            or root.id in facts.provenance.mutated | facts.provenance.external_bindings
        ):
            return None
        binding = facts.provenance.binding(root.id, expression)
        if binding is None or binding in seen:
            return None
        match binding:
            case ast.FunctionDef() | ast.AsyncFunctionDef() if not attributes:
                return _FunctionReturn(facts, binding) if not binding.decorator_list else None
            case ast.Name() if not attributes:
                value = facts.provenance.assignment_value(binding, expression)
                return (
                    self.function(value, facts, seen | {binding})
                    if isinstance(value, ast.Name | ast.Attribute)
                    else None
                )
            case ast.alias():
                return self.imported(binding, tuple(reversed(attributes)), facts, seen)
            case _:
                return None

    def imported(
        self, binding: ast.alias, attributes: tuple[str, ...], facts: MappingShapeFacts, seen: frozenset[ast.AST]
    ) -> _FunctionReturn | None:
        if len(seen) >= _MAX_DEPTH or binding in seen:
            return None
        location = _import_location(binding, attributes, facts)
        if location is None:
            return None
        path = self.local_source.resolve_module(
            facts.context.path, location.module, location.level, facts=facts.context.session.first_party
        )
        if path is None or _namespace_uncertain(facts, path):
            return None
        owner = self._owner(path, facts)
        if (
            owner is None
            or owner.context.tree is None
            or owner.provenance.wildcard
            or owner.provenance.dynamic_namespace
        ):
            return None
        bindings = owner.provenance.bindings.get(owner.context.tree, {}).get(location.name, ())
        if len(bindings) != 1 or location.name in owner.provenance.mutated | owner.provenance.external_bindings:
            return None
        [target] = bindings
        following = seen | {binding}
        match target:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                result = _FunctionReturn(owner, target) if not target.decorator_list else None
            case ast.alias():
                result = self.imported(target, (), owner, following)
            case _:
                result = None
        return result if result is not None and not _namespace_uncertain(facts, result.owner.context.path) else None

    def _owner(self, path: Path, facts: MappingShapeFacts) -> MappingShapeFacts | None:
        if path not in self.owners:
            if len(self.owners) >= _MAX_DEPTH:
                return None
            module = self.local_source.read_module(path)
            if module is None:
                return None
            from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- source owners are constructed after analysis-session initialization.

            self.owners[path] = MappingShapeFacts(PythonFileContext(path, module.source, facts.context.session))
        return self.owners[path]


def _import_location(
    binding: ast.alias, attributes: tuple[str, ...], facts: MappingShapeFacts
) -> _ImportLocation | None:
    parent = facts.context.parents.get(binding)
    match parent:
        case ast.ImportFrom(module=module, level=level):
            parts = (*((module,) if module else ()), *((binding.name, *attributes[:-1]) if attributes else ()))
            return _ImportLocation(".".join(parts), level, attributes[-1] if attributes else binding.name)
        case ast.Import() if attributes:
            prefix = binding.name if binding.asname else binding.name.partition(".")[0]
            return _ImportLocation(".".join((prefix, *attributes[:-1])), 0, attributes[-1])
        case _:
            return None


def _namespace_uncertain(facts: MappingShapeFacts, path: Path) -> bool:
    if facts.provenance.mock_namespace_patching:
        return True
    target = path.resolve()
    return any(
        target == source or (source.name == "__init__.py" and target.is_relative_to(source.parent))
        for source in facts.provenance.imported_namespace_hazards
    )


def _untyped_receiver(
    node: ast.expr, facts: MappingShapeFacts, contracts: _ReturnContracts, *, seen: frozenset[ast.AST] = frozenset()
) -> bool:
    if len(seen) >= _MAX_DEPTH:
        return False
    if facts.mapping(node):
        return True
    match node:
        case ast.Name():
            return _name_receiver(node, facts, contracts, seen)
        case ast.Call(func=func, keywords=keywords) if facts.qualified(func, node) in _JSON_PARSERS:
            return not any(keyword.arg in {None, "object_hook", "object_pairs_hook", "cls"} for keyword in keywords)
        case ast.Call(func=ast.Attribute(value=receiver, attr="get")) | ast.Subscript(value=receiver):
            return _untyped_receiver(receiver, facts, contracts, seen=seen | {node})
        case ast.Await(value=ast.Call() as call):
            return _returned_mapping(call, facts, contracts, seen, awaited=True)
        case ast.Call():
            return _returned_mapping(node, facts, contracts, seen, awaited=False)
        case _:
            return False


def _returned_mapping(
    call: ast.Call, facts: MappingShapeFacts, contracts: _ReturnContracts, seen: frozenset[ast.AST], *, awaited: bool
) -> bool:
    resolved = contracts.function(call.func, facts, seen)
    if resolved is None:
        return False
    owner, function = resolved.owner, resolved.definition
    if function in seen or isinstance(function, ast.AsyncFunctionDef) != awaited:
        return False
    if function.returns is not None:
        return owner.annotation(function.returns, function.returns, mapping=True) or _erased_annotation(
            function.returns, owner
        )
    return contracts.returned_mapping(owner, function, seen)


def _name_receiver(
    node: ast.Name, facts: MappingShapeFacts, contracts: _ReturnContracts, seen: frozenset[ast.AST]
) -> bool:
    if node.id in facts.provenance.external_bindings:
        return False
    binding = facts.provenance.binding(node.id, node)
    if binding is None or binding in seen:
        return False
    if isinstance(binding, ast.arg):
        return binding.annotation is not None and _erased_annotation(binding.annotation, facts)
    parent = facts.context.parents.get(binding)
    if isinstance(parent, ast.AnnAssign):
        return _erased_annotation(parent.annotation, facts)
    value = facts.provenance.assignment_value(binding, node) if isinstance(binding, ast.Name) else None
    return value is not None and _untyped_receiver(value, facts, contracts, seen=seen | {binding})


def _erased_annotation(node: ast.expr, facts: MappingShapeFacts) -> bool:
    resolved = facts.resolve_annotation(node)
    if resolved is None:
        return False
    return (
        facts.builtin(resolved.expression, "dict", resolved.at)
        or facts.builtin(resolved.expression, "object", resolved.at)
        or facts.qualified(resolved.expression, resolved.at) in _UNTYPED
    )
