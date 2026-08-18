from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from types import MappingProxyType
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
    parse_or_none,
)
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


class _LiteralAliases(NamedTuple):
    names: frozenset[str]
    value_sets: list[frozenset[str]]


class _ExtractedCompare(NamedTuple):
    key: str
    literals: list[str]
    operator: str


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
        "attr",
        "attribute",
        "action_name",
        "code",
        "country",
        "country_code",
        "currency",
        "date_str",
        "default_search",
        "encoding",
        "event_name",
        "ext",
        "extension",
        "format_key",
        "key",
        "lang",
        "language",
        "locale",
        "name",
        "protocol",
        "region",
        "timezone",
        "tool_name",
        "tz",
        "user_input",
        "username",
    }
)

_OPEN_DOMAIN_SUFFIXES = ("_encoding", "_ext", "_protocol", "_username")

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
_WIRE_CALL_NAMES = frozenset(
    {
        "get",
        "get_mapping_or_attr",
        "getenv",
        "items",
        "keys",
        "next",
        "pop",
        "popleft",
        "r1",
        "traverse_obj",
        "values",
    }
)

#: Calls that wrap an iterable without changing where its elements came from.
_ITERABLE_WRAPPERS = frozenset({"enumerate", "iter", "list", "reversed", "set", "sorted", "tuple", "zip"})

#: Attribute roots the module owns; `self.mode` is this class's own field, while
#: `token.type` / `expr.arg_names` belong to somebody else's object.
_OWNED_ROOTS = frozenset({"self", "cls"})

#: Depth at which an attribute chain has left the object the module owns:
#: `self._config_wrapper.extra` reads a collaborator's field, not `self`'s.
_FOREIGN_CHAIN_DEPTH = 2
_BUILDER_PREFIXES = ("build_", "make_")
_MIN_COPIED_LITERAL_DOMAINS = 2
_MIN_LITERAL_DOMAIN_VALUES = 3
_ENUM_BASE_NAMES = frozenset({"Enum", "Flag", "IntEnum", "IntFlag", "ReprEnum", "StrEnum"})
_ENUM_BASE_SUFFIXES = ("Enum", "Flag")


