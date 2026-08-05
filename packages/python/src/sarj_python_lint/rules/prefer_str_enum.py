"""SARJ006 — Raw `str` used where a closed enumeration is clearly intended.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_str_enum.py
"""

from __future__ import annotations

import ast
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, walk
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


#: Per-variable accumulator containing location and literals grouped by comparison operator.
type _ClusterEntry = tuple[int, int, set[str], set[str], set[str], set[str]]

_MIN_CAST_ARGS = 2
_MIN_TYPE_ALIAS_ARGS = 2
_CHOICE_PAIR_ARITY = 2
_CAST_FUNCTION = "cast"
_STR_CONSTRUCTOR = "str"


#: Sibling class attributes whose presence marks all raw-str fields as choice-like.
CHOICES_ATTR_NAMES = frozenset({"choices", "states", "statuses", "values", "allowed"})

CHOICE_COLLECTION_FIELDS = MappingProxyType({"statuses": "status", "states": "state"})

#: Literals that are an external / reserved vocabulary rather than an app enum.
#: Only multi-character tokens live here — single characters are handled by the
#: tokenizer-scan heuristic (`_is_scanner_key`) so that a genuine two-way
#: dispatch like `kind == "a"` / `kind == "b"` still fires.
EXTERNAL_VOCAB = frozenset(
    {
        "is",
        "in",
        "not",
        "and",
        "or",
        "self",
        "cls",
        "rb",
        "rt",
        "wb",
        "wt",
        "ab",
        "at",
        "xb",
        "xt",
        "http",
        "https",
        "ftp",
        "ws",
        "wss",
        "ssh",
        "socks5",
        "socks5h",
        "file",
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "head",
        "options",
        "trace",
        "connect",
    }
)

#: Variable keys whose single-character comparisons are a tokenizer scan, not an
#: enum dispatch (`last_char == "g"`), so single-character clusters on them are
#: not flagged.
_SCANNER_KEY_SEGMENTS = frozenset({"c", "ch", "chr", "char", "token", "tok", "letter", "digit", "glyph"})

#: Variable names whose external vocabulary is open-ended rather than an application enum.
OPEN_DOMAIN_CODE_NAMES = frozenset(
    {
        "language",
        "lang",
        "country",
        "currency",
        "timezone",
        "tz",
        "locale",
        "region",
        "code",
        "country_code",
    }
)

#: A "short lowercase token" — the shape enum member values take.
_LOWER_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]{0,30}$")

#: The stdlib `open()` mode vocabulary: 1-3 characters drawn from `rwxab+t`.
_FILE_MODE_RE = re.compile(r"[rwxabt+]{1,3}")

#: Variable names that hold an `open()` mode.
_FILE_MODE_KEYS = frozenset({"filemode", "mode", "open_mode", "openmode"})

#: How many distinct literals one operator must enumerate before firing.
_MIN_CLUSTER_SIZE = 2

#: Comparison-operator buckets a cluster accumulates literals into.
_EQ = "=="
_NE = "!="
_MEMBERSHIP = "in"

#: Call names that read a value out of a payload / stream / environment the
#: module does not own, so the vocabulary of the result is not the module's.
_WIRE_CALL_NAMES = frozenset({"get", "getenv", "items", "keys", "next", "pop", "popleft", "values"})

#: Calls that wrap an iterable without changing where its elements came from.
_ITERABLE_WRAPPERS = frozenset({"enumerate", "iter", "list", "reversed", "set", "sorted", "tuple", "zip"})

#: Attribute roots the module owns; `self.mode` is this class's own field, while
#: `token.type` / `expr.arg_names` belong to somebody else's object.
_OWNED_ROOTS = frozenset({"self", "cls"})

#: Depth at which an attribute chain has left the object the module owns:
#: `self._config_wrapper.extra` reads a collaborator's field, not `self`'s.
_FOREIGN_CHAIN_DEPTH = 2


