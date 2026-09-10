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
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_OVERRIDE_MODULES = frozenset({"typing", "typing_extensions"})


@final
class NoDeletedOnlyOverrideParameter(Rule):
    id = "no-deleted-only-override-parameter"
    code = "SARJ442"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Do not use direct deletion as the only reference to an override parameter.",
        rationale=(
            "Deleting an otherwise unread override parameter is commonly used as an unused-value marker, but "
            "`@override` already preserves the interface contract without requiring a synthetic reference."
        ),
        remediation=(
            "Keep the override signature and remove the deletion marker. If deletion intentionally shortens the "
            "reference lifetime, retain it with an exact suppression that explains the lifetime boundary."
        ),
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct methods of module-level classes decorated by a proven runtime import of typing.override or typing_extensions.override are checked.",
            "A parameter is reported only when every occurrence in the method is a direct bare-name deletion; any load, rebinding, nested occurrence, attribute deletion, or subscription deletion excludes it.",
            "Removing a deletion can change reference lifetime, finalization, frame tracing, or locals() visibility, so the rule has no autofix and supports an exact reasoned suppression.",
            "Generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="override-parameter-delete-marker",
                title="Remove a deletion used only as an override parameter marker",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/handler.py",
                        "from typing import override\n\n"
                        "class Handler(BaseHandler):\n"
                        "    @override\n"
                        "    def handle(self, request: Request) -> None:\n"
                        "        del request\n"
                        "        emit_ready()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/handler.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="override-uses-parameter",
                title="Keep an override parameter that contributes to behavior",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/handler.py",
                        "from typing import override\n\n"
                        "class Handler(BaseHandler):\n"
                        "    @override\n"
                        "    def handle(self, request: Request) -> None:\n"
                        "        dispatch(request)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/handler.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if "del" not in source or "override" not in source or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        direct_aliases, module_aliases = _proven_override_imports(tree)
        if not direct_aliases and not module_aliases:
            return []
        source_lines = source.splitlines()
        diagnostics: list[Diagnostic] = []
        for statement in tree.body:
            if not isinstance(statement, ast.ClassDef):
                continue
            class_bound = _class_bound_names(statement)
            available_direct = direct_aliases - class_bound
            available_modules = module_aliases - class_bound
            for method in statement.body:
                if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _is_override(
                    method, available_direct, available_modules
                ):
                    continue
                diagnostics.extend(_method_diagnostics(path, source_lines, method))
        diagnostics.sort(key=lambda item: (item.line, item.col))
        return diagnostics


def _proven_override_imports(tree: ast.Module) -> tuple[frozenset[str], frozenset[str]]:
    direct: set[str] = set()
    modules: set[str] = set()
    conflicting: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and statement.module in _OVERRIDE_MODULES:
            for alias in statement.names:
                name = alias.asname or alias.name
                if alias.name == "override" and name not in direct:
                    direct.add(name)
                else:
                    conflicting.add(name)
            continue
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                name = alias.asname or alias.name.split(".")[0]
                if alias.name in _OVERRIDE_MODULES and name not in modules:
                    modules.add(name)
                else:
                    conflicting.add(name)
            continue
        conflicting.update(_statement_bound_names(statement))
    return frozenset(direct - conflicting), frozenset(modules - conflicting)


def _statement_bound_names(statement: ast.stmt) -> set[str]:
    names: set[str] = set()
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(statement.name)
    for node in ast.walk(statement):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.split(".")[0])
    return names


def _class_bound_names(node: ast.ClassDef) -> frozenset[str]:
    names: set[str] = set()
    for statement in node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(statement.name)
        elif not isinstance(statement, ast.ClassDef):
            names.update(_statement_bound_names(statement))
    return frozenset(names)


def _is_override(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    direct_aliases: frozenset[str],
    module_aliases: frozenset[str],
) -> bool:
    for decorator in method.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id in direct_aliases:
            return True
        if (
            isinstance(decorator, ast.Attribute)
            and decorator.attr == "override"
            and isinstance(decorator.value, ast.Name)
            and decorator.value.id in module_aliases
        ):
            return True
    return False


def _method_diagnostics(
    path: Path,
    source_lines: list[str],
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[Diagnostic]:
    delete_targets = _direct_delete_targets(method.body)
    parameters = {
        argument.arg
        for argument in (
            *method.args.posonlyargs,
            *method.args.args,
            *method.args.kwonlyargs,
            *(() if method.args.vararg is None else (method.args.vararg,)),
            *(() if method.args.kwarg is None else (method.args.kwarg,)),
        )
    }
    direct_nodes = {id(node) for nodes in delete_targets.values() for node in nodes}
    other_occurrences = {
        node.id
        for statement in method.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Name) and id(node) not in direct_nodes
    }
    diagnostics: list[Diagnostic] = []
    for name in sorted(parameters.intersection(delete_targets) - other_occurrences):
        target = min(delete_targets[name], key=lambda node: (node.lineno, node.col_offset))
        if is_suppressed(source_lines, target.lineno, NoDeletedOnlyOverrideParameter.code):
            continue
        diagnostics.append(
            Diagnostic(
                path=path,
                line=target.lineno,
                col=target.col_offset + 1,
                code=NoDeletedOnlyOverrideParameter.code,
                severity=Severity.WARNING,
                message=(
                    f"override parameter `{name}` is referenced only by direct deletion — remove the unused-marker "
                    "deletion, or suppress this warning with a reason when early reference release is intentional."
                ),
            )
        )
    return diagnostics


def _direct_delete_targets(statements: list[ast.stmt]) -> dict[str, list[ast.Name]]:
    targets: dict[str, list[ast.Name]] = {}

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return
        if isinstance(node, ast.Delete):
            for target in node.targets:
                for name in _bare_delete_names(target):
                    targets.setdefault(name.id, []).append(name)
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in statements:
        visit(statement)
    return targets


def _bare_delete_names(target: ast.expr) -> list[ast.Name]:
    if isinstance(target, ast.Name):
        return [target]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for item in target.elts for name in _bare_delete_names(item)]
    return []
