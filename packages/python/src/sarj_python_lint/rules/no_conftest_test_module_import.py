from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NamedTuple, final, override

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
from sarj_python_lint.rules._ast_index import nodes


if TYPE_CHECKING:
    from pathlib import Path


class _PluginTarget(NamedTuple):
    statement: ast.stmt
    module: str


@final
class NoConftestTestModuleImport(Rule):
    id = "no-conftest-test-module-import"
    code = "SARJ426"
    documentation = RuleDocumentation(
        summary="Do not import individual test modules from conftest.py.",
        rationale=(
            "pytest imports conftest for every test module in its scope; importing a specific test from conftest "
            "turns that test into global collection infrastructure and creates cycles and order dependence."
        ),
        remediation="Move shared fixtures or helpers into conftest.py or a dedicated support module.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only files named conftest.py are inspected.",
            "A test module is recognized from an explicit module-path component or test-package import name beginning with `test_` or ending with `_test`.",
            "Literal pytest_plugins declarations are checked; dynamically assembled plugin paths are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="conftest-imports-test-module",
                title="Conftest imports a specific test module",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/conftest.py", "from tests.test_api import make_client\n"),),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="conftest-imports-support-module",
                title="Conftest imports dedicated support code",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("tests/conftest.py", "from tests.helpers import make_client\n"),),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.name != "conftest.py":
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diagnostics: list[Diagnostic] = []
        for statement in nodes(tree, ast.Import, ast.ImportFrom):
            targets = _imported_test_targets(statement)
            if not targets:
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=statement.lineno,
                    col=statement.col_offset + 1,
                    code=self.code,
                    message=(
                        f"conftest.py imports test module `{targets[0]}`; move shared fixtures or helpers to "
                        "conftest or a dedicated support module."
                    ),
                )
            )
        for statement, target in _pytest_plugin_test_targets(tree):
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=statement.lineno,
                    col=statement.col_offset + 1,
                    code=self.code,
                    message=(
                        f"conftest.py registers test module `{target}` as a pytest plugin; move shared fixtures "
                        "or hooks to conftest or a dedicated support module."
                    ),
                )
            )
        diagnostics.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diagnostics


def _imported_test_targets(statement: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(statement, ast.Import):
        return [alias.name for alias in statement.names if _module_has_test_leaf(alias.name)]
    module = statement.module
    if module is not None and _module_has_test_leaf(module):
        return [module]
    if not _is_test_package_import(module, statement.level):
        return []
    prefix = "." * statement.level + (module or "")
    return [f"{prefix}.{alias.name}" for alias in statement.names if _is_test_module_name(alias.name)]


def _is_test_package_import(module: str | None, level: int) -> bool:
    if level > 0 and module is None:
        return True
    return module is not None and module.rsplit(".", 1)[-1] in {"test", "tests"}


def _pytest_plugin_test_targets(tree: ast.Module) -> list[_PluginTarget]:
    findings: list[_PluginTarget] = []
    for statement in tree.body:
        value: ast.expr | None = None
        match statement:
            case ast.Assign(targets=[ast.Name(id="pytest_plugins")]) | ast.AnnAssign(
                target=ast.Name(id="pytest_plugins")
            ):
                value = statement.value
            case _:
                continue
        findings.extend(
            _PluginTarget(statement, target)
            for target in _literal_strings(value)
            if _module_has_test_leaf(target)
        )
    return findings


def _literal_strings(node: ast.expr | None) -> tuple[str, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return tuple(
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        )
    return ()


def _module_has_test_leaf(module: str) -> bool:
    parts = module.split(".")
    return any(_is_test_module_name(part) for part in parts)


def _is_test_module_name(name: str) -> bool:
    return name.startswith("test_") or name.endswith("_test")
