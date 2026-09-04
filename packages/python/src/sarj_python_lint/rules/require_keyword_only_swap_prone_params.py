from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
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
    Severity,
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MIN_SAME_TYPE = 2

# Ruff FBT001 already owns positional booleans in the same production domain.
_PRIMITIVES = frozenset({"str", "int", "float"})

_EXEMPT_DECORATORS = frozenset({"override", "overload", "abstractmethod"})

_HTTP_ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "websocket"})

#: Decorator receivers whose attribute access marks a CLI command handler.
_CLI_DECORATOR_MODULES = frozenset({"click", "typer"})

#: `@<name>.command(...)` / `@<name>.group(...)` — click groups and typer apps.
_CLI_DECORATOR_ATTRS = frozenset({"command", "group"})

#: Methods that implement a duck-typed stdlib protocol.
_DUCK_PROTOCOL_METHODS = frozenset(
    {
        "read",
        "read1",
        "readinto",
        "readinto1",
        "readline",
        "readlines",
        "seek",
        "truncate",
        "write",
        "writelines",
        "connect",
        "connect_ex",
        "getsockopt",
        "setsockopt",
        "recv",
        "recv_into",
        "recvfrom",
        "recvfrom_into",
        "send",
        "sendall",
        "sendto",
        "add_header",
        "add_unredirected_header",
        "get_header",
        "has_header",
    }
)

#: Parameter-name vocabularies whose ORDER is the notation.
_CONVENTIONAL_ORDER_GROUPS = (
    frozenset({"x", "y", "z"}),
    frozenset({"lat", "lon", "alt"}),
    frozenset({"latitude", "longitude", "altitude"}),
    frozenset({"width", "height", "depth"}),
    frozenset({"red", "green", "blue", "alpha"}),
    frozenset({"row", "column"}),
    frozenset({"top", "right", "bottom", "left"}),
    frozenset({"left", "right"}),
    frozenset({"lo", "hi"}),
    frozenset({"low", "high"}),
    frozenset({"minimum", "maximum"}),
    frozenset({"min_value", "max_value"}),
    frozenset({"begin", "end"}),
    frozenset({"source", "sink"}),
    frozenset({"year", "month", "day"}),
    frozenset({"hour", "minute", "second", "microsecond"}),
    frozenset({"start", "stop", "step"}),
)

#: A DIRECTORY named `tests_common`, `test_utils`, `system_tests`, ...
_TEST_SUPPORT_DIR_RE = re.compile(r"tests?_.+|.+_tests?", re.IGNORECASE)

#: A numbered migration: an append-only artifact that has already run.
_MIGRATIONS_DIR = "migrations"
_MIGRATION_FILE_RE = re.compile(r"\d{4}_")

_EXEMPT_NAME_PREFIXES = ("visit_", "test_")
_RISKY_NAME_PART_RE = re.compile(
    r"(?:^|_)(?:id|key|token|secret|password|signature|hash|email|url|uri|path|file|"
    r"source|src|target|dst|dest|destination|parent|child|from|to|old|new|"
    r"before|after|previous|next|expected|actual|left_id|right_id)(?:_|$)"
)


class _SwapProneGroup(NamedTuple):
    annotation: str
    parameters: tuple[str, ...]


