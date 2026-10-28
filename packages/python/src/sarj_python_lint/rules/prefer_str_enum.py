from __future__ import annotations

import ast
from dataclasses import dataclass
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
    is_suppressed,
)
from sarj_python_lint.rules._annotation_semantics import bit_or_members as _flatten_annotation_union
from sarj_python_lint.rules._ast_index import children, walk, walk as walk_ast
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex


#: Per-variable accumulator containing location and literals grouped by comparison operator.
type _ClusterEntry = tuple[int, int, set[str], set[str], set[str], set[str], bool]

_MIN_CAST_ARGS = 2
_MIN_TYPE_ALIAS_ARGS = 2
_CHOICE_PAIR_ARITY = 2
_CAST_FUNCTION = "cast"
_STR_CONSTRUCTOR = "str"
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_NAMESPACE_ACCESS_MEMBERS = frozenset({"__dict__", "__getattribute__", "__setattr__", "__delattr__"})


class _LiteralAliases(NamedTuple):
    names: frozenset[str]


class _ExtractedCompare(NamedTuple):
    key: str
    literals: list[str]
    operator: str


class _LocalBinding(NamedTuple):
    target: str
    value: ast.expr


@dataclass(frozen=True, slots=True)
class _ClassFieldDiagnostics:
    diagnostics: list[Diagnostic]
    member_keys: dict[int, set[str]]


@dataclass(frozen=True, slots=True)
class _TypingNamespaceOrigins:
    namespaces: frozenset[str]
    handles: frozenset[str]


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
_ENUM_BASE_NAMES = frozenset({"Enum", "Flag", "IntEnum", "IntFlag", "ReprEnum", "StrEnum"})
_ENUM_BASE_SUFFIXES = ("Enum", "Flag")


