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
from sarj_python_lint.rules._runtime_names import RuntimeNames


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MUTATORS = frozenset(
    {
        "append",
        "extend",
        "insert",
        "remove",
        "pop",
        "clear",
        "reverse",
        "sort",
        "__setitem__",
        "__delitem__",
        "__iadd__",
        "__imul__",
        "__init__",
    }
)
_OPERATOR_MUTATORS = frozenset(
    {"operator.setitem", "operator.delitem", "operator.iadd", "operator.imul", "operator.iconcat"}
)


@final
class NoSysPathMutation(Rule):
    id = "no-sys-path-mutation"
    code = "SARJ558"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Do not mutate the interpreter import search path.",
        rationale="Changing the process-wide import search path makes import resolution depend on execution order and can shadow installed packages.",
        remediation="Install the package and use explicit package imports. A required interpreter bootstrap boundary needs an explained local suppression.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Covers direct writes, item/slice writes, deletion, in-place operators, mutating list methods, static setters and simple import/value aliases.",
            "Read-only access, copied paths and locally shadowed sys names are accepted. Arbitrary reflection, container-held aliases and unknown callback effects are not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="mutating-search-path",
                title="Import resolution depends on process-wide mutation",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python("service/bootstrap.py", "import sys\nsys.path.insert(0, '/opt/application')\n"),
                ),
                focus_path=PurePosixPath("service/bootstrap.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="inspect-search-path",
                title="Inspecting a snapshot does not change import resolution",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("service/bootstrap.py", "import sys\nsearch_path = tuple(sys.path)\n"),),
                focus_path=PurePosixPath("service/bootstrap.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "sys" not in context.symbol_source or context.tree is None or context.generated:
            return []
        names = RuntimeNames(context)
        mutations: list[ast.expr | ast.AugAssign] = []
        for node in context.nodes(ast.Attribute, ast.Subscript, ast.AugAssign, ast.Call):
            if isinstance(node, ast.Attribute | ast.Subscript):
                parent = context.parents.get(node)
                if isinstance(parent, ast.AugAssign) and parent.target is node:
                    continue
                if isinstance(node.ctx, ast.Store | ast.Del) and _path_write_target(node, names):
                    mutations.append(node)
            elif isinstance(node, ast.AugAssign):
                if _path_write_target(node.target, names) or names.qualified(node.target) == "sys.path":
                    mutations.append(node)
            elif _mutating_call(node, names):
                mutations.append(node)
        return [
            Diagnostic(
                context.path,
                node.lineno,
                node.col_offset + 1,
                self.code,
                "Do not mutate sys.path. Install the package and use explicit package imports; required bootstrap code needs an explained local suppression.",
            )
            for node in sorted(mutations, key=lambda item: (item.lineno, item.col_offset))
        ]


def _path_write_target(node: ast.expr, names: RuntimeNames) -> bool:
    if isinstance(node, ast.Attribute):
        return names.qualified(node) == "sys.path"
    return isinstance(node, ast.Subscript) and names.qualified(node.value) == "sys.path"


def _mutating_call(node: ast.Call, names: RuntimeNames) -> bool:
    qualified = names.qualified(node.func)
    if qualified is None:
        return False
    if qualified.startswith("sys.path.") and qualified.removeprefix("sys.path.") in _MUTATORS:
        return True
    if qualified in {"builtins.setattr", "builtins.delattr"}:
        match node.args:
            case [target, ast.Constant(value="path"), *_]:
                return names.qualified(target) == "sys"
            case _:
                return False
    direct_list_mutator = (
        qualified.startswith("builtins.list.") and qualified.removeprefix("builtins.list.") in _MUTATORS
    )
    return (
        bool(node.args)
        and (direct_list_mutator or qualified in _OPERATOR_MUTATORS)
        and names.qualified(node.args[0]) == "sys.path"
    )
