"""SARJ012 — Secrets passed by keyword argument to a logging call.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_secret_in_log.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ012.md
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint._secret_names import identifier_tokens, is_secret_name
from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._logging import is_logger_expr


if TYPE_CHECKING:
    from pathlib import Path


# Logging method names (the `.attr` of the call's func).
_LOG_METHODS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical"})

# A redaction marker (`token_prefix`, `password_hash`, `secret_masked`,
# `api_key_tag`) means the keyword carries a masked/derived value, not the raw
# secret — the intended safe form.
_REDACTION_RE = re.compile(
    r"prefix|suffix|redact|mask|hash|hint|_len|length",
    re.IGNORECASE,
)

# `tag` marks a redaction tag derived purely for logging
# (`api_key_tag=_api_key_log_tag(api_key)`), but only as a WHOLE token — matched
# as a substring it wrongly exempts raw env secrets like `staging_secret`
# (`s·tag·ing`), which is a leak.
_WHOLE_TOKEN_REDACTION_MARKERS = frozenset({"tag"})


def _is_secret_keyword(name: str) -> bool:
    """Report whether the keyword name names a raw secret (not a redacted derivative)."""
    if _REDACTION_RE.search(name):
        return False
    if any(tok in _WHOLE_TOKEN_REDACTION_MARKERS for tok in identifier_tokens(name)):
        return False
    return is_secret_name(name)


class NoSecretInLog(Rule):
    id: str = "no-secret-in-log"
    code: str = "SARJ012"
    has_evidence: bool = True
    description: str = "Secret passed by keyword to a logging call — redact or omit."

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
                if _is_secret_keyword(kw.arg):
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=getattr(kw.value, "lineno", node.lineno),
                            col=getattr(kw.value, "col_offset", node.col_offset) + 1,
                            code=self.code,
                            message=(
                                f"Secret keyword `{kw.arg}` passed to a logging "
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
    if func.attr not in _LOG_METHODS:
        return False
    return is_logger_expr(func.value)