@final
class PreferStrEnum(Rule):
    id: str = "prefer-str-enum"
    code: str = "SARJ006"
    documentation = RuleDocumentation(
        summary="Prefer `StrEnum` for application-owned string domains with explicit closed-set evidence.",
        rationale="A named closed domain lets type checking and review catch invalid values and incomplete handling.",
        remediation="Define a `StrEnum`, or a named `Literal` alias when enum runtime behavior is unnecessary.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Automatic fixes reuse one existing canonical module Literal alias only when its finite string domain strictly contains a closed private nested helper's handled literal match cases and every direct caller supplies a handled-case literal. Reachable fallback exceptions retain manual ownership because their tracebacks can expose private helper frames. An unhandled alias member must keep the existing rejecting fallback reachable; exact handled-domain aliases remain manual because narrowing would introduce an unreachable-pattern type error. Only the str parameter annotation changes; defaults, comments, generics, aliases/escapes, reflection/frame access, shared bodies and runtime enum creation remain manual.",
            "Containing callables must also be ordinary synchronous nongenerators with proven inert execution; unknown callouts, properties, overloads, reachable frame-exporting exceptions, and helper references crossing additional function, class, lambda, or comprehension scopes prevent fixes.",
            "The rule requires a sibling choice collection or dispatch that explicitly rejects unlisted strings.",
            "Generated code, external vocabularies, open-ended name domains, and test-only comparison clusters are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="safe-autofix",
                title="Reuse an existing finite private domain with reachable rejection",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        'from typing import Literal\ntype Mode = Literal["text", "image", "reserved"]\ndef outer() -> str:\n    def _render(kind: str) -> str:\n        match kind:\n            case "text":\n                return "Text"\n            case "image":\n                return "Image"\n            case _:\n                raise ValueError("unsupported kind")\n    return _render("text")\n',
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py",
                        'from typing import Literal\ntype Mode = Literal["text", "image", "reserved"]\ndef outer() -> str:\n    def _render(kind: Mode) -> str:\n        match kind:\n            case "text":\n                return "Text"\n            case "image":\n                return "Image"\n            case _:\n                raise ValueError("unsupported kind")\n    return _render("text")\n',
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
            ),
            RuleExample(
                example_id="tabbed-rejecting-match",
                scenario="tabbed-match-admission",
                title="Tab-separated matching keeps the closed string domain",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/render.py",
                        'def render(kind: str) -> str:\n    match\tkind:\n        case\t"text":\n            return "Text"\n        case\t"image":\n            return "Image"\n        case\t_:\n            raise ValueError("unsupported kind")\n',
                    ),
                ),
                focus_path=PurePosixPath("app/render.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="tabbed-open-match",
                scenario="tabbed-match-admission",
                title="An open tab-separated match keeps string dispatch",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/render.py",
                        'def render(kind: str) -> str:\n    match\tkind:\n        case\t"text":\n            return "Text"\n        case\t"image":\n            return "Image"\n        case\t_:\n            return kind\n',
                    ),
                ),
                focus_path=PurePosixPath("app/render.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="parenthesized-rejecting-membership",
                scenario="membership-admission",
                title="Parentheses do not open a rejecting string domain",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/render.py",
                        'def render(kind: str) -> str:\n    if kind not in ({r"text", r"image"}):\n        raise ValueError("unsupported kind")\n    return kind\n',
                    ),
                ),
                focus_path=PurePosixPath("app/render.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="parenthesized-open-membership",
                scenario="membership-admission",
                title="Membership data without rejection keeps strings",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/render.py", 'def render(kind: str) -> str:\n    return kind in ({r"text", r"image"})\n'
                    ),
                ),
                focus_path=PurePosixPath("app/render.py"),
                expected_count=0,
                public=True,
            ),
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
                scenario="choice-field",
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
                scenario="choice-field",
            ),
            RuleExample(
                example_id="rejecting-string-dispatch",
                title="Dispatch rejects every unlisted string",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/render.py",
                        "def render(kind: str) -> str:\n"
                        "    match kind:\n"
                        '        case "text":\n'
                        '            return "Text"\n'
                        '        case "image":\n'
                        '            return "Image"\n'
                        "        case _:\n"
                        '            raise ValueError("unsupported kind")\n',
                    ),
                ),
                focus_path=PurePosixPath("app/render.py"),
                expected_count=1,
                public=True,
                scenario="rejecting-dispatch",
            ),
            RuleExample(
                example_id="open-string-dispatch",
                title="Dispatch forwards unlisted strings",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/render.py",
                        "def render(kind: str) -> str:\n"
                        '    if kind == "text":\n'
                        '        return "Text"\n'
                        '    if kind == "image":\n'
                        '        return "Image"\n'
                        "    return render_plugin(kind)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/render.py"),
                expected_count=0,
                public=True,
                scenario="rejecting-dispatch",
            ),
            RuleExample(
                example_id="generic-string-binding",
                scenario="provider-identity",
                title="A generic parameter does not become the builtin string type",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py", "class Order[str]:\n    statuses = ('pending', 'shipped')\n    status: str\n"
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="generic-builtin-string",
                scenario="provider-identity",
                title="An unrelated generic parameter preserves the builtin string field",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py", "class Order[T]:\n    statuses = ('pending', 'shipped')\n    status: str\n"
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:  # ruff: ignore[too-many-locals] -- traversal state.
        path = context.path
        if path.suffix != ".py":
            return []
        if context.generated:
            return []
        if not _has_str_enum_signal(context.symbol_source):
            return []
        tree = context.tree
        if tree is None:
            return []
        signals = context.symbol_source
        class_choice_signal = "str" in signals and any(name in signals.lower() for name in CHOICES_ATTR_NAMES)
        wrapper_signal = any(symbol in signals for symbol in ("Annotated", "Optional", "Union"))
        imports = context.imports if class_choice_signal or "assert_never" in signals or wrapper_signal else None
        rejection_imports = _assert_never_imports(context, imports)
        test_path = is_test_path(path)
        check_clusters = not test_path
        literal_aliases = _module_literal_aliases(tree)
        alias_names = literal_aliases.names
        closed_collections = _module_closed_collections(tree, node_index=context.node_index)
        raw_string_aliases = _module_raw_string_aliases(tree)
        choice_string_aliases: frozenset[str] = (
            _module_proven_raw_string_aliases(tree, imports, node_index=context.node_index)
            if imports is not None
            else frozenset()
        )
        literal_funcs = _literal_returning_functions(tree)
        module_func_names = frozenset(
            statement.name for statement in tree.body if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        method_owned_attributes = _class_method_owned_attributes(tree, node_index=context.node_index)
        method_closed_attributes = _class_method_closed_attributes(
            tree, alias_names, raw_string_aliases, imports=imports, node_index=context.node_index
        )
        enum_like_classes = _enum_like_class_ids(tree, node_index=context.node_index)
        unsafe_attribute_collections = (
            _unsafe_attribute_collection_uses(tree, node_index=context.node_index)
            if class_choice_signal and context.nodes(ast.ClassDef)
            else {}
        )
        class_nodes: list[ast.ClassDef] = []
        all_clusters: list[tuple[dict[str, _ClusterEntry], frozenset[str], frozenset[str] | None]] = []
        cluster_opacity: dict[int, frozenset[str]] = {}
        cluster_owned_attributes: dict[int, frozenset[str] | None] = {}
        cluster_closed_nodes: dict[int, frozenset[int]] = {}
        cluster_methods: dict[int, int | None] = {}
        comprehension_opacity: dict[int, frozenset[str]] = {}

        def function_cluster(
            node: ast.FunctionDef | ast.AsyncFunctionDef, active: dict[str, _ClusterEntry] | None
        ) -> dict[str, _ClusterEntry] | None:
            if check_clusters:
                comprehension_opacity.update(
                    _closed_comprehension_targets(node, alias_names, raw_string_aliases, imports=imports)
                )
                child_active: dict[str, _ClusterEntry] = {}
                shadowed = _function_shadowed_names(node)
                inherited = cluster_opacity.get(id(active), frozenset()) - shadowed
                opaque = (
                    inherited
                    | _opaque_names(
                        node,
                        alias_names,
                        literal_funcs,
                        raw_string_aliases,
                        module_func_names,
                        closed_collections=frozenset(closed_collections),
                        imports=imports,
                        type_parameters=_annotation_type_parameters(node, context.parents),
                    )
                    | method_closed_attributes.get(id(node), frozenset())
                )
                owned_attributes = method_owned_attributes.get(id(node))
                all_clusters.append((child_active, opaque, owned_attributes))
                cluster_opacity[id(child_active)] = opaque
                cluster_owned_attributes[id(child_active)] = owned_attributes
                cluster_closed_nodes[id(child_active)] = _closed_domain_node_ids(
                    node, rejection_imports, closed_collections
                )
                inherited_method = cluster_methods.get(id(active))
                if not _OWNED_ROOTS.isdisjoint(shadowed):
                    inherited_method = None
                cluster_methods[id(child_active)] = (
                    id(node) if id(node) in method_owned_attributes else inherited_method
                )
            else:
                return None
            return child_active

        def comprehension_cluster(
            node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
            active: dict[str, _ClusterEntry] | None,
        ) -> dict[str, _ClusterEntry] | None:
            # Comprehension targets have separate scopes; same-named comparisons cannot be merged across them.
            if active is None:
                return None
            child_active: dict[str, _ClusterEntry] = {}
            bound_targets = {name for generator in node.generators for name in _bound_target_names(generator.target)}
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
            cluster_closed_nodes[id(child_active)] = frozenset()
            cluster_methods[id(child_active)] = cluster_methods.get(id(active))
            return child_active

        def schedule_children(
            stack: list[tuple[ast.AST, dict[str, _ClusterEntry] | None]],
            node: ast.AST,
            active: dict[str, _ClusterEntry] | None,
            child_active: dict[str, _ClusterEntry] | None,
        ) -> None:
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

        def collect_clusters() -> None:
            stack: list[tuple[ast.AST, dict[str, _ClusterEntry] | None]] = [(tree, None)]
            while stack:
                node, active = stack.pop()
                child_active: dict[str, _ClusterEntry] | None
                match node:
                    case ast.ClassDef():
                        class_nodes.append(node)
                        child_active = None
                    case ast.FunctionDef() | ast.AsyncFunctionDef():
                        child_active = function_cluster(node, active)
                    case ast.Lambda():
                        child_active = None
                    case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                        child_active = comprehension_cluster(node, active)
                    case _:
                        child_active = active
                        if active is not None:
                            if isinstance(node, ast.Compare):
                                _accumulate_compare(
                                    active,
                                    node,
                                    closed=id(node) in cluster_closed_nodes.get(id(active), frozenset()),
                                    closed_collections=closed_collections,
                                )
                            elif isinstance(node, ast.Match) and id(node) in cluster_closed_nodes.get(
                                id(active), frozenset()
                            ):
                                _accumulate_match(active, node, rejection_imports)
                schedule_children(stack, node, active, child_active)

        collect_clusters()

        class_findings = self._all_class_field_diags(
            path,
            class_nodes,
            choice_string_aliases,
            enum_like_classes,
            imports,
            unsafe_attribute_collections=unsafe_attribute_collections,
            parents=context.parents,
        )
        diags: list[Diagnostic] = []

        def collect_diagnostics() -> None:
            for clusters, literal_typed, owned_attributes in all_clusters:
                for key, entry in clusters.items():
                    if _cluster_is_already_closed(key, literal_typed):
                        continue
                    if (
                        owned_attributes is not None
                        and key.startswith(("self.", "cls."))
                        and key.rsplit(".", 1)[-1] not in owned_attributes
                    ):
                        continue
                    if not _cluster_fires(key, entry):
                        continue
                    if key in class_findings.member_keys.get(cluster_methods.get(id(clusters)) or 0, set()):
                        continue
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=entry[0],
                            col=entry[1],
                            code=self.code,
                            message=(
                                f"`{key}` rejects unlisted string values — define a named `Literal` alias or `StrEnum`"
                            ),
                            severity=Severity.ERROR,
                        )
                    )

        collect_diagnostics()

        diags.extend(class_findings.diagnostics)
        diags.sort(key=lambda d: (d.line, d.col))
        source_lines = context.source_lines
        return [diag for diag in diags if not is_suppressed(source_lines, diag.line, self.code)]

    def _all_class_field_diags(
        self,
        path: Path,
        classes: list[ast.ClassDef],
        raw_string_aliases: frozenset[str],
        enum_like_classes: frozenset[int],
        imports: ImportIndex | None,
        *,
        unsafe_attribute_collections: dict[str, set[str]],
        parents: Mapping[ast.AST, ast.AST],
    ) -> _ClassFieldDiagnostics:
        diagnostics: list[Diagnostic] = []
        member_keys: dict[int, set[str]] = {}
        if imports is None:
            return _ClassFieldDiagnostics(diagnostics, member_keys)
        for cls in classes:
            annotation_scope = _class_annotation_imports(cls, imports, parents)
            current = self._class_field_diags(
                path,
                cls,
                raw_string_aliases - annotation_scope.shadowed_names,
                enum_like_classes,
                annotation_scope.imports,
                unsafe_attribute_collections=unsafe_attribute_collections,
            )
            diagnostics.extend(current)
            keys = _choice_member_keys(current)
            member_keys.update(
                (id(method), keys) for method in cls.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
        return _ClassFieldDiagnostics(diagnostics, member_keys)

    def _class_field_diags(
        self,
        path: Path,
        cls: ast.ClassDef,
        raw_string_aliases: frozenset[str],
        enum_like_classes: frozenset[int],
        imports: ImportIndex,
        *,
        unsafe_attribute_collections: dict[str, set[str]],
    ) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        if id(cls) in enum_like_classes or any(_trailing_name(base) in _ENUM_BASE_NAMES for base in cls.bases):
            return diags
        choice_groups = _class_choice_groups(cls, unsafe_attribute_collections)
        candidates = _class_choice_fields(cls, raw_string_aliases, imports)
        for stmt, name, default in candidates:
            choices = _choice_values_for_field(choice_groups, name)
            if not choices.associated and not (
                default is not None and len(candidates) == 1 and default in choices.generic
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
                    severity=Severity.ERROR,
                )
            )
        return diags


