"""SARJ011 — `==`/`!=` comparisons on secret-like values.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_constant_time_secret_compare.py
"""

from __future__ import annotations

import ast
from itertools import pairwise
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
from sarj_python_lint.rules._ast_index import children, nodes


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# Logging protects broad secret-shaped data; timing checks only cover authenticators that gate access.

# Descriptor suffixes name secret metadata rather than credential bytes.
_DESCRIPTOR_WORDS = frozenset(
    {"type", "types", "name", "names", "id", "ids", "kind", "kinds", "scope", "scopes", "permission", "permissions"}
)

# A `type`/`kind` token anywhere marks an enum/category discriminator, not a
# credential: `TOKEN_TYPE_SYSTEM`, `credential_type`, `grant_kind`.
_CATEGORY_WORDS = frozenset({"type", "types", "kind", "kinds"})

# Auth words distinguish access-gating hashes from ordinary content digests.
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
        # Keep bearer aligned with the TypeScript authenticator vocabulary.
        "bearer",
    }
)

_CONFIRMATION_OPERAND_COUNT = 2


class PreferConstantTimeSecretCompare(Rule):
    id: str = "prefer-constant-time-secret-compare"
    code: str = "SARJ011"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Secret-like values are compared with timing-sensitive equality operators.",
        rationale="Direct equality can reveal authenticator contents through data-dependent comparison timing.",
        remediation="Compare secret values with `hmac.compare_digest` or `secrets.compare_digest`.",
        category=RuleCategory.SECURITY,
        limitations=(
            "Detection depends on authenticator-shaped identifier names and selected cryptographic imports.",
            "Tests, equality methods, literals, container membership, and existing digest comparisons are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="direct-token-comparison",
                title="Token compared with equality",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "auth.py",
                        "def authenticated(token, expected):\n    return token == expected\n",
                    ),
                ),
                focus_path=PurePosixPath("auth.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="constant-time-token-comparison",
                title="Token compared in constant time",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "auth.py",
                        "import hmac\n\ndef authenticated(token, expected):\n    return hmac.compare_digest(token, expected)\n",
                    ),
                ),
                focus_path=PurePosixPath("auth.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

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
        literal_constants = _literal_constant_names(tree)
        dunder_compares = _equality_dunder_compares(tree, source)
        diags: list[Diagnostic] = []
        for node in compares:
            # Equality dunders compare held objects rather than gate access on attacker input.
            if id(node) in dunder_compares:
                continue
            # Only single-operator comparisons using == or != (Eq/NotEq).
            if len(node.ops) != 1:
                continue
            if not isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
                continue
            operands = [node.left, *node.comparators]
            if _is_password_confirmation_pair(operands):
                continue
            # Skip presence checks (None/True/False, numbers) and comparisons
            # against a compile-time str/bytes literal sentinel — an attacker
            # can't extract a runtime secret by timing a compare to a fixed
            # literal (ruff S105 covers hardcoded-secret literals separately).
            if any(_is_excluded_operand(op, literal_constants=literal_constants) for op in operands) and not any(
                _is_auth_lookup(op, crypto_module=crypto_module) for op in operands
            ):
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
    match node:
        case ast.NamedExpr(target=ast.Name(id=name)) | ast.Name(id=name) | ast.Attribute(attr=name):
            return _is_auth_secret_name(name, crypto_module=crypto_module)
        case ast.Subscript(slice=ast.Constant(value=str() as key)):
            return not _is_constant_reference(key) and _is_auth_secret_name(
                key,
                crypto_module=crypto_module,
            )
        case ast.Call(func=ast.Attribute(value=receiver, attr="get"), args=[ast.Constant(value=str() as key), *_]):
            return _is_auth_mapping(receiver) and _is_auth_secret_name(
                key,
                crypto_module=crypto_module,
            )
        case ast.JoinedStr(values=values):
            return any(
                isinstance(value, ast.FormattedValue) and _is_secret_operand(value.value, crypto_module=crypto_module)
                for value in values
            )
        case _:
            return False


def _is_password_confirmation_pair(operands: list[ast.expr]) -> bool:
    """Exclude two user-entered password fields checked for confirmation equality."""
    if len(operands) != _CONFIRMATION_OPERAND_COUNT:
        return False
    names = [_operand_name(operand) for operand in operands]
    if any(name is None for name in names):
        return False
    tokens = [set(identifier_tokens(name or "")) for name in names]
    return all("password" in operand_tokens for operand_tokens in tokens) and any(
        "confirmation" in operand_tokens or "confirm" in operand_tokens for operand_tokens in tokens
    )


def _operand_name(node: ast.AST) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


_AUTH_MAPPING_WORDS = frozenset({"authorization", "cookies", "headers", "path_params", "query_params"})


def _is_auth_mapping(node: ast.AST) -> bool:
    """Report whether `.get(...)` reads a request authenticator container."""
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name.lower() in _AUTH_MAPPING_WORDS
        case _:
            return False


def _is_auth_lookup(node: ast.AST, *, crypto_module: bool) -> bool:
    """Report whether an operand reads a named authenticator from a request mapping."""
    match node:
        case ast.Call(func=ast.Attribute(value=receiver, attr="get"), args=[ast.Constant(value=str() as key), *_]):
            return _is_auth_mapping(receiver) and _is_auth_secret_name(key, crypto_module=crypto_module)
        case _:
            return False


# Treat signature as an authenticator only when the surrounding module is cryptographic.
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
    # Lexical/content tokens are pieces of text, not authenticators. Requiring
    # a second auth word avoids timing warnings on parsers and translation code.
    if (
        "token" in tokens
        and tokens[0] in {"clean", "lexical", "parsed", "raw", "word"}
        and not any(tok in tokens for tok in _AUTH_WORDS - {"token"})
    ):
        return False
    auth_tokens = {tok for tok in tokens if tok in _AUTH_WORDS} | {
        f"{a}_{b}" for a, b in pairwise(tokens) if a == "api" and b == "key"
    }
    if not auth_tokens:
        return False
    if auth_tokens <= _CRYPTO_GATED_WORDS:
        return crypto_module
    return True


def _is_excluded_operand(node: ast.AST, *, literal_constants: frozenset[str]) -> bool:
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
        return _is_constant_reference(node.id) or node.id in literal_constants
    if isinstance(node, ast.Attribute):
        return _is_constant_reference(node.attr)
    return False


def _literal_constant_names(tree: ast.AST) -> frozenset[str]:
    """Collect immutable-looking names bound directly to fixed str/bytes sentinels."""
    names: set[str] = set()
    for node in nodes(tree, ast.Assign, ast.AnnAssign):
        match node:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=ast.Constant(value=str() | bytes()))
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.Constant(value=str() | bytes()))
            ):
                names.add(name)
            case _:
                pass
    return frozenset(names)


def _is_constant_reference(identifier: str) -> bool:
    """Report whether `identifier` is an ALL-CAPS named constant (a compile-time sentinel)."""
    return identifier.isupper() and any(c.isalpha() for c in identifier)
