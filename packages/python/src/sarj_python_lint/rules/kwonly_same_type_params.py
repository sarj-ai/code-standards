"""SARJ034 — >=2 positional parameters with the same primitive annotation — swap-prone.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_kwonly_same_type_params.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MIN_SAME_TYPE = 2

_PRIMITIVES = frozenset({"str", "int", "float", "bool"})

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


class KwonlySameTypeParams(Rule):
    id: str = "kwonly-same-type-params"
    code: str = "SARJ034"
    description: str = (
        "two or more positional parameters with the same primitive annotation "
        "are swap-prone — make them keyword-only by inserting `*`."
    )

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
        diags: list[Diagnostic] = []
        for node, offending in candidates:
            if node.name in value_referenced or node.name in overload_names:
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
                    message=(
                        f"`{node.name}` takes multiple positional `{offending}` "
                        "parameters — swap-prone at call sites; insert `*` to "
                        "make them keyword-only."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_exempt_path(path: Path) -> bool:
    """Report whether the file is exempt on location alone."""
    directories = path.parts[:-1]
    if any(_TEST_SUPPORT_DIR_RE.fullmatch(part) for part in directories):
        return True
    return _MIGRATIONS_DIR in directories and _MIGRATION_FILE_RE.match(path.name) is not None


def _is_exempt(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    name = node.name
    if name.startswith("__") and name.endswith("__"):
        return True
    if name.startswith(_EXEMPT_NAME_PREFIXES):
        return True
    return any(
        (isinstance(dec, ast.Name) and dec.id in _EXEMPT_DECORATORS)
        or (isinstance(dec, ast.Attribute) and dec.attr in _EXEMPT_DECORATORS)
        or _is_route_decorator(dec)
        or _is_cli_command_decorator(dec)
        for dec in node.decorator_list
    )


def _is_cli_command_decorator(dec: ast.expr) -> bool:
    """Report whether `dec` registers the function as a click/typer CLI handler."""
    target = dec.func if isinstance(dec, ast.Call) else dec
    match target:
        case ast.Attribute(value=ast.Name(id=receiver)) if receiver in _CLI_DECORATOR_MODULES:
            return True
        case ast.Attribute(value=ast.Name(), attr=attr) if attr in _CLI_DECORATOR_ATTRS:
            return True
        case _:
            return False


def _method_node_ids(tree: ast.AST) -> frozenset[int]:
    """Identify the defs that are methods — direct children of a class body."""
    return frozenset(
        id(child)
        for node in nodes(tree, ast.ClassDef)
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _calls_super_same_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the body calls `super().<this method's name>(...)`."""
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
    """Report whether `dec` is an HTTP-route decorator like `@router.get(...)`."""
    target = dec.func if isinstance(dec, ast.Call) else dec
    match target:
        case ast.Attribute(value=ast.Name(), attr=attr) if attr in _HTTP_ROUTE_METHODS:
            return True
        case _:
            return False


def _swap_prone_annotation(args: ast.arguments) -> str | None:
    """Find a primitive annotation shared by >= 2 swap-prone positional parameters."""
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
            and _is_high_value_group(name, arg_names)
        ):
            return name
    return None


def _is_high_value_group(annotation: str, arg_names: list[str]) -> bool:
    """Report whether a same-primitive group is worth enforcing globally."""
    if annotation == "bool":
        return True
    return sum(1 for name in arg_names if _RISKY_NAME_PART_RE.search(name)) >= _MIN_SAME_TYPE


def _is_dunder_prefixed(arg: str) -> bool:
    """Report whether `arg` uses the PEP 484 positional-only naming convention."""
    return arg.startswith("__") and not arg.endswith("__")


def _is_conventional_order(arg_names: list[str]) -> bool:
    """Report whether every name comes from one conventional ordered vocabulary."""
    names = set(arg_names)
    return any(names <= vocabulary for vocabulary in _CONVENTIONAL_ORDER_GROUPS)


_NUMERIC_SUFFIX_RE = re.compile(r"_?\d+$")

#: `policy_id_a` / `policy_id_b` — the alphabetic spelling of the same symmetry.
#: The underscore is required, so `a`/`b` and `s`/`d` keep firing: there the
#: whole name is the label and the call site really cannot tell them apart.
_LETTER_SUFFIX_RE = re.compile(r"_[a-z]$")


def _is_symmetric_numbering(arg_names: list[str]) -> bool:
    """Report whether the group is one stem plus a symmetric per-parameter label."""
    return _shares_one_stem(arg_names, _NUMERIC_SUFFIX_RE) or _shares_one_stem(arg_names, _LETTER_SUFFIX_RE)


def _shares_one_stem(arg_names: list[str], suffix: re.Pattern[str]) -> bool:
    """Report whether every name is the same stem plus a match of `suffix`."""
    if not all(suffix.search(name) for name in arg_names):
        return False
    stems = {suffix.sub("", name) for name in arg_names}
    return len(stems) == 1 and bool(next(iter(stems)))


def _value_referenced_names(tree: ast.AST) -> frozenset[str]:
    """Names referenced as a VALUE (loaded but not called) anywhere in the module."""
    call_funcs = {id(node.func) for node in nodes(tree, ast.Call)}
    return frozenset(
        node.id for node in nodes(tree, ast.Name) if isinstance(node.ctx, ast.Load) and id(node) not in call_funcs
    )


def _overload_stub_names(tree: ast.AST) -> frozenset[str]:
    """Names carrying an `@overload` decorator anywhere in the module."""
    return frozenset(
        node.name
        for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef)
        if any(
            (isinstance(dec, ast.Name) and dec.id == "overload")
            or (isinstance(dec, ast.Attribute) and dec.attr == "overload")
            for dec in node.decorator_list
        )
    )