def _has_str_enum_signal(source: str) -> bool:
    has_string_literal = '"' in source or "'" in source
    if "str" in source and any(name in source.lower() for name in CHOICES_ATTR_NAMES):
        return True
    has_rejection = "raise" in source or "assert_never" in source
    return (
        has_string_literal
        and has_rejection
        and ("==" in source or "!=" in source or "in" in source or "match" in source)
    )


def _assert_never_imports(context: PythonFileContext, imports: ImportIndex | None) -> ImportIndex | None:
    if imports is None or "assert_never" not in context.symbol_source:
        return imports
    origins = _typing_namespace_origins(context)
    for node in context.nodes(ast.Name, ast.Attribute):
        parent = context.parents.get(node)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in origins.handles:
            return None
        if _typing_namespace_exposed(node, parent, origins.namespaces):
            return None
        if (
            isinstance(node.ctx, ast.Load)
            and imports.resolves(node, sources=_TYPING_SOURCES, symbol="assert_never")
            and (not isinstance(parent, ast.Call) or parent.func is not node)
        ):
            return None
    return imports


def _typing_namespace_origins(context: PythonFileContext) -> _TypingNamespaceOrigins:
    namespaces: set[str] = set()
    handles: set[str] = set()
    for node in context.nodes(ast.Import):
        namespaces.update(alias.asname or alias.name for alias in node.names if alias.name in _TYPING_SOURCES)
    for node in context.nodes(ast.ImportFrom):
        if node.level == 0 and node.module in _TYPING_SOURCES:
            handles.update(
                alias.asname or alias.name for alias in node.names if alias.name in _NAMESPACE_ACCESS_MEMBERS
            )
    return _TypingNamespaceOrigins(frozenset(namespaces), frozenset(handles))


def _typing_namespace_exposed(node: ast.AST, parent: ast.AST | None, namespaces: frozenset[str]) -> bool:
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in namespaces:
        return not isinstance(parent, ast.Attribute) or parent.value is not node
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in namespaces
        and node.attr in _NAMESPACE_ACCESS_MEMBERS
    ):
        return True
    if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, (ast.Store, ast.Del)):
        return False
    root: ast.expr = node
    while isinstance(root, ast.Attribute):
        root = root.value
    return isinstance(root, ast.Name) and root.id in namespaces


def _enum_like_class_ids(tree: ast.Module, *, node_index: NodeIndex | None = None) -> frozenset[int]:
    enum_names = set(_ENUM_BASE_NAMES)
    enum_modules = {"enum"}
    assignments: list[tuple[str, ast.expr]] = []
    _collect_enum_bindings(tree, enum_names, enum_modules, assignments, node_index=node_index)

    classes = [node for node in walk_ast(tree, index=node_index) if isinstance(node, ast.ClassDef)]
    enum_class_ids: set[int] = set()
    changed = True
    while changed:
        changed = False
        for name, value in assignments:
            if name not in enum_names and _is_enum_reference(value, enum_names, enum_modules):
                enum_names.add(name)
                changed = True
        if _register_enum_subclasses(classes, enum_class_ids, enum_names, enum_modules):
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


