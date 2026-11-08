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
)
from sarj_python_lint.rules._ast_index import has_own_yield
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path

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
_MAX_BASE_DEPTH = 8


@final
class NoCustomControlFlowException(Rule):
    id = "no-custom-control-flow-exception"
    code = "SARJ542"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Return coded typed outcomes for expected domain failures instead of exception-only contracts.",
        rationale=(
            "A marker, fixed-message or payload-bearing custom exception creates another control-flow type without declaring failure data in "
            "the function's return contract. Expected domain outcomes can often use tagged result variants "
            "that callers handle explicitly. A caller may need error identifiers for an access check before "
            "reporting a rejected record; preserve that handling context. Exceptional failures and framework "
            "rejection still need exceptions."
        ),
        remediation=(
            "Review direct raises of this exception. If the condition is an expected domain outcome, return a "
            "typed tagged success/failure union with a stable error code and the handling context, and update every caller. "
            "Format the message at the consumer. Preserve true exceptional failures, "
            "validation rejection, transport/framework protocols, cancellation, unwinding and useful cause context. "
            "A class name or a raise does not prove the condition is expected."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This review warning checks stable module-level Exception/ValueError markers and fixed-message subclasses with a source-visible direct raise. It also reviews typed payload constructors limited to assignments and super().__init__ argument formatting, when raised by a single-statement guard in an explicitly annotated function. Constructor parameters must be typed, nonvariadic and actually used; calls must supply their required arguments. Imported base semantics remain a manual contract check.",
            "Payload guards under try/except/finally, with, loops and match are excluded, as are generators, quoted return annotations and import-proven NoReturn/Never functions. Constructor calls, arbitrary computations, extra methods or behavior, decorated/generic constructors and unknown argument expansion abstain. Source-visible formatting is not a purity proof and never authorizes an automatic rewrite.",
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
            RuleExample(
                example_id="typed-context-hidden-in-exception",
                scenario="typed-payload",
                title="A guarded rejection hides typed context in its exception contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/content.py",
                        "class Denied(Exception):\n"
                        "    def __init__(self, name: str) -> None:\n"
                        "        self.name = name\n"
                        "        super().__init__(f'Denied {name}')\n"
                        "def load(name: str, allowed: bool) -> str:\n"
                        "    if not allowed:\n        raise Denied(name)\n    return name\n",
                    ),
                ),
                focus_path=PurePosixPath("app/content.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="code-context-and-consumer-formatting",
                scenario="typed-payload",
                title="A typed outcome retains the code and formatting context",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/content.py",
                        "from dataclasses import dataclass\nfrom typing import Literal\n"
                        "@dataclass(frozen=True)\nclass Denied:\n"
                        "    name: str\n    code: Literal['denied'] = 'denied'\n"
                        "def load(name: str, allowed: bool) -> str | Denied:\n"
                        "    return name if allowed else Denied(name)\n"
                        "def format_error(error: Denied) -> str:\n    return f'Denied {error.name}'\n",
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
            if context.suppressions.is_suppressed(marker.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    marker.lineno,
                    marker.col_offset + 1,
                    self.code,
                    f"Review `{marker.name}`: its identity, message or typed context is communicated only through an exception. "
                    "If this is an expected domain outcome, return a typed tagged result with a stable error code and the required context, and "
                    "format the message at the consumer; preserve exceptional failures, validation, framework contracts "
                    "and transaction/resource unwinding.",
                    severity=Severity.WARNING,
                )
            )
        return findings


def _markers(context: PythonFileContext, provenance: ResourceProvenance) -> dict[str, ast.ClassDef]:
    if context.tree is None:
        return {}
    markers: dict[str, ast.ClassDef] = {}
    base_contexts = {context.path: context}
    for node in context.tree.body:
        if not isinstance(node, ast.ClassDef) or not _marker_body(node):
            continue
        if not _stable_marker(node, context, provenance):
            continue
        base = node.bases[0]
        fixed_message = any(isinstance(member, ast.FunctionDef) for member in node.body)
        payload = _payload_constructor(node) is not None
        if not _marker_base(
            base, markers, context, fixed_message=fixed_message, payload=payload, contexts=base_contexts
        ):
            continue
        if fixed_message and not context.imports.builtin_is_unshadowed("super"):
            continue
        markers[node.name] = node
    return markers


