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
from sarj_python_lint.rules._httpx_clients import (
    ASYNC_CLIENTS,
    COMPREHENSIONS,
    allocates,
    imports_untouched,
    runtime_expression,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


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
        if not imports_untouched(context, ASYNC_CLIENTS):
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
            and allocates(context, call, clients=ASYNC_CLIENTS, follow_factory=True, factories=factories)
            and not context.suppressions.is_suppressed(call.lineno, self.code)
        ]
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _in_constructor(context: PythonFileContext, call: ast.Call, constructors: frozenset[ast.FunctionDef]) -> bool:
    if not runtime_expression(context, call):
        return False
    scope = context.binding_inventory.scope(call)
    while isinstance(scope, (ast.ClassDef, *COMPREHENSIONS)):
        if isinstance(scope, ast.ClassDef) and (scope.bases or scope.keywords):
            return False
        if isinstance(scope, ast.GeneratorExp) and not context.resource_provenance.contains(
            scope.generators[0].iter, call
        ):
            return False
        scope = context.binding_inventory.scope(scope)
    return scope in constructors