@final
class RequireKeywordOnlySwapProneParams(Rule):
    id: str = "require-keyword-only-swap-prone-params"
    code: str = "SARJ034"
    documentation = RuleDocumentation(
        summary="Risky-name positional parameters sharing a primitive annotation may be confused.",
        rationale="A caller can exchange semantically distinct positional values without a type-checking failure.",
        remediation=(
            "If API, callback, and protocol compatibility permit, make the risky parameters keyword-only and update "
            "callers; otherwise retain the contract and suppress the warning locally."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        aliases=("kwonly-same-type-params",),
        limitations=(
            "Only high-risk groups of bare `str`, `int`, or `float` annotations are reported.",
            "Tests, generated code, migrations, conventional ordered groups, explicit inheritance, local structural protocols, and recognized routes, CLI handlers, callbacks, and runtime protocols are excluded.",
            "External and published calling contracts cannot be proven from one file, so this compatibility-sensitive rule remains a warning without autofix.",
        ),
        examples=(
            RuleExample(
                example_id="positional-source-and-target",
                title="Source and target IDs are positional",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def move(source_id: str, target_id: str) -> None: ...\n\nmove('inbox', 'archive')\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="keyword-only-source-and-target",
                title="Source and target IDs are keyword-only",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def move(*, source_id: str, target_id: str) -> None: ...\n\nmove(source_id='inbox', target_id='archive')\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source) or _is_exempt_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        # Run cheap signature guards before allocating the analysis visitor.
        candidates = [
            (node, offending)
            for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef)
            if not _is_exempt(node) and (offending := _swap_prone_annotation(node.args)) is not None
        ]
        if not candidates:
            return []
        value_referenced = _value_referenced_names(tree)
        overload_names = _overload_stub_names(tree)
        method_ids = _method_node_ids(tree)
        externally_owned_method_ids = _externally_owned_method_node_ids(tree)
        protocol_method_names = _protocol_method_names(tree)
        trusted_hmac_bindings = _trusted_hmac_bindings(tree)
        source_lines = source.splitlines()
        diags: list[Diagnostic] = []
        for node, offending in candidates:
            exclusions = (
                node.name in value_referenced,
                node.name in overload_names,
                id(node) in externally_owned_method_ids,
                id(node) in method_ids and node.name in protocol_method_names,
                _is_symmetric_rejection_guard(node, offending.parameters, trusted_hmac_bindings),
                is_suppressed(source_lines, node.lineno, self.code),
            )
            if any(exclusions):
                continue
            # Checked last: `_calls_super_same_name` walks the body, so it runs
            # only for the few signatures that would otherwise be reported.
            if id(node) in method_ids and (node.name in _DUCK_PROTOCOL_METHODS or _calls_super_same_name(node)):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"`{node.name}` has confusable positional `{offending.annotation}` parameters "
                        f"{_parameter_list(offending.parameters)}; make them keyword-only only if this callable owns "
                        "its calling convention."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_exempt_path(path: Path) -> bool:
    directories = path.parts[:-1]
    if any(_TEST_SUPPORT_DIR_RE.fullmatch(part) for part in directories):
        return True
    return _MIGRATIONS_DIR in directories and _MIGRATION_FILE_RE.match(path.name) is not None


def _is_exempt(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    name = node.name
    # Locally owned constructors are ordinary call sites and are especially
    # prone to silent swaps. Other dunders implement fixed Python protocols.
    if name != "__init__" and name.startswith("__") and name.endswith("__"):
        return True
    # A variadic constructor commonly forwards a third-party/base signature;
    # syntax alone cannot prove that making its named prefix keyword-only is
    # compatible with the inherited API.
    if name == "__init__" and (node.args.vararg is not None or node.args.kwarg is not None):
        return True
    if name.startswith(_EXEMPT_NAME_PREFIXES):
        return True
    if node.decorator_list and not all(_is_locally_owned_method_decorator(dec) for dec in node.decorator_list):
        return True
    return any(
        (isinstance(dec, ast.Name) and dec.id in _EXEMPT_DECORATORS)
        or (isinstance(dec, ast.Attribute) and dec.attr in _EXEMPT_DECORATORS)
        or _is_route_decorator(dec)
        or _is_cli_command_decorator(dec)
        for dec in node.decorator_list
    )


def _is_locally_owned_method_decorator(dec: ast.expr) -> bool:
    return isinstance(dec, ast.Name) and dec.id in {"classmethod", "staticmethod"}


def _is_cli_command_decorator(dec: ast.expr) -> bool:
    target = dec.func if isinstance(dec, ast.Call) else dec
    match target:
        case ast.Attribute(value=ast.Name(id=receiver)) if receiver in _CLI_DECORATOR_MODULES:
            return True
        case ast.Attribute(value=ast.Name(), attr=attr) if attr in _CLI_DECORATOR_ATTRS:
            return True
        case _:
            return False


def _dotted_name(node: ast.expr) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return None if parent is None else (*parent, node.attr)
    return None


def _method_node_ids(tree: ast.AST) -> frozenset[int]:
    return frozenset(
        id(child)
        for node in nodes(tree, ast.ClassDef)
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _externally_owned_method_node_ids(tree: ast.AST) -> frozenset[int]:
    return frozenset(
        id(child)
        for node in nodes(tree, ast.ClassDef)
        if node.decorator_list
        or node.keywords
        or any(not (isinstance(base, ast.Name) and base.id == "object") for base in node.bases)
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _protocol_method_names(tree: ast.AST) -> frozenset[str]:
    return frozenset(
        child.name
        for node in nodes(tree, ast.ClassDef)
        if any((base_name := _dotted_name(base)) is not None and base_name[-1] == "Protocol" for base in node.bases)
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _calls_super_same_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(func := call.func, ast.Attribute)
        and func.attr == node.name
        and isinstance(inner := func.value, ast.Call)
        and isinstance(inner.func, ast.Name)
        and inner.func.id == "super"
        for call in walk(node)
        if isinstance(call, ast.Call)
    )


def _is_route_decorator(dec: ast.expr) -> bool:
    target = dec.func if isinstance(dec, ast.Call) else dec
    match target:
        case ast.Attribute(value=ast.Name(), attr=attr) if attr in _HTTP_ROUTE_METHODS:
            return True
        case _:
            return False


def _swap_prone_annotation(args: ast.arguments) -> _SwapProneGroup | None:
    params = list(args.args)
    if params and params[0].arg in {"self", "cls"}:
        params = params[1:]
    groups: dict[str, list[str]] = {}
    for p in params:
        if _is_dunder_prefixed(p.arg):
            continue
        if isinstance(ann := p.annotation, ast.Name) and ann.id in _PRIMITIVES:
            groups.setdefault(ann.id, []).append(p.arg)
    for name, arg_names in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if (
            len(arg_names) >= _MIN_SAME_TYPE
            and not (_is_symmetric_numbering(arg_names) or _is_conventional_order(arg_names))
            and _is_high_value_group(arg_names)
        ):
            return _SwapProneGroup(name, tuple(arg_names))
    return None


def _parameter_list(parameters: tuple[str, ...]) -> str:
    rendered = [f"`{parameter}`" for parameter in parameters]
    if len(rendered) == _MIN_SAME_TYPE:
        return f"{rendered[0]} and {rendered[1]}"
    return f"{', '.join(rendered[:-1])}, and {rendered[-1]}"


def _is_symmetric_rejection_guard(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parameters: tuple[str, ...],
    trusted_hmac_bindings: frozenset[str],
) -> bool:
    if len(parameters) != _MIN_SAME_TYPE:
        return False
    body = node.body[1:] if ast.get_docstring(node, clean=False) is not None else node.body
    if not (
        len(body) == _MIN_SAME_TYPE
        and isinstance(guard := body[0], ast.If)
        and not guard.orelse
        and len(guard.body) == 1
        and isinstance(guard.body[0], ast.Raise)
        and isinstance(result := body[1], ast.Return)
        and isinstance(result.value, ast.Constant)
        and result.value.value is True
    ):
        return False
    if any(
        loaded.id in parameters
        for statement in (*guard.body, result)
        for loaded in walk(statement)
        if isinstance(loaded, ast.Name) and isinstance(loaded.ctx, ast.Load)
    ):
        return False
    operands = _symmetric_guard_operands(guard.test, trusted_hmac_bindings)
    return operands is not None and _same_parameter_transform(*operands, *parameters)


def _symmetric_guard_operands(
    condition: ast.expr,
    trusted_hmac_bindings: frozenset[str],
) -> tuple[ast.expr, ast.expr] | None:
    if (
        isinstance(condition, ast.Compare)
        and len(condition.ops) == 1
        and isinstance(condition.ops[0], ast.NotEq)
        and len(condition.comparators) == 1
    ):
        return condition.left, condition.comparators[0]
    if not (isinstance(condition, ast.UnaryOp) and isinstance(condition.op, ast.Not)):
        return None
    call = condition.operand
    if not isinstance(call, ast.Call) or call.keywords or len(call.args) != _MIN_SAME_TYPE:
        return None
    callee = _dotted_name(call.func)
    return (
        (call.args[0], call.args[1])
        if callee is not None
        and len(callee) == _MIN_SAME_TYPE
        and callee[-1] == "compare_digest"
        and callee[0] in trusted_hmac_bindings
        else None
    )


def _trusted_hmac_bindings(tree: ast.Module) -> frozenset[str]:
    top_level_imports = {
        alias.asname or alias.name
        for statement in tree.body
        if isinstance(statement, ast.Import)
        for alias in statement.names
        if alias.name == "hmac"
    }
    if not top_level_imports:
        return frozenset()
    rebound = {
        node.id
        for node in walk(tree)
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load) and node.id in top_level_imports
    }
    rebound.update(node.arg for node in walk(tree) if isinstance(node, ast.arg) and node.arg in top_level_imports)
    rebound.update(
        node.name
        for node in walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in top_level_imports
    )
    rebound.update(
        node.name
        for node in walk(tree)
        if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar))
        and node.name is not None
        and node.name in top_level_imports
    )
    rebound.update(
        node.name
        for node in walk(tree)
        if isinstance(node, (ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple)) and node.name in top_level_imports
    )
    rebound.update(
        node.rest
        for node in walk(tree)
        if isinstance(node, ast.MatchMapping) and node.rest is not None and node.rest in top_level_imports
    )
    for node in walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for alias in node.names:
            binding = alias.asname or alias.name.rsplit(".", maxsplit=1)[-1]
            is_trusted_import = (
                node in tree.body
                and isinstance(node, ast.Import)
                and alias.name == "hmac"
                and binding in top_level_imports
            )
            if binding in top_level_imports and not is_trusted_import:
                rebound.add(binding)
    return frozenset(top_level_imports - rebound)


def _same_parameter_transform(left: ast.expr, right: ast.expr, left_name: str, right_name: str) -> bool:
    return _same_parameter_transform_in_order(left, right, left_name, right_name) or _same_parameter_transform_in_order(
        left, right, right_name, left_name
    )


def _same_parameter_transform_in_order(left: ast.expr, right: ast.expr, left_name: str, right_name: str) -> bool:
    left_transform = _safe_parameter_transform(left, left_name)
    return left_transform is not None and left_transform == _safe_parameter_transform(right, right_name)


def _safe_parameter_transform(node: ast.expr, parameter: str) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name) and node.id == parameter:
        return ("identity",)
    if not (
        isinstance(node, ast.Call)
        and not node.keywords
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "utf-8"
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "encode"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == parameter
    ):
        return None
    return ("encode", "utf-8")


def _is_high_value_group(arg_names: list[str]) -> bool:
    return sum(1 for name in arg_names if _RISKY_NAME_PART_RE.search(name)) >= _MIN_SAME_TYPE


def _is_dunder_prefixed(arg: str) -> bool:
    return arg.startswith("__") and not arg.endswith("__")


def _is_conventional_order(arg_names: list[str]) -> bool:
    names = set(arg_names)
    return any(names <= vocabulary for vocabulary in _CONVENTIONAL_ORDER_GROUPS)


_NUMERIC_SUFFIX_RE = re.compile(r"_?\d+$")

#: `policy_id_a` / `policy_id_b` — the alphabetic spelling of the same symmetry.
#: The underscore is required, so `a`/`b` and `s`/`d` keep firing: there the
#: whole name is the label and the call site really cannot tell them apart.
_LETTER_SUFFIX_RE = re.compile(r"_[a-z]$")


def _is_symmetric_numbering(arg_names: list[str]) -> bool:
    return _shares_one_stem(arg_names, _NUMERIC_SUFFIX_RE) or _shares_one_stem(arg_names, _LETTER_SUFFIX_RE)


def _shares_one_stem(arg_names: list[str], suffix: re.Pattern[str]) -> bool:
    if not all(suffix.search(name) for name in arg_names):
        return False
    stems = {suffix.sub("", name) for name in arg_names}
    return len(stems) == 1 and bool(next(iter(stems)))


def _value_referenced_names(tree: ast.AST) -> frozenset[str]:
    call_funcs = {id(node.func) for node in nodes(tree, ast.Call)}
    names = {node.id for node in nodes(tree, ast.Name) if isinstance(node.ctx, ast.Load) and id(node) not in call_funcs}
    names.update(
        node.attr
        for node in nodes(tree, ast.Attribute)
        if isinstance(node.ctx, ast.Load) and id(node) not in call_funcs
    )
    return frozenset(names)


def _overload_stub_names(tree: ast.AST) -> frozenset[str]:
    return frozenset(
        node.name
        for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef)
        if any(
            (isinstance(dec, ast.Name) and dec.id == "overload")
            or (isinstance(dec, ast.Attribute) and dec.attr == "overload")
            for dec in node.decorator_list
        )
    )
