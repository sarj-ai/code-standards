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
from sarj_python_lint.rules._ast_index import has_own_yield
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_BUILTIN_BASES = frozenset({"Exception", "ValueError"})
_VALIDATOR_DECORATORS = frozenset(
    {
        "pydantic.field_validator",
        "pydantic.model_validator",
        "pydantic.validator",
        "pydantic.root_validator",
        "pydantic.functional_validators.field_validator",
        "pydantic.functional_validators.model_validator",
        "pydantic.v1.validator",
        "pydantic.v1.root_validator",
        "pydantic.class_validators.validator",
        "pydantic.class_validators.root_validator",
        "pydantic.deprecated.class_validators.validator",
        "pydantic.deprecated.class_validators.root_validator",
        "pydantic.v1.class_validators.validator",
        "pydantic.v1.class_validators.root_validator",
    }
)
_FUNCTIONAL_VALIDATORS = frozenset(
    f"{module}.{name}"
    for module in ("pydantic", "pydantic.functional_validators")
    for name in ("AfterValidator", "BeforeValidator", "PlainValidator", "WrapValidator")
)
_MAX_VALIDATOR_DEPTH = 32


@final
class NoCustomControlFlowException(Rule):
    id = "no-custom-control-flow-exception"
    code = "SARJ542"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Return typed outcomes for expected domain failures instead of name-only exceptions.",
        rationale=(
            "An empty custom exception creates another control-flow type without declaring failure data in "
            "the function's return contract. Expected domain outcomes can often use tagged result variants "
            "that callers handle explicitly, while exceptional failures and framework rejection still need exceptions."
        ),
        remediation=(
            "Review direct raises of this marker. If the condition is an expected domain outcome, return a "
            "typed tagged success/failure union and update every caller. Preserve true exceptional failures, "
            "validation rejection, transport/framework protocols, cancellation, unwinding and useful cause context. "
            "A class name or a raise does not prove the condition is expected."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This review warning checks stable module-level local Exception/ValueError subclasses whose bodies contain only pass, ellipsis or docstring expressions, including direct from-builtins exception imports and empty local subclasses of those markers. A source-visible direct raise of the class or its constructor is required; imported errors, payload-bearing classes, methods, decorators, generic/ambiguous bases and unused definitions abstain.",
            "Raising a ValueError-derived marker from an import-proven Pydantic field/model validator or legacy validator preserves that rejection protocol. Direct synchronous module callbacks used only as Annotated validator metadata on plain direct BaseModel fields, and stable nonescaping direct nested helpers, also preserve rejection; lexical helper ownership is bounded to 32 levels. Unknown external bases and visible mutations or escapes of the class or a local base to registrations, callbacks or other value consumers abstain; HTTPException and other framework-required exception types remain valid.",
            "Expectedness is not inferred from a name, message or prefix. Genuine exceptional markers may also match and require review rather than conversion. Cross-module callers and registrations, indirect raises, dynamically mutated namespaces and class aliases are not inferred. Only simple stable module assignment aliases and nongeneric annotation aliases consumed directly by model fields are followed. Explicit string annotations, custom model hooks, async/generator callbacks, escaped helpers and broader call graphs are not followed. Generic lexical resolution can miss a module marker shadowed only in a method's class namespace.",
            "Tests, generated and vendor code are excluded. No automatic rewrite is safe: a result return must preserve failure handling and transaction/resource unwinding. SARJ435 separately reviews joined-string reason identities.",
        ),
        examples=(
            RuleExample(
                example_id="empty-domain-exception",
                title="A local marker hides a domain outcome outside the return contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/content.py",
                        "class UnsupportedContent(ValueError):\n    pass\n"
                        "def read_content(known: bool) -> str:\n"
                        "    if not known:\n        raise UnsupportedContent('Unsupported content')\n    return 'content'\n",
                    ),
                ),
                focus_path=PurePosixPath("app/content.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="tagged-domain-result",
                title="The return contract represents the expected unsupported outcome",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/content.py",
                        "from dataclasses import dataclass\nfrom typing import Literal\n"
                        "@dataclass(frozen=True)\nclass Content:\n    value: str\n    kind: Literal['content'] = 'content'\n"
                        "@dataclass(frozen=True)\nclass Unsupported:\n    kind: Literal['unsupported'] = 'unsupported'\n"
                        "def read_content(known: bool) -> Content | Unsupported:\n"
                        "    return Content('content') if known else Unsupported()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/content.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or is_test_path(context.path):
            return []
        if not {"vendor", "vendored", "third_party"}.isdisjoint(context.path.parts):
            return []
        provenance = context.static_resource_provenance
        if (
            provenance.wildcard
            or provenance.dynamic_namespace
            or (not provenance.builtin_namespace_untouched and not _builtin_namespace_safe(context))
        ):
            return []
        markers = _markers(context, provenance)
        raised_markers = _direct_raises(markers, context, provenance)
        findings: list[Diagnostic] = []
        for marker in markers.values():
            if marker not in raised_markers:
                continue
            if is_suppressed(context.source_lines, marker.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    marker.lineno,
                    marker.col_offset + 1,
                    self.code,
                    f"Review `{marker.name}`: it adds only an exception identity and is directly raised. "
                    "If this is an expected domain outcome, return a typed tagged result; preserve genuine "
                    "exceptional failures, validation and framework contracts.",
                    severity=Severity.WARNING,
                )
            )
        return findings