@final
class PreferStrEnum(Rule):
    id: str = "prefer-str-enum"
    code: str = "SARJ006"
    documentation = RuleDocumentation(
        summary="Represent corroborated closed string domains with `StrEnum` or a named `Literal` alias.",
        rationale="A named closed domain lets type checking and review catch invalid values and incomplete handling.",
        remediation="Define a `StrEnum` for model fields, or reuse one named `Literal` alias across transparent builders.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule requires corroborating choice collections, comparison clusters, or repeated literal domains.",
            "Tests, generated code, external vocabularies, and open-ended name domains receive conservative exemptions.",
        ),
        examples=(
            RuleExample(
                example_id="raw-string-choice-field",
                title="String field backed by a closed choice collection",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/order.py",
                        'class Order:\n    statuses = ("pending", "shipped")\n    status: str = "pending"\n',
                    ),
                ),
                focus_path=PurePosixPath("app/order.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="string-enum-field",
                title="Closed domain represented by a string enum",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/order.py",
                        'from enum import StrEnum\n\nclass Status(StrEnum):\n    PENDING = "pending"\n    SHIPPED = "shipped"\n\nclass Order:\n    status: Status = Status.PENDING\n',
                    ),
                ),
                focus_path=PurePosixPath("app/order.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:  # ruff: ignore[too-many-locals] -- traversal state.
        if path.suffix != ".py":
            return []
        if is_generated(path, source):
            return []
        if not _has_str_enum_signal(source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        test_path = is_test_path(path)
        check_clusters = not test_path
        literal_aliases = _module_literal_aliases(tree)
        alias_names = literal_aliases.names
        alias_valuesets = literal_aliases.value_sets
        raw_string_aliases = _module_raw_string_aliases(tree)
        literal_funcs = _literal_returning_functions(tree)
        module_func_names = frozenset(
            statement.name for statement in tree.body if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        method_owned_attributes = _class_method_owned_attributes(tree)
        method_closed_attributes = _class_method_closed_attributes(tree, alias_names, raw_string_aliases)
        enum_like_classes = _enum_like_class_ids(tree)
        class_nodes: list[ast.ClassDef] = []
        all_clusters: list[tuple[dict[str, _ClusterEntry], frozenset[str], frozenset[str] | None]] = []
        cluster_opacity: dict[int, frozenset[str]] = {}
        cluster_owned_attributes: dict[int, frozenset[str] | None] = {}
        comprehension_opacity: dict[int, frozenset[str]] = {}
        stack: list[tuple[ast.AST, dict[str, _ClusterEntry] | None]] = [(tree, None)]
        while stack:
            node, active = stack.pop()
            child_active: dict[str, _ClusterEntry] | None
            match node:
                case ast.ClassDef():
                    class_nodes.append(node)
                    child_active = None
                case ast.FunctionDef() | ast.AsyncFunctionDef():
                    if check_clusters:
                        comprehension_opacity.update(
                            _closed_comprehension_targets(node, alias_names, raw_string_aliases)
                        )
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
                        opaque = (
                            inherited
                            | _opaque_names(
                                node,
                                alias_names,
                                literal_funcs,
                                raw_string_aliases,
                                module_func_names,
                            )
                            | method_closed_attributes.get(id(node), frozenset())
                        )
                        owned_attributes = method_owned_attributes.get(id(node))
                        all_clusters.append((child_active, opaque, owned_attributes))
                        cluster_opacity[id(child_active)] = opaque
                        cluster_owned_attributes[id(child_active)] = owned_attributes
                    else:
                        child_active = None
                case ast.Lambda():
                    child_active = None
                case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
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
                        owned_attributes = cluster_owned_attributes.get(id(active))
                        all_clusters.append((child_active, frozenset(opaque), owned_attributes))
                        cluster_opacity[id(child_active)] = frozenset(opaque)
                        cluster_owned_attributes[id(child_active)] = owned_attributes
                case _:
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

        class_diags = [
            diag
            for cls in class_nodes
            for diag in self._class_field_diags(path, cls, raw_string_aliases, enum_like_classes)
        ]
        choice_field_names = {
            diag.message.split("`", maxsplit=2)[1].split(":", maxsplit=1)[0]
            for diag in class_diags
            if diag.message.startswith("`") and "`" in diag.message[1:]
        }
        choice_member_keys = {f"{receiver}.{name}" for receiver in ("self", "cls") for name in choice_field_names}
        diags: list[Diagnostic] = []
        for clusters, literal_typed, owned_attributes in all_clusters:
            for key, entry in clusters.items():
                if _cluster_is_already_closed(key, entry, literal_typed, alias_valuesets):
                    continue
                if (
                    owned_attributes is not None
                    and key.startswith(("self.", "cls."))
                    and key.rsplit(".", 1)[-1] not in owned_attributes
                ):
                    continue
                if not _cluster_fires(key, entry):
                    continue
                if key in choice_member_keys:
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

        diags.extend(class_diags)
        if not test_path:
            diags.extend(_named_literal_builder_diags(path, tree, self.code))
        diags.sort(key=lambda d: (d.line, d.col))
        return diags

    def _class_field_diags(
        self,
        path: Path,
        cls: ast.ClassDef,
        raw_string_aliases: frozenset[str],
        enum_like_classes: frozenset[int],
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        if id(cls) in enum_like_classes or any(_trailing_name(base) in _ENUM_BASE_NAMES for base in cls.bases):
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
            if not _is_choice_string_annotation(stmt.annotation, raw_string_aliases):
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
    if "Literal[" in source and any(f"def {prefix}" in source for prefix in _BUILDER_PREFIXES):
        return True
    has_string_literal = '"' in source or "'" in source
    if "str" in source and any(name in source.lower() for name in CHOICES_ATTR_NAMES):
        return True
    return has_string_literal and ("==" in source or "!=" in source or "case " in source or "match " in source)


def _enum_like_class_ids(tree: ast.Module) -> frozenset[int]:
    enum_names = set(_ENUM_BASE_NAMES)
    enum_modules = {"enum"}
    assignments: list[tuple[str, ast.expr]] = []
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=aliases):
                enum_modules.update(alias.asname or alias.name for alias in aliases if alias.name == "enum")
            case ast.ImportFrom(names=aliases):
                enum_names.update(
                    alias.asname or alias.name for alias in aliases if _looks_like_enum_base_name(alias.name)
                )
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=value)
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
            ):
                assignments.append((name, value))
            case _:
                pass

    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    enum_class_ids: set[int] = set()
    changed = True
    while changed:
        changed = False
        for name, value in assignments:
            if name not in enum_names and _is_enum_reference(value, enum_names, enum_modules):
                enum_names.add(name)
                changed = True
        for cls in classes:
            if id(cls) in enum_class_ids:
                continue
            if any(_is_enum_reference(base, enum_names, enum_modules) for base in cls.bases):
                enum_class_ids.add(id(cls))
                enum_names.add(cls.name)
                changed = True
    return frozenset(enum_class_ids)


def _is_enum_reference(node: ast.expr, enum_names: set[str], enum_modules: set[str]) -> bool:
    match node:
        case ast.Name(id=name):
            return name in enum_names or _looks_like_enum_base_name(name)
        case ast.Attribute(value=ast.Name(id=module), attr=name):
            return _looks_like_enum_base_name(name) or (module in enum_modules and name in enum_names)
        case _:
            return False


def _looks_like_enum_base_name(name: str) -> bool:
    return name in _ENUM_BASE_NAMES or name.endswith(_ENUM_BASE_SUFFIXES)


def _named_literal_builder_diags(path: Path, tree: ast.Module, code: str) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    for statement in tree.body:
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if statement.decorator_list or not statement.name.startswith(_BUILDER_PREFIXES):
            continue
        call = _transparent_constructor_call(statement)
        if call is None:
            continue
        inline_domains = _inline_literal_parameters(statement.args)
        copied = [name for name in inline_domains if _forwards_keyword_unchanged(call, name)]
        if len(copied) < _MIN_COPIED_LITERAL_DOMAINS:
            continue
        findings.append(
            Diagnostic(
                path=path,
                line=statement.lineno,
                col=statement.col_offset + 1,
                code=code,
                message=(
                    f"`{statement.name}` copies {len(copied)} inline Literal domains into "
                    f"`{_trailing_name(call.func) or ast.unparse(call.func)}`; export named aliases from the model owner "
                    "and reuse them here so the accepted values have one source of truth."
                ),
                severity=Severity.ERROR,
            )
        )
    return findings


def _transparent_constructor_call(function: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Call | None:
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return) or not isinstance(body[0].value, ast.Call):
        return None
    call = body[0].value
    callee = _trailing_name(call.func)
    return call if callee is not None and callee[:1].isupper() else None


def _inline_literal_parameters(arguments: ast.arguments) -> frozenset[str]:
    parameters = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    return frozenset(
        argument.arg
        for argument in parameters
        if argument.annotation is not None and _is_inline_string_domain(argument.annotation)
    )


def _is_inline_string_domain(annotation: ast.expr) -> bool:
    if not isinstance(annotation, ast.Subscript) or _trailing_name(annotation.value) != "Literal":
        return False
    values = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
    return len(values) >= _MIN_LITERAL_DOMAIN_VALUES and all(
        isinstance(value, ast.Constant) and isinstance(value.value, str) for value in values
    )


def _forwards_keyword_unchanged(call: ast.Call, name: str) -> bool:
    return any(
        keyword.arg == name and isinstance(keyword.value, ast.Name) and keyword.value.id == name
        for keyword in call.keywords
    )


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
    segment = key.rsplit(".", 1)[-1].lower()
    if segment in OPEN_DOMAIN_CODE_NAMES or segment.endswith(_OPEN_DOMAIN_SUFFIXES):
        return True
    if key in literal_typed:
        return True
    _line, _col, literals, _eq, _ne, _in = entry
    return any(literals <= vs for vs in alias_valuesets)


def _module_literal_aliases(tree: ast.Module) -> _LiteralAliases:
    names: set[str] = set()
    valuesets: list[frozenset[str]] = []
    for stmt in tree.body:
        match stmt:
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                pass
            case ast.AnnAssign(target=ast.Name(id=name), value=value):
                pass
            case ast.TypeAlias(name=ast.Name(id=name), value=value):
                pass
            case _:
                continue
        if value is None:
            continue
        members = _literal_string_values(value)
        if members is None:
            continue
        names.add(name)
        if members:
            valuesets.append(frozenset(members))
    return _LiteralAliases(frozenset(names), valuesets)


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
    module_func_names: frozenset[str],
) -> frozenset[str]:
    base = (
        _literal_typed_names(func, alias_names)
        | _explicitly_open_literal_union_names(func, raw_string_aliases)
        | _dynamically_constrained_names(func)
        | _foreign_typed_names(func, raw_string_aliases)
        | _wire_bound_names(func, literal_funcs, module_func_names)
        | _fallback_consumed_names(func)
    )
    return _close_over_assignments(func, base)