class PreferStrEnum(Rule):
    id: str = "prefer-str-enum"
    code: str = "SARJ006"
    description: str = "Corroborated choice-like str field or equality cluster — prefer StrEnum."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:  # ruff: ignore[too-many-locals] -- traversal state.
        if is_generated(path, source):
            return []
        if not _has_str_enum_signal(source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        check_clusters = not is_test_path(path)
        alias_names, alias_valuesets = _module_literal_aliases(tree)
        raw_string_aliases = _module_raw_string_aliases(tree)
        literal_funcs = _literal_returning_functions(tree)
        class_nodes: list[ast.ClassDef] = []
        all_clusters: list[tuple[dict[str, _ClusterEntry], frozenset[str]]] = []
        cluster_opacity: dict[int, frozenset[str]] = {}
        comprehension_opacity: dict[int, frozenset[str]] = {}
        stack: list[tuple[ast.AST, dict[str, _ClusterEntry] | None]] = [(tree, None)]
        while stack:
            node, active = stack.pop()
            if isinstance(node, ast.ClassDef):
                class_nodes.append(node)
                child_active: dict[str, _ClusterEntry] | None = None
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if check_clusters:
                    comprehension_opacity.update(_closed_comprehension_targets(node, alias_names, raw_string_aliases))
                    child_active = {}
                    shadowed = {
                        arg.arg
                        for arg in (
                            *node.args.posonlyargs,
                            *node.args.args,
                            *node.args.kwonlyargs,
                        )
                    }
                    shadowed.update(target for target, _value in _local_bindings(node))
                    inherited = cluster_opacity.get(id(active), frozenset()) - shadowed
                    opaque = inherited | _opaque_names(node, alias_names, literal_funcs, raw_string_aliases)
                    all_clusters.append((child_active, opaque))
                    cluster_opacity[id(child_active)] = opaque
                else:
                    child_active = None
            elif isinstance(node, ast.Lambda):
                child_active = None
            elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                # Comprehension targets have their own implicit scope and can
                # shadow the enclosing function's variables, so collect their
                # comparisons separately rather than merging same-named keys.
                if active is None:
                    child_active = None
                else:
                    child_active = {}
                    bound_targets = {
                        name for generator in node.generators for name in _bound_target_names(generator.target)
                    }
                    wire_targets = {
                        name
                        for generator in node.generators
                        if _is_wire_lookup(generator.iter)
                        for name in _bound_target_names(generator.target)
                    }
                    opaque = (
                        (cluster_opacity.get(id(active), frozenset()) - bound_targets)
                        | wire_targets
                        | comprehension_opacity.get(id(node), frozenset())
                    )
                    all_clusters.append((child_active, frozenset(opaque)))
                    cluster_opacity[id(child_active)] = frozenset(opaque)
            else:
                child_active = active
                if active is not None:
                    if isinstance(node, ast.Compare):
                        _accumulate_compare(active, node)
                    elif isinstance(node, ast.Match):
                        _accumulate_match(active, node)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                outer_expressions = {
                    id(expression)
                    for expression in (
                        *node.decorator_list,
                        *node.args.defaults,
                        *(default for default in node.args.kw_defaults if default is not None),
                    )
                }
                stack.extend(
                    (child, active if id(child) in outer_expressions else child_active) for child in children(node)
                )
            else:
                stack.extend((child, child_active) for child in children(node))

        diags: list[Diagnostic] = []
        for clusters, literal_typed in all_clusters:
            for key, entry in clusters.items():
                if _cluster_is_already_closed(key, entry, literal_typed, alias_valuesets):
                    continue
                if not _cluster_fires(key, entry):
                    continue
                diags.append(
                    Diagnostic(
                        path=path,
                        line=entry[0],
                        col=entry[1],
                        code=self.code,
                        message=(f"`{key}` is compared against a closed set of string literals — define a StrEnum"),
                    )
                )

        for cls in class_nodes:
            diags.extend(self._class_field_diags(path, cls))
        diags.sort(key=lambda d: (d.line, d.col))
        return diags

    def _class_field_diags(self, path: Path, cls: ast.ClassDef) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        if any(_trailing_name(b) in {"Enum", "StrEnum", "IntEnum"} for b in cls.bases):
            return diags
        choice_groups: list[tuple[str, set[str]]] = []
        for stmt in cls.body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                target = (
                    stmt.targets[0] if isinstance(stmt, ast.Assign) and stmt.targets else getattr(stmt, "target", None)
                )
                if not isinstance(target, ast.Name):
                    continue
                val = getattr(stmt, "value", None)
                values = _string_collection_values(val)
                binding = target.id.lower()
                if (
                    values is not None
                    and len(values) >= _MIN_CLUSTER_SIZE
                    and (binding in CHOICES_ATTR_NAMES or binding.endswith("_choices"))
                ):
                    choice_groups.append((binding, values))
        candidates: list[tuple[ast.AnnAssign, str, str | None]] = []
        for stmt in cls.body:
            if not isinstance(stmt, ast.AnnAssign):
                continue
            if not isinstance(stmt.target, ast.Name):
                continue
            if not _is_choice_string_annotation(stmt.annotation):
                continue
            name = stmt.target.id
            default = _str_const(stmt.value) if stmt.value is not None else None
            candidates.append((stmt, name, default))
        for stmt, name, default in candidates:
            associated_values = {
                value
                for binding, values in choice_groups
                if _choice_binding_field(binding) == name.lower()
                for value in values
            }
            generic_values = {
                value for binding, values in choice_groups if _choice_binding_field(binding) is None for value in values
            }
            if not associated_values and not (
                default is not None and len(candidates) == 1 and default in generic_values
            ):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=stmt.lineno,
                    col=stmt.col_offset + 1,
                    code=self.code,
                    message=(
                        f"`{name}: str` is used as a closed choice set — "
                        "prefer `StrEnum`. (`Literal[...]` is also acceptable.)"
                    ),
                )
            )
        return diags


