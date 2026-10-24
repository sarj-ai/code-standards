from __future__ import annotations

import ast
from keyword import iskeyword
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override
from unicodedata import is_normalized

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
from sarj_python_lint.rules._namespace_access import dynamic_namespace_access


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class PreferDirectImportModule(Rule):
    id = "prefer-direct-import-module"
    code = "SARJ529"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Prefer static imports for eager module loads with a literal module name.",
        rationale="Static imports expose known dependencies to readers and tooling without dynamic loader indirection.",
        remediation="Replace a fixed eager module load with a module-level import, preserving its binding: plugin = importlib.import_module('plugins.billing') becomes import plugins.billing as plugin. Keep dynamic loading when module selection or import timing requires it.",
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks direct module-level assignments and expression statements calling the proven stdlib import_module function, through qualified or directly imported names, with one literal absolute module name.",
            "Function/class bodies, conditional or guarded imports, variable module names, relative imports, callback references, shadowed or mutated providers and generated code are excluded. Static import syntax must be valid for every module-name segment.",
            "This is a warning without automatic rewriting: moving an import can change execution order, optional-dependency behavior or cycle handling. The rule does not prefer one spelling of genuinely dynamic import_module calls.",
        ),
        examples=(
            RuleExample(
                example_id="literal-eager-loader",
                title="A known eager dependency is loaded dynamically",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app.py", "import importlib\nplugin = importlib.import_module('plugins.billing')\n"
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="static-module-import",
                title="A static import preserves the module binding",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app.py", "import plugins.billing as plugin\n"),),
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
        loader_references = {
            reference
            for call in context.nodes(ast.Call)
            if context.imports.resolved_qualified_name(call.func) == "importlib.import_module"
            for reference in ast.walk(call.func)
        }
        if dynamic_namespace_access(
            (node for node in context.nodes(ast.AST) if node not in loader_references),
            context.imports,
            context.parents,
        ):
            return []
        return [
            Diagnostic(
                context.path,
                node.lineno,
                node.col_offset + 1,
                self.code,
                f"Use a module-level static import for the known module '{module}'; preserve the binding with 'import {module} as plugin' when needed.",
                severity=Severity.WARNING,
            )
            for statement in context.tree.body
            if isinstance(statement, ast.Assign | ast.AnnAssign | ast.Expr)
            and isinstance(node := statement.value, ast.Call)
            and (module := _literal_module(node)) is not None
            and context.resource_provenance.runtime_import_name(node.func) == "importlib.import_module"
        ]


def _literal_module(call: ast.Call) -> str | None:
    match call:
        case ast.Call(args=[ast.Constant(value=str() as module)], keywords=[]):
            pass
        case ast.Call(args=[], keywords=[ast.keyword(arg="name", value=ast.Constant(value=str() as module))]):
            pass
        case _:
            return None
    if not is_normalized("NFKC", module):
        return None
    return module if all(part.isidentifier() and not iskeyword(part) for part in module.split(".")) else None
