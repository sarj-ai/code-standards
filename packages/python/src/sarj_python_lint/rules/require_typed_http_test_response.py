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
            "Only test files and direct or simple local-aliased HTTP JSON access are checked; branch and nested-scope aliases are excluded.",
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
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            findings.extend(_alias_findings(path, lines, node, self.code))
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


def _alias_findings(
    path: Path,
    lines: list[str],
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    code: str,
) -> list[Diagnostic]:
    aliases: set[str] = set()
    response_names: set[str] = set()
    findings: list[Diagnostic] = []
    for statement in function.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign, ast.Assert, ast.Expr, ast.Return)):
            # Branches and nested scopes need control-flow analysis before alias state can be trusted.
            aliases.clear()
            response_names.clear()
            continue
        for node in ast.walk(statement):
            access = _alias_access(node, aliases)
            if access is None or is_suppressed(lines, access.lineno, code):
                continue
            findings.append(
                Diagnostic(
                    path=path,
                    line=access.lineno,
                    col=access.col_offset + 1,
                    code=code,
                    message="validate the HTTP JSON body into its named Pydantic response model before asserting fields",
                )
            )
        _record_alias_assignment(statement, aliases, response_names)
    return findings


def _record_alias_assignment(statement: ast.stmt, aliases: set[str], response_names: set[str]) -> None:
    target: ast.expr | None = None
    value: ast.expr | None = None
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target, value = statement.targets[0], statement.value
    elif isinstance(statement, ast.AnnAssign):
        target, value = statement.target, statement.value
    if not isinstance(target, ast.Name) or value is None:
        return
    is_alias = _is_http_json_call(value, response_names) or (isinstance(value, ast.Name) and value.id in aliases)
    if is_alias:
        aliases.add(target.id)
    else:
        aliases.discard(target.id)
    if _is_http_response_call(value):
        response_names.add(target.id)
    else:
        response_names.discard(target.id)


def _alias_access(node: ast.AST, aliases: set[str]) -> ast.Name | None:
    value: ast.expr | None = None
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
        value = node.value
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"get", "items", "keys"}
    ):
        value = node.func.value
    if isinstance(value, ast.Name) and value.id in aliases:
        return value
    return None


def _is_http_json_call(value: ast.expr, response_names: set[str]) -> bool:
    if not isinstance(value, ast.Call) or value.args or value.keywords:
        return False
    if not isinstance(value.func, ast.Attribute) or value.func.attr != "json":
        return False
    receiver = value.func.value
    return (isinstance(receiver, ast.Name) and receiver.id in response_names) or _is_http_response_call(receiver)


def _is_http_response_call(value: ast.expr) -> bool:
    if isinstance(value, ast.Await):
        value = value.value
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr in {"get", "post", "put", "patch", "delete", "request"}
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id.endswith("client")
        and bool(value.args)
        and isinstance(value.args[0], ast.Constant)
        and isinstance(value.args[0].value, str)
        and value.args[0].value.startswith(("/", "http://", "https://"))
    )