def _cluster_fires(key: str, entry: _ClusterEntry) -> bool:
    _line, _col, _literals, eq_literals, _ne_literals, in_literals, closed = entry
    if not closed or (not eq_literals and not in_literals):
        return False
    domain_literals = eq_literals | in_literals
    # One operator must enumerate multiple alternatives before the vocabulary is demonstrably closed.
    enumerated = len(domain_literals)
    if enumerated < _MIN_CLUSTER_SIZE:
        return False
    if not all(_LOWER_TOKEN_RE.fullmatch(lit) for lit in domain_literals):
        return False
    if all(lit in EXTERNAL_VOCAB for lit in domain_literals):
        return False  # URL schemes, language keywords, HTTP methods, reflection args
    if _is_file_mode_key(key) and all(_FILE_MODE_RE.fullmatch(lit) for lit in domain_literals):
        return False  # `mode not in {"r", "rt", "rb"}` — the stdlib open() vocabulary
    # A single-character cluster on a char/token variable is a tokenizer scan.
    return not (_is_scanner_key(key) and all(len(lit) == 1 for lit in domain_literals))


def _cluster_is_already_closed(
    key: str,
    literal_typed: frozenset[str],
) -> bool:
    segment = key.rsplit(".", 1)[-1].lower()
    if segment in OPEN_DOMAIN_CODE_NAMES or segment.endswith(_OPEN_DOMAIN_SUFFIXES):
        return True
    return key in literal_typed


def _module_literal_aliases(tree: ast.Module) -> _LiteralAliases:
    names: set[str] = set()
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
    return _LiteralAliases(frozenset(names))


def _module_raw_string_aliases(tree: ast.Module) -> frozenset[str]:
    aliases = _raw_alias_assignments(tree)
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


def _module_proven_raw_string_aliases(
    tree: ast.Module, imports: ImportIndex, *, node_index: NodeIndex | None = None
) -> frozenset[str]:
    assignments: dict[str, list[ast.expr]] = {}
    for statement in tree.body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=value)
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
                | ast.TypeAlias(name=ast.Name(id=name), value=value)
            ):
                assignments.setdefault(name, []).append(value)
            case _:
                pass
    binding_counts = _alias_binding_counts(tree, node_index=node_index)
    unique = {
        name: values[0] for name, values in assignments.items() if len(values) == 1 and binding_counts.get(name) == 1
    }
    aliases: set[str] = set()
    for _round in range(len(unique)):
        grown = {
            name
            for name, value in unique.items()
            if name not in aliases
            and (_is_builtin_str(value, imports) or (isinstance(value, ast.Name) and value.id in aliases))
        }
        if not grown:
            break
        aliases.update(grown)
    return frozenset(aliases)


def _is_builtin_str(node: ast.expr, imports: ImportIndex) -> bool:
    return (isinstance(node, ast.Name) and node.id == "str" and imports.builtin_is_unshadowed("str")) or (
        imports.resolves(node, sources=frozenset({"builtins"}), symbol="str")
    )


def _opaque_names(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    alias_names: frozenset[str],
    literal_funcs: frozenset[str],
    raw_string_aliases: frozenset[str],
    module_func_names: frozenset[str],
    *,
    closed_collections: frozenset[str],
    imports: ImportIndex | None,
    type_parameters: frozenset[str],
) -> frozenset[str]:
    base = (
        _literal_typed_names(func, alias_names)
        | _explicitly_open_literal_union_names(func, raw_string_aliases)
        | _dynamically_constrained_names(func, closed_collections)
        | _foreign_typed_names(func, raw_string_aliases, imports=imports, type_parameters=type_parameters)
        | _wire_bound_names(func, literal_funcs, module_func_names)
        | _fallback_consumed_names(func)
    )
    return _close_over_assignments(func, base)


def _class_method_owned_attributes(
    tree: ast.Module, *, node_index: NodeIndex | None = None
) -> dict[int, frozenset[str]]:
    result: dict[int, frozenset[str]] = {}
    for cls in (node for node in walk_ast(tree, index=node_index) if isinstance(node, ast.ClassDef)):
        attributes: set[str] = set()
        methods = [stmt for stmt in cls.body if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))]
        _collect_class_owned_attributes(cls, attributes)
        _collect_method_owned_attributes(methods, attributes)
        owned = frozenset(attributes)
        result.update((id(method), owned) for method in methods)
    return result