def _stable_marker(marker: ast.ClassDef, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    return (
        provenance.binding(marker.name, marker) is marker
        and marker.name not in provenance.mutated | provenance.external_bindings
        and not _escapes(marker, context, provenance)
    )


def _marker_base(
    base: ast.expr,
    markers: dict[str, ast.ClassDef],
    context: PythonFileContext,
    *,
    fixed_message: bool,
    payload: bool,
    contexts: dict[Path, PythonFileContext],
) -> bool:
    provenance = context.static_resource_provenance
    local = isinstance(base, ast.Name) and base.id in markers and provenance.binding(base.id, base) is markers[base.id]
    if payload:
        return _payload_exception_base(base, context, contexts, frozenset())
    if local or _builtin_base(base, context, provenance):
        return True
    imported = provenance.runtime_import_name(base)
    return (
        fixed_message
        and imported is not None
        and not imported.startswith(("builtins.", "asyncio.", "fastapi.", "starlette.", "concurrent.futures."))
    )


def _payload_exception_base(
    base: ast.expr,
    context: PythonFileContext,
    contexts: dict[Path, PythonFileContext],
    seen: frozenset[tuple[Path, str]],
) -> bool:
    provenance = context.static_resource_provenance
    if provenance.wildcard or provenance.dynamic_namespace:
        return False
    if not provenance.builtin_namespace_untouched and not _builtin_namespace_safe(context):
        return False
    if _builtin_base(base, context, provenance):
        return True
    if not isinstance(base, ast.Name) or len(seen) >= _MAX_BASE_DEPTH:
        return False
    binding = provenance.binding(base.id, base)
    owner = context
    if isinstance(binding, ast.alias):
        imported = _imported_base_context(binding, context, contexts)
        if imported is None:
            return False
        owner = imported
        binding = _module_class(owner, binding.name)
    if not isinstance(binding, ast.ClassDef) or len(binding.bases) != 1:
        return False
    key = (owner.path, binding.name)
    facts = owner.static_resource_provenance
    if key in seen or owner.generated or binding.name in facts.mutated | facts.external_bindings:
        return False
    if binding.decorator_list or binding.keywords or binding.type_params:
        return False
    if _escapes(binding, owner, facts):
        return False
    return _payload_exception_base(binding.bases[0], owner, contexts, seen | {key})


def _imported_base_context(
    binding: ast.alias, context: PythonFileContext, contexts: dict[Path, PythonFileContext]
) -> PythonFileContext | None:
    from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- resolve source contexts only after registry initialization.

    statement = context.parents.get(binding)
    if not isinstance(statement, ast.ImportFrom) or context.parents.get(statement) is not context.tree:
        return None
    path = context.session.local_source.resolve_module(
        context.path, statement.module, statement.level, facts=context.session.first_party
    )
    module = context.session.local_source.read_module(path) if path is not None else None
    if module is None:
        return None
    if module.path not in contexts:
        contexts[module.path] = PythonFileContext(module.path, module.source, context.session)
    return contexts[module.path]


def _module_class(context: PythonFileContext, name: str) -> ast.ClassDef | None:
    if context.tree is None:
        return None
    declarations = [node for node in context.tree.body if isinstance(node, ast.ClassDef) and node.name == name]
    return declarations[0] if len(declarations) == 1 else None


def _marker_body(node: ast.ClassDef) -> bool:
    payload = _payload_constructor(node)
    return (
        len(node.bases) == 1
        and not node.decorator_list
        and not node.keywords
        and not node.type_params
        and all(
            isinstance(member, ast.Pass)
            or (isinstance(member, ast.FunctionDef) and (_fixed_message_initializer(member) or member is payload))
            or (
                payload is not None
                and isinstance(member, ast.AnnAssign)
                and isinstance(member.target, ast.Name)
                and member.value is None
            )
            or (
                isinstance(member, ast.Expr)
                and isinstance(member.value, ast.Constant)
                and (isinstance(member.value.value, str) or member.value.value is Ellipsis)
            )
            for member in node.body
        )
    )


def _payload_constructor(node: ast.ClassDef) -> ast.FunctionDef | None:
    constructors = [member for member in node.body if isinstance(member, ast.FunctionDef) and member.name == "__init__"]
    if len(constructors) != 1:
        return None
    constructor = constructors[0]
    return constructor if _payload_initializer(constructor) else None


def _payload_initializer(node: ast.FunctionDef) -> bool:
    names = _payload_parameters(node)
    if names is None:
        return False
    fields: set[str] = set()
    used = False
    self_name = [*node.args.posonlyargs, *node.args.args][0].arg
    for statement in node.body:
        value = _payload_statement(statement, names, fields, self_name)
        if value is None:
            return False
        used = used or any(isinstance(child, ast.Name) and child.id in names for child in ast.walk(value))
    return used


def _payload_parameters(node: ast.FunctionDef) -> set[str] | None:
    arguments = [*node.args.posonlyargs, *node.args.args]
    parameters = [*arguments[1:], *node.args.kwonlyargs]
    if node.name != "__init__" or not arguments or not parameters or node.decorator_list or node.type_params:
        return None
    if (
        node.args.vararg
        or node.args.kwarg
        or not isinstance(node.returns, ast.Constant)
        or node.returns.value is not None
    ):
        return None
    if any(parameter.annotation is None for parameter in parameters):
        return None
    if any(not isinstance(default, ast.Constant) for default in node.args.defaults):
        return None
    if any(default is not None and not isinstance(default, ast.Constant) for default in node.args.kw_defaults):
        return None
    return {parameter.arg for parameter in parameters}


def _payload_statement(statement: ast.stmt, names: set[str], fields: set[str], self_name: str) -> ast.expr | None:
    match statement:
        case ast.Assign(targets=[target], value=value) | ast.AnnAssign(target=target, value=ast.expr() as value):
            if not (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == self_name
                and not target.attr.startswith("__")
                and _payload_expression(value, names, fields, self_name)
            ):
                return None
            fields.add(target.attr)
            return value
        case ast.Expr(value=value) if _payload_super_call(value, names, fields, self_name):
            return value
        case _:
            return None


def _payload_expression(value: ast.expr, names: set[str], fields: set[str], self_name: str) -> bool:
    match value:
        case ast.Constant(value=constant):
            return constant is not Ellipsis
        case ast.Name(id=name):
            return name in names
        case ast.Attribute(value=ast.Name(id=owner), attr=field):
            return owner == self_name and field in fields
        case ast.JoinedStr(values=parts):
            return all(
                isinstance(part, ast.Constant)
                or (
                    isinstance(part, ast.FormattedValue)
                    and _payload_expression(part.value, names, fields, self_name)
                    and (part.format_spec is None or _payload_expression(part.format_spec, names, fields, self_name))
                )
                for part in parts
            )
        case _:
            return False


def _payload_super_call(value: ast.expr, names: set[str], fields: set[str], self_name: str) -> bool:
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "__init__"
        and isinstance(value.func.value, ast.Call)
        and isinstance(value.func.value.func, ast.Name)
        and value.func.value.func.id == "super"
        and not value.func.value.args
        and not value.func.value.keywords
        and not value.keywords
        and all(_payload_expression(argument, names, fields, self_name) for argument in value.args)
    )


