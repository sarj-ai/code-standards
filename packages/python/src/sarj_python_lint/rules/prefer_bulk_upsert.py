from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._store_writes import (
    StoreOwners,
    depends_on_target,
    discarded_call,
    method_parameters,
    upsert_pair,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_CONTRACT = "class UserStore:\n    async def upsert(self, user: UserInput) -> User:\n        ...\n    async def upsert_many(self, users: list[UserInput]) -> list[User]:\n        ...\n"


@final
class PreferBulkUpsert(ProjectRule):
    id = "prefer-bulk-upsert"
    code = "SARJ516"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use a declared compatible upsert_many instead of discarded serial upserts.",
        rationale="A loop of independent singleton writes repeats database calls while an existing bulk command centralizes conflict handling and batch execution.",
        remediation="Collect commands and call upsert_many in bounded batches after reviewing duplicate keys, failure atomicity, ordering, and tenant scope. Preserve deliberately per-row transactions or effects with an exact suppression.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only a synchronous for loop containing one discarded upsert call is considered. Its receiver must resolve to a typed parameter or a constructor-injected attribute with source-declared compatible upsert/upsert_many methods.",
            "Signatures must have one required command argument and matching scalar/collection input and output types. Annotated first-party imports use the existing project index; unresolved, inherited, overloaded, decorated, rebound and dynamic contracts are excluded.",
            "Result-dependent loops, comprehensions, async streams, loop else clauses, extra statements and per-row exception or transaction blocks are excluded. A batch can change duplicate-key and failure semantics, so this remains an advisory without an autofix.",
            "Maintained tests are checked; generated/vendor sources are excluded. A bulk method is not invented when none is declared.",
        ),
        examples=(
            RuleExample(
                example_id="serial-upserts",
                title="Collect writes for an available bulk command",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        _CONTRACT
                        + "async def save(store: UserStore, users: list[UserInput]):\n    for user in users:\n        await store.upsert(user)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="bulk-upsert",
                title="Use the existing bulk command",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        _CONTRACT
                        + "async def save(store: UserStore, users: list[UserInput]):\n    await store.upsert_many(users)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or "upsert" not in context.symbol_source or context.tree is None:
            return []
        owners = StoreOwners(context)
        if owners.provenance.dynamic_namespace:
            return []
        findings: list[Diagnostic] = []
        for loop in context.nodes(ast.For):
            call = _bulk_candidate(loop, owners)
            if call is None:
                continue
            if is_suppressed(context.source_lines, call.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message="This discarded serial upsert has a declared compatible `upsert_many`; collect commands and use bounded bulk writes after preserving duplicate-key, atomicity, and tenant semantics.",
                )
            )
        return findings


def _bulk_candidate(loop: ast.For, owners: StoreOwners) -> ast.Call | None:
    candidate = discarded_call(loop)
    if candidate is None:
        return None
    call, awaited = candidate
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "upsert":
        return None
    owner = owners.receiver(call.func.value, call)
    pair = upsert_pair(*owner) if owner is not None else None
    if pair is None or isinstance(pair[0], ast.AsyncFunctionDef) != awaited:
        return None
    parameters = method_parameters(pair[0])
    if parameters is None:
        return None
    argument = _command_argument(call, parameters[0].arg)
    if argument is None or isinstance(argument, ast.Starred) or not depends_on_target(argument, loop.target):
        return None
    return call


def _command_argument(call: ast.Call, parameter: str) -> ast.expr | None:
    if len(call.args) == 1 and not call.keywords:
        return call.args[0]
    if not call.args and len(call.keywords) == 1 and call.keywords[0].arg == parameter:
        return call.keywords[0].value
    return None