def _class_method_owned_attributes(tree: ast.Module) -> dict[int, frozenset[str]]:
    result: dict[int, frozenset[str]] = {}
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        attributes: set[str] = set()
        methods = [stmt for stmt in cls.body if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for statement in cls.body:
            class_targets: list[ast.expr] = []
            if isinstance(statement, ast.Assign):
                class_targets.extend(statement.targets)
            elif isinstance(statement, ast.AnnAssign):
                class_targets.append(statement.target)
            attributes.update(target.id for target in class_targets if isinstance(target, ast.Name))
        for method in methods:
            stack: list[ast.AST] = list(method.body)
            while stack:
                node = stack.pop()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    continue
                method_targets: list[ast.expr] = []
                if isinstance(node, ast.Assign):
                    method_targets.extend(node.targets)
                elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                    method_targets.append(node.target)
                for target in method_targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id in _OWNED_ROOTS
                    ):
                        attributes.add(target.attr)
                stack.extend(children(node))
        owned = frozenset(attributes)
        result.update((id(method), owned) for method in methods)
    return result


def _class_method_closed_attributes(
    tree: ast.Module,
    alias_names: frozenset[str],
    raw_string_aliases: frozenset[str],
) -> dict[int, frozenset[str]]:
    result: dict[int, frozenset[str]] = {}
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        closed = {
            statement.target.id
            for statement in cls.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and (
                _is_literal_annotation(statement.annotation, alias_names)
                or _is_foreign_annotation(statement.annotation, raw_string_aliases)
            )
        }
        keys = frozenset(f"{receiver}.{name}" for receiver in _OWNED_ROOTS for name in closed)
        result.update(
            (id(method), keys) for method in cls.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    return result


def _dynamically_constrained_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    result: set[str] = set()
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            collection = node.comparators[0]
            if (
                isinstance(node.ops[0], (ast.In, ast.NotIn))
                and not isinstance(collection, (ast.List, ast.Set, ast.Tuple))
                and not (isinstance(collection, ast.Name) and collection.id.isupper())
            ):
                key = _name_key(node.left)
            else:
                key = None
            if key is not None:
                result.add(key)
        stack.extend(children(node))
    return frozenset(result)


def _fallback_consumed_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    open_names: set[str] = set()
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.If):
            compared: set[str] = set()
            current = node
            while True:
                bare_key = _name_key(current.test)
                if bare_key is not None and bare_key in compared and _statements_read_key(current.body, bare_key):
                    open_names.add(bare_key)
                extracted = _extract_compare(current.test) if isinstance(current.test, ast.Compare) else None
                if extracted is not None:
                    compared.add(extracted.key)
                if len(current.orelse) != 1 or not isinstance(current.orelse[0], ast.If):
                    break
                current = current.orelse[0]
        stack.extend(children(node))
    return frozenset(open_names)


