from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sqlglot import exp

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
from sarj_python_lint.rules._store_writes import depends_on_target, discarded_call, sql_query


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_BAD = "from psycopg import AsyncCursor\nasync def save(cursor: AsyncCursor, rows):\n    for row in rows:\n        await cursor.execute('INSERT INTO users (id) VALUES (%s)', (row.id,))\n"
_EXECUTE_ARGUMENT_COUNT = 2


@final
class PreferPsycopgExecutemany(Rule):
    id = "prefer-psycopg-executemany"
    code = "SARJ518"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use Psycopg executemany for a serial loop of invariant parameterized writes without row results.",
        rationale="A bare execute loop repeats the same statement through separate client calls. Psycopg executemany centralizes batch execution and can pipeline those operations.",
        remediation="Prefer an existing bulk store method; otherwise send bounded parameter batches through cursor.executemany. Preserve transaction ownership, per-row failure behavior, ordering and backpressure.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only a synchronous for loop with one discarded execute call on an import-proven typed Psycopg Cursor or AsyncCursor parameter is inspected. The query must be one literal INSERT, UPDATE or DELETE with placeholders and loop-dependent bound parameters.",
            "RETURNING, queries, dynamic SQL, extra execute options, async streams, loop else clauses, additional statements and per-row exception or transaction contexts are excluded. Connection.execute is excluded because connections do not expose the same executemany API.",
            "No automatic batching or performance claim is made for a particular workload. Advisory severity preserves deliberately sequential database effects; exact suppressions document those contracts.",
            "Generated/vendor sources are excluded; maintained tests are checked. Stable aliases and cursors acquired through context managers are intentionally outside the initial proof boundary.",
            "Cursor state reads, iteration and opaque cursor escapes are excluded: executemany accumulates rowcount and can change observable execution interleaving.",
        ),
        examples=(
            RuleExample(
                example_id="serial-execute",
                title="Batch the same parameterized statement",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/user_store.py", _BAD),),
                focus_path=PurePosixPath("app/user_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="batch-execute",
                title="Use the cursor's batch API",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/user_store.py",
                        "from psycopg import AsyncCursor\nasync def save(cursor: AsyncCursor, rows):\n    await cursor.executemany('INSERT INTO users (id) VALUES (%s)', [(row.id,) for row in rows])\n",
                    ),
                ),
                focus_path=PurePosixPath("app/user_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or "execute" not in context.symbol_source or context.tree is None:
            return []
        provenance = context.static_resource_provenance
        findings: list[Diagnostic] = []
        for loop in context.nodes(ast.For):
            candidate = discarded_call(loop)
            if candidate is None:
                continue
            call, awaited = candidate
            if (
                not isinstance(call.func, ast.Attribute)
                or call.func.attr != "execute"
                or not isinstance(call.func.value, ast.Name)
                or len(call.args) != _EXECUTE_ARGUMENT_COUNT
                or call.keywords
            ):
                continue
            qualified = _cursor_contract(call.func.value, call, context, provenance)
            if qualified not in {"psycopg.Cursor", "psycopg.AsyncCursor"} or awaited != (
                qualified == "psycopg.AsyncCursor"
            ):
                continue
            if not _cursor_uses_are_batch_safe(call.func.value, call, context, provenance):
                continue
            query = sql_query(call.args[0], context.imports)
            if (
                not isinstance(query, exp.Insert | exp.Update | exp.Delete)
                or query.find(exp.Returning) is not None
                or query.find(exp.Placeholder) is None
            ):
                continue
            if not depends_on_target(call.args[1], loop.target) or is_suppressed(
                context.source_lines, call.lineno, self.code
            ):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message="This loop repeats one parameterized Psycopg write without row results; prefer the existing bulk store command or bounded `cursor.executemany()` batches, preserving transaction and failure semantics.",
                )
            )
        return findings


def _cursor_uses_are_batch_safe(
    receiver: ast.Name, call: ast.Call, context: PythonFileContext, provenance: ResourceProvenance
) -> bool:
    binding = provenance.binding(receiver.id, call)
    for read in provenance.reads.get(receiver.id, ()):
        if provenance.binding(receiver.id, read) is not binding:
            continue
        attribute = context.parents.get(read)
        if not isinstance(attribute, ast.Attribute):
            return False
        invocation = context.parents.get(attribute)
        if (
            attribute.value is not read
            or attribute.attr not in {"execute", "executemany", "close"}
            or not isinstance(invocation, ast.Call)
            or invocation.func is not attribute
        ):
            return False
    return True


def _cursor_contract(
    receiver: ast.Name, call: ast.Call, context: PythonFileContext, provenance: ResourceProvenance
) -> str | None:
    binding = provenance.binding(receiver.id, call)
    if not isinstance(binding, ast.arg) or context.tree is None or provenance.dynamic_namespace or provenance.wildcard:
        return None
    annotation = AnnotationSemantics.parse(binding.annotation)
    if isinstance(annotation, ast.Subscript):
        annotation = annotation.value
    root = annotation.value if isinstance(annotation, ast.Attribute) else annotation
    if isinstance(root, ast.Name) and root.id in provenance.mutated:
        return None
    return context.module_imports.resolved_qualified_name(annotation) if annotation is not None else None
