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


#: Per-variable comparison-cluster accumulator:
#: (first line, first col, saw-an-equality-comparison, distinct literals).
type _ClusterEntry = tuple[int, int, bool, set[str]]


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

#: How many distinct literals a variable must be compared against to fire.
_MIN_CLUSTER_SIZE = 2


class PreferStrEnum(Rule):
    """Choice-shaped str field or literal equality cluster — prefer StrEnum."""

    id: str = "prefer-str-enum"
    code: str = "SARJ006"
    description: str = "Corroborated choice-like str field or equality cluster — prefer StrEnum."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        check_clusters = not _is_test_path(path)
        alias_names, alias_valuesets = _module_literal_aliases(tree)
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
                    all_clusters.append(
                        (child_active, _literal_typed_names(node, alias_names) | _wire_bound_names(node))
                    )
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
        if any(_base_name(b) in {"Enum", "StrEnum", "IntEnum"} for b in cls.bases):
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


def _cluster_fires(key: str, entry: _ClusterEntry) -> bool:
    _line, _col, saw_equality, literals = entry
    if not saw_equality:
        return False  # a lone `in`/`not in` membership guard is not an app enum
    if len(literals) < _MIN_CLUSTER_SIZE:
        return False
    if not all(_LOWER_TOKEN_RE.fullmatch(lit) for lit in literals):
        return False
    if all(lit in EXTERNAL_VOCAB for lit in literals):
        return False  # file modes, URL schemes, language keywords, HTTP methods
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
    _line, _col, _saw_eq, literals = entry
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


def _wire_bound_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    """Collect names in `func` bound from a subscript or `.get(...)` lookup.

    `schema_type = schema['type']` / `extra = cfg.get('behavior')` read a value
    off a dict-shaped wire format the module does not own; clusters on such
    names are external-vocabulary dispatch, not an app enum. Nested
    functions/classes own their scope and are not descended into.

    Returns:
        The set of such names.

    """
    names: set[str] = set()
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
        if isinstance(target, ast.Name) and value is not None and _is_wire_lookup(value):
            names.add(target.id)
        stack.extend(ast.iter_child_nodes(node))
    return frozenset(names)


def _is_wire_lookup(value: ast.expr) -> bool:
    """Report whether `value` is a subscript read or a `.get(...)` call (chained included).

    Returns:
        True for `x[...]` or `x.get(...)` shapes.

    """
    if isinstance(value, ast.Subscript):
        return True
    return isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "get"


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


def _is_scanner_key(key: str) -> bool:
    segment = key.rsplit(".", 1)[-1].lower()
    return segment in _SCANNER_KEY_SEGMENTS or "char" in segment


def _base_name(base: ast.AST) -> str | None:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None


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
    key, literals, is_equality = extracted
    _merge_cluster(clusters, key, literals, (node.lineno, node.col_offset + 1), is_equality=is_equality)


def _accumulate_match(clusters: dict[str, _ClusterEntry], node: ast.Match) -> None:
    key = _name_key(node.subject)
    if key is None:
        return
    literals: list[str] = []
    for case in node.cases:
        literals.extend(_match_pattern_literals(case.pattern))
    if not literals:
        return
    _merge_cluster(clusters, key, literals, (node.lineno, node.col_offset + 1), is_equality=True)


def _merge_cluster(
    clusters: dict[str, _ClusterEntry],
    key: str,
    literals: list[str],
    pos: tuple[int, int],
    *,
    is_equality: bool,
) -> None:
    entry = clusters.get(key)
    if entry is not None:
        line, col, saw_eq, seen = entry
        line, col = min((line, col), pos)
        clusters[key] = (line, col, saw_eq or is_equality, seen | set(literals))
    else:
        clusters[key] = (*pos, is_equality, set(literals))


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


def _extract_compare(node: ast.Compare) -> tuple[str, list[str], bool] | None:
    """Return (variable key, string literals, is_equality) for an enum-shaped compare.

    Handles `x == "a"`, `"a" == x` (yoda), `x != "a"`, and
    `x in ("a", "b")` / `x not in {...}` where every element is a string
    constant. The compared variable must be a plain *name* — subscripts (dict
    keys), calls, f-strings, and attribute chains (`url.scheme`, `field.mode`,
    reflection keys) are excluded: the module cannot turn a value it doesn't
    own into a StrEnum. `is_equality` is True only for `==` / `!=`; a bare
    membership test is not on its own strong enough to fire.

    Returns:
        The (key, literals, is_equality) triple, or None for a non-enum-shaped compare.

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
        return key, [value], True
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
        return key, values, False
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