def _has_str_enum_signal(source: str) -> bool:
    """Cheap source gate for files that cannot contain this rule's triggers."""
    has_string_literal = '"' in source or "'" in source
    if "str" in source and any(name in source.lower() for name in CHOICES_ATTR_NAMES):
        return True
    return has_string_literal and ("==" in source or "!=" in source or "case " in source or "match " in source)


def _cluster_fires(key: str, entry: _ClusterEntry) -> bool:
    _line, _col, literals, eq_literals, ne_literals, in_literals = entry
    if not eq_literals and not ne_literals:
        return False  # a lone `in`/`not in` membership guard is not an app enum
    # One operator must enumerate multiple alternatives before the vocabulary is demonstrably closed.
    enumerated = max(len(eq_literals | in_literals), len(ne_literals | in_literals))
    if enumerated < _MIN_CLUSTER_SIZE:
        return False
    if not all(_LOWER_TOKEN_RE.fullmatch(lit) for lit in literals):
        return False
    if all(lit in EXTERNAL_VOCAB for lit in literals):
        return False  # URL schemes, language keywords, HTTP methods, reflection args
    if _is_file_mode_key(key) and all(_FILE_MODE_RE.fullmatch(lit) for lit in literals):
        return False  # `mode not in {"r", "rt", "rb"}` — the stdlib open() vocabulary
    # A single-character cluster on a char/token variable is a tokenizer scan.
    return not (_is_scanner_key(key) and all(len(lit) == 1 for lit in literals))


def _cluster_is_already_closed(
    key: str,
    entry: _ClusterEntry,
    literal_typed: frozenset[str],
    alias_valuesets: list[frozenset[str]],
) -> bool:
    """Report whether a cluster is on a variable whose domain is already closed."""
    if key.lower() in OPEN_DOMAIN_CODE_NAMES:
        return True
    if key in literal_typed:
        return True
    _line, _col, literals, _eq, _ne, _in = entry
    return any(literals <= vs for vs in alias_valuesets)


def _module_literal_aliases(tree: ast.Module) -> tuple[frozenset[str], list[frozenset[str]]]:
    """Collect module-level `X = Literal[...]` aliases."""
    names: set[str] = set()
    valuesets: list[frozenset[str]] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            target = stmt.targets[0] if len(stmt.targets) == 1 else None
            name = target.id if isinstance(target, ast.Name) else None
            value = stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            name = stmt.target.id if isinstance(stmt.target, ast.Name) else None
            value = stmt.value
        elif isinstance(stmt, ast.TypeAlias):
            name = stmt.name.id
            value = stmt.value
        else:
            continue
        if name is None or value is None:
            continue
        members = _literal_string_values(value)
        if members is None:
            continue
        names.add(name)
        if members:
            valuesets.append(frozenset(members))
    return frozenset(names), valuesets


