from __future__ import annotations

import ast
from itertools import pairwise
from operator import itemgetter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

from sarj_python_lint._secret_names import identifier_tokens, is_secret_name, leading_word
from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, nodes
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path


_AUTH_WORDS = frozenset(
    {
        "apikey",
        "authorization",
        "bearer",
        "credential",
        "credentials",
        "hmac",
        "jwt",
        "passwd",
        "password",
        "passwords",
        "secret",
        "secrets",
        "signature",
        "signatures",
        "token",
    }
)
_CATEGORY_WORDS = frozenset({"kind", "kinds", "type", "types"})
_DESCRIPTOR_WORDS = frozenset(
    {"id", "ids", "kind", "kinds", "name", "names", "permission", "permissions", "scope", "scopes", "type", "types"}
)
_EXTERNAL_PREFIXES = frozenset({"given", "incoming", "presented", "provided", "received", "request", "submitted", "supplied"})
_EXPECTED_PREFIXES = frozenset({"configured", "current", "expected", "known", "stored"})
_AUTH_MAPPING_WORDS = frozenset({"authorization", "cookies", "headers", "path_params", "query_params"})
_STORED_OWNER_WORDS = frozenset({"config", "configuration", "self", "session", "settings"})
_PUBLIC_SENTINELS = frozenset({"", "MISSING", "NOT_CHANGED", "PLACEHOLDER", "UNSET", "WILDCARD"})
_PUBLIC_AUTH_SCHEMES = frozenset({"BASIC", "BEARER", "DIGEST"})
_ENV_CALLS = frozenset({"getenv"})
_ENV_MAPPINGS = frozenset({"environ"})
_EQUALITY_DUNDERS = frozenset({"__eq__", "__ne__"})
_PAIR_OPERAND_COUNT = 2
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


class _Role(NamedTuple):
    external: bool
    expected: bool
    password: bool = False


class _AssignmentParts(NamedTuple):
    target: str | None
    value: ast.expr | None


class _Roles:
    def __init__(self, environment_names: frozenset[str]) -> None:
        self.bindings: dict[str, list[tuple[tuple[int, int], _Role]]] = {}
        self.environment_names: frozenset[str] = environment_names

    def add(self, name: str, role: _Role, position: tuple[int, int]) -> None:
        self.bindings.setdefault(name, []).append((position, role))

    def role(self, name: str, position: tuple[int, int]) -> _Role | None:
        candidates = (binding for binding in self.bindings.get(name, ()) if binding[0] <= position)
        latest = max(candidates, default=None, key=itemgetter(0))
        return latest[1] if latest is not None else None


