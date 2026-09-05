from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_SYS_SOURCES = frozenset({"sys"})


@final
class NoRedundantModuleAliasExports(Rule):
    id: str = "no-redundant-module-alias-exports"
    code: str = "SARJ440"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Do not replace the current module through `sys.modules`.",
        rationale=(
            "Replacing the current module mutates import identity at runtime in a way static tools cannot model. "
            "It makes introspection, reloads, circular imports, state, and monkeypatch behavior surprising."
        ),
        remediation=(
            "Import the canonical path inside maintained code. If a compatibility module is still required, expose "
            "its supported names with explicit same-name imports grouped by source module."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only module-scope assignments through an unconditional, unshadowed stdlib `sys` import are checked.",
            "Assignments inside functions, classes, and `TYPE_CHECKING` branches are excluded.",
            "Literal-key registrations, child-module registrations, method calls, reads, and arbitrary registries are excluded.",
            "Generated source, malformed source, and stub files (`.pyi`) are outside this rule's scope.",
            "No autofix is offered because the intended compatibility surface and identity requirements need review.",
        ),
        examples=(
            RuleExample(
                example_id="current-module-replacement",
                title="Do not replace a compatibility module at runtime",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "legacy/settings.py",
                        "import sys\n\n"
                        "from canonical import settings as _canonical\n\n\n"
                        "sys.modules[__name__] = _canonical\n",
                    ),
                ),
                focus_path=PurePosixPath("legacy/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-compatibility-exports",
                title="Expose the supported compatibility surface explicitly",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "legacy/settings.py",
                        "from canonical.settings import (\n    Settings as Settings,\n    load as load,\n)\n",
                    ),
                ),
                focus_path=PurePosixPath("legacy/settings.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix != ".py" or "modules" not in source or "__name__" not in source or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree, module_scope_only=True)
        if not imports.builtin_is_unshadowed("__name__"):
            return []
        direct_sys_bindings = _direct_sys_bindings(tree)
        findings = [
            Diagnostic(
                path=path,
                line=target.lineno,
                col=target.col_offset + 1,
                code=self.code,
                message=(
                    "Do not replace the current module through `sys.modules[__name__]`; expose compatibility names "
                    "with explicit imports and update maintained callers to the canonical module."
                ),
            )
            for statement in _module_statements(tree.body)
            for target in _assignment_targets(statement)
            if _is_current_module_target(target, imports, direct_sys_bindings)
        ]
        return sorted(findings, key=lambda finding: (finding.line, finding.col, finding.code))


def _direct_sys_bindings(tree: ast.Module) -> frozenset[str]:
    bindings: set[str] = set()
    for statement in tree.body:
        match statement:
            case ast.Import(names=names):
                bindings.update(alias.asname or "sys" for alias in names if alias.name == "sys")
            case ast.ImportFrom(module="sys", level=0, names=names):
                bindings.update(alias.asname or "modules" for alias in names if alias.name == "modules")
            case _:
                pass
    return frozenset(bindings)


def _module_statements(statements: list[ast.stmt]) -> list[ast.stmt]:
    result: list[ast.stmt] = []
    pending = list(reversed(statements))
    while pending:
        statement = pending.pop()
        result.append(statement)
        pending.extend(reversed(_module_control_flow_bodies(statement)))
    return result


def _module_control_flow_bodies(statement: ast.stmt) -> list[ast.stmt]:
    match statement:
        case ast.If() if _is_type_checking_guard(statement.test):
            return list(statement.orelse)
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            return [*statement.body, *statement.orelse]
        case ast.With() | ast.AsyncWith():
            return list(statement.body)
        case ast.Try() | ast.TryStar():
            return [
                *statement.body,
                *(nested for handler in statement.handlers for nested in handler.body),
                *statement.orelse,
                *statement.finalbody,
            ]
        case ast.Match():
            return [nested for match_case in statement.cases for nested in match_case.body]
        case _:
            return []


def _assignment_targets(statement: ast.stmt) -> list[ast.expr]:
    match statement:
        case ast.Assign(targets=targets):
            return [nested for target in targets for nested in _nested_targets(target)]
        case ast.AnnAssign(target=target):
            return _nested_targets(target)
        case _:
            return []


def _nested_targets(target: ast.expr) -> list[ast.expr]:
    if isinstance(target, (ast.Tuple, ast.List)):
        return [nested for element in target.elts for nested in _nested_targets(element)]
    return [target]


def _is_current_module_target(
    target: ast.expr,
    imports: ImportIndex,
    direct_sys_bindings: frozenset[str],
) -> bool:
    match target:
        case ast.Subscript(
            value=value,
            slice=ast.Name(id="__name__", ctx=ast.Load()),
            ctx=ast.Store(),
        ):
            root = value.value if isinstance(value, ast.Attribute) else value
            return (
                isinstance(root, ast.Name)
                and root.id in direct_sys_bindings
                and imports.resolves(value, sources=_SYS_SOURCES, symbol="modules")
            )
        case _:
            return False


def _is_type_checking_guard(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING") or (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in {"typing", "typing_extensions"}
        and node.attr == "TYPE_CHECKING"
    )
