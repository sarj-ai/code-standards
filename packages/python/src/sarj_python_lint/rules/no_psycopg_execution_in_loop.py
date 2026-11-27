from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
)
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
from sarj_python_lint.rules._store_writes import depends_on_target, discarded_call, known_single_iteration, sql_query
from sarj_python_lint.rules.no_psycopg_execution_outside_injected_owner import psycopg_execution_calls


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_BAD = "from psycopg import AsyncConnection\nasync def remove(connection: AsyncConnection, rows):\n    for row in rows:\n        await connection.execute('DELETE FROM item WHERE id = %s', (row.id,))\n"
_GOOD = "from psycopg import AsyncConnection\nasync def remove(connection: AsyncConnection, rows):\n    identifiers = [row.id for row in rows]\n    await connection.execute('DELETE FROM item WHERE id = ANY(%s)', (identifiers,))\n"
_EXECUTEMANY_BAD = "from psycopg import AsyncCursor\nasync def save(cursor: AsyncCursor, rows):\n    for row in rows:\n        await cursor.execute('INSERT INTO users (id) VALUES (%s)', (row.id,))\n"
_EXECUTE_ARGUMENT_COUNT = 2


@final
class NoPsycopgExecutionInLoop(Rule):
    id = "no-psycopg-execution-in-loop"
    code = "SARJ560"
    documentation = RuleDocumentation(
        aliases=("prefer-psycopg-executemany",),
        default_level=Severity.WARNING,
        summary="Use bounded bulk queries instead of executing Psycopg operations inside item loops.",
        rationale="Executing a database operation for each input item makes round trips scale with collection size, including loops that prepare each row before executing.",
        remediation="Collect inputs and use a bounded set-based query, typed bulk store operation or executemany batch. Preserve tenant checks, revision predicates, transaction boundaries, returned rows, ordering and deliberate sequential effects.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks import-proven Psycopg execute calls in for/async-for bodies and repeated comprehension expressions, including injected pools, connections and cursors. Explicit executemany batch loops remain valid for bounded chunking.",
            "In-memory preparation, one-shot iteration inputs, known zero/single-item loops, deferred nested functions, unrelated execute methods and generated code are excluded. While retry/stream loops and interprocedural helper execution are not inferred.",
            "A serial loop of one invariant parameterized write on a typed cursor parameter receives the specific executemany message instead of the general one at the same call. Unknown SQL and result-consuming loops still require bulk-query review; no automatic rewrite changes database semantics.",
            "Only a synchronous for loop with one discarded execute call on an import-proven typed Psycopg Cursor or AsyncCursor parameter is inspected. The query must be one literal INSERT, UPDATE or DELETE with placeholders and loop-dependent bound parameters.",
            "RETURNING, queries, dynamic SQL, extra execute options, async streams, loop else clauses, additional statements and per-row exception or transaction contexts are excluded. Connection.execute is excluded because connections do not expose the same executemany API.",
            "No automatic batching or performance claim is made for a particular workload. Advisory severity preserves deliberately sequential database effects; exact suppressions document those contracts.",
            "Generated/vendor sources are excluded; maintained tests are checked. Stable aliases and cursors acquired through context managers are intentionally outside the initial proof boundary.",
            "Cursor state reads, iteration and opaque cursor escapes are excluded: executemany accumulates rowcount and can change observable execution interleaving.",
        ),
        examples=(
            RuleExample(
                example_id="per-item-write",
                title="A connection executes once per item",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/store.py", _BAD),),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="set-based-write",
                title="One query consumes the collected identifiers",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/store.py", _GOOD),),
                focus_path=PurePosixPath("app/store.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="serial-execute",
                scenario="executemany",
                title="Batch the same parameterized statement",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/user_store.py", _EXECUTEMANY_BAD),),
                focus_path=PurePosixPath("app/user_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="batch-execute",
                scenario="executemany",
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
        if context.generated or context.tree is None:
            return []
        findings = self._batchable_writes(context)
        specific_positions = {(finding.line, finding.col) for finding in findings}
        calls = [
            call
            for call in psycopg_execution_calls(context, include_injected=True, include_probes=False)
            if isinstance(call.func, ast.Attribute) and call.func.attr == "execute" and _repeated(call, context)
        ]
        unique = {(call.lineno, call.col_offset): call for call in calls}
        findings.extend(
            Diagnostic(
                context.path,
                call.lineno,
                call.col_offset + 1,
                self.code,
                "This item loop executes a Psycopg operation per iteration; collect inputs and prefer a bounded bulk query or bulk store method, preserving transaction, result and failure semantics.",
                severity=Severity.WARNING,
            )
            for call in unique.values()
            if not context.suppressions.is_suppressed(call.lineno, self.code)
            and (call.lineno, call.col_offset + 1) not in specific_positions
        )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))

    def _batchable_writes(self, context: PythonFileContext) -> list[Diagnostic]:
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
            if not depends_on_target(call.args[1], loop.target) or context.suppressions.is_suppressed(
                call.lineno, self.code
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


def _repeated(call: ast.Call, context: PythonFileContext) -> bool:
    child: ast.AST = call
    parent = context.parents.get(child)
    while parent is not None:
        match parent:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.Lambda() | ast.ClassDef():
                return False
            case ast.For() | ast.AsyncFor() if child in parent.body and not known_single_iteration(parent.iter):
                return True
            case ast.comprehension() if _comprehension_repeats(parent, child, context):
                return True
            case ast.ListComp() | ast.SetComp() | ast.GeneratorExp() if child is parent.elt and not _at_most_once(
                parent.generators
            ):
                return True
            case ast.DictComp() if child in {parent.key, parent.value} and not _at_most_once(parent.generators):
                return True
            case _:
                pass
        child, parent = parent, context.parents.get(parent)
    return False


def _comprehension_repeats(parent: ast.comprehension, child: ast.AST, context: PythonFileContext) -> bool:
    owner = context.parents.get(parent)
    if not isinstance(owner, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
        return False
    index = owner.generators.index(parent)
    if child in parent.ifs:
        return not _at_most_once(owner.generators[: index + 1])
    return child is parent.iter and index > 0 and not _at_most_once(owner.generators[:index])


def _at_most_once(generators: list[ast.comprehension]) -> bool:
    return any(_empty(item.iter) for item in generators) or all(
        known_single_iteration(item.iter) for item in generators
    )


def _empty(iterable: ast.expr) -> bool:
    match iterable:
        case ast.List(elts=[]) | ast.Tuple(elts=[]) | ast.Set(elts=[]) | ast.Dict(keys=[]):
            return True
        case ast.Constant(value=str() | bytes() as value):
            return not value
        case _:
            return False


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