class PreferConstantTimeSecretCompare(Rule):
    id: str = "prefer-constant-time-secret-compare"
    code: str = "SARJ011"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Externally supplied authenticators are compared with timing-sensitive equality.",
        rationale=(
            "Ordinary equality may short-circuit based on matching content when attacker-controlled credentials are "
            "checked against configured secret state."
        ),
        remediation=(
            "For opaque tokens and MACs, normalize both operands to the same supported type and use "
            "`hmac.compare_digest`; for passwords, use the password-hashing library's verification API."
        ),
        category=RuleCategory.SECURITY,
        limitations=(
            "The warning requires evidence of an externally supplied credential and configured or stored secret state.",
            "Only direct equality and unambiguous same-scope aliases from headers, cookies, settings, or environment are traced.",
            "Generated files, tests, test-support modules, equality methods, public sentinels, and type-like values are excluded.",
            "`compare_digest` requires compatible ASCII string or bytes-like operands and may still reveal type or length.",
        ),
        examples=(
            RuleExample(
                example_id="request-api-key-equality",
                title="Request API key uses ordinary equality",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "auth.py",
                        'def authenticated(request, settings):\n    return request.headers["X-API-Key"] == settings.api_key\n',
                    ),
                ),
                focus_path=PurePosixPath("auth.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="request-api-key-constant-time",
                title="Request API key uses constant-time comparison",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "auth.py",
                        'import hmac\n\ndef authenticated(request, settings):\n    provided = request.headers["X-API-Key"]\n    return hmac.compare_digest(provided.encode("ascii"), settings.api_key.encode("ascii"))\n',
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
        if is_generated(path, source) or is_test_path(path) or is_test_support_path(path):
            return []
        if "==" not in source and "!=" not in source:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        role_cache: dict[int, _Roles] = {}
        environment_names = _environment_names(tree)
        dunder_compares = _equality_dunder_compares(tree, source)
        diagnostics: list[Diagnostic] = []
        for comparison in nodes(tree, ast.Compare):
            if id(comparison) in dunder_compares or len(comparison.ops) != 1:
                continue
            if not isinstance(comparison.ops[0], (ast.Eq, ast.NotEq)):
                continue
            operands = [comparison.left, *comparison.comparators]
            if _is_password_confirmation_pair(operands):
                continue
            scope = _enclosing_scope(comparison, parents, tree)
            roles = role_cache.setdefault(id(scope), _roles_for_scope(scope, environment_names))
            position = (comparison.lineno, comparison.col_offset)
            dominant_roles = _dominating_walrus_roles(comparison, parents, roles, position)
            operand_roles = [_operand_role(operand, roles, position, dominant_roles) for operand in operands]
            if not _has_authentication_pair(operand_roles):
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=comparison.lineno,
                    col=comparison.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=_message(operand_roles),
                )
            )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _message(roles: list[_Role]) -> str:
    if any(role.password for role in roles):
        return "password equality may leak information; use the password-hashing library's verification API"
    return (
        "equality on an externally supplied authenticator may short-circuit; normalize both operands to the same "
        "supported type and use `hmac.compare_digest(a, b)`"
    )


def _has_authentication_pair(roles: list[_Role]) -> bool:
    if len(roles) != _PAIR_OPERAND_COUNT:
        return False
    left, right = roles
    return (left.external and right.expected) or (right.external and left.expected)


def _roles_for_scope(
    scope: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef,
    module_environment_names: frozenset[str],
) -> _Roles:
    shadowed: frozenset[str] = _bound_names(scope) if not isinstance(scope, ast.Module) else frozenset()
    roles = _Roles(module_environment_names - shadowed)
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for argument in (*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs):
            role = _name_role(argument.arg)
            if argument.arg.lower() in _AUTH_MAPPING_WORDS:
                role = _Role(external=True, expected=False)
            roles.add(argument.arg, role, (scope.lineno, -1))
    assignments = sorted(_assignments(_scope_statements(scope)), key=lambda item: (item.lineno, item.col_offset))
    assigned_names: set[str] = set()
    for assignment in assignments:
        target, value = _assignment_parts(assignment)
        if target is None or value is None:
            continue
        position = (assignment.lineno, assignment.col_offset)
        role = _operand_role(value, roles, position)
        if not (role.external or role.expected) and target not in assigned_names:
            role = _name_role(target)
        roles.add(target, role, position)
        assigned_names.add(target)
    return roles


