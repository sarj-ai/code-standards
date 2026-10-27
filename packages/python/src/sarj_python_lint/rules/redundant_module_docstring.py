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
from sarj_python_lint.rules._docstrings import docstring_expression
from sarj_python_lint.rules.no_unnecessary_docstring import module_docstring_consumed


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class RedundantModuleDocstring(Rule):
    id: str = "redundant-module-docstring"
    code: str = "SARJ099"
    documentation = RuleDocumentation(
        summary="Delete top-of-file module docstrings without a detected runtime or documentation consumer.",
        rationale="Module prose creates a second maintenance surface; names and code structure should explain the implementation, with hidden constraints kept next to their owner.",
        remediation="Delete the module docstring. Preserve legal notices as comments, express ordinary meaning through names and types, and move a necessary hidden constraint next to the code it governs. Keep externally consumed documentation with an explained exact-code exception.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        aliases=("module-docstring-restates-path",),
        limitations=(
            "The historical rule ID is retained for compatibility, but every unconsumed module docstring is checked, including multiline prose, tests, special modules, stubs and executable scripts.",
            "Generated files, doctests, explicit __doc__/help/getdoc consumers and exact SARJ099 suppressions are excluded. Module consumer analysis is shared with SARJ420; when both rules are selected, SARJ099 takes diagnostic precedence.",
            "Safe fixes delete standalone module docstrings only when SARJ420 also confirms no detected consumer. Visible dynamic namespace or frame observation, module escapes, adjacent strings, comments within the expression, same-line code and trailing comments prevent fixes.",
            "A fix must retain source encoding and shebang interpretation. Unknown external documentation consumers require an explained local exception; classes and callable documentation remain owned by SARJ420.",
            "Imports of __main__ or pydoc conservatively withhold module fixes because they can publish the module or its help. They do not establish that an imported __main__ is the current module, so diagnostics still require an explicit consumer proof or exception.",
            "Legal/license notices are never automatically deleted. Keep their text as comments when removing the surrounding module docstring manually.",
        ),
        examples=(
            RuleExample(
                example_id="module-prose",
                title="Delete the module's implementation walkthrough",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py", '"""Service entry points.\n\nCoordinates requests.\n"""\nVALUE = 1\n'
                    ),
                ),
                fixed_files=(ExampleFile.python("app/service.py", "VALUE = 1\n"),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="module-consumer",
                title="Keep a module description consumed at runtime",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/service.py", '"""Service command help."""\nDESCRIPTION = __doc__\n'),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="safe-autofix-subset",
                title="Unconsumed module prose has a convergent deletion fix",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/service.py", '"""Service module."""\nVALUE = 1\n'),),
                fixed_files=(ExampleFile.python("app/service.py", "VALUE = 1\n"),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        tree = context.tree
        if context.generated or tree is None:
            return []
        expression = docstring_expression(tree)
        if expression is None or ">>>" in (ast.get_docstring(tree, clean=False) or ""):
            return []
        if module_docstring_consumed(context) or is_suppressed(
            context.source_lines, expression.end_lineno or expression.lineno, self.code
        ):
            return []
        return [
            Diagnostic(
                path=context.path,
                line=expression.lineno,
                col=expression.col_offset + 1,
                code=self.code,
                message=self.description,
                severity=Severity.ERROR,
            )
        ]