def _module_raw_string_aliases(tree: ast.Module) -> frozenset[str]:
    aliases: dict[str, ast.expr] = {}
    for statement in tree.body:
        if isinstance(statement, ast.TypeAlias):
            aliases[statement.name.id] = statement.value
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            value = statement.value
            if isinstance(value, ast.Call) and _trailing_name(value.func) == "TypeAliasType":
                value = (
                    value.args[1]
                    if len(value.args) >= _MIN_TYPE_ALIAS_ARGS
                    else next((keyword.value for keyword in value.keywords if keyword.arg == "value"), value)
                )
            aliases[statement.targets[0].id] = value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
        ):
            aliases[statement.target.id] = statement.value
    raw: set[str] = set()
    for _round in range(len(aliases)):
        grown = {
            name
            for name, value in aliases.items()
            if name not in raw and isinstance(value, ast.Name) and (value.id == "str" or value.id in raw)
        }
        if not grown:
            break
        raw |= grown
    return frozenset(raw)


def _opaque_names(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    alias_names: frozenset[str],
    literal_funcs: frozenset[str],
    raw_string_aliases: frozenset[str],
) -> frozenset[str]:
    """Collect the names in `func` a StrEnum recommendation cannot apply to."""
    base = (
        _literal_typed_names(func, alias_names)
        | _foreign_typed_names(func, raw_string_aliases)
        | _wire_bound_names(func, literal_funcs)
    )
    return _close_over_assignments(func, base)


def _literal_typed_names(func: ast.FunctionDef | ast.AsyncFunctionDef, alias_names: frozenset[str]) -> frozenset[str]:
    """Collect names in `func` annotated as a `Literal` (inline or via a module alias)."""
    names: set[str] = set()
    args = func.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
        if _is_literal_annotation(arg.annotation, alias_names):
            names.add(arg.arg)
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and _is_literal_annotation(node.annotation, alias_names)
        ):
            names.add(node.target.id)
        stack.extend(children(node))
    return frozenset(names)


def _closed_comprehension_targets(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    alias_names: frozenset[str],
    raw_string_aliases: frozenset[str],
) -> dict[int, frozenset[str]]:
    annotations: dict[str, ast.expr] = {
        arg.arg: arg.annotation
        for arg in (*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs)
        if arg.annotation is not None
    }
    own_nodes: list[ast.AST] = []
    pending: list[ast.AST] = list(func.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        own_nodes.append(node)
        pending.extend(children(node))
    for node in own_nodes:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            annotations[node.target.id] = node.annotation
    result: dict[int, frozenset[str]] = {}
    for node in own_nodes:
        if not isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            continue
        closed: set[str] = set()
        for generator in node.generators:
            if not isinstance(generator.iter, ast.Name):
                continue
            annotation = annotations.get(generator.iter.id)
            if not isinstance(annotation, ast.Subscript):
                continue
            element = annotation.slice.elts[0] if isinstance(annotation.slice, ast.Tuple) else annotation.slice
            if _is_literal_annotation(element, alias_names) or _is_foreign_annotation(element, raw_string_aliases):
                closed.update(_bound_target_names(generator.target))
        if closed:
            result[id(node)] = frozenset(closed)
    return result


def _close_over_assignments(func: ast.FunctionDef | ast.AsyncFunctionDef, seed: frozenset[str]) -> frozenset[str]:
    """Propagate opacity along `x = <expr mentioning an opaque name>`."""
    edges: list[tuple[str, frozenset[str]]] = []
    for target, value in _local_bindings(func):
        sources = {node.id for node in walk(value) if isinstance(node, ast.Name)}
        if sources:
            edges.append((target, frozenset(sources)))
    names = set(seed)
    for _round in range(len(edges)):
        grown = {target for target, sources in edges if target not in names and sources & names}
        if not grown:
            break
        names |= grown
    return frozenset(names)


def _local_bindings(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, ast.expr]]:
    """Collect `x = <value>` / `x: T = <value>` / `(x := <value>)` bindings in `func`'s own scope."""
    bindings: list[tuple[str, ast.expr]] = []
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            targets, value = [node.target], node.value
        if value is not None:
            bindings.extend((name, value) for target in targets for name in _bound_target_names(target))
        stack.extend(children(node))
    return bindings