def _class_method_closed_attributes(
    tree: ast.Module,
    alias_names: frozenset[str],
    raw_string_aliases: frozenset[str],
    *,
    imports: ImportIndex | None,
    node_index: NodeIndex | None = None,
) -> dict[int, frozenset[str]]:
    result: dict[int, frozenset[str]] = {}
    for cls in (node for node in walk_ast(tree, index=node_index) if isinstance(node, ast.ClassDef)):
        closed = {
            statement.target.id
            for statement in cls.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and _is_closed_annotation(statement.annotation, alias_names, raw_string_aliases, imports=imports)
        }
        keys = frozenset(f"{receiver}.{name}" for receiver in _OWNED_ROOTS for name in closed)
        result.update(
            (id(method), keys) for method in cls.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    return result


def _dynamically_constrained_names(
    func: ast.FunctionDef | ast.AsyncFunctionDef, closed_collections: frozenset[str]
) -> frozenset[str]:
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
                and not (isinstance(collection, ast.Name) and collection.id in closed_collections)
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
            _collect_fallback_chain_names(node, open_names)
        stack.extend(children(node))
    return frozenset(open_names)


def _collect_fallback_chain_names(node: ast.If, open_names: set[str]) -> None:
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


def _statements_read_key(statements: list[ast.stmt], key: str) -> bool:
    for statement in statements:
        for node in walk_ast(statement):
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
        return _flatten_annotation_union(annotation)
    if isinstance(annotation, ast.Subscript) and _trailing_name(annotation.value) == "Union":
        return list(annotation.slice.elts) if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
    return [annotation]


def _closed_comprehension_targets(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    alias_names: frozenset[str],
    raw_string_aliases: frozenset[str],
    *,
    imports: ImportIndex | None,
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
        closed = _closed_generator_targets(node, annotations, alias_names, raw_string_aliases, imports=imports)
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


def _function_shadowed_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    arguments = [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]
    if func.args.vararg is not None:
        arguments.append(func.args.vararg)
    if func.args.kwarg is not None:
        arguments.append(func.args.kwarg)
    return {argument.arg for argument in arguments} | {target for target, _value in _local_bindings(func)}


def _local_bindings(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[_LocalBinding]:
    bindings: list[_LocalBinding] = []
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        match node:
            case ast.Assign():
                targets, value = list(node.targets), node.value
            case ast.AnnAssign() | ast.NamedExpr():
                targets, value = [node.target], node.value
            case _:
                pass
        if value is not None:
            bindings.extend(_LocalBinding(name, value) for target in targets for name in _bound_target_names(target))
        stack.extend(children(node))
    return bindings


def _foreign_typed_names(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    raw_string_aliases: frozenset[str],
    *,
    imports: ImportIndex | None,
    type_parameters: frozenset[str],
) -> frozenset[str]:
    names: set[str] = set()
    args = func.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
        if _uses_type_parameter(arg.annotation, type_parameters, imports) or _is_foreign_annotation(
            arg.annotation, raw_string_aliases, imports=imports
        ):
            names.add(arg.arg)
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and (
                _uses_type_parameter(node.annotation, type_parameters, imports)
                or _is_foreign_annotation(node.annotation, raw_string_aliases, imports=imports)
            )
        ):
            names.add(node.target.id)
        stack.extend(children(node))
    return frozenset(names)


def _uses_type_parameter(annotation: ast.expr | None, names: frozenset[str], imports: ImportIndex | None) -> bool:
    if not names or annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        parsed = _parse_string_annotation(annotation.value)
        return parsed is not None and _uses_type_parameter(parsed, names, imports)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _uses_type_parameter(annotation.left, names, imports) or _uses_type_parameter(
            annotation.right, names, imports
        )
    root = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    while isinstance(root, ast.Attribute):
        root = root.value
    if isinstance(root, ast.Name) and root.id in names:
        return True
    wrapped = _transparent_annotation_members(annotation, imports)
    if wrapped is not None:
        return any(_uses_type_parameter(member, names, imports) for member in wrapped)
    return False


def _is_foreign_annotation(
    annotation: ast.expr | None,
    raw_string_aliases: frozenset[str] = frozenset(),
    *,
    imports: ImportIndex | None = None,
) -> bool:
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        parsed = _parse_string_annotation(annotation.value)
        return parsed is not None and _is_foreign_annotation(parsed, raw_string_aliases, imports=imports)
    if _is_literal_annotation(annotation, frozenset()):
        return True
    inner = _strip_optional(annotation)
    wrapped = _transparent_annotation_members(inner, imports)
    if wrapped is not None:
        return not wrapped or any(
            _is_foreign_annotation(member, raw_string_aliases, imports=imports) for member in wrapped
        )
    if isinstance(inner, ast.Subscript) and _trailing_name(inner.value) == "Annotated":
        first = inner.slice.elts[0] if isinstance(inner.slice, ast.Tuple) and inner.slice.elts else None
        return first is not None and _is_foreign_annotation(first, raw_string_aliases, imports=imports)
    match inner:
        case ast.Name(id=ident):
            return ident != "str" and ident not in raw_string_aliases
        case ast.Attribute(attr=attr):
            return attr != "str"
        case ast.Subscript():
            return True
        case _:
            return False


def _transparent_annotation_members(annotation: ast.expr, imports: ImportIndex | None) -> list[ast.expr] | None:
    if not isinstance(annotation, ast.Subscript) or imports is None:
        return None
    symbol = imports.resolved_symbol(annotation.value, sources=frozenset({"typing", "typing_extensions"}))
    if symbol == "Optional":
        return [annotation.slice]
    if symbol == "Annotated" and isinstance(annotation.slice, ast.Tuple) and annotation.slice.elts:
        return [annotation.slice.elts[0]]
    if symbol == "Union":
        members = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return [member for member in members if not _is_none_annotation(member)]
    return None


def _strip_optional(annotation: ast.expr) -> ast.expr:
    current = annotation
    while True:
        match current:
            case ast.BinOp(op=ast.BitOr(), left=left, right=ast.Constant(value=None)):
                current = left
            case ast.BinOp(op=ast.BitOr(), left=ast.Constant(value=None), right=right):
                current = right
            case ast.Subscript(value=head, slice=inner) if _trailing_name(head) == "Optional":
                current = inner
            case _:
                return current


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
            return _is_wire_call(value, callee, args, blocked_call_names)
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


def _is_file_mode_key(key: str) -> bool:
    segment = key.rsplit(".", 1)[-1].lstrip("_").lower()
    return segment in _FILE_MODE_KEYS or segment.endswith("_mode")


def _is_scanner_key(key: str) -> bool:
    segment = key.rsplit(".", 1)[-1].lower()
    return segment in _SCANNER_KEY_SEGMENTS or "char" in segment


def _class_choice_groups(
    cls: ast.ClassDef, unsafe_attribute_collections: dict[str, set[str]]
) -> list[tuple[str, set[str]]]:
    candidates: list[tuple[str, str, set[str]]] = []
    for stmt in cls.body:
        match stmt:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=value)
                | ast.AnnAssign(target=ast.Name(id=name), value=value)
            ):
                pass
            case _:
                continue
        values = _string_collection_values(value)
        binding = name.lower()
        if (
            values is not None
            and len(values) >= _MIN_CLUSTER_SIZE
            and (binding in CHOICES_ATTR_NAMES or binding.endswith("_choices"))
        ):
            candidates.append((name, binding, values))
    if not candidates:
        return []
    binding_counts = _alias_binding_counts(cls)
    mutated = _non_membership_collection_reads(cls)
    local_unsafe = _unsafe_attribute_collection_uses(cls)
    mutated.update(unsafe_attribute_collections.get(cls.name, set()))
    mutated.update(local_unsafe.get("self", set()))
    mutated.update(local_unsafe.get("cls", set()))
    return [
        (binding, values)
        for name, binding, values in candidates
        if binding_counts.get(name) == 1 and name not in mutated and "*" not in mutated
    ]


def _module_closed_collections(tree: ast.Module, *, node_index: NodeIndex) -> dict[str, list[str]]:
    candidates = _module_literal_collections(tree)
    if not candidates:
        return {}
    if any(
        isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
        for node in node_index.query((ast.ImportFrom,))
    ):
        return {}
    bindings = _alias_binding_counts(tree, node_index=node_index)
    unsafe = _non_membership_collection_reads(tree, node_index=node_index)
    return {name: values for name, values in candidates.items() if bindings.get(name) == 1 and name not in unsafe}


def _module_literal_collections(tree: ast.Module) -> dict[str, list[str]]:
    candidates: dict[str, list[str]] = {}
    for statement in tree.body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=value)
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
            ):
                pass
            case _:
                continue
        if not isinstance(value, (ast.List, ast.Tuple, ast.Set)) or not value.elts:
            continue
        members = [_str_const(element) for element in value.elts]
        if all(member is not None for member in members):
            candidates[name] = [member for member in members if member is not None]
    return candidates


