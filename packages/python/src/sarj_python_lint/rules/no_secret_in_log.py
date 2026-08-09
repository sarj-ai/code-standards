"""SARJ012 — Secrets passed by keyword argument to a logging call.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_secret_in_log.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint._secret_names import identifier_tokens, is_secret_name
from sarj_python_lint.rule_base import (
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
from sarj_python_lint.rules._logging import LOG_METHODS, is_logger_expr


if TYPE_CHECKING:
    from pathlib import Path


# A whole redaction token (`token_prefix`, `password_hash`, `secret_masked`,
# `api_key_tag`) means the identifier names a masked/derived value. Whole-token
# matching avoids treating unrelated substrings as redaction evidence.
_REDACTION_TOKENS = frozenset(
    {"prefix", "suffix", "redact", "redacted", "mask", "masked", "hash", "hint", "len", "length", "tag"}
)


def _is_secret_keyword(name: str) -> bool:
    """Report whether the keyword name names a raw secret (not a redacted derivative)."""
    if any(token in _REDACTION_TOKENS for token in identifier_tokens(name)):
        return False
    return is_secret_name(name)


def _is_raw_secret_reference(value: ast.expr) -> bool:
    """Report a direct, secret-named reference without guessing through aliases or calls."""
    match value:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return _is_secret_keyword(name)
        case _:
            return False


class NoSecretInLog(Rule):
    id: str = "no-secret-in-log"
    code: str = "SARJ012"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="A secret-named direct reference is passed to a logging call under a secret-like keyword.",
        rationale="Raw credentials in logs can spread to durable sinks and readers outside the request boundary.",
        remediation="Omit the secret or log a deliberately redacted derivative under a redaction-specific name.",
        category=RuleCategory.SECURITY,
        limitations=(
            "Detection covers secret-named direct references passed by secret-named keyword to known logger calls.",
            "Aliases, calls, subscripts, positional values, message interpolation, and values under non-secret keywords are not inspected.",
        ),
        examples=(
            RuleExample(
                example_id="secret-logging-keyword",
                title="Raw token passed to a logger",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("service.py", "logger.info('request', token=token)\n"),),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="redacted-logging-keyword",
                title="Token prefix logged under a redacted name",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("service.py", "logger.info('request', token_prefix=token[:6])\n"),),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.Call):
            if not _is_logging_call(node):
                continue
            for kw in node.keywords:
                # `**kwargs` has arg=None — nothing to inspect.
                if kw.arg is None:
                    continue
                if _is_secret_keyword(kw.arg) and _is_raw_secret_reference(kw.value):
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=getattr(kw.value, "lineno", node.lineno),
                            col=getattr(kw.value, "col_offset", node.col_offset) + 1,
                            code=self.code,
                            message=(
                                f"Secret reference passed as `{kw.arg}` to a logging "
                                "call leaks it to log sinks — redact "
                                "(e.g. `token_prefix=token[:6]`) or omit it."
                            ),
                        )
                    )
        return diags


def _is_logging_call(node: ast.Call) -> bool:
    """Report whether `node` looks like `logger.<level>(...)`."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in LOG_METHODS:
        return False
    return is_logger_expr(func.value)
