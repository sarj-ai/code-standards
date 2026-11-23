from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
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
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_WRITE_METHODS = frozenset({"post", "put", "patch", "delete"})
_MUTATION = re.compile(
    r"^(?:delete|remove|update|set|replace|upsert|disable|enable|archive|revoke|cancel|clear|rename|move"
    r"|assign|unassign|patch|toggle|mark)(?:_|$)"
)
_SCOPE_NAMES = frozenset({"organization_id", "organization", "subject"})
_ORGANIZATION_ID = frozenset({"organization_id"})


def _example(*, example_id: str, title: str, source: str, matches: bool, public: bool = True) -> RuleExample:
    return RuleExample(
        example_id=example_id,
        title=title,
        outcome=ExampleOutcome.MATCH if matches else ExampleOutcome.NO_MATCH,
        files=(ExampleFile.python("app/routes.py", source),),
        focus_path=PurePosixPath("app/routes.py"),
        expected_count=1 if matches else 0,
        public=public,
    )


@final
class RouteMutationRequiresOrganizationScope(Rule):
    id = "route-mutation-requires-organization-scope"
    code = "SARJ595"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Scope store mutations in FastAPI write routes to the route's organization_id",
        rationale=(
            "A write route that resolves the caller's organization_id but mutates a store by other keys alone can "
            "change another tenant's record whenever those keys collide or are guessed. An automation delete keyed "
            "only by merchant and event type removed rows outside the requesting organization."
        ),
        remediation=(
            "Pass the route's organization_id (or the resolved organization or subject) to the store mutation and "
            "filter the write by it, directly or through a request object built from organization_id."
        ),
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Checks functions decorated with a `.post`, `.put`, `.patch` or `.delete` call that declare an "
                "`organization_id` parameter. Receivers must end in `store` or `_store` and methods must start "
                "with a mutation verb such as delete, update, set or upsert."
            ),
            (
                "A call is scoped when an argument mentions organization_id, organization or subject, or is a local "
                "name whose assignment mentions organization_id. Scoping inside the store or through other aliases "
                "is not traced."
            ),
            "Tests and generated code are excluded.",
        ),
        examples=(
            _example(
                example_id="unscoped-store-delete",
                title="A delete route ignores the organization_id it receives",
                source=(
                    "@router.delete('/automations/{merchant_id}/{event_type}')\n"
                    "async def delete_automation(merchant_id: str, event_type: str, organization_id: str) -> None:\n"
                    "    if not await automation_store.delete(merchant_id, event_type):\n"
                    "        raise HTTPException(status_code=404)\n"
                ),
                matches=True,
            ),
            _example(
                example_id="scoped-store-delete",
                title="The store mutation receives the route's organization_id",
                source=(
                    "@router.delete('/automations/{merchant_id}/{event_type}')\n"
                    "async def delete_automation(merchant_id: str, event_type: str, organization_id: str) -> None:\n"
                    "    if not await automation_store.delete(merchant_id, event_type, organization_id):\n"
                    "        raise HTTPException(status_code=404)\n"
                ),
                matches=False,
            ),
            _example(
                example_id="scoped-request-object",
                title="The mutation receives a request built from organization_id",
                source=(
                    "@router.post('/webhooks')\n"
                    "async def upsert_webhook(url: str, organization_id: str) -> Webhook:\n"
                    "    data = UpsertWebhook(organization_id=organization_id, url=url)\n"
                    "    return await webhook_store.upsert(data)\n"
                ),
                matches=False,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if is_test_path(context.path) or context.generated or context.tree is None:
            return []
        return [
            Diagnostic(
                path=context.path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=self.code,
                message="Pass the route's organization_id to this store mutation so the write is scoped to the requesting tenant.",
                severity=Severity.WARNING,
            )
            for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef)
            if _is_scoped_write_route(function)
            for call in _unscoped_store_mutations(function)
        ]


def _is_scoped_write_route(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    arguments = function.args
    parameters = {argument.arg for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
    return "organization_id" in parameters and any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in _WRITE_METHODS
        for decorator in function.decorator_list
    )


def _unscoped_store_mutations(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    scoped_locals = _organization_bound_names(function)
    calls: list[ast.Call] = []
    for node in ast.walk(function):
        match node:
            case ast.Call(func=ast.Attribute(value=receiver, attr=method), args=args, keywords=keywords) if (
                _MUTATION.match(method) and _is_store(receiver)
            ):
                arguments = (*args, *(keyword.value for keyword in keywords))
                if not any(_is_scoped(argument, scoped_locals) for argument in arguments):
                    calls.append(node)
            case _:
                pass
    return calls


def _organization_bound_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(function):
        match node:
            case ast.Assign(targets=targets, value=value) if _mentions(value, _ORGANIZATION_ID):
                names.update(target.id for target in targets if isinstance(target, ast.Name))
            case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value) if _mentions(
                value, _ORGANIZATION_ID
            ):
                names.add(name)
            case _:
                pass
    return names


def _is_scoped(argument: ast.expr, scoped_locals: set[str]) -> bool:
    match argument:
        case ast.Name(id=name) if name in scoped_locals:
            return True
        case _:
            return _mentions(argument, _SCOPE_NAMES)


def _is_store(receiver: ast.expr) -> bool:
    match receiver:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name == "store" or name.endswith("_store")
        case _:
            return False


def _mentions(expression: ast.AST, names: frozenset[str]) -> bool:
    return any(
        (isinstance(node, ast.Name) and node.id in names) or (isinstance(node, ast.Attribute) and node.attr in names)
        for node in ast.walk(expression)
    )
