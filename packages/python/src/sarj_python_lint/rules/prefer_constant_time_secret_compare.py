"""SARJ011 — `==`/`!=` comparisons on secret-like values.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_constant_time_secret_compare.py
"""

from __future__ import annotations

import ast
from itertools import pairwise
from typing import TYPE_CHECKING, override

from sarj_python_lint._secret_names import identifier_tokens, is_secret_name
from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, nodes


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# `is_secret_name` (shared with SARJ012) treats a hash/digest as secret material
# because logging one can still be sensitive. A timing-attack surface is narrower:
# only a MAC / authenticator whose bytes gate access. These extra SARJ011-only
# filters strip the classes that are secret-shaped by name but are not an auth
# comparison — so no_secret_in_log keeps its broader reach unchanged.

# Trailing token that makes the identifier metadata *about* a secret (its category
# / handle / label), not the credential: `token_type`, `token_name`, `session_id`,
# `credential_kind`. `type`/`id` are already dropped by the shared innocuous set;
# `name`/`kind` are added here because logging them can still matter (SARJ012) but
# they are never a timing surface.
_DESCRIPTOR_WORDS = frozenset({"type", "types", "name", "names", "id", "ids", "kind", "kinds"})

# A `type`/`kind` token anywhere marks an enum/category discriminator, not a
# credential: `TOKEN_TYPE_SYSTEM`, `credential_type`, `grant_kind`.
_CATEGORY_WORDS = frozenset({"type", "types", "kind", "kinds"})

# Words that make an identifier a secret *only* via an integrity/content hash
# (`content_hash`, `metadata_hash`, `row_hash`) rather than an authenticator.
# A name that ALSO carries one of these keeps firing (`password_hash`,
# `token_hash`, `computed_hmac`, `signature`): those gate access, a plain digest
# of content does not.
_AUTH_WORDS = frozenset(
    {
        "token",
        "secret",
        "secrets",
        "password",
        "passwd",
        "passwords",
        "jwt",
        "credential",
        "credentials",
        "authorization",
        "signature",
        "hmac",
        "apikey",
        # `bearer` was in the TypeScript twin's AUTH_WORDS and in neither Python
        # list, so `bearer == provided` was a flagged timing attack in TS and a
        # silent one here. The two lists are otherwise identical, which is what
        # made the gap invisible.
        "bearer",
    }
)


class PreferConstantTimeSecretCompare(Rule):
    id: str = "prefer-constant-time-secret-compare"
    code: str = "SARJ011"
    description: str = "Direct `==`/`!=` on a secret — prefer `hmac.compare_digest(a, b)`."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        # Fixture equality assertions in tests (`result.api_key == "known"`) are
        # not a timing-attack surface — no attacker measures a test's clock.
        if _is_test_path(path):
            return []
        # Every diagnostic is an `==`/`!=` comparison, so a module spelling
        # neither operator cannot produce one and need not be parsed.
        if "==" not in source and "!=" not in source:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        compares = nodes(tree, ast.Compare)
        if not compares:
            return []
        crypto_module = _imports_crypto(tree, source)
        dunder_compares = _equality_dunder_compares(tree, source)
        diags: list[Diagnostic] = []
        for node in compares:
            # Value equality between two objects the process holds is not an
            # auth gate — nothing is granted on the result.
            if id(node) in dunder_compares:
                continue
            # Only single-operator comparisons using == or != (Eq/NotEq).
            # Chained comparisons (a == b == c) and is/is not don't apply.
            if len(node.ops) != 1:
                continue
            if not isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
                continue
            operands = [node.left, *node.comparators]
            # Skip presence checks (None/True/False, numbers) and comparisons
            # against a compile-time str/bytes literal sentinel — an attacker
            # can't extract a runtime secret by timing a compare to a fixed
            # literal (ruff S105 covers hardcoded-secret literals separately).
            if any(_is_excluded_operand(op) for op in operands):
                continue
            if not any(_is_secret_operand(op, crypto_module=crypto_module) for op in operands):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        "Direct `==`/`!=` on a secret-like value is "
                        "timing-attack-prone — prefer "
                        "`hmac.compare_digest(a, b)`."
                    ),
                )
            )
        return diags


