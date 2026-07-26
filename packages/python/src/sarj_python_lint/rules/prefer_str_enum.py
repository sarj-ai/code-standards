"""SARJ006: raw `str` used where a closed enumeration is clearly intended.

`Literal["a", "b", "c"]` is acceptable — that's a proper closed set. After a
real-world sweep (Flask, requests, httpx, FastAPI, Django) the rule was tightened
to two corroborated triggers only:

1. **Sibling choices attribute** — a class with a string-collection attribute
   named `choices`/`states`/`statuses`/`values`/`allowed` flags its raw-`str`
   fields (the collection is the enum that should exist). A bare `status: str`
   with no such corroboration does NOT fire: a field name alone is too weak a
   signal (a free-form HTTP `status` string is still `str`).
2. **Equality comparison cluster** — within one function, the same *plain
   variable* (not an attribute of a value the module doesn't own) is compared
   with `==`/`!=` (or matched with `case`) against 2+ distinct short lowercase
   string literals. A lone `x in {...}` / `x not in {...}` membership test is
   NOT enough on its own — it is usually a guard over an external vocabulary
   (URL schemes, file modes, reflection keys), not an app-owned enum. A field
   whose name matches such a cluster is corroborated and also flagged.

   The 2+ literals must be enumerated by ONE operator (`x == "a" ... elif
   x == "b"`, or `x != "a" and x != "b"`), optionally corroborated by a
   membership set over the same variable (`assert x in ("a", "b")` next to
   `if x == "a"`). `==` and `!=` literals are never summed with each other: an
   `x == "a"` plus `x != "b"` pair is two independent guards, not a dispatch
   over a domain. Four of the famous-repo sweep's 31 hits were that pair
   (`fastapi/docs_src/dependencies/tutorial008c_py310.py:19` and its three
   siblings: `if item_id == "portal-gun": ... if item_id != "plumbus": ...`).

Deliberately NOT flagged (real-world false positives the sweep surfaced):
- Attribute comparands whose root the module does not own (`url.scheme`,
  `field.mode`, `self.__dict__` reflection keys) — you cannot turn someone
  else's attribute into a StrEnum.
- Lone membership guards over external vocabularies.
- Single-character tokenizer scans (`last_char == "g"`) and language-keyword
  tokenizers (`token in ("is", "not", "in")`).
- Variables that are already a closed `Literal` — either annotated inline
  (`x: Literal["a", "b"]`) or via a module-level alias (`Mode = Literal[...]`;
  `x: Mode`), or whose compared literals are all members of such an in-module
  alias (Rich's `align = self.align` where `AlignMethod = Literal[...]`). The
  closed set already exists; recommending a StrEnum is redundant.
- Open-domain code variables (`language`, `country`, `currency`, `timezone`,
  `locale`, `region`, `code`, ...): special-casing a few ISO codes is not a
  closed enum.
- Variables bound from a subscript or `.get(...)` lookup in the same function
  (`schema_type = schema['type']`, `extra = cfg.get('behavior')`): the value
  comes off a dict-shaped wire format owned by someone else (pydantic-core
  schemas were the motivating sweep case) — you cannot impose a StrEnum on
  another system's payload keys.

The famous-repo sweep (31 hits over fastapi / pydantic / rich / flask / black)
retired four more classes, all of them "the domain is not this comparison's to
define":

- **Separately-typed variables.** Anything annotated with a named type other
  than `str` — `justify: JustifyMethod` (`rich/rich/containers.py:129`),
  `align: AlignMethod` (`rich/rich/text.py:955`),
  `vertical: VerticalAlignMethod` (`rich/rich/table.py:859`),
  `mode: FieldValidatorModes` (`pydantic/pydantic/_internal/_decorators.py:563`).
  All four are `Literal` aliases the rule cannot see, because they are declared
  in the module that owns them and imported here; what it CAN see is that the
  domain already has a name and a definition site. Opacity propagates through
  assignment, so `_overflow = overflow or self.overflow or DEFAULT_OVERFLOW`
  (`rich/rich/text.py:874`) is opaque too. Same for a local bound from a
  same-module function that returns a `Literal`
  (`pydantic/pydantic/_internal/_generate_schema.py:2833`).
- **Foreign reads, extended to loops and attributes.** The direct form
  (`token.type == "text"`) never fired; binding it to a local first must not
  change the answer. So `node_type = token.type` (`rich/rich/markdown.py:605`),
  `v = leaf.value` (`black/src/black/nodes.py:940`),
  `copy_on_model_validation = cls.__config__.copy_on_model_validation`
  (`pydantic/pydantic/v1/main.py:711`, a chain that has left `self`),
  `event = os.getenv("GITHUB_EVENT_NAME")`
  (`black/scripts/diff_shades_gha_helper.py:125`), `word = next(words, "")`
  (`rich/rich/style.py:522`, a token scan) and every `for` target over somebody
  else's mapping or attribute — `for k, v in obj.items()`
  (`pydantic/pydantic/_internal/_core_utils.py:117`), `for ann_name, _ in
  type_hints.items()` (`.../_fields.py:273`), `for arg, name in zip(expr.args,
  expr.arg_names)` (`pydantic/pydantic/mypy.py:1096`,
  `pydantic/pydantic/v1/mypy.py:616`), `for field in sorted(node._fields)`
  (`black/src/black/parsing.py:218`) — are all reflection over an external
  vocabulary.
- **`open()` modes.** A variable named `mode` / `_mode` / `*_mode` compared only
  against 1-3 characters drawn from `rwxab+t` is the stdlib file-mode
  vocabulary (`flask/src/flask/app.py:437`,
  `flask/src/flask/blueprints.py:120`, `rich/rich/progress.py:1345`). Matching
  on the name AND the shape keeps single-character enums elsewhere
  (`grade == "a"` / `grade == "b"`) firing.
- **`self` / `cls`**, added to `EXTERNAL_VOCAB`: comparing against those
  inspects a function signature (`pydantic/pydantic/v1/class_validators.py:268`),
  it does not dispatch over a domain.

Replace a genuine hit with:
    class Status(StrEnum):
        ACTIVE = "active"
        INACTIVE = "inactive"

References:
- https://docs.python.org/3/library/enum.html#enum.StrEnum
- https://docs.pydantic.dev/latest/concepts/types/#enums

"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none


if TYPE_CHECKING:
    from pathlib import Path


#: Per-variable comparison-cluster accumulator: first line, first col, every
#: distinct literal seen, then the literals bucketed by operator — `==` / `case`,
#: `!=`, and `in` / `not in`. A closed set is *enumerated*: one equality operator
#: reaching 2+ alternatives, on its own or corroborated by a membership set. The
#: `==` and `!=` buckets are never summed with each other, so an
#: `x == "a"` / `x != "b"` pair of independent guards does not fire.
type _ClusterEntry = tuple[int, int, set[str], set[str], set[str], set[str]]


#: Sibling class attributes whose presence marks all raw-str fields as choice-like.
CHOICES_ATTR_NAMES = frozenset({"choices", "states", "statuses", "values", "allowed"})

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

#: Variable names that denote an OPEN external vocabulary (ISO language / country
#: / currency codes, timezones, locales, regions). Special-casing a few of these
#: with `if language == "en": elif language == "zh":` is not a closed app enum —
#: the domain has thousands of members, so a StrEnum would be wrong.
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

#: Variable names that hold an `open()` mode. Combined with `_FILE_MODE_RE` this
#: covers the mode-check idiom without swallowing single-character enums
#: elsewhere (`grade == "a"` / `grade == "b"` is still a dispatch).
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
    """Choice-shaped str field or literal equality cluster — prefer StrEnum."""

    id: str = "prefer-str-enum"
    code: str = "SARJ006"
    description: str = "Corroborated choice-like str field or equality cluster — prefer StrEnum."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not _has_str_enum_signal(source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        check_clusters = not _is_test_path(path)
        alias_names, alias_valuesets = _module_literal_aliases(tree)
        literal_funcs = _literal_returning_functions(tree)
        class_nodes: list[ast.ClassDef] = []
        all_clusters: list[tuple[dict[str, _ClusterEntry], frozenset[str]]] = []
        stack: list[tuple[ast.AST, dict[str, _ClusterEntry] | None]] = [(tree, None)]
        while stack:
            node, active = stack.pop()
            if isinstance(node, ast.ClassDef):
                class_nodes.append(node)
                child_active: dict[str, _ClusterEntry] | None = None
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if check_clusters:
                    child_active = {}
                    all_clusters.append((child_active, _opaque_names(node, alias_names, literal_funcs)))
                else:
                    child_active = None
            elif isinstance(node, ast.Lambda):
                child_active = None
            else:
                child_active = active
                if active is not None:
                    if isinstance(node, ast.Compare):
                        _accumulate_compare(active, node)
                    elif isinstance(node, ast.Match):
                        _accumulate_match(active, node)
            stack.extend((child, child_active) for child in ast.iter_child_nodes(node))

        diags: list[Diagnostic] = []
        firing_field_names: set[str] = set()
        for clusters, literal_typed in all_clusters:
            for key, entry in clusters.items():
                if _cluster_is_already_closed(key, entry, literal_typed, alias_valuesets):
                    continue
                if not _cluster_fires(key, entry):
                    continue
                firing_field_names.add(key)
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
            diags.extend(self._class_field_diags(path, cls, firing_field_names))
        diags.sort(key=lambda d: (d.line, d.col))
        return diags

    def _class_field_diags(self, path: Path, cls: ast.ClassDef, firing_field_names: set[str]) -> list[Diagnostic]:
        diags: list[Diagnostic] = []
        if any(_trailing_name(b) in {"Enum", "StrEnum", "IntEnum"} for b in cls.bases):
            return diags
        choices_attrs: set[str] = set()
        for stmt in cls.body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                target = (
                    stmt.targets[0] if isinstance(stmt, ast.Assign) and stmt.targets else getattr(stmt, "target", None)
                )
                if not isinstance(target, ast.Name):
                    continue
                val = getattr(stmt, "value", None)
                if _is_string_collection(val) and target.id.lower() in CHOICES_ATTR_NAMES:
                    choices_attrs.add(target.id)
        for stmt in cls.body:
            if not isinstance(stmt, ast.AnnAssign):
                continue
            if not isinstance(stmt.target, ast.Name):
                continue
            ann_text = _annotation_text(stmt.annotation)
            if ann_text.strip() != "str":
                continue  # Literal[...] etc. is fine
            name = stmt.target.id
            corroborated = bool(choices_attrs) or name in firing_field_names
            if not corroborated:
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
    """Cheap source gate for files that cannot contain this rule's triggers.

    Returns:
        True when the source contains enough lexical signal to justify parsing.

    """
    has_string_literal = '"' in source or "'" in source
    if "str" in source and any(name in source.lower() for name in CHOICES_ATTR_NAMES):
        return True
    return (
        has_string_literal
        and ("==" in source or "!=" in source or "case " in source or "match " in source)
    )


def _cluster_fires(key: str, entry: _ClusterEntry) -> bool:
    _line, _col, literals, eq_literals, ne_literals, in_literals = entry
    if not eq_literals and not ne_literals:
        return False  # a lone `in`/`not in` membership guard is not an app enum
    # A closed set is enumerated by ONE operator reaching 2+ alternatives
    # (`x == "a" ... elif x == "b"`, `x != "a" and x != "b"`), optionally
    # corroborated by a membership set over the same variable. `==` and `!=`
    # literals are never summed together: `x == "a"` plus `x != "b"` is two
    # independent guards, not a dispatch over a domain.
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
    """Report whether a cluster is on a variable whose domain is already closed.

    Suppressed when the variable is an open-domain code name, is annotated as a
    `Literal` (inline or via a module alias), or its compared literals are all
    members of an in-module `Literal` alias's value set.

    Returns:
        True when the cluster should be suppressed as already-closed.

    """
    if key.lower() in OPEN_DOMAIN_CODE_NAMES:
        return True
    if key in literal_typed:
        return True
    _line, _col, literals, _eq, _ne, _in = entry
    return any(literals <= vs for vs in alias_valuesets)


def _module_literal_aliases(tree: ast.Module) -> tuple[frozenset[str], list[frozenset[str]]]:
    """Collect module-level `X = Literal[...]` aliases.

    Returns:
        The alias names, plus each alias's set of string-literal values.

    """
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


def _literal_typed_names(func: ast.FunctionDef | ast.AsyncFunctionDef, alias_names: frozenset[str]) -> frozenset[str]:
    """Collect names in `func` annotated as a `Literal` (inline or via a module alias).

    Covers the function's own parameters and `x: <literal>` annotated locals in
    its body (not descending into nested functions/classes, which own their
    scope).

    Returns:
        The set of such names.

    """
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
        stack.extend(ast.iter_child_nodes(node))
    return frozenset(names)


def _opaque_names(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    alias_names: frozenset[str],
    literal_funcs: frozenset[str],
) -> frozenset[str]:
    """Collect the names in `func` a StrEnum recommendation cannot apply to.

    Three families, then closed under assignment (a name derived from an opaque
    name is itself opaque — Rich's `_overflow = overflow or self.overflow or
    DEFAULT_OVERFLOW`):

    * already-closed domains — a `Literal` annotation, or a call to a
      same-module function that returns one;
    * separately-typed names — anything annotated with a named type other than
      `str` (`justify: JustifyMethod`): the domain already has a home, and it
      is not this comparison's to redefine;
    * wire-bound names — read off a payload, an iteration over somebody else's
      mapping/attribute, an environment variable, or a token stream.

    Returns:
        The set of names whose clusters must not fire.

    """
    base = _literal_typed_names(func, alias_names) | _foreign_typed_names(func) | _wire_bound_names(func, literal_funcs)
    return _close_over_assignments(func, base)


def _close_over_assignments(func: ast.FunctionDef | ast.AsyncFunctionDef, seed: frozenset[str]) -> frozenset[str]:
    """Propagate opacity along `x = <expr mentioning an opaque name>`.

    Returns:
        The seed set plus every name derived from it.

    """
    edges: list[tuple[str, frozenset[str]]] = []
    for target, value in _local_bindings(func):
        sources = {node.id for node in ast.walk(value) if isinstance(node, ast.Name)}
        if sources:
            edges.append((target.id, frozenset(sources)))
    names = set(seed)
    for _round in range(len(edges)):
        grown = {target for target, sources in edges if target not in names and sources & names}
        if not grown:
            break
        names |= grown
    return frozenset(names)


def _local_bindings(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[ast.Name, ast.expr]]:
    """Collect `x = <value>` / `x: T = <value>` / `(x := <value>)` bindings in `func`'s own scope.

    Nested functions/classes own their scope and are not descended into.

    Returns:
        The bound names paired with their initializers.

    """
    bindings: list[tuple[ast.Name, ast.expr]] = []
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and value is not None:
            bindings.append((target, value))
        stack.extend(ast.iter_child_nodes(node))
    return bindings


def _foreign_typed_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    """Collect names annotated with a named type other than `str`.

    Rich's `justify: JustifyMethod` / pydantic's `mode: FieldValidatorModes` are
    already closed sets — declared as `Literal` aliases in the module that owns
    them — but the alias is imported, so it cannot be resolved from here. What
    IS visible is that the value is not a bare `str`: its domain has a name and
    a definition site, and "define a StrEnum" belongs there, not here.

    Returns:
        The set of such names.

    """
    names: set[str] = set()
    args = func.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
        if _is_foreign_annotation(arg.annotation):
            names.add(arg.arg)
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and _is_foreign_annotation(node.annotation)
        ):
            names.add(node.target.id)
        stack.extend(ast.iter_child_nodes(node))
    return frozenset(names)


def _is_foreign_annotation(annotation: ast.expr | None) -> bool:
    """Report whether the annotation names a type other than `str`.

    `str`, `str | None` and `Optional[str]` are the shapes this rule is about
    and are NOT foreign; a bare name or dotted reference to anything else is.

    Returns:
        True when the annotation is a named non-`str` type.

    """
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        text = annotation.value.strip()
        return bool(text) and text != "str" and text.isidentifier()
    inner = _strip_optional(annotation)
    match inner:
        case ast.Name(id=ident):
            return ident != "str"
        case ast.Attribute(attr=attr):
            return attr != "str"
        case _:
            return False


def _strip_optional(annotation: ast.expr) -> ast.expr:
    """Unwrap `X | None` and `Optional[X]` down to `X`.

    Returns:
        The annotation with its optionality removed.

    """
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
    """Collect the names of functions in this module that return a `Literal[...]`.

    A local bound from such a call already has a closed domain, declared at the
    function that produced it (pydantic's `_inlining_behavior(...) ->
    Literal['inline', 'keep', 'preserve_metadata']`).

    Returns:
        The function names.

    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.returns is not None
            and _literal_string_values(node.returns) is not None
        ):
            names.add(node.name)
    return frozenset(names)


def _wire_bound_names(func: ast.FunctionDef | ast.AsyncFunctionDef, literal_funcs: frozenset[str]) -> frozenset[str]:
    """Collect names in `func` bound from a value the module does not own.

    `schema_type = schema['type']` / `extra = cfg.get('behavior')` read a value
    off a dict-shaped wire format; `for k, v in obj.items()` and
    `for arg, name in zip(expr.args, expr.arg_names)` iterate somebody else's
    keys; `event = os.getenv(...)` reads the environment; `word = next(words,
    "")` pulls a token off a scan. Clusters on such names are
    external-vocabulary dispatch, not an app enum — and the direct form
    (`obj.attr == "a"`) never fired either, so binding it to a local first must
    not change the answer. Nested functions/classes own their scope and are not
    descended into.

    Returns:
        The set of such names.

    """
    names: set[str] = set()
    for target, value in _local_bindings(func):
        if _is_wire_lookup(value) or (isinstance(value, ast.Call) and _trailing_name(value.func) in literal_funcs):
            names.add(target.id)
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)) and _is_wire_lookup(node.iter):
            names.update(_bound_target_names(node.target))
        stack.extend(ast.iter_child_nodes(node))
    return frozenset(names)


def _bound_target_names(target: ast.expr) -> set[str]:
    """Collect every name bound by an assignment target, nested unpacking included.

    Returns:
        The bound names.

    """
    return {node.id for node in ast.walk(target) if isinstance(node, ast.Name)}


def _is_wire_lookup(value: ast.expr) -> bool:
    """Report whether `value` reads from something the module does not own.

    Subscripts, `.get()` / `.items()` / `next()` / `os.getenv()` style reads,
    attribute reads off another object, and any of those behind one iterable
    wrapper (`zip(...)`, `sorted(...)`, `enumerate(...)`).

    Returns:
        True for a foreign read.

    """
    match value:
        case ast.Subscript():
            return True
        case ast.Attribute():
            return _is_foreign_attribute(value)
        case ast.Call(func=callee, args=args):
            name = _trailing_name(callee)
            if name in _WIRE_CALL_NAMES:
                return True
            if name in _ITERABLE_WRAPPERS:
                return any(_is_wire_lookup(arg) for arg in args)
            return isinstance(callee, ast.Attribute) and _is_foreign_attribute(callee)
        case _:
            return False


def _is_foreign_attribute(node: ast.Attribute) -> bool:
    """Report whether an attribute chain reads a value off an object the module does not own.

    `token.type` is somebody else's field; `self.mode` is this class's own, but
    `self._config_wrapper.extra` has left `self` and reached a collaborator.

    Returns:
        True when the chain root is foreign, or the chain is deep enough to have left it.

    """
    depth = 0
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        depth += 1
        current = current.value
    if not isinstance(current, ast.Name):
        return False
    return current.id not in _OWNED_ROOTS or depth >= _FOREIGN_CHAIN_DEPTH


def _trailing_name(node: ast.AST) -> str | None:
    """Return the trailing identifier of a `Name` / `Attribute` chain.

    Returns:
        The trailing name, or None when the node is neither.

    """
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
        text = annotation.value.strip()
        return text in alias_names or text.startswith("Literal[")
    if _literal_string_values(annotation) is not None:
        return True
    if isinstance(annotation, ast.Name):
        return annotation.id in alias_names
    return False


def _literal_string_values(node: ast.expr) -> list[str] | None:
    """Return the string members of a `Literal[...]` subscript, or None if not one.

    A `Literal[...]` with only non-string members yields an empty list (still a
    Literal); a non-`Literal` node yields None.

    Returns:
        The string members, or None when `node` is not a `Literal[...]`.

    """
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
    """Report whether the variable holds an `open()` mode (`mode`, `_mode`, `file_mode`).

    Returns:
        True when the name marks a file mode.

    """
    segment = key.rsplit(".", 1)[-1].lstrip("_").lower()
    return segment in _FILE_MODE_KEYS or segment.endswith("_mode")


def _is_scanner_key(key: str) -> bool:
    segment = key.rsplit(".", 1)[-1].lower()
    return segment in _SCANNER_KEY_SEGMENTS or "char" in segment


def _is_string_collection(node: ast.AST | None) -> bool:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return False
    return all(isinstance(elt, ast.Constant) and isinstance(elt.value, str) for elt in node.elts)


def _is_test_path(path: Path) -> bool:
    if path.name.startswith("test_"):
        return True
    return "tests" in path.parts


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
    """Collect string-constant literals from a `case` pattern (`MatchValue` / `MatchOr`).

    Returns:
        The string literals found in the pattern.

    """
    if isinstance(pattern, ast.MatchValue):
        value = _str_const(pattern.value)
        return [value] if value is not None else []
    if isinstance(pattern, ast.MatchOr):
        literals: list[str] = []
        for sub in pattern.patterns:
            literals.extend(_match_pattern_literals(sub))
        return literals
    return []


def _annotation_text(annotation: ast.expr | None) -> str:
    """Unparse the annotation, unwrapping a stringized forward-ref (`x: "str"`).

    Returns:
        The unparsed annotation text, or "" when the annotation is None.

    """
    if annotation is None:
        return ""
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value
    return ast.unparse(annotation)


def _extract_compare(node: ast.Compare) -> tuple[str, list[str], str] | None:
    """Return (variable key, string literals, operator kind) for an enum-shaped compare.

    Handles `x == "a"`, `"a" == x` (yoda), `x != "a"`, and
    `x in ("a", "b")` / `x not in {...}` where every element is a string
    constant. The compared variable must be a plain *name* — subscripts (dict
    keys), calls, f-strings, and attribute chains (`url.scheme`, `field.mode`,
    reflection keys) are excluded: the module cannot turn a value it doesn't
    own into a StrEnum. `is_equality` is True only for `==` / `!=`; a bare
    membership test is not on its own strong enough to fire.

    Returns:
        The (key, literals, operator) triple, or None for a non-enum-shaped compare.

    """
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
    """Return a stable key for a plain name; attribute chains and everything else -> None.

    Returns:
        The name's identifier, or None when `node` is not a plain name.

    """
    if isinstance(node, ast.Name):
        return node.id
    return None


def _str_const(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None
