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


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_BAD = (
    "from uuid import UUID\ndef same_owner(item, request):\n    return UUID(item.owner_id) == UUID(request.owner_id)\n"
)
_GOOD = "from uuid import UUID\nfrom typing import NewType\nOwnerId = NewType('OwnerId', UUID)\ndef same_owner(current: OwnerId, requested: OwnerId) -> bool:\n    return current == requested\n"


@final
class PreferValidatedUuidComparison(Rule):
    id = "prefer-validated-uuid-comparison"
    code = "SARJ562"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Validate UUID identifiers at input boundaries before comparing them.",
        rationale="Reparsing both operands while comparing identifiers moves input validation into business logic, repeats normalization and can raise on malformed input after the boundary has accepted it.",
        remediation="Parse and normalize UUIDs in the router's request schema or ingestion adapter, use the same nominal UUID-backed ID in domain and store contracts, then compare the typed values directly. Preserve canonicalization of existing string-backed data before removing constructors.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks equality/inequality where both adjacent operands directly call the import-proven uuid.UUID constructor. Imported aliases and module qualification are supported; shadowed, rebound or mutated factories abstain.",
            "Single boundary parsing, direct comparisons of typed IDs, literal values on one side, arbitrary conversion helpers and UUID attribute comparisons are not inferred. Tests remain checked; generated sources are excluded.",
            "The comparison may itself be an intentional ingestion boundary, so this remains a review warning. No autofix removes validation or changes string/UUID equality behavior.",
        ),
        examples=(
            RuleExample(
                example_id="late-reparsing",
                title="Both identifiers are reparsed at comparison time",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/router.py", _BAD),),
                focus_path=PurePosixPath("app/router.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-comparison",
                title="Compare the validated nominal identifiers",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/router.py", _GOOD),),
                focus_path=PurePosixPath("app/router.py"),
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
        provenance = context.static_resource_provenance
        findings: list[Diagnostic] = []
        for comparison in context.nodes(ast.Compare):
            operands = [comparison.left, *comparison.comparators]
            if not any(
                isinstance(operator, ast.Eq | ast.NotEq)
                and all(
                    isinstance(value, ast.Call) and provenance.runtime_import_name(value.func) == "uuid.UUID"
                    for value in (left, right)
                )
                for left, operator, right in zip(operands, comparison.ops, operands[1:], strict=False)
            ) or is_suppressed(context.source_lines, comparison.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    comparison.lineno,
                    comparison.col_offset + 1,
                    self.code,
                    "Both comparison operands are reparsed as UUIDs; validate and normalize them at the router/schema or ingestion boundary, propagate the nominal ID type, then compare typed values directly.",
                    severity=Severity.WARNING,
                )
            )
        return findings