def _is_test_path(path: Path) -> bool:
    return path.name.startswith("test_") or "tests" in path.parts


# Dunders that implement value equality rather than an authentication decision.
_EQUALITY_DUNDERS = frozenset({"__eq__", "__ne__"})


def _equality_dunder_compares(tree: ast.AST, source: str) -> frozenset[int]:
    """Collect the `id()`s of every `Compare` written directly in an `__eq__`/`__ne__` body."""
    if not any(dunder in source for dunder in _EQUALITY_DUNDERS):
        return frozenset()
    return frozenset(
        id(inner)
        for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef)
        if node.name in _EQUALITY_DUNDERS
        for inner in _same_scope_compares(node)
    )


def _same_scope_compares(func: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.Compare]:
    """Yield `func`'s own comparisons, not descending into nested `def`/`lambda` scopes."""
    stack: list[ast.AST] = list(func.body)
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(current, ast.Compare):
            yield current
        stack.extend(children(current))


def _is_secret_operand(node: ast.AST, *, crypto_module: bool) -> bool:
    """Report whether the operand's identifier names an auth secret worth constant-time compare."""
    if isinstance(node, ast.NamedExpr):
        node = node.target
    if isinstance(node, ast.Name):
        return _is_auth_secret_name(node.id, crypto_module=crypto_module)
    if isinstance(node, ast.Attribute):
        return _is_auth_secret_name(node.attr, crypto_module=crypto_module)
    return False


# The polysemous auth words: a MAC in crypto code, a *function* signature in
# reflection code. They count as auth words only in a module that imports
# crypto machinery.
_CRYPTO_GATED_WORDS = frozenset({"signature", "signatures"})

_CRYPTO_MODULES = frozenset({"hmac", "hashlib", "secrets", "jwt", "cryptography", "Crypto", "nacl"})


def _imports_crypto(tree: ast.AST, source: str) -> bool:
    """Report whether the module imports crypto machinery anywhere."""
    if not any(module in source for module in _CRYPTO_MODULES):
        return False
    for node in nodes(tree, ast.Import, ast.ImportFrom):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in _CRYPTO_MODULES for alias in node.names):
                return True
        elif node.module is not None and node.module.split(".")[0] in _CRYPTO_MODULES:
            return True
    return False


def _is_auth_secret_name(identifier: str, *, crypto_module: bool) -> bool:
    """Report whether `identifier` names an authenticator (an access-gating secret)."""
    if not is_secret_name(identifier):
        return False
    tokens = identifier_tokens(identifier)
    if tokens and tokens[-1] in _DESCRIPTOR_WORDS:
        return False
    if any(tok in _CATEGORY_WORDS for tok in tokens):
        return False
    auth_tokens = {tok for tok in tokens if tok in _AUTH_WORDS} | {
        f"{a}_{b}" for a, b in pairwise(tokens) if a == "api" and b == "key"
    }
    if not auth_tokens:
        return False
    if auth_tokens <= _CRYPTO_GATED_WORDS:
        return crypto_module
    return True


def _is_excluded_operand(node: ast.AST) -> bool:
    """Report whether the operand makes the comparison a non-timing-attack surface."""
    if isinstance(node, ast.Constant):
        value = node.value
        if value is None or isinstance(value, bool):
            return True
        if isinstance(value, (int, float, complex)):
            return True
        if isinstance(value, (str, bytes)):
            return True
    if isinstance(node, ast.Name):
        return _is_constant_reference(node.id)
    if isinstance(node, ast.Attribute):
        return _is_constant_reference(node.attr)
    return False


def _is_constant_reference(identifier: str) -> bool:
    """Report whether `identifier` is an ALL-CAPS named constant (a compile-time sentinel)."""
    return identifier.isupper() and any(c.isalpha() for c in identifier)