def _foreign_typed_names(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    raw_string_aliases: frozenset[str],
) -> frozenset[str]:
    """Collect names annotated with a named type other than `str`."""
    names: set[str] = set()
    args = func.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
        if _is_foreign_annotation(arg.annotation, raw_string_aliases):
            names.add(arg.arg)
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and _is_foreign_annotation(node.annotation, raw_string_aliases)
        ):
            names.add(node.target.id)
        stack.extend(children(node))
    return frozenset(names)


def _is_foreign_annotation(
    annotation: ast.expr | None,
    raw_string_aliases: frozenset[str] = frozenset(),
) -> bool:
    """Report whether the annotation names a type other than `str`."""
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        parsed = _parse_string_annotation(annotation.value)
        return parsed is not None and _is_foreign_annotation(parsed, raw_string_aliases)
    if _is_literal_annotation(annotation, frozenset()):
        return True
    inner = _strip_optional(annotation)
    if isinstance(inner, ast.Subscript) and _trailing_name(inner.value) == "Annotated":
        first = inner.slice.elts[0] if isinstance(inner.slice, ast.Tuple) and inner.slice.elts else None
        return first is not None and _is_foreign_annotation(first, raw_string_aliases)
    match inner:
        case ast.Name(id=ident):
            return ident != "str" and ident not in raw_string_aliases
        case ast.Attribute(attr=attr):
            return attr != "str"
        case _:
            return False


def _strip_optional(annotation: ast.expr) -> ast.expr:
    """Unwrap `X | None` and `Optional[X]` down to `X`."""
    match annotation:
        case ast.BinOp(op=ast.BitOr(), left=left, right=ast.Constant(value=None)):
            return _strip_optional(left)
        case ast.BinOp(op=ast.BitOr(), left=ast.Constant(value=None), right=right):
            return _strip_optional(right)
        case ast.Subscript(value=head, slice=inner) if _trailing_name(head) == "Optional":
            return _strip_optional(inner)
        case _:
            return annotation


def _literal_returning_functions(tree: ast.Module) -> frozenset[str]:
    """Collect the names of functions in this module that return a `Literal[...]`."""
    return frozenset(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _is_literal_annotation(node.returns, frozenset())
    )


def _wire_bound_names(func: ast.FunctionDef | ast.AsyncFunctionDef, literal_funcs: frozenset[str]) -> frozenset[str]:
    """Collect names in `func` bound from a value the module does not own."""
    names: set[str] = set()
    local_shadows = {
        node.name for node in func.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    local_shadows.update(target for target, _value in _local_bindings(func))
    visible_literal_funcs = literal_funcs - local_shadows
    for target, value in _local_bindings(func):
        if _is_wire_lookup(value) or (
            isinstance(value, ast.Call) and _trailing_name(value.func) in visible_literal_funcs
        ):
            names.add(target)
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)) and _is_wire_lookup(node.iter):
            names.update(_bound_target_names(node.target))
        stack.extend(children(node))
    return frozenset(names)


def _bound_target_names(target: ast.expr) -> set[str]:
    """Collect every name bound by an assignment target, nested unpacking included."""
    return {node.id for node in walk(target) if isinstance(node, ast.Name)}


def _is_wire_lookup(value: ast.expr) -> bool:
    """Report whether `value` reads from something the module does not own."""
    match value:
        case ast.Subscript():
            return True
        case ast.Attribute():
            return _is_foreign_attribute(value)
        case ast.Call(func=callee, args=args):
            name = _trailing_name(callee)
            if name in _WIRE_CALL_NAMES:
                return True
            if name == _STR_CONSTRUCTOR:
                return any(_is_wire_lookup(arg) for arg in args)
            if name == _CAST_FUNCTION and len(args) >= _MIN_CAST_ARGS:
                return _is_wire_lookup(args[1])
            if name in _ITERABLE_WRAPPERS:
                return any(_is_wire_lookup(arg) for arg in args)
            if isinstance(callee, ast.Attribute) and _is_wire_lookup(callee.value):
                return True
            if any(_is_wire_lookup(arg) for arg in args):
                return True
            if any(_is_wire_lookup(keyword.value) for keyword in value.keywords):
                return True
            return isinstance(callee, ast.Attribute) and _is_foreign_attribute(callee)
        case ast.BoolOp(values=values):
            return any(_is_wire_lookup(item) for item in values)
        case ast.IfExp(body=body, orelse=orelse):
            return _is_wire_lookup(body) or _is_wire_lookup(orelse)
        case ast.Await(value=inner) | ast.FormattedValue(value=inner):
            return _is_wire_lookup(inner)
        case ast.JoinedStr(values=values):
            return any(_is_wire_lookup(item) for item in values)
        case ast.BinOp(left=left, right=right):
            return _is_wire_lookup(left) or _is_wire_lookup(right)
        case _:
            return False


