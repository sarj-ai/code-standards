from __future__ import annotations

import ast
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
            "Checks get calls on string mappings annotated with object, Any or JsonValue values, bare standard dict/Mapping annotations, explicit Any/object receivers and import-proven json.load/loads results. Source-visible undecorated function return annotations, stable local aliases, projections and chained gets retain raw provenance through bounded resolution.",
            "Precise mappings and TypedDicts, arbitrary unannotated parameters, application methods named get, unresolved external return types, ambiguous assignments and custom JSON object hooks abstain. This syntax analysis does not replace the type checker.",
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
            and _untyped_receiver(call.func.value, facts)
            and not is_suppressed(context.source_lines, call.lineno, self.code)
        ]
        return list({(finding.line, finding.col): finding for finding in findings}.values())


def _untyped_receiver(node: ast.expr, facts: MappingShapeFacts, *, seen: frozenset[ast.AST] = frozenset()) -> bool:
    if len(seen) >= _MAX_DEPTH:
        return False
    if facts.mapping(node):
        return True
    match node:
        case ast.Name():
            return _name_receiver(node, facts, seen)
        case ast.Call(func=func, keywords=keywords) if facts.qualified(func, node) in _JSON_PARSERS:
            return not any(keyword.arg in {None, "object_hook", "object_pairs_hook", "cls"} for keyword in keywords)
        case ast.Call(func=ast.Attribute(value=receiver, attr="get")) | ast.Subscript(value=receiver):
            return _untyped_receiver(receiver, facts, seen=seen | {node})
        case ast.Call(func=ast.Name(id=name)):
            function = facts.provenance.binding(name, node)
            return (
                isinstance(function, ast.FunctionDef)
                and not function.decorator_list
                and function.returns is not None
                and (
                    facts.annotation(function.returns, function.returns, mapping=True)
                    or _erased_annotation(function.returns, facts)
                )
            )
        case _:
            return False


def _name_receiver(node: ast.Name, facts: MappingShapeFacts, seen: frozenset[ast.AST]) -> bool:
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
    return value is not None and _untyped_receiver(value, facts, seen=seen | {binding})


def _erased_annotation(node: ast.expr, facts: MappingShapeFacts) -> bool:
    resolved = facts.resolve_annotation(node)
    if resolved is None:
        return False
    return (
        facts.builtin(resolved.expression, "dict", resolved.at)
        or facts.builtin(resolved.expression, "object", resolved.at)
        or facts.qualified(resolved.expression, resolved.at) in _UNTYPED
    )