def _markers(context: PythonFileContext, provenance: ResourceProvenance) -> dict[str, ast.ClassDef]:
    if context.tree is None:
        return {}
    markers: dict[str, ast.ClassDef] = {}
    for node in context.tree.body:
        if not isinstance(node, ast.ClassDef) or not _name_only(node):
            continue
        if provenance.binding(node.name, node) is not node:
            continue
        base = node.bases[0]
        local = (
            isinstance(base, ast.Name)
            and provenance.binding(base.id, base) is markers.get(base.id)
            and base.id in markers
        )
        if not (local or _builtin_base(base, context, provenance)):
            continue
        if node.name in provenance.mutated or node.name in provenance.external_bindings:
            continue
        if _escapes(node, context, provenance):
            continue
        markers[node.name] = node
    return markers


def _name_only(node: ast.ClassDef) -> bool:
    return (
        len(node.bases) == 1
        and not node.decorator_list
        and not node.keywords
        and not node.type_params
        and all(
            isinstance(member, ast.Pass)
            or (
                isinstance(member, ast.Expr)
                and isinstance(member.value, ast.Constant)
                and (isinstance(member.value.value, str) or member.value.value is Ellipsis)
            )
            for member in node.body
        )
    )


def _builtin_namespace_safe(context: PythonFileContext) -> bool:
    # Direct exception imports expose immutable class objects.
    for node in context.nodes(ast.Import, ast.ImportFrom, ast.Name):
        if isinstance(node, ast.Import) and any(alias.name == "builtins" for alias in node.names):
            return False
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "builtins"
            and (node.level or any(alias.name not in _BUILTIN_BASES for alias in node.names))
        ):
            return False
        if isinstance(node, ast.Name) and node.id == "__builtins__":
            return False
    return True