def _fixed_message_initializer(node: ast.FunctionDef) -> bool:
    arguments = [*node.args.posonlyargs, *node.args.args]
    if node.name != "__init__" or node.decorator_list or node.type_params or len(arguments) != 1:
        return False
    if node.args.vararg or node.args.kwarg or node.args.kwonlyargs or node.args.defaults:
        return False
    match node.body:
        case [
            ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(
                        value=ast.Call(func=ast.Name(id="super"), args=[], keywords=[]), attr="__init__"
                    ),
                    args=[ast.Constant(value=str())],
                    keywords=[],
                )
            )
        ]:
            return True
        case _:
            return False


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
        constructor = _payload_constructor(marker)
        if constructor is not None and not _payload_guard(raised, constructor, context):
            continue
        if marker not in value_errors:
            value_errors[marker] = _value_error_marker(marker, context, provenance)
        if not (value_errors[marker] and _validation_callback(raised, context, provenance, validators)):
            raised_markers.add(marker)
    return raised_markers


def _payload_guard(raised: ast.Raise, constructor: ast.FunctionDef, context: PythonFileContext) -> bool:
    guard = context.parents.get(raised)
    if not isinstance(guard, ast.If) or not (guard.body == [raised] or guard.orelse == [raised]):
        return False
    owner = context.parents.get(guard)
    while isinstance(owner, ast.If):
        owner = context.parents.get(owner)
    if not isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef) or owner.returns is None:
        return False
    if isinstance(owner.returns, ast.Constant) and isinstance(owner.returns.value, str):
        return False
    if has_own_yield(owner):
        return False
    if _validation_callback(raised, context, context.static_resource_provenance, {}):
        return False
    if any(
        context.imports.resolves(owner.returns, sources=frozenset({"typing", "typing_extensions"}), symbol=name)
        for name in ("Never", "NoReturn")
    ):
        return False
    return _payload_call(raised.exc, constructor.args)


def _payload_call(expression: ast.expr | None, arguments: ast.arguments) -> bool:
    if not isinstance(expression, ast.Call) or any(isinstance(argument, ast.Starred) for argument in expression.args):
        return False
    positional = [*arguments.posonlyargs, *arguments.args][1:]
    keywords = [keyword.arg for keyword in expression.keywords]
    if len(expression.args) > len(positional) or None in keywords or len(set(keywords)) != len(keywords):
        return False
    supplied = {argument.arg for argument in positional[: len(expression.args)]}
    if not supplied.isdisjoint(keywords):
        return False
    supplied.update(keyword for keyword in keywords if keyword is not None)
    if not {argument.arg for argument in arguments.posonlyargs[1:]}.isdisjoint(keywords):
        return False
    allowed = {argument.arg for argument in (*positional, *arguments.kwonlyargs)}
    required = {argument.arg for argument in positional[: len(positional) - len(arguments.defaults)]}
    required.update(
        argument.arg
        for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
        if default is None
    )
    return supplied <= allowed and required <= supplied


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
        if not isinstance(bound, ast.ClassDef) or not _marker_body(bound):
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