def _statements_read_key(statements: list[ast.stmt], key: str) -> bool:
    for statement in statements:
        for node in ast.walk(statement):
            if (
                isinstance(node, (ast.Name, ast.Attribute))
                and _name_key(node) == key
                and isinstance(node.ctx, ast.Load)
            ):
                return True
    return False


def _literal_typed_names(func: ast.FunctionDef | ast.AsyncFunctionDef, alias_names: frozenset[str]) -> frozenset[str]:
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


def _explicitly_open_literal_union_names(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    raw_string_aliases: frozenset[str],
) -> frozenset[str]:
    names: set[str] = set()
    args = func.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
        if _is_literal_plus_open_string(arg.annotation, raw_string_aliases):
            names.add(arg.arg)
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and _is_literal_plus_open_string(node.annotation, raw_string_aliases)
        ):
            names.add(node.target.id)
        stack.extend(children(node))
    return frozenset(names)


def _is_literal_plus_open_string(
    annotation: ast.expr | None,
    raw_string_aliases: frozenset[str],
) -> bool:
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        parsed = _parse_string_annotation(annotation.value)
        return parsed is not None and _is_literal_plus_open_string(parsed, raw_string_aliases)
    members = _union_annotation_members(annotation)
    if len(members) < _MIN_TYPE_ALIAS_ARGS:
        return False
    has_literal = any(_is_literal_annotation(member, frozenset()) for member in members)
    has_open_string = any(
        isinstance(member, ast.Name) and (member.id == "str" or member.id in raw_string_aliases) for member in members
    )
    return has_literal and has_open_string