def _non_membership_collection_reads(tree: ast.AST, *, node_index: NodeIndex | None = None) -> set[str]:
    unsafe: set[str] = set()
    for parent in walk_ast(tree, index=node_index):
        for child in children(parent):
            if not isinstance(child, ast.Name) or not isinstance(child.ctx, ast.Load):
                continue
            if (
                isinstance(parent, ast.Compare)
                and len(parent.ops) == 1
                and isinstance(parent.ops[0], (ast.In, ast.NotIn))
                and parent.comparators == [child]
            ):
                continue
            unsafe.add(child.id)
    return unsafe


def _unsafe_attribute_collection_uses(tree: ast.AST, *, node_index: NodeIndex | None = None) -> dict[str, set[str]]:
    unsafe: dict[str, set[str]] = {}
    for parent in walk_ast(tree, index=node_index):
        for child in children(parent):
            if not isinstance(child, ast.Attribute) or not isinstance(child.value, ast.Name):
                continue
            if (
                isinstance(parent, ast.Compare)
                and len(parent.ops) == 1
                and isinstance(parent.ops[0], (ast.In, ast.NotIn))
                and parent.comparators == [child]
            ):
                continue
            unsafe.setdefault(child.value.id, set()).add(child.attr)
        if (
            isinstance(parent, ast.Call)
            and _trailing_name(parent.func) in {"setattr", "delattr"}
            and len(parent.args) >= _CHOICE_PAIR_ARITY
            and isinstance(parent.args[0], ast.Name)
        ):
            name = _str_const(parent.args[1])
            unsafe.setdefault(parent.args[0].id, set()).add(name if name is not None else "*")
    _propagate_collection_alias_uses(tree, unsafe, node_index=node_index)
    return unsafe


def _propagate_collection_alias_uses(
    tree: ast.AST, unsafe: dict[str, set[str]], *, node_index: NodeIndex | None = None
) -> None:
    aliases = _collection_owner_aliases(tree, node_index=node_index)
    # Exposure invalidates proof even when an alias has other possible bindings.
    # The finite owner/attribute sets converge without following runtime values.
    for _round in range(len(aliases)):
        changed = False
        for alias, original in aliases:
            exposed = unsafe.get(alias, set())
            if exposed and not exposed <= unsafe.get(original, set()):
                unsafe.setdefault(original, set()).update(exposed)
                changed = True
        if not changed:
            break


def _collection_owner_aliases(tree: ast.AST, *, node_index: NodeIndex | None) -> list[tuple[str, str]]:
    aliases: list[tuple[str, str]] = []
    for node in walk_ast(tree, index=node_index):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
            aliases.extend((target.id, node.value.id) for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and isinstance(node.value, ast.Name):
            aliases.append((node.target.id, node.value.id))
    return aliases


def _string_collection_values(node: ast.AST | None) -> set[str] | None:
    if isinstance(node, ast.Dict):
        return _dictionary_choice_values(node)
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


def _is_choice_string_annotation(
    annotation: ast.expr,
    raw_string_aliases: frozenset[str],
    imports: ImportIndex,
) -> bool:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        parsed = _parse_string_annotation(annotation.value)
        return parsed is not None and _is_choice_string_annotation(parsed, raw_string_aliases, imports)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_optional_choice_union(annotation, raw_string_aliases, imports)
    if isinstance(annotation, ast.Subscript) and imports.resolves(
        annotation.value,
        sources=frozenset({"typing", "typing_extensions"}),
        symbol="Optional",
    ):
        return _is_choice_string_annotation(annotation.slice, raw_string_aliases, imports)
    if isinstance(annotation, ast.Subscript) and imports.resolves(
        annotation.value,
        sources=frozenset({"typing", "typing_extensions"}),
        symbol="Annotated",
    ):
        first = annotation.slice.elts[0] if isinstance(annotation.slice, ast.Tuple) and annotation.slice.elts else None
        return first is not None and _is_choice_string_annotation(first, raw_string_aliases, imports)
    return _is_builtin_str(annotation, imports) or (
        isinstance(annotation, ast.Name) and annotation.id in raw_string_aliases
    )


def _accumulate_compare(
    clusters: dict[str, _ClusterEntry],
    node: ast.Compare,
    *,
    closed: bool,
    closed_collections: dict[str, list[str]],
) -> None:
    if not closed:
        return
    extracted = _extract_compare(node) or _extract_named_membership(node, closed_collections)
    if extracted is None:
        return
    _merge_cluster(
        clusters,
        extracted.key,
        extracted.literals,
        (node.lineno, node.col_offset + 1),
        operator=extracted.operator,
        closed=closed,
    )


def _extract_named_membership(node: ast.Compare, closed_collections: dict[str, list[str]]) -> _ExtractedCompare | None:
    if not (
        len(node.ops) == 1
        and isinstance(node.ops[0], (ast.In, ast.NotIn))
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Name)
    ):
        return None
    key = _name_key(node.left)
    values = closed_collections.get(node.comparators[0].id)
    return _ExtractedCompare(key, values, _MEMBERSHIP) if key is not None and values is not None else None


def _accumulate_match(clusters: dict[str, _ClusterEntry], node: ast.Match, imports: ImportIndex | None) -> None:
    key = _name_key(node.subject)
    if key is None or not _match_rejects_unlisted_values(node, key, imports):
        return
    literals: list[str] = []
    for case in node.cases:
        literals.extend(_match_pattern_literals(case.pattern))
    if not literals:
        return
    _merge_cluster(clusters, key, literals, (node.lineno, node.col_offset + 1), operator=_EQ, closed=True)


def _match_rejects_unlisted_values(node: ast.Match, key: str, imports: ImportIndex | None) -> bool:
    rejecting_fallback = False
    for case in node.cases:
        rejects = _statements_definitely_reject(case.body, key, imports)
        if isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None:
            if not rejects:
                return False
            if case.guard is None:
                rejecting_fallback = True
        elif not rejects and not _is_finite_string_pattern(case.pattern):
            return False
    return rejecting_fallback


def _is_finite_string_pattern(pattern: ast.pattern) -> bool:
    match pattern:
        case ast.MatchValue(value=value):
            return _str_const(value) is not None
        case ast.MatchAs(pattern=inner) if inner is not None:
            return _is_finite_string_pattern(inner)
        case ast.MatchOr(patterns=patterns):
            return all(_is_finite_string_pattern(inner) for inner in patterns)
        case _:
            return False


