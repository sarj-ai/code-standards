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
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext

_BAD = "def group(rows):\n    groups = {}\n    for key, value in rows:\n        groups.setdefault(key, []).append(value)\n    return dict(groups)\n"
_GOOD = "from collections import defaultdict\ndef group(rows):\n    groups = defaultdict(list)\n    for key, value in rows:\n        groups[key].append(value)\n    return dict(groups)\n"
_SETDEFAULT_ARGUMENTS = 2


@final
class PreferDefaultdict(Rule):
    id = "prefer-defaultdict"
    code = "SARJ579"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Use defaultdict(list) for a locally owned list-grouping dictionary.",
        rationale="setdefault(key, []) constructs a new empty list on every grouping iteration, including keys already present. A declared list factory keeps initialization in one place and avoids discarded defaults for repeated keys.",
        remediation="Use collections.defaultdict(list) for this local accumulator and append through groups[key]. Preserve ordering, missing-key behavior and the concrete type at any returned boundary.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks only fresh function-local empty dict literals whose stable binding is used for loop-local setdefault(key, []).append(value) and read-only items/keys/values or native len/dict calls.",
            "Returned dictionaries, indexing, get/membership probes, aliases, captures, rebinding and opaque escapes abstain because defaultdict can change missing-key and concrete-type behavior. Nonempty defaults, custom mappings, grouping outside loops and loop else suites remain allowed.",
            "One finding is emitted per local accumulator. Cardinality and repeated-key frequency are not inferred; this is an organization grouping policy rather than a guaranteed speedup. Tests remain in scope; generated or malformed sources are excluded. No automatic rewrite changes mapping behavior.",
        ),
        examples=(
            RuleExample(
                example_id="list-grouping",
                title="A loop repeats the list default",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/group.py", _BAD),),
                focus_path=PurePosixPath("app/group.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-list-factory",
                title="The accumulator declares one list factory",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/group.py", _GOOD),),
                focus_path=PurePosixPath("app/group.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None or "setdefault" not in context.symbol_source:
            return []
        facts = AnnotationOrigins(context)
        if facts.provenance.wildcard or facts.provenance.dynamic_namespace:
            return []
        findings: list[Diagnostic] = []
        reported: set[ast.AST] = set()
        for call in context.nodes(ast.Call):
            receiver = _grouping_receiver(call, context)
            if receiver is None:
                continue
            binding = facts.provenance.binding(receiver.id, receiver)
            if binding is None or binding in reported or not _local_accumulator(receiver, binding, facts):
                continue
            reported.add(binding)
            if not context.suppressions.is_suppressed(call.lineno, self.code):
                findings.append(
                    Diagnostic(
                        context.path,
                        call.lineno,
                        call.col_offset + 1,
                        self.code,
                        "Declare defaultdict(list) for this local grouping accumulator instead of allocating [] in every setdefault call; preserve missing-key and return-type contracts.",
                        severity=Severity.ERROR,
                    )
                )
        return findings


def _grouping_receiver(call: ast.Call, context: PythonFileContext) -> ast.Name | None:
    if not (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "setdefault"
        and isinstance(call.func.value, ast.Name)
        and len(call.args) == _SETDEFAULT_ARGUMENTS
        and not call.keywords
        and isinstance(call.args[1], ast.List)
        and not call.args[1].elts
    ):
        return None
    attribute = context.parents.get(call)
    append = context.parents.get(attribute) if attribute is not None else None
    if not (
        isinstance(attribute, ast.Attribute)
        and attribute.attr == "append"
        and isinstance(append, ast.Call)
        and append.func is attribute
        and len(append.args) == 1
        and not append.keywords
    ):
        return None
    current: ast.AST = append
    while (parent := context.parents.get(current)) is not None:
        match parent:
            case ast.For() | ast.AsyncFor() | ast.While():
                return call.func.value if current in parent.body else None
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Lambda():
                return None
            case _:
                pass
        current = parent
    return None


def _local_accumulator(receiver: ast.Name, binding: ast.AST, facts: AnnotationOrigins) -> bool:
    context = facts.context
    scope = facts.provenance.scope(binding)
    if not isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef) or not isinstance(binding, ast.Name):
        return False
    declaration = context.parents.get(binding)
    if not (
        isinstance(declaration, ast.Assign | ast.AnnAssign)
        and isinstance(declaration.value, ast.Dict)
        and not declaration.value.keys
    ):
        return False
    if isinstance(declaration, ast.Assign) and len(declaration.targets) != 1:
        return False
    reads = facts.provenance.binding_reads(receiver.id, binding)
    return bool(reads) and all(facts.provenance.scope(read) is scope and _grouping_read(read, facts) for read in reads)


def _grouping_read(read: ast.Name, facts: AnnotationOrigins) -> bool:
    context = facts.context
    parent = context.parents.get(read)
    if isinstance(parent, ast.Attribute):
        call = context.parents.get(parent)
        if not isinstance(call, ast.Call) or call.func is not parent:
            return False
        if parent.attr == "setdefault":
            return _grouping_receiver(call, context) is read
        return parent.attr in {"items", "keys", "values"} and not call.args and not call.keywords
    return (
        isinstance(parent, ast.Call)
        and len(parent.args) == 1
        and parent.args[0] is read
        and not parent.keywords
        and any(facts.builtin(parent.func, name, parent) for name in ("dict", "len"))
    )
