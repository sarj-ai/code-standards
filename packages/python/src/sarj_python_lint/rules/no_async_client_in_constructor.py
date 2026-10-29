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
from sarj_python_lint.rules._resource_provenance import import_name_for_binding


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_CLIENTS = frozenset({"httpx.AsyncClient", "httpx._client.AsyncClient"})
_MODULES = frozenset({"httpx", "httpx._client"})
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_MAX_ALIAS_DEPTH = 32
_BAD = "import httpx\nclass Service:\n    def __init__(self):\n        self.client = httpx.AsyncClient()\n"
_GOOD = "from contextlib import asynccontextmanager\nimport httpx\nclass Service:\n    def __init__(self, client: httpx.AsyncClient):\n        self.client = client\n@asynccontextmanager\nasync def service_scope(endpoint):\n    async with httpx.AsyncClient(base_url=endpoint) as client:\n        yield Service(client)\n"


@final
class NoAsyncClientInConstructor(Rule):
    id = "no-async-client-in-constructor"
    code = "SARJ549"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Inject an HTTPX AsyncClient instead of constructing one in __init__.",
        rationale="Constructor-owned clients repeat transport setup for each service instance and hide the boundary that owns pooling and asynchronous cleanup.",
        remediation="Create and close an appropriately scoped AsyncClient at the async composition boundary, and inject it into consumers. Keep tenant credentials, cookies, event loops and independent ownership boundaries separate; do not replace them with a global client.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This is an explicit architecture policy for import-proven HTTPX AsyncClient calls executed by synchronous nongenerator class __init__ methods, including import aliases and stable constructor assignment aliases bounded to 32 links, eager comprehensions and nested definition defaults/decorators.",
            "One-hop same-file undecorated synchronous factories with stable lexical bindings are followed only when their sole statement after an optional docstring returns a proven constructor call. Zero-argument lambda factories are supported when invoked; deferred function/lambda/generator bodies are not constructor execution.",
            "Unknown or imported factory implementations, overridable methods, wrapper chains, dynamic namespace access, wildcard imports, ambiguous/rebound aliases and visible namespace mutation are not inferred. A generator's first iterable is eager; other generator expressions remain deferred even when a caller might consume them immediately.",
            "Constructor parameter defaults execute at class definition, not on each constructor call, and are outside this rule. No automatic ownership transfer, sharing decision or lifecycle rewrite is safe.",
            "Annotations and lazy type-alias/type-parameter expressions are excluded: their source location does not prove constructor-time execution. Framework-driven evaluation of annotations is not inferred.",
            "Escaped HTTPX module objects cause conservative abstention, including module-object assignment aliases. Constructor aliases must remain confined to calls, annotations, attribute access or stable single-name aliases; unknown argument, return or storage escapes and visible mutation invalidate the import proof.",
            "Nested class bodies are followed only without bases or metaclass keywords, because custom class namespace preparation can replace imported names. Method bodies still use their normal lexical bindings. Generator factories and lambdas create deferred generators rather than clients and are excluded.",
            "HTTPX recommends scoped client reuse and explicit asynchronous closure; its API does not universally prohibit constructor ownership. This stricter constructor boundary is the requested policy. See https://www.python-httpx.org/async/ . Ruff ASYNC212 instead owns blocking HTTPX use in async functions.",
        ),
        examples=(
            RuleExample(
                example_id="constructor-allocation",
                title="Do not hide client allocation in a service constructor",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/service.py", _BAD),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="scoped-injection",
                title="Inject a client owned by the async composition scope",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/service.py", _GOOD),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "__init__" not in context.symbol_source or "AsyncClient" not in context.symbol_source:
            return []
        if context.generated or context.tree is None or context.has_wildcard_import or context.dynamic_namespace:
            return []
        if not _imports_untouched(context):
            return []
        constructors = frozenset(
            node
            for node in context.nodes(ast.FunctionDef)
            if node.name == "__init__"
            and isinstance(context.parents.get(node), ast.ClassDef)
            and not has_own_yield(node)
        )
        factories: dict[ast.FunctionDef | ast.Lambda, bool] = {}
        findings = [
            Diagnostic(
                path=context.path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=self.code,
                severity=Severity.ERROR,
                message="httpx.AsyncClient construction in __init__; inject a caller-owned, appropriately scoped AsyncClient and close it at the async composition boundary",
            )
            for call in context.nodes(ast.Call)
            if _in_constructor(context, call, constructors)
            and _allocates(context, call, follow_factory=True, factories=factories)
            and not is_suppressed(context.source_lines, call.lineno, self.code)
        ]
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _imports_untouched(context: PythonFileContext) -> bool:
    safe: dict[ast.alias | ast.Name, bool] = {}
    for binding in context.nodes(ast.alias):
        expression = ast.Name(id=binding.asname or binding.name, ctx=ast.Load())
        qualified = import_name_for_binding(expression, binding, context.parents.get(binding))
        if (
            qualified is not None
            and qualified in _MODULES | _CLIENTS
            and not _alias_untouched(context, binding, qualified, safe, remaining=_MAX_ALIAS_DEPTH)
        ):
            return False
    return True


def _alias_untouched(
    context: PythonFileContext,
    binding: ast.alias | ast.Name,
    qualified: str,
    safe: dict[ast.alias | ast.Name, bool],
    *,
    remaining: int,
) -> bool:
    if binding in safe:
        return safe[binding]
    safe[binding] = False
    name = binding.id if isinstance(binding, ast.Name) else binding.asname or binding.name.partition(".")[0]
    if remaining == 0 or name in context.binding_inventory.mutated:
        return False
    safe[binding] = all(
        _reference_untouched(context, read, qualified, safe, remaining=remaining)
        for read in context.nodes(ast.Name)
        if isinstance(read.ctx, ast.Load) and read.id == name and _binding(context, name, read) is binding
    )
    return safe[binding]


def _reference_untouched(
    context: PythonFileContext,
    expression: ast.expr,
    qualified: str,
    safe: dict[ast.alias | ast.Name, bool],
    *,
    remaining: int,
) -> bool:
    if not _runtime_expression(context, expression):
        return True
    while qualified in _MODULES:
        parent = context.parents.get(expression)
        if not isinstance(parent, ast.Attribute) or parent.value is not expression:
            return False
        expression, qualified = parent, f"{qualified}.{parent.attr}"
    if qualified not in _CLIENTS:
        return True
    parent = context.parents.get(expression)
    if (isinstance(parent, ast.Call) and parent.func is expression) or (
        isinstance(parent, ast.Attribute) and parent.value is expression
    ):
        return True
    target = _alias_target(context, parent, expression)
    return target is not None and _alias_untouched(context, target, qualified, safe, remaining=remaining - 1)


def _alias_target(context: PythonFileContext, statement: ast.AST | None, value: ast.expr) -> ast.Name | None:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and statement.value is value:
        target = statement.targets[0]
    elif isinstance(statement, ast.AnnAssign) and statement.value is value:
        target = statement.target
    else:
        return None
    if not isinstance(context.parents.get(statement), ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
        return None
    return target if isinstance(target, ast.Name) and _binding(context, target.id, target) is target else None


def _in_constructor(context: PythonFileContext, call: ast.Call, constructors: frozenset[ast.FunctionDef]) -> bool:
    if not _runtime_expression(context, call):
        return False
    scope = context.binding_inventory.scope(call)
    while isinstance(scope, (ast.ClassDef, *_COMPREHENSIONS)):
        if isinstance(scope, ast.ClassDef) and (scope.bases or scope.keywords):
            return False
        if isinstance(scope, ast.GeneratorExp) and not context.resource_provenance.contains(
            scope.generators[0].iter, call
        ):
            return False
        scope = context.binding_inventory.scope(scope)
    return scope in constructors


def _runtime_expression(context: PythonFileContext, expression: ast.expr) -> bool:
    child: ast.AST = expression
    parent = context.parents.get(child)
    while parent is not None:
        if isinstance(parent, ast.TypeAlias | ast.type_param):
            return False
        if isinstance(parent, ast.AnnAssign | ast.arg) and parent.annotation is child:
            return False
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef) and parent.returns is child:
            return False
        child, parent = parent, context.parents.get(parent)
    return True


def _allocates(
    context: PythonFileContext,
    call: ast.Call,
    *,
    follow_factory: bool,
    factories: dict[ast.FunctionDef | ast.Lambda, bool],
) -> bool:
    target = _target(context, call.func)
    if isinstance(target, str):
        return target in _CLIENTS
    if not follow_factory or not isinstance(target, ast.FunctionDef | ast.Lambda):
        return False
    if isinstance(target, ast.Lambda):
        arguments = target.args
        if any(
            (
                call.args,
                call.keywords,
                arguments.posonlyargs,
                arguments.args,
                arguments.kwonlyargs,
                arguments.vararg,
                arguments.kwarg,
            )
        ):
            return False
    if target not in factories:
        factories[target] = _factory_allocates(context, target, factories)
    return factories[target]


def _factory_allocates(
    context: PythonFileContext,
    target: ast.FunctionDef | ast.Lambda,
    factories: dict[ast.FunctionDef | ast.Lambda, bool],
) -> bool:
    if has_own_yield(target):
        return False
    if isinstance(target, ast.Lambda):
        return isinstance(target.body, ast.Call) and _allocates(
            context, target.body, follow_factory=False, factories=factories
        )
    if target.decorator_list:
        return False
    body = target.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return (
        len(body) == 1
        and isinstance(body[0], ast.Return)
        and isinstance(body[0].value, ast.Call)
        and _allocates(context, body[0].value, follow_factory=False, factories=factories)
    )


def _target(context: PythonFileContext, expression: ast.expr) -> str | ast.FunctionDef | ast.Lambda | None:
    for _ in range(_MAX_ALIAS_DEPTH):
        if isinstance(expression, ast.Lambda):
            return expression
        root = expression
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name) or root.id in context.binding_inventory.mutated:
            return None
        binding = _binding(context, root.id, expression)
        if isinstance(binding, ast.alias):
            return import_name_for_binding(expression, binding, context.parents.get(binding))
        if not isinstance(expression, ast.Name):
            return None
        if isinstance(binding, ast.FunctionDef):
            return _factory_binding(context, binding, expression)
        if not isinstance(binding, ast.Name):
            return None
        value = context.resource_provenance.assignment_value(binding, expression)
        if value is None:
            return None
        expression = value
    return None


def _factory_binding(context: PythonFileContext, definition: ast.FunctionDef, at: ast.expr) -> ast.FunctionDef | None:
    parent = context.parents.get(definition)
    if parent is context.tree:
        return definition
    if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef) and definition.lineno < at.lineno:
        return definition
    return None