def _union_annotation_members(annotation: ast.expr) -> list[ast.expr]:
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return [*_union_annotation_members(annotation.left), *_union_annotation_members(annotation.right)]
    if isinstance(annotation, ast.Subscript) and _trailing_name(annotation.value) == "Union":
        return list(annotation.slice.elts) if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
    return [annotation]


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
    edges: list[tuple[str, frozenset[str]]] = []
    for target, value in _local_bindings(func):
        if _is_valid_url_group(value):
            continue
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


def _is_valid_url_group(value: ast.expr) -> bool:
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr in {"group", "groupdict", "groups"}
        and isinstance(value.func.value, ast.Call)
        and _trailing_name(value.func.value.func) == "_match_valid_url"
    )


def _local_bindings(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, ast.expr]]:
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
    return frozenset(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _is_literal_annotation(node.returns, frozenset())
    )


def _wire_bound_names(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    literal_funcs: frozenset[str],
    module_func_names: frozenset[str],
) -> frozenset[str]:
    names: set[str] = set()
    local_shadows = {
        node.name for node in func.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    local_shadows.update(target for target, _value in _local_bindings(func))
    blocked_wire_calls = module_func_names | local_shadows
    visible_literal_funcs = literal_funcs - local_shadows
    for target, value in _local_bindings(func):
        if _is_wire_lookup(value, blocked_wire_calls) or (
            isinstance(value, ast.Call) and _trailing_name(value.func) in visible_literal_funcs
        ):
            names.add(target)
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)) and _is_wire_lookup(
            node.iter, blocked_wire_calls
        ):
            names.update(_bound_target_names(node.target))
        stack.extend(children(node))
    return frozenset(names)


def _bound_target_names(target: ast.expr) -> set[str]:
    return {node.id for node in walk(target) if isinstance(node, ast.Name)}


