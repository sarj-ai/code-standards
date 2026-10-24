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


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class PreferDirectImportModule(Rule):
    id = "prefer-direct-import-module"
    code = "SARJ529"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Import import_module directly instead of accessing importlib.import_module.",
        rationale="A focused import makes the loader dependency explicit and removes repeated module qualification.",
        remediation="Use 'from importlib import import_module' and annotate importer callables with 'Callable[[str], ModuleType]'. Keep intentional module patching behind an explained local exception.",
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only provenance-resolved importlib.import_module attribute reads are checked. Other importlib APIs, direct imports, shadowed or mutated namespaces and generated code are preserved. No automatic rewrite because changing the lookup can change monkeypatch behavior.",
        ),
        examples=(
            RuleExample(
                example_id="qualified-loader",
                title="The module loader is qualified at each use",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app.py", "import importlib\nloader = importlib.import_module\n"),),
                focus_path=PurePosixPath("app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="focused-loader",
                title="Import only the loader",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app.py", "from importlib import import_module\nloader = import_module\n"),),
                focus_path=PurePosixPath("app.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None or "import_module" not in context.symbol_source:
            return []
        provenance = context.static_resource_provenance
        return [
            Diagnostic(
                context.path,
                node.lineno,
                node.col_offset + 1,
                self.code,
                "Use 'from importlib import import_module' and call 'import_module(...)' directly.",
                severity=Severity.WARNING,
            )
            for node in context.nodes(ast.Attribute)
            if node.attr == "import_module"
            and isinstance(node.ctx, ast.Load)
            and context.imports.resolved_qualified_name(node) == "importlib.import_module"
            and isinstance(node.value, ast.Name)
            and isinstance(provenance.binding(node.value.id, node), ast.alias)
            and node.value.id not in provenance.mutated
            and not provenance.wildcard
        ]