def _scope_statements(scope: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    return scope.body


def _assignments(statements: Iterable[ast.stmt]) -> Iterator[ast.Assign | ast.AnnAssign | ast.NamedExpr]:
    for node in statements:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            yield node


def _assignment_parts(node: ast.Assign | ast.AnnAssign | ast.NamedExpr) -> _AssignmentParts:
    if isinstance(node, ast.Assign):
        target = node.targets[0] if len(node.targets) == 1 else None
        value = node.value
    else:
        target = node.target
        value = node.value
    return _AssignmentParts(target.id if isinstance(target, ast.Name) else None, value)


def _operand_role(
    node: ast.expr,
    roles: _Roles,
    position: tuple[int, int],
    dominant_roles: dict[str, _Role] | None = None,
) -> _Role:
    if isinstance(node, ast.NamedExpr):
        return _operand_role(node.value, roles, position, dominant_roles)
    if isinstance(node, ast.Name):
        if dominant_roles is not None and node.id in dominant_roles:
            return dominant_roles[node.id]
        known = roles.role(node.id, position)
        return known if known is not None else _name_role(node.id)
    if isinstance(node, ast.JoinedStr):
        return _combined_roles(
            _operand_role(value.value, roles, position, dominant_roles)
            for value in node.values
            if isinstance(value, ast.FormattedValue)
        )
    if _is_external_lookup(node):
        return _Role(external=True, expected=False, password=_external_lookup_is_password(node))
    if _is_expected_source(node, roles.environment_names):
        return _Role(external=False, expected=True, password=_node_is_password(node))
    return _Role(external=False, expected=False)


def _combined_roles(roles: Iterable[_Role]) -> _Role:
    role_list = list(roles)
    return _Role(
        any(role.external for role in role_list),
        any(role.expected for role in role_list),
        any(role.password for role in role_list),
    )


def _name_role(identifier: str) -> _Role:
    tokens = identifier_tokens(identifier)
    if not _is_authenticator_name(identifier):
        return _Role(external=False, expected=False)
    first = leading_word(identifier) or ""
    external = first in _EXTERNAL_PREFIXES or ("header" in tokens and bool(set(tokens) & {"auth", "authorization"}))
    expected = first in _EXPECTED_PREFIXES or identifier.isupper()
    return _Role(external=external, expected=expected, password=_node_name_is_password(identifier))


def _is_authenticator_name(identifier: str) -> bool:
    tokens = identifier_tokens(identifier)
    token_set = set(tokens)
    is_auth_header = "header" in token_set and bool(token_set & {"auth", "authorization"})
    if not is_secret_name(identifier) and not is_auth_header:
        return False
    if (token_set == {"token"} and not identifier.isupper()) or not tokens:
        return False
    if tokens[-1] in _DESCRIPTOR_WORDS or token_set & _CATEGORY_WORDS:
        return False
    return bool(
        token_set & _AUTH_WORDS
        or is_auth_header
        or any(left == "api" and right == "key" for left, right in pairwise(tokens))
    )


def _is_external_lookup(node: ast.expr) -> bool:
    if isinstance(node, ast.Subscript):
        key = node.slice
        return _is_auth_mapping(node.value) and _is_auth_key(key)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        return bool(node.args) and _is_auth_mapping(node.func.value) and _is_auth_key(node.args[0])
    return False


def _external_lookup_is_password(node: ast.expr) -> bool:
    if isinstance(node, ast.Subscript):
        key = node.slice
    elif isinstance(node, ast.Call) and node.args:
        key = node.args[0]
    else:
        return False
    return isinstance(key, ast.Constant) and isinstance(key.value, str) and _node_name_is_password(key.value)


def _is_auth_mapping(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id.lower() in _AUTH_MAPPING_WORDS
    if isinstance(node, ast.Attribute):
        root = _root_name(node)
        return node.attr.lower() in _AUTH_MAPPING_WORDS and root is not None and root.lower() in {"req", "request"}
    return False


def _is_auth_key(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and (
        node.value.lower() == "token" or _is_authenticator_name(node.value)
    )


def _is_expected_source(node: ast.expr, environment_names: frozenset[str]) -> bool:
    match node:
        case ast.Constant(value=str() | bytes() as value):
            return not _is_public_sentinel(value)
        case ast.Attribute() as attribute:
            owner = _root_name(attribute)
            return owner is not None and owner.lower() in _STORED_OWNER_WORDS and _is_authenticator_name(attribute.attr)
        case ast.Subscript(value=value, slice=index):
            return (
                _root_name(value) in environment_names
                and _terminal_name(value) in _ENV_MAPPINGS
                and _is_auth_key(index)
            )
        case ast.Call(func=ast.Attribute(value=value, attr="strip"), args=[]):
            return _is_expected_source(value, environment_names)
        case ast.Call() as call:
            return _is_environment_call(call, environment_names)
        case _:
            return False


def _is_environment_call(node: ast.Call, environment_names: frozenset[str]) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _ENV_CALLS:
        return _root_name(func.value) in environment_names and bool(node.args) and _is_auth_key(node.args[0])
    if isinstance(func, ast.Attribute) and func.attr == "get":
        return (
            _root_name(func.value) in environment_names
            and _terminal_name(func.value) in _ENV_MAPPINGS
            and bool(node.args)
            and _is_auth_key(node.args[0])
        )
    return False


def _is_public_sentinel(value: str | bytes) -> bool:
    text = value.decode(errors="ignore") if isinstance(value, bytes) else value
    normalized = text.strip().upper().replace("-", "_").replace(" ", "_")
    return normalized in _PUBLIC_SENTINELS or normalized in _PUBLIC_AUTH_SCHEMES


def _node_is_password(node: ast.expr) -> bool:
    name = _operand_name(node)
    return name is not None and _node_name_is_password(name)


def _node_name_is_password(identifier: str) -> bool:
    return bool(set(identifier_tokens(identifier)) & {"passwd", "password", "passwords"})


def _environment_names(module: ast.Module) -> frozenset[str]:
    names: set[str] = set()
    rebound: set[str] = set()
    for statement in module.body:
        if isinstance(statement, ast.Import):
            names.update(alias.asname or alias.name for alias in statement.names if alias.name == "os")
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            target, _ = _assignment_parts(statement)
            if target is not None:
                rebound.add(target)
    return frozenset(names - rebound)


def _bound_names(scope: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    names = {
        argument.arg
        for argument in (*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs)
    }
    for assignment in _assignments(scope.body):
        target, _ = _assignment_parts(assignment)
        if target is not None:
            names.add(target)
    return frozenset(names)


def _dominating_walrus_roles(
    comparison: ast.Compare,
    parents: dict[int, ast.AST],
    roles: _Roles,
    position: tuple[int, int],
) -> dict[str, _Role]:
    result: dict[str, _Role] = {}
    current: ast.AST = comparison
    while (parent := parents.get(id(current))) is not None:
        if isinstance(parent, ast.If) and current in parent.body:
            for named in nodes(parent.test, ast.NamedExpr):
                result[named.target.id] = _operand_role(named.value, roles, position, result)
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            break
        current = parent
    return result


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _terminal_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def _enclosing_scope(
    node: ast.AST,
    parents: dict[int, ast.AST],
    module: ast.Module,
) -> ast.Module | ast.FunctionDef | ast.AsyncFunctionDef:
    current: ast.AST = node
    while (parent := parents.get(id(current))) is not None:
        if isinstance(parent, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
            return parent
        current = parent
    return module


def _is_password_confirmation_pair(operands: list[ast.expr]) -> bool:
    if len(operands) != _PAIR_OPERAND_COUNT:
        return False
    names = [_operand_name(operand) for operand in operands]
    if any(name is None for name in names):
        return False
    tokens = [set(identifier_tokens(name or "")) for name in names]
    return all("password" in operand_tokens for operand_tokens in tokens) and any(
        "confirmation" in operand_tokens or "confirm" in operand_tokens for operand_tokens in tokens
    )


def _operand_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def _equality_dunder_compares(tree: ast.AST, source: str) -> frozenset[int]:
    if not any(dunder in source for dunder in _EQUALITY_DUNDERS):
        return frozenset()
    return frozenset(
        id(inner)
        for function in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef)
        if function.name in _EQUALITY_DUNDERS
        for inner in _same_scope_compares(function)
    )


def _same_scope_compares(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.Compare]:
    stack: list[ast.AST] = list(function.body)
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(current, ast.Compare):
            yield current
        stack.extend(children(current))
