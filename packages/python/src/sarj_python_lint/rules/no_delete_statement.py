from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final

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


@final
class NoDeleteStatement(Rule):
    id = "no-delete-statement"
    code = "SARJ442"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Avoid `del` statements; prefer constructing an immutable replacement value.",
        rationale=(
            "Deleting a name, attribute, or collection entry introduces lifetime or in-place mutation semantics "
            "that are harder to follow than explicit value construction."
        ),
        remediation=(
            "Remove unused-value deletion markers. Rebuild collections with comprehensions, copies, or immutable "
            "value helpers such as dataclasses.replace. When an external API or deliberate lifetime boundary "
            "requires deletion, add an exact SARJ442 suppression on the statement and explain why."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        aliases=("no-deleted-only-override-parameter",),
        limitations=(
            "Every authored Python del statement is reported once, regardless of how many targets it contains.",
            "Autofix only blanks one standalone, comment-free local deletion in a closed private nested ordinary helper with no parameters and exactly a None assignment to that same name, that deletion, and a literal return. Existing names, the assignment, line numbers and line endings remain unchanged; multiline deletion and unsupported source line separators are refused; all other deletion requires review.",
            "Containing callables must have proven inert execution and no observable helper references, frame or metadata access, callbacks, reachable failures or unknown finalizers. Only proven local None deletion is modeled; deleted names retain an unbound tombstone so subsequent reads cannot resolve to a builtin or global.",
            "Generated and vendored files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="closed-none-deletion",
                title="Remove a redundant None deletion marker",
                outcome=ExampleOutcome.MATCH,
                scenario="closed-none-deletion",
                files=(
                    ExampleFile.python(
                        "app/request.py",
                        "def ready():\n    def _ready():\n        unused = None\n        del unused\n        return True\n    return _ready()\n",
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/request.py",
                        "def ready():\n    def _ready():\n        unused = None\n\n        return True\n    return _ready()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/request.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="closed-none-deletion-removed",
                title="The retained assignment has no lifetime marker",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="closed-none-deletion",
                files=(
                    ExampleFile.python(
                        "app/request.py",
                        "def ready():\n    def _ready():\n        unused = None\n\n        return True\n    return _ready()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/request.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="delete-mapping-entry",
                title="Build a mapping without the removed entry",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/request.py",
                        "payload = dict(raw_payload)\ndel payload['secret']\n",
                    ),
                ),
                focus_path=PurePosixPath("app/request.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="immutable-mapping-filter",
                title="Construct the desired mapping directly",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/request.py",
                        "payload = {key: value for key, value in raw_payload.items() if key != 'secret'}\n",
                    ),
                ),
                focus_path=PurePosixPath("app/request.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        source = context.source
        if "del" not in source or context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        source_lines = context.source_lines
        return [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                severity=Severity.ERROR,
                message=(
                    "`del` introduces mutation or hidden lifetime behavior — construct the desired value "
                    "immutably, or add an exact SARJ442 suppression explaining why deletion is required."
                ),
            )
            for node in context.nodes(ast.AST)
            if isinstance(node, ast.Delete) and not is_suppressed(source_lines, node.lineno, self.code)
        ]
