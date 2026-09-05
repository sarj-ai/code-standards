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
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_MIN_ALIAS_STATEMENTS = 4


@final
class NoRedundantModuleAliasExports(Rule):
    id: str = "no-redundant-module-alias-exports"
    code: str = "SARJ440"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Do not copy names before replacing a compatibility module.",
        rationale=(
            "A compatibility module that replaces itself in `sys.modules` already exposes the canonical module. "
            "Copying every public attribute first duplicates the API surface and invites drift."
        ),
        remediation=(
            "Delete the forwarding assignments and keep the canonical module import plus the final "
            "`sys.modules[__name__] = alias` replacement. Import the canonical path inside maintained code."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only otherwise-pure compatibility modules with a final, unconditional self-replacement are checked.",
            "Forwarding must use exact same-name assignments such as `Thing = canonical.Thing`.",
            "Conditional, nested, computed, annotated, chained, destructured, or mixed-purpose modules are excluded.",
            "Generated source, malformed source, and stub files (`.pyi`) are outside this rule's scope.",
            "No autofix is offered because attribute access can have side effects and circular imports require review.",
        ),
        examples=(
            RuleExample(
                example_id="self-replacing-compatibility-module",
                title="Remove bindings that the canonical module replacement supersedes",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "legacy/settings.py",
                        "import sys\n\n"
                        "from canonical import settings as _canonical\n\n\n"
                        "Settings = _canonical.Settings\n"
                        "load = _canonical.load\n"
                        "sys.modules[__name__] = _canonical\n",
                    ),
                ),
                focus_path=PurePosixPath("legacy/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="pure-module-alias",
                title="Replace the compatibility module without copying its attributes",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "legacy/settings.py",
                        "import sys\n\n"
                        "from canonical import settings as _canonical\n\n\n"
                        "sys.modules[__name__] = _canonical\n",
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
        if path.suffix != ".py" or "sys.modules" not in source or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        first_forward = _redundant_forward(tree)
        if first_forward is None:
            return []
        return [
            Diagnostic(
                path=path,
                line=first_forward.lineno,
                col=first_forward.col_offset + 1,
                code=self.code,
                severity=Severity.ERROR,
                message=(
                    "Delete the forwarding assignments; this compatibility module already replaces itself with "
                    "the canonical module."
                ),
            )
        ]


def _redundant_forward(tree: ast.Module) -> ast.Assign | None:
    body = list(tree.body)
    if body and _is_docstring(body[0]):
        body.pop(0)
    while body and isinstance(body[0], ast.ImportFrom) and body[0].module == "__future__":
        body.pop(0)
    if len(body) < _MIN_ALIAS_STATEMENTS or not _imports_sys(body[0]):
        return None
    alias = _canonical_alias(body[1])
    if alias is None or not _replaces_current_module(body[-1], alias):
        return None
    forwards = body[2:-1]
    if not forwards:
        return None
    for statement in forwards:
        if not _is_same_name_forward(statement, alias):
            return None
    return forwards[0] if isinstance(forwards[0], ast.Assign) else None


def _is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _imports_sys(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Import)
        and len(statement.names) == 1
        and statement.names[0].name == "sys"
        and (statement.names[0].asname is None)
    )


def _canonical_alias(statement: ast.stmt) -> str | None:
    match statement:
        case ast.Import(names=[ast.alias(asname=alias)]) if alias is not None:
            return alias
        case ast.ImportFrom(module=module, names=[ast.alias(name=name, asname=alias)]) if (
            module is not None and name != "*" and alias is not None
        ):
            return alias
        case _:
            return None


def _is_same_name_forward(statement: ast.stmt, alias: str) -> bool:
    match statement:
        case ast.Assign(
            targets=[ast.Name(id=target, ctx=ast.Store())],
            value=ast.Attribute(value=ast.Name(id=owner, ctx=ast.Load()), attr=attribute, ctx=ast.Load()),
        ):
            return owner == alias and target == attribute and target not in {"sys", "__name__", alias}
        case _:
            return False


def _replaces_current_module(statement: ast.stmt, alias: str) -> bool:
    match statement:
        case ast.Assign(
            targets=[
                ast.Subscript(
                    value=ast.Attribute(value=ast.Name(id="sys", ctx=ast.Load()), attr="modules", ctx=ast.Load()),
                    slice=ast.Name(id="__name__", ctx=ast.Load()),
                    ctx=ast.Store(),
                )
            ],
            value=ast.Name(id=replacement, ctx=ast.Load()),
        ):
            return replacement == alias
        case _:
            return False