def _builtin_base(base: ast.expr, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    if isinstance(base, ast.Name) and base.id in _BUILTIN_BASES and context.imports.builtin_is_unshadowed(base.id):
        return True
    return any(provenance.imported(base, f"builtins.{name}") for name in _BUILTIN_BASES)


def _direct_raises(
    markers: dict[str, ast.ClassDef], context: PythonFileContext, provenance: ResourceProvenance
) -> set[ast.ClassDef]:
    candidates = set(markers.values())
    raised_markers: set[ast.ClassDef] = set()
    value_errors: dict[ast.ClassDef, bool] = {}
    validators: dict[ast.AST, bool] = {}
    for raised in context.nodes(ast.Raise):
        target = raised.exc.func if isinstance(raised.exc, ast.Call) else raised.exc
        if not isinstance(target, ast.Name):
            continue
        marker = provenance.binding(target.id, target)
        if not isinstance(marker, ast.ClassDef) or marker not in candidates or marker in raised_markers:
            continue
        if marker not in value_errors:
            value_errors[marker] = _value_error_marker(marker, context, provenance)
        if not (value_errors[marker] and _validation_callback(raised, context, provenance, validators)):
            raised_markers.add(marker)
    return raised_markers


def _value_error_marker(marker: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    seen: set[int] = set()
    current = marker
    while id(current) not in seen:
        seen.add(id(current))
        base = current.bases[0]
        if (
            isinstance(base, ast.Name) and base.id == "ValueError" and context.imports.builtin_is_unshadowed(base.id)
        ) or provenance.imported(base, "builtins.ValueError"):
            return True
        bound = provenance.binding(base.id, base) if isinstance(base, ast.Name) else None
        if not isinstance(bound, ast.ClassDef) or not _name_only(bound):
            return False
        current = bound
    return False


def _validation_callback(
    node: ast.AST,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    cache: dict[ast.AST, bool],
    depth: int = 0,
) -> bool:
    if depth >= _MAX_VALIDATOR_DEPTH:
        return False
    owner = context.parents.get(node)
    while owner is not None and not isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef):
        owner = context.parents.get(owner)
    if not isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef):
        return False
    if owner in cache:
        return cache[owner]
    cache[owner] = any(
        provenance.imported(decorator.func if isinstance(decorator, ast.Call) else decorator, qualified)
        for decorator in owner.decorator_list
        for qualified in _VALIDATOR_DECORATORS
    ) or _functional_callback(owner, context, provenance)
    parent = context.parents.get(owner)
    if (
        not cache[owner]
        and isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef)
        and _local_validator_helper(owner, parent, context, provenance)
    ):
        cache[owner] = _validation_callback(owner, context, provenance, cache, depth + 1)
    return cache[owner]


def _local_validator_helper(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    provenance: ResourceProvenance,
) -> bool:
    if (
        not isinstance(function, ast.FunctionDef)
        or function.decorator_list
        or has_own_yield(function)
        or function.name in provenance.mutated | provenance.external_bindings
        or provenance.binding(function.name, function) is not function
    ):
        return False
    reads = provenance.reads.get(function.name, ())
    return bool(reads) and all(
        provenance.binding(read.id, read) is function
        and isinstance(parent := context.parents.get(read), ast.Call)
        and parent.func is read
        and provenance.scope(read) in {owner, function}
        for read in reads
    )


def _functional_callback(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    provenance: ResourceProvenance,
) -> bool:
    if not isinstance(function, ast.FunctionDef) or not isinstance(context.parents.get(function), ast.Module):
        return False
    if (
        function.decorator_list
        or has_own_yield(function)
        or function.name in provenance.mutated | provenance.external_bindings
        or provenance.binding(function.name, function) is not function
    ):
        return False
    return _functional_callback_uses(function, context, provenance)


def _functional_callback_uses(
    function: ast.FunctionDef, context: PythonFileContext, provenance: ResourceProvenance
) -> bool:
    pending: list[ast.FunctionDef | ast.Name] = [function]
    seen: set[ast.AST] = set()
    registered = False
    while pending:
        binding = pending.pop()
        if binding in seen:
            continue
        if len(seen) >= _MAX_VALIDATOR_DEPTH:
            return False
        seen.add(binding)
        name = binding.id if isinstance(binding, ast.Name) else binding.name
        reads = provenance.reads.get(name, ())
        if not reads:
            return False
        for read in reads:
            if provenance.binding(read.id, read) is not binding:
                return False
            if _functional_metadata(read, context, provenance):
                registered = True
            elif (alias := _callback_alias(read, context, provenance)) is not None:
                pending.append(alias)
            else:
                return False
    return registered