def _is_foreign_attribute(node: ast.Attribute) -> bool:
    """Report whether an attribute chain reads a value off an object the module does not own."""
    depth = 0
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        depth += 1
        current = current.value
    if not isinstance(current, ast.Name):
        return False
    return current.id not in _OWNED_ROOTS or depth >= _FOREIGN_CHAIN_DEPTH


def _trailing_name(node: ast.AST) -> str | None:
    """Return the trailing identifier of a `Name` / `Attribute` chain."""
    match node:
        case ast.Name(id=ident):
            return ident
        case ast.Attribute(attr=attr):
            return attr
        case _:
            return None


def _is_literal_annotation(annotation: ast.expr | None, alias_names: frozenset[str]) -> bool:
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        parsed = _parse_string_annotation(annotation.value)
        return parsed is not None and _is_literal_annotation(parsed, alias_names)
    if _literal_string_values(annotation) is not None:
        return True
    stripped = _strip_optional(annotation)
    if stripped is not annotation:
        return _is_literal_annotation(stripped, alias_names)
    if isinstance(annotation, ast.Subscript) and _trailing_name(annotation.value) == "Annotated":
        first = annotation.slice.elts[0] if isinstance(annotation.slice, ast.Tuple) and annotation.slice.elts else None
        return first is not None and _is_literal_annotation(first, alias_names)
    if isinstance(annotation, ast.Subscript) and _trailing_name(annotation.value) == "Union":
        members = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        relevant = [member for member in members if not _is_none_annotation(member)]
        return bool(relevant) and all(_is_literal_annotation(member, alias_names) for member in relevant)
    if isinstance(annotation, ast.Name):
        return annotation.id in alias_names
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        members = _flatten_annotation_union(annotation)
        relevant = [member for member in members if not _is_none_annotation(member)]
        return bool(relevant) and all(_is_literal_annotation(member, alias_names) for member in relevant)
    return False


def _is_none_annotation(node: ast.expr) -> bool:
    return (isinstance(node, ast.Constant) and node.value is None) or (isinstance(node, ast.Name) and node.id == "None")


def _literal_string_values(node: ast.expr) -> list[str] | None:
    """Return the string members of a `Literal[...]` subscript, or None if not one."""
    if not isinstance(node, ast.Subscript):
        return None
    head = node.value
    is_literal = (isinstance(head, ast.Name) and head.id == "Literal") or (
        isinstance(head, ast.Attribute) and head.attr == "Literal"
    )
    if not is_literal:
        return None
    elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    return [value for elt in elts if (value := _str_const(elt)) is not None]