def _statements_definitely_reject(statements: list[ast.stmt], key: str, imports: ImportIndex | None) -> bool:
    if not statements:
        return False
    if any(not isinstance(statement, (ast.Expr, ast.Pass)) for statement in statements[:-1]):
        return False
    final = statements[-1]
    return (
        isinstance(final, ast.Raise)
        or (
            isinstance(final, ast.Expr)
            and isinstance(final.value, ast.Call)
            and imports is not None
            and imports.resolves(
                final.value.func,
                sources=frozenset({"typing", "typing_extensions"}),
                symbol="assert_never",
            )
            and len(final.value.args) == 1
            and _name_key(final.value.args[0]) == key
        )
        or (
            isinstance(final, ast.If)
            and _statements_definitely_reject(final.body, key, imports)
            and _statements_definitely_reject(final.orelse, key, imports)
        )
    )


def _closed_domain_node_ids(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex | None,
    closed_collections: dict[str, list[str]],
) -> frozenset[int]:
    closed: set[int] = set()
    # Only whole-function rejection proves closure; nested rejection may be skipped, repeated or caught.
    for node in function.body:
        if isinstance(node, ast.If):
            _record_rejecting_membership_guard(node, imports, closed, closed_collections)
            _record_exhaustive_if_chain(node, imports, closed)
        elif isinstance(node, ast.Match) and _match_rejects_unlisted_values(
            node, _name_key(node.subject) or "", imports
        ):
            closed.add(id(node))
        if not _statement_always_falls_through(node):
            break
    return frozenset(closed)


def _statement_always_falls_through(statement: ast.stmt) -> bool:
    stack: list[ast.AST] = [statement]
    while stack:
        node = stack.pop()
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Lambda():
                continue
            case ast.Return() | ast.Yield() | ast.YieldFrom() | ast.Break() | ast.Continue() | ast.Raise():
                return False
            case _:
                pass
        stack.extend(children(node))
    return True


def _record_rejecting_membership_guard(
    node: ast.If,
    imports: ImportIndex | None,
    closed: set[int],
    closed_collections: dict[str, list[str]],
) -> str | None:
    if not (
        isinstance(node.test, ast.Compare)
        and len(node.test.ops) == 1
        and isinstance(node.test.ops[0], ast.NotIn)
        and len(node.test.comparators) == 1
    ):
        return None
    key = _name_key(node.test.left)
    collection = node.test.comparators[0]
    explicit = _extract_compare(node.test) is not None or (
        isinstance(collection, ast.Name) and collection.id in closed_collections
    )
    if key is None or not explicit or not _statements_definitely_reject(node.body, key, imports):
        return None
    closed.add(id(node.test))
    return key


def _record_exhaustive_if_chain(node: ast.If, imports: ImportIndex | None, closed: set[int]) -> None:
    comparisons: list[ast.Compare] = []
    key: str | None = None
    current = node
    while True:
        branch = _positive_domain_comparisons(current.test)
        branch_keys = {extracted.key for compare in branch if (extracted := _extract_compare(compare)) is not None}
        if not branch or len(branch_keys) != 1:
            return
        branch_key = next(iter(branch_keys))
        if key is not None and branch_key != key:
            return
        key = branch_key
        comparisons.extend(branch)
        if len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
            current = current.orelse[0]
            continue
        if not current.orelse or not _statements_definitely_reject(current.orelse, key, imports):
            return
        closed.update(id(compare) for compare in comparisons)
        return


def _positive_domain_comparisons(node: ast.expr) -> list[ast.Compare]:
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        parts = [_positive_domain_comparisons(value) for value in node.values]
        return [comparison for part in parts for comparison in part] if all(parts) else []
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], (ast.Eq, ast.In)):
        return []
    return [node] if _extract_compare(node) is not None else []


def _merge_cluster(
    clusters: dict[str, _ClusterEntry],
    key: str,
    literals: list[str],
    pos: tuple[int, int],
    *,
    operator: str,
    closed: bool,
) -> None:
    entry = clusters.get(key, (*pos, set[str](), set[str](), set[str](), set[str](), False))
    line, col, seen, eq_seen, ne_seen, in_seen, was_closed = entry
    line, col = min((line, col), pos)
    match operator:
        case "==":
            eq_seen |= set(literals)
        case "!=":
            ne_seen |= set(literals)
        case _:
            in_seen |= set(literals)
    clusters[key] = (line, col, seen | set(literals), eq_seen, ne_seen, in_seen, was_closed or closed)


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


@dataclass(frozen=True, slots=True)
class _ChoiceValues:
    associated: set[str]
    generic: set[str]


def _choice_values_for_field(choice_groups: list[tuple[str, set[str]]], name: str) -> _ChoiceValues:
    associated_values = {
        value for binding, values in choice_groups if _choice_binding_field(binding) == name.lower() for value in values
    }
    generic_values = {
        value for binding, values in choice_groups if _choice_binding_field(binding) is None for value in values
    }
    return _ChoiceValues(associated=associated_values, generic=generic_values)


def _choice_binding_field(binding: str) -> str | None:
    if binding.endswith("_choices") and len(binding) > len("_choices"):
        return binding.removesuffix("_choices")
    return CHOICE_COLLECTION_FIELDS.get(binding)


def _extract_compare(node: ast.Compare) -> _ExtractedCompare | None:
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    op = node.ops[0]
    left, right = node.left, node.comparators[0]
    match op:
        case ast.Eq() | ast.NotEq():
            return _extract_equality_compare(op, left, right)
        case ast.In() | ast.NotIn():
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
        case _:
            pass
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