def _callback_alias(read: ast.Name, context: PythonFileContext, provenance: ResourceProvenance) -> ast.Name | None:
    statement = context.parents.get(read)
    if not (
        isinstance(statement, ast.Assign)
        and statement.value is read
        and isinstance(context.parents.get(statement), ast.Module)
        and len(statement.targets) == 1
        and isinstance(target := statement.targets[0], ast.Name)
        and target.id not in provenance.mutated | provenance.external_bindings
        and provenance.binding(target.id, target) is target
    ):
        return None
    return target


def _functional_metadata(read: ast.Name, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    parent = context.parents.get(read)
    call = context.parents.get(parent) if isinstance(parent, ast.keyword) else parent
    if not isinstance(call, ast.Call) or not any(
        provenance.imported(call.func, qualified) for qualified in _FUNCTIONAL_VALIDATORS
    ):
        return False
    if call.args:
        if len(call.args) != 1 or call.args[0] is not read or any(keyword.arg == "func" for keyword in call.keywords):
            return False
    elif not isinstance(parent, ast.keyword) or parent.arg != "func":
        return False
    if any(keyword.arg not in {"func", "json_schema_input_type"} for keyword in call.keywords):
        return False
    members = context.parents.get(call)
    if not isinstance(members, ast.Tuple) or call not in members.elts[1:]:
        return False
    annotation = context.parents.get(members)
    if not (
        isinstance(annotation, ast.Subscript)
        and annotation.slice is members
        and any(
            provenance.imported(annotation.value, f"{module}.Annotated") for module in ("typing", "typing_extensions")
        )
    ):
        return False
    return _validation_annotation(annotation, context, provenance)


def _validation_annotation(annotation: ast.expr, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    declaration = context.parents.get(annotation)
    if isinstance(declaration, ast.TypeAlias):
        binding = declaration.name
    elif (
        isinstance(declaration, ast.AnnAssign)
        and isinstance(declaration.target, ast.Name)
        and declaration.value is annotation
    ):
        binding = declaration.target
    else:
        return _validation_field(annotation, context, provenance)
    if not (
        isinstance(context.parents.get(declaration), ast.Module)
        and context.annotation_semantics.aliases.get(binding.id) is annotation
        and binding.id not in provenance.mutated | provenance.external_bindings
        and provenance.binding(binding.id, binding) is binding
    ):
        return False
    reads = provenance.reads.get(binding.id, ())
    return bool(reads) and all(
        provenance.binding(read.id, read) is binding and _validation_field(read, context, provenance) for read in reads
    )


def _validation_field(annotation: ast.expr, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    field = context.parents.get(annotation)
    if not isinstance(field, ast.AnnAssign) or field.annotation is not annotation:
        return False
    model = context.parents.get(field)
    if not (
        isinstance(model, ast.ClassDef)
        and isinstance(context.parents.get(model), ast.Module)
        and len(model.bases) == 1
        and any(provenance.imported(model.bases[0], f"{module}.BaseModel") for module in ("pydantic", "pydantic.main"))
        and not (model.decorator_list or model.keywords or model.type_params)
        and model.name not in provenance.mutated | provenance.external_bindings
        and provenance.binding(model.name, model) is model
    ):
        return False
    return all(
        isinstance(member, ast.Pass)
        or (
            isinstance(member, ast.Expr)
            and isinstance(member.value, ast.Constant)
            and isinstance(member.value.value, str)
        )
        or (
            isinstance(member, ast.AnnAssign)
            and isinstance(member.target, ast.Name)
            and not member.target.id.startswith("__")
            and (member.value is None or isinstance(member.value, ast.Constant))
        )
        for member in model.body
    )


def _escapes(marker: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    for read in provenance.binding_reads(marker.name, marker):
        parent = context.parents.get(read)
        if isinstance(parent, ast.Call) and parent.func is read:
            owner = context.parents.get(parent)
            if isinstance(owner, ast.Raise) and owner.exc is parent:
                continue
            return True
        if isinstance(parent, ast.Raise | ast.ExceptHandler):
            continue
        if isinstance(parent, ast.Tuple) and isinstance(context.parents.get(parent), ast.ExceptHandler):
            continue
        if isinstance(parent, ast.ClassDef) and read in parent.bases:
            continue
        return True
    return False