def _flatten_annotation_union(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [*_flatten_annotation_union(node.left), *_flatten_annotation_union(node.right)]
    return [node]


def _is_file_mode_key(key: str) -> bool:
    """Report whether the variable holds an `open()` mode (`mode`, `_mode`, `file_mode`)."""
    segment = key.rsplit(".", 1)[-1].lstrip("_").lower()
    return segment in _FILE_MODE_KEYS or segment.endswith("_mode")


def _is_scanner_key(key: str) -> bool:
    segment = key.rsplit(".", 1)[-1].lower()
    return segment in _SCANNER_KEY_SEGMENTS or "char" in segment


def _string_collection_values(node: ast.AST | None) -> set[str] | None:
    if isinstance(node, ast.Dict):
        keys = {None if key is None else _str_const(key) for key in node.keys}
        return None if None in keys else {key for key in keys if key is not None}
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return None
    values = {
        _str_const(element.elts[0])
        if isinstance(element, (ast.List, ast.Tuple)) and len(element.elts) == _CHOICE_PAIR_ARITY
        else _str_const(element)
        for element in node.elts
    }
    if None in values:
        return None
    return {value for value in values if value is not None}


def _parse_string_annotation(value: str) -> ast.expr | None:
    try:
        return ast.parse(value, mode="eval").body
    except SyntaxError:
        return None


def _is_choice_string_annotation(annotation: ast.expr) -> bool:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        parsed = _parse_string_annotation(annotation.value)
        return parsed is not None and _is_choice_string_annotation(parsed)
    annotation = _strip_optional(annotation)
    if isinstance(annotation, ast.Subscript) and _trailing_name(annotation.value) == "Annotated":
        first = annotation.slice.elts[0] if isinstance(annotation.slice, ast.Tuple) and annotation.slice.elts else None
        return first is not None and _is_choice_string_annotation(first)
    return isinstance(annotation, ast.Name) and annotation.id == "str"


def _accumulate_compare(clusters: dict[str, _ClusterEntry], node: ast.Compare) -> None:
    extracted = _extract_compare(node)
    if extracted is None:
        return
    key, literals, operator = extracted
    _merge_cluster(clusters, key, literals, (node.lineno, node.col_offset + 1), operator=operator)


def _accumulate_match(clusters: dict[str, _ClusterEntry], node: ast.Match) -> None:
    key = _name_key(node.subject)
    if key is None:
        return
    literals: list[str] = []
    for case in node.cases:
        literals.extend(_match_pattern_literals(case.pattern))
    if not literals:
        return
    _merge_cluster(clusters, key, literals, (node.lineno, node.col_offset + 1), operator=_EQ)


def _merge_cluster(
    clusters: dict[str, _ClusterEntry],
    key: str,
    literals: list[str],
    pos: tuple[int, int],
    *,
    operator: str,
) -> None:
    entry = clusters.get(key, (*pos, set[str](), set[str](), set[str](), set[str]()))
    line, col, seen, eq_seen, ne_seen, in_seen = entry
    line, col = min((line, col), pos)
    if operator == _EQ:
        eq_seen |= set(literals)
    elif operator == _NE:
        ne_seen |= set(literals)
    else:
        in_seen |= set(literals)
    clusters[key] = (line, col, seen | set(literals), eq_seen, ne_seen, in_seen)


def _match_pattern_literals(pattern: ast.pattern) -> list[str]:
    """Collect string-constant literals from a `case` pattern (`MatchValue` / `MatchOr`)."""
    if isinstance(pattern, ast.MatchValue):
        value = _str_const(pattern.value)
        return [value] if value is not None else []
    if isinstance(pattern, ast.MatchOr):
        literals: list[str] = []
        for sub in pattern.patterns:
            literals.extend(_match_pattern_literals(sub))
        return literals
    return []


def _choice_binding_field(binding: str) -> str | None:
    """Return the field explicitly named by a choice collection, if any."""
    if binding.endswith("_choices") and len(binding) > len("_choices"):
        return binding.removesuffix("_choices")
    return CHOICE_COLLECTION_FIELDS.get(binding)


def _extract_compare(node: ast.Compare) -> tuple[str, list[str], str] | None:
    """Return (variable key, string literals, operator kind) for an enum-shaped compare."""
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    op = node.ops[0]
    left, right = node.left, node.comparators[0]
    if isinstance(op, (ast.Eq, ast.NotEq)):
        if _name_key(left) is not None and _str_const(right) is not None:
            ref, lit = left, right
        elif _str_const(left) is not None and _name_key(right) is not None:
            ref, lit = right, left
        else:
            return None
        key = _name_key(ref)
        value = _str_const(lit)
        if key is None or value is None:  # pragma: no cover — guarded above
            return None
        return key, [value], _EQ if isinstance(op, ast.Eq) else _NE
    if isinstance(op, (ast.In, ast.NotIn)):
        key = _name_key(left)
        if key is None:
            return None
        if not isinstance(right, (ast.Tuple, ast.List, ast.Set)) or not right.elts:
            return None
        values: list[str] = []
        for elt in right.elts:
            value = _str_const(elt)
            if value is None:
                return None
            values.append(value)
        return key, values, _MEMBERSHIP
    return None


def _name_key(node: ast.AST) -> str | None:
    """Return a stable local key; only one-hop owned attributes cross a method boundary."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"}:
        return f"{node.value.id}.{node.attr}"
    return None


def _str_const(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None