def _is_wire_lookup(value: ast.expr, blocked_call_names: frozenset[str] = frozenset()) -> bool:
    match value:
        case ast.Subscript():
            return True
        case ast.Attribute():
            return _is_foreign_attribute(value)
        case ast.Call(func=callee, args=args):
            name = _trailing_name(callee)
            if name in _WIRE_CALL_NAMES and name not in blocked_call_names:
                return True
            if name == _STR_CONSTRUCTOR:
                return any(_is_wire_lookup(arg, blocked_call_names) for arg in args)
            if name == _CAST_FUNCTION and len(args) >= _MIN_CAST_ARGS:
                return _is_wire_lookup(args[1], blocked_call_names)
            if name in _ITERABLE_WRAPPERS:
                return any(_is_wire_lookup(arg, blocked_call_names) for arg in args)
            if isinstance(callee, ast.Attribute) and _is_wire_lookup(callee.value, blocked_call_names):
                return True
            if any(_is_wire_lookup(arg, blocked_call_names) for arg in args):
                return True
            if any(_is_wire_lookup(keyword.value, blocked_call_names) for keyword in value.keywords):
                return True
            return isinstance(callee, ast.Attribute) and _is_foreign_attribute(callee)
        case ast.BoolOp(values=values):
            return any(_is_wire_lookup(item, blocked_call_names) for item in values)
        case ast.IfExp(body=body, orelse=orelse):
            return _is_wire_lookup(body, blocked_call_names) or _is_wire_lookup(orelse, blocked_call_names)
        case ast.Await() | ast.FormattedValue():
            return _is_wire_lookup(value.value, blocked_call_names)
        case ast.JoinedStr(values=values):
            return any(_is_wire_lookup(item, blocked_call_names) for item in values)
        case ast.BinOp(left=left, right=right):
            return _is_wire_lookup(left, blocked_call_names) or _is_wire_lookup(right, blocked_call_names)
        case _:
            return False


def _is_foreign_attribute(node: ast.Attribute) -> bool:
    depth = 0
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        depth += 1
        current = current.value
    if not isinstance(current, ast.Name):
        return False
    return current.id not in _OWNED_ROOTS or depth >= _FOREIGN_CHAIN_DEPTH


def _trailing_name(node: ast.AST) -> str | None:
    match node:
        case ast.Name(id=ident):
            return ident
        case ast.Attribute(attr=attr):
            return attr
        case _:
            return None


def _is_literal_annotation(annotation: ast.expr | None, alias_names: frozenset[str]) -> bool:
    match annotation:
        case None:
            return False
        case ast.Constant(value=str() as value):
            parsed = _parse_string_annotation(value)
            return parsed is not None and _is_literal_annotation(parsed, alias_names)
        case _:
            pass
    if _literal_string_values(annotation) is not None:
        return True
    stripped = _strip_optional(annotation)
    if stripped is not annotation:
        return _is_literal_annotation(stripped, alias_names)
    match annotation:
        case ast.Subscript(value=value, slice=ast.Tuple(elts=elements)) if (
            _trailing_name(value) == "Annotated" and elements
        ):
            return _is_literal_annotation(elements[0], alias_names)
        case ast.Subscript(value=value, slice=annotation_slice) if _trailing_name(value) == "Annotated":
            return _is_literal_annotation(annotation_slice, alias_names)
        case ast.Subscript(value=value, slice=annotation_slice) if _trailing_name(value) == "Union":
            members = annotation_slice.elts if isinstance(annotation_slice, ast.Tuple) else [annotation_slice]
        case ast.Name(id=name):
            return name in alias_names
        case ast.BinOp(op=ast.BitOr()):
            members = _flatten_annotation_union(annotation)
        case _:
            return False
    relevant = [member for member in members if not _is_none_annotation(member)]
    return bool(relevant) and all(_is_literal_annotation(member, alias_names) for member in relevant)


def _is_none_annotation(node: ast.expr) -> bool:
    return (isinstance(node, ast.Constant) and node.value is None) or (isinstance(node, ast.Name) and node.id == "None")


def _literal_string_values(node: ast.expr) -> list[str] | None:
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
    segment = key.rsplit(".", 1)[-1].lstrip("_").lower()
    return segment in _FILE_MODE_KEYS or segment.endswith("_mode")


def _is_scanner_key(key: str) -> bool:
    segment = key.rsplit(".", 1)[-1].lower()
    return segment in _SCANNER_KEY_SEGMENTS or "char" in segment


