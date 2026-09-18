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
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


@final
class RequireTypedHttpTestResponse(Rule):
    id = "require-typed-http-test-response"
    code = "SARJ449"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="HTTP tests must validate JSON response bodies into named models before asserting fields.",
        rationale=(
            "Raw dictionary assertions duplicate wire spelling and do not prove that the complete response contract validates."
        ),
        remediation=(
            "Parse `response.json()` once with `ResponseModel.model_validate(...)` or a Pydantic `TypeAdapter`, then assert "
            "typed attributes."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only test files and direct fixed-key `.json()` consumption are checked; status-only and non-JSON tests are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="raw-http-json-assertion",
                title="A test indexes an unvalidated response body",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_cards.py",
                        "def test_interaction(client):\n    response = client.post('/actions')\n    assert response.json()['interactionId']\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_cards.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="validated-http-json-assertion",
                title="A test validates its response model",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_cards.py",
                        "def test_interaction(client):\n    response = client.post('/actions')\n    body = InteractionResponse.model_validate(response.json())\n    assert body.interaction_id\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_cards.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        lines = source.splitlines()
        findings: list[Diagnostic] = []
        for node in ast.walk(tree):
            call = _raw_json_access(node)
            if call is None or is_suppressed(lines, call.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    message=(
                        "validate the HTTP JSON body into its named Pydantic response model before asserting fields"
                    ),
                )
            )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _raw_json_access(node: ast.AST) -> ast.Call | None:
    value: ast.expr | None = None
    if isinstance(node, ast.Subscript):
        value = node.value
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"get", "items", "keys"}
    ):
        value = node.func.value
    if not isinstance(value, ast.Call) or value.args or value.keywords:
        return None
    if not isinstance(value.func, ast.Attribute) or value.func.attr != "json":
        return None
    return value