def _annotation_type_parameters(owner: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> frozenset[str]:
    names: set[str] = set()
    node: ast.AST | None = owner
    while node is not None:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.update(
                parameter.name
                for parameter in node.type_params
                if isinstance(parameter, (ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple))
            )
        node = parents.get(node)
    return frozenset(names)


@dataclass(frozen=True, slots=True)
class _ClassAnnotationScope:
    imports: ImportIndex
    shadowed_names: frozenset[str]


def _class_annotation_imports(
    cls: ast.ClassDef, imports: ImportIndex, parents: Mapping[ast.AST, ast.AST]
) -> _ClassAnnotationScope:
    shadowed = _annotation_type_parameters(cls, parents)
    return _ClassAnnotationScope(
        imports=ImportIndex(
            {name: binding for name, binding in imports.bindings.items() if name not in shadowed},
            imports.shadowed_names | shadowed,
        ),
        shadowed_names=shadowed,
    )


def _class_choice_fields(
    cls: ast.ClassDef, raw_string_aliases: frozenset[str], imports: ImportIndex
) -> list[tuple[ast.AnnAssign, str, str | None]]:
    candidates: dict[str, tuple[ast.AnnAssign, str, str | None] | None] = {}
    for stmt in cls.body:
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        name = stmt.target.id
        if not _is_choice_string_annotation(stmt.annotation, raw_string_aliases, imports):
            candidates[name] = None
            continue
        default = _str_const(stmt.value) if stmt.value is not None else None
        previous = candidates.get(name)
        if previous is None or previous[2] != default:
            candidates[name] = (stmt, name, default)
    return [candidate for candidate in candidates.values() if candidate is not None]


def _is_wire_call(value: ast.Call, callee: ast.expr, args: list[ast.expr], blocked_call_names: frozenset[str]) -> bool:
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


def _dictionary_choice_values(node: ast.Dict) -> set[str] | None:
    keys: set[str] = set()
    for key in node.keys:
        if key is not None and _is_none_annotation(key):
            continue
        value = None if key is None else _str_const(key)
        if value is None:
            return None
        keys.add(value)
    return keys


def _is_optional_choice_union(annotation: ast.BinOp, raw_string_aliases: frozenset[str], imports: ImportIndex) -> bool:
    members = _flatten_annotation_union(annotation)
    non_none = [member for member in members if not _is_none_annotation(member)]
    return (
        len(non_none) == 1
        and len(non_none) < len(members)
        and _is_choice_string_annotation(non_none[0], raw_string_aliases, imports)
    )


def _extract_equality_compare(op: ast.Eq | ast.NotEq, left: ast.expr, right: ast.expr) -> _ExtractedCompare | None:
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


def _collect_enum_bindings(
    tree: ast.Module,
    enum_names: set[str],
    enum_modules: set[str],
    assignments: list[tuple[str, ast.expr]],
    *,
    node_index: NodeIndex | None = None,
) -> None:
    for node in walk_ast(tree, index=node_index):
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


def _raw_alias_assignments(tree: ast.Module) -> dict[str, ast.expr]:
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
            value = _unwrap_type_alias_value(value)
            aliases[statement.targets[0].id] = value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
        ):
            aliases[statement.target.id] = statement.value
    return aliases


def _unwrap_type_alias_value(value: ast.expr) -> ast.expr:
    if isinstance(value, ast.Call) and _trailing_name(value.func) == "TypeAliasType":
        return (
            value.args[1]
            if len(value.args) >= _MIN_TYPE_ALIAS_ARGS
            else next((keyword.value for keyword in value.keywords if keyword.arg == "value"), value)
        )
    return value


def _alias_binding_counts(tree: ast.AST, *, node_index: NodeIndex | None = None) -> dict[str, int]:
    binding_counts: dict[str, int] = {}
    for node in walk_ast(tree, index=node_index):
        match node:
            case (
                ast.Name(id=name, ctx=(ast.Store() | ast.Del()))
                | ast.arg(arg=name)
                | ast.ExceptHandler(name=str() as name)
                | ast.MatchAs(name=str() as name)
                | ast.MatchStar(name=str() as name)
                | ast.MatchMapping(rest=str() as name)
            ):
                binding_counts[name] = binding_counts.get(name, 0) + 1
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                binding_counts[node.name] = binding_counts.get(node.name, 0) + 1
            case ast.alias(name=name, asname=asname):
                local = asname or name.partition(".")[0]
                binding_counts[local] = binding_counts.get(local, 0) + 1
            case _:
                pass
    return binding_counts


def _collect_method_owned_attributes(
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef], attributes: set[str]
) -> None:
    for method in methods:
        stack: list[ast.AST] = list(method.body)
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            method_targets = _assignment_targets(node)
            for target in method_targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in _OWNED_ROOTS
                ):
                    attributes.add(target.attr)
            stack.extend(children(node))


def _assignment_targets(node: ast.AST) -> list[ast.expr]:
    method_targets: list[ast.expr] = []
    match node:
        case ast.Assign():
            method_targets.extend(node.targets)
        case ast.AnnAssign() | ast.AugAssign():
            method_targets.append(node.target)
        case _:
            pass
    return method_targets


def _is_closed_annotation(
    annotation: ast.expr,
    alias_names: frozenset[str],
    raw_string_aliases: frozenset[str],
    *,
    imports: ImportIndex | None,
) -> bool:
    return _is_literal_annotation(annotation, alias_names) or _is_foreign_annotation(
        annotation, raw_string_aliases, imports=imports
    )


def _closed_generator_targets(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    annotations: dict[str, ast.expr],
    alias_names: frozenset[str],
    raw_string_aliases: frozenset[str],
    *,
    imports: ImportIndex | None,
) -> set[str]:
    closed: set[str] = set()
    for generator in node.generators:
        if not isinstance(generator.iter, ast.Name):
            continue
        annotation = annotations.get(generator.iter.id)
        if not isinstance(annotation, ast.Subscript):
            continue
        element = annotation.slice.elts[0] if isinstance(annotation.slice, ast.Tuple) else annotation.slice
        if _is_literal_annotation(element, alias_names) or _is_foreign_annotation(
            element, raw_string_aliases, imports=imports
        ):
            closed.update(_bound_target_names(generator.target))
    return closed


def _choice_member_keys(class_diags: list[Diagnostic]) -> set[str]:
    choice_field_names = {
        diag.message.split("`", maxsplit=2)[1].split(":", maxsplit=1)[0]
        for diag in class_diags
        if diag.message.startswith("`") and "`" in diag.message[1:]
    }
    return {f"{receiver}.{name}" for receiver in ("self", "cls") for name in choice_field_names}


def _register_enum_subclasses(
    classes: list[ast.ClassDef], enum_class_ids: set[int], enum_names: set[str], enum_modules: set[str]
) -> bool:
    changed = False
    for cls in classes:
        if id(cls) in enum_class_ids:
            continue
        if any(_is_enum_reference(base, enum_names, enum_modules) for base in cls.bases):
            enum_class_ids.add(id(cls))
            enum_names.add(cls.name)
            changed = True
    return changed


def _collect_class_owned_attributes(cls: ast.ClassDef, attributes: set[str]) -> None:
    for statement in cls.body:
        class_targets: list[ast.expr] = []
        match statement:
            case ast.Assign():
                class_targets.extend(statement.targets)
            case ast.AnnAssign():
                class_targets.append(statement.target)
            case _:
                pass
        attributes.update(target.id for target in class_targets if isinstance(target, ast.Name))
