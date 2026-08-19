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
    parse_or_none,
)


if TYPE_CHECKING:
    from pathlib import Path


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
            "A test module is recognized only when an explicit module-path component begins with `test_` or ends with `_test`.",
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
        for statement in tree.body:
            targets: list[str] = []
            match statement:
                case ast.Import(names=names):
                    targets.extend(alias.name for alias in names if _module_has_test_leaf(alias.name))
                case ast.ImportFrom(module=module, names=names):
                    if module is not None and _module_has_test_leaf(module):
                        targets.append(module)
                case _:
                    continue
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
        return diagnostics


def _module_has_test_leaf(module: str) -> bool:
    parts = module.split(".")
    return any(_is_test_module_name(part) for part in parts)


def _is_test_module_name(name: str) -> bool:
    return name.startswith("test_") or name.endswith("_test")