def _binding(context: PythonFileContext, name: str, at: ast.AST) -> ast.AST | None:
    if (binding := context.resource_provenance.runtime_binding(name, at)) is not None:
        return binding
    scope = context.binding_inventory.scope(at)
    lambda_body = False
    while isinstance(scope, (*_COMPREHENSIONS, ast.Lambda)):
        lambda_body |= isinstance(scope, ast.Lambda)
        first_iterable = isinstance(scope, _COMPREHENSIONS) and context.resource_provenance.contains(
            scope.generators[0].iter, at
        )
        if not first_iterable and name in context.binding_inventory.bindings.get(scope, {}):
            return None
        scope = context.binding_inventory.scope(scope)
    bindings = context.runtime_bindings.lookup(scope, name)
    if bindings is None and lambda_body:
        return _lambda_module_binding(context, scope, name)
    return bindings[0] if bindings is not None and len(bindings) == 1 else None


def _lambda_module_binding(context: PythonFileContext, scope: ast.AST | None, name: str) -> ast.AST | None:
    if name in context.binding_inventory.external_bindings:
        return None
    while scope is not context.tree:
        if scope is None:
            return None
        if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef) and name in context.binding_inventory.bindings.get(
            scope, {}
        ):
            return None
        scope = context.binding_inventory.scope(scope)
    bindings = context.runtime_bindings.lookup(scope, name)
    return bindings[0] if bindings is not None and len(bindings) == 1 else None