def _string_collection_values(node: ast.AST | None) -> set[str] | None:
    if isinstance(node, ast.Dict):
        keys: set[str] = set()
        for key in node.keys:
            if key is not None and _is_none_annotation(key):
                continue
            value = None if key is None else _str_const(key)
            if value is None:
                return None
            keys.add(value)
        return keys
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return None
    values: set[str] = set()
    for element in node.elts:
        candidate = (
            element.elts[0]
            if isinstance(element, (ast.List, ast.Tuple)) and len(element.elts) == _CHOICE_PAIR_ARITY
            else element
        )
        # Ignore Django's `(None, "---")` blank sentinel while preserving the
        # closed string vocabulary alongside it.
        if _is_none_annotation(candidate):
            continue
        value = _str_const(candidate)
        if value is None:
            return None
        values.add(value)
    return values


def _parse_string_annotation(value: str) -> ast.expr | None:
    try:
        return ast.parse(value, mode="eval").body
    except SyntaxError:
        return None


def _is_choice_string_annotation(annotation: ast.expr, raw_string_aliases: frozenset[str]) -> bool:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        parsed = _parse_string_annotation(annotation.value)
        return parsed is not None and _is_choice_string_annotation(parsed, raw_string_aliases)
    annotation = _strip_optional(annotation)
    if isinstance(annotation, ast.Subscript) and _trailing_name(annotation.value) == "Annotated":
        first = annotation.slice.elts[0] if isinstance(annotation.slice, ast.Tuple) and annotation.slice.elts else None
        return first is not None and _is_choice_string_annotation(first, raw_string_aliases)
    return isinstance(annotation, ast.Name) and (annotation.id == "str" or annotation.id in raw_string_aliases)


def _accumulate_compare(clusters: dict[str, _ClusterEntry], node: ast.Compare) -> None:
    extracted = _extract_compare(node)
    if extracted is None:
        return
    _merge_cluster(
        clusters,
        extracted.key,
        extracted.literals,
        (node.lineno, node.col_offset + 1),
        operator=extracted.operator,
    )


def _accumulate_match(clusters: dict[str, _ClusterEntry], node: ast.Match) -> None:
    key = _name_key(node.subject)
    if key is None or _match_accepts_unlisted_values(node):
        return
    literals: list[str] = []
    for case in node.cases:
        literals.extend(_match_pattern_literals(case.pattern))
    if not literals:
        return
    _merge_cluster(clusters, key, literals, (node.lineno, node.col_offset + 1), operator=_EQ)


def _match_accepts_unlisted_values(node: ast.Match) -> bool:
    return any(
        case.guard is None
        and isinstance(case.pattern, ast.MatchAs)
        and case.pattern.pattern is None
        and not _statements_reject_value(case.body)
        for case in node.cases
    )


def _statements_reject_value(statements: list[ast.stmt]) -> bool:
    return len(statements) == 1 and (
        isinstance(statements[0], ast.Raise)
        or (
            isinstance(statements[0], ast.Expr)
            and isinstance(statements[0].value, ast.Call)
            and _trailing_name(statements[0].value.func) == "assert_never"
        )
    )


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
    match pattern:
        case ast.MatchValue(value=value_node):
            value = _str_const(value_node)
            return [value] if value is not None else []
        case ast.MatchAs(pattern=inner) if inner is not None:
            return _match_pattern_literals(inner)
        case ast.MatchOr(patterns=patterns):
            literals: list[str] = []
            for subpattern in patterns:
                literals.extend(_match_pattern_literals(subpattern))
            return literals
        case _:
            return []


def _choice_binding_field(binding: str) -> str | None:
    if binding.endswith("_choices") and len(binding) > len("_choices"):
        return binding.removesuffix("_choices")
    return CHOICE_COLLECTION_FIELDS.get(binding)


def _extract_compare(node: ast.Compare) -> _ExtractedCompare | None:
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
        return _ExtractedCompare(key, [value], _EQ if isinstance(op, ast.Eq) else _NE)
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
        return _ExtractedCompare(key, values, _MEMBERSHIP)
    return None


def _name_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"}:
        return f"{node.value.id}.{node.attr}"
    return None


def _str_const(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None
