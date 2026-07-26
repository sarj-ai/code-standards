"""SARJ032: silent fall-through on closed-set dispatch — prefer `assert_never`.

Dispatch over a closed set of variants that quietly does nothing for "anything
else" is the highest-volume exhaustiveness bug in review feedback: a new variant
is added, no branch handles it, and the code silently no-ops instead of failing
loudly. `typing.assert_never` (or a `raise`) in the fallthrough turns the missed
variant into a pyright error / instant crash. The TS linter enforces the same
invariant via require-assert-never.

Two deterministic detectors, mirroring SARJ003's corroboration discipline (no
type inference is available, so each detector demands structural proof that the
dispatch is over a CLOSED set — corpus validation showed that without this
gate, matches over open-set data such as external API strings and free-form
payload shapes dominate and are deliberate fall-throughs, not bugs):

1. **Silent `case _:` in a closed-set `match`.** A `match` with at least two
   real, unguarded `case` arms that are all either

   * enum-member values of ONE owner class (`case Kind.A:` / `case Kind.A |
     Kind.B:`) — dotted members of a single class are a closed set someone
     owns. The owner name must be bound by a module-scope `class` statement in
     this file or by a `from x import Kind` binding: those are the shapes that
     name a class. Attribute access on a name bound by `import constants`
     (a module of loose constants) or on a plain variable (`cfg.A`) is NOT
     member access on a closed set and never qualifies, or
   * class patterns over classes **defined at module scope of this module**
     (`case Created():`) — the SARJ003 local-union gate. Classes defined
     inside some function elsewhere in the file are invisible here and do not
     make an unrelated match closed,

   whose final `case _:` (bare wildcard, no guard, no capture name) body is
   exactly `pass`, bare `return`, or `return None`. String/number literal
   cases, mapping/sequence patterns, and imported class patterns never qualify:
   they routinely match open-set data where ignoring the rest is the intended
   behavior. `case _: return False` and other value-returning defaults are also
   not flagged — a predicate's default answer is a legitimate result.

   One further corpus-validated exemption: when EVERY real arm's body is purely
   assignments (`x = ...` refinement), the match is the default-then-refine
   idiom — defaults are set before the match and the silent wildcard means
   "keep the defaults", which is defined behavior, not a swallowed variant. The
   detector fires only when at least one arm *does* something (a call, return,
   raise), because that is what a missed variant silently skips.

        # flagged
        match kind:
            case Kind.A: ...
            case Kind.B: ...
            case _:
                pass          # new Kind member silently ignored

        # preferred
            case _:
                assert_never(kind)

2. **`if/elif` chain over a local enum with a silent `else`.** Every arm
   compares the SAME variable via `==` (or `in` over a tuple/list/set) against
   members of the SAME class, that class is **defined at module scope of this
   module** with an `Enum`-family base (`Enum`, `StrEnum`, `IntEnum`, `Flag`,
   `IntFlag`, `ReprEnum`), and the terminal `else` is exactly `pass` / bare
   `return` / `return None`. For an imported name the rule cannot prove it is
   an enum (it could be a constants holder), so imported classes are never
   flagged. A chain whose head is NOT an enum comparison (e.g. a null-check
   first: `if x is None: ... elif x == Status.A: ...`) does not shield the
   enum sub-chain that starts at the first enum arm — that sub-chain is
   checked on its own. The default-then-refine exemption applies here exactly
   as in detector 1: when EVERY arm body is purely assignments, the silent
   `else` means "keep the pre-set defaults" and is not flagged.

        # flagged
        class Status(StrEnum):
            OPEN = "open"
            CLOSED = "closed"

        if status == Status.OPEN:
            ...
        elif status == Status.CLOSED:
            ...
        else:
            return None       # new Status member silently ignored

3. **Handler dict that does not cover the enum.** A `dict` literal whose keys
   are all members of ONE enum defined at module scope of this module, whose
   values all look like handlers (a name, an attribute, or a lambda — never a
   literal), and which names FEWER members than the enum declares. This is the
   lookup-table spelling of the same bug: `HANDLERS[kind]` raises `KeyError` on
   the missed member if you are lucky and `HANDLERS.get(kind)` silently returns
   `None` if you are not, and neither pyright nor a `match` statement is there
   to notice. The message names the shortfall so the missing members are
   obvious.

        # flagged — Kind has three members, the map has two
        class Kind(StrEnum):
            A = "a"
            B = "b"
            C = "c"

        HANDLERS = {Kind.A: handle_a, Kind.B: handle_b}

   Deliberately NOT flagged here: a map whose values are literals (that is a
   lookup table of data — a partial one is routinely intentional, e.g. "only
   these two members have a display colour"); a map that spreads `**other`
   (its real key set is not visible); a map whose name is later `.update(...)`d
   or assigned into by subscript anywhere in the file (it is built in pieces on
   purpose); and any map over an imported enum, since the rule cannot see how
   many members that enum has and guessing would invent findings.

A deliberate ignore-the-rest dispatch (e.g. classifying external ids where the
provider can add values at any time) is suppressed with
`# sarj-noqa: SARJ032 — <reason>`.

References:
- https://docs.python.org/3/library/typing.html#typing.assert_never
- https://typing.python.org/en/latest/spec/narrowing.html#assert-never-and-exhaustiveness-checking

"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none


if TYPE_CHECKING:
    from pathlib import Path


# A dispatch needs at least this many real (non-wildcard) arms to be flagged.
_MIN_ARMS = 2

_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag", "ReprEnum"})

# Methods that grow a dict in place — a map built in pieces is not incomplete.
_DICT_GROWING_METHODS = frozenset({"update", "setdefault"})


class PreferMatchAssertNever(Rule):
    """Silent fallthrough on closed-set dispatch — raise or `assert_never` instead."""

    id: str = "prefer-match-assert-never"
    code: str = "SARJ032"
    description: str = (
        "silent `case _:` / silent `else` on closed-set dispatch — a new variant "
        "no-ops instead of failing; use assert_never (or raise) in the fallthrough."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        module_classdefs = _module_scope_classdefs(tree)
        local_classes = frozenset(node.name for node in module_classdefs)
        local_enums = frozenset(
            node.name
            for node in module_classdefs
            if any(
                (isinstance(b, ast.Name) and b.id in _ENUM_BASES)
                or (isinstance(b, ast.Attribute) and b.attr in _ENUM_BASES)
                for b in node.bases
            )
        )
        member_owners = local_classes | _importfrom_bound_names(tree)
        enum_members = _enum_member_names(module_classdefs, local_enums)
        grown_maps = _grown_dict_names(tree)
        diags: list[Diagnostic] = []
        consumed_elifs: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Match):
                wildcard = _silent_closed_set_wildcard(node, local_classes, member_owners)
                if wildcard is not None:
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=wildcard.pattern.lineno,
                            col=wildcard.pattern.col_offset + 1,
                            code=self.code,
                            message=(
                                "silent `case _:` on a closed-set match — a new variant no-ops "
                                "instead of failing; use `assert_never(subject)` or raise."
                            ),
                        )
                    )
            elif isinstance(node, ast.If):
                if id(node) in consumed_elifs:
                    continue
                enum_name = _silent_enum_chain(node, local_enums, consumed_elifs)
                if enum_name is not None:
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=node.lineno,
                            col=node.col_offset + 1,
                            code=self.code,
                            message=(
                                f"if/elif over `{enum_name}` members with a silent `else` — a new "
                                "member no-ops instead of failing; use `assert_never` or raise "
                                "(ideally as a match/case)."
                            ),
                        )
                    )
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                shortfall = _incomplete_dispatch_map(node, enum_members, grown_maps)
                if shortfall is not None:
                    enum_name, covered, total, missing = shortfall
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=node.lineno,
                            col=node.col_offset + 1,
                            code=self.code,
                            message=(
                                f"dispatch map covers {covered} of `{enum_name}`'s {total} "
                                f"members (missing {missing}) — a new member falls through to "
                                "a KeyError or a silent None; cover every member and "
                                "`assert_never` (or raise) on a lookup miss."
                            ),
                        )
                    )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _module_scope_classdefs(tree: ast.Module) -> list[ast.ClassDef]:
    """Collect class definitions at module scope (including class-nested ones).

    Deliberately does NOT descend into function bodies: a class defined inside
    some unrelated function is not visible where a `match` elsewhere in the
    file dispatches, so it must not make that match look closed-set.

    Returns:
        The module-scope ClassDef nodes.

    """
    found: list[ast.ClassDef] = []
    stack: list[ast.stmt] = list(tree.body)
    while stack:
        stmt = stack.pop()
        if isinstance(stmt, ast.ClassDef):
            found.append(stmt)
            stack.extend(stmt.body)
    return found


def _enum_member_names(classdefs: list[ast.ClassDef], local_enums: frozenset[str]) -> dict[str, frozenset[str]]:
    """Map each module-scope enum's name to the member names it declares.

    A member is a plain `NAME = <value>` assignment in the class body. Methods,
    annotations without a value (`x: int`), and private/dunder names are not
    members. Members sharing one constant value are ALIASES of a single member
    (`AKA = "open"` beside `OPEN = "open"`), so they are counted once —
    over-counting members would invent a shortfall that does not exist.

    Returns:
        A mapping of enum class name to its member-name set.

    """
    members: dict[str, frozenset[str]] = {}
    for classdef in classdefs:
        if classdef.name not in local_enums:
            continue
        by_value: dict[str, str] = {}
        names: set[str] = set()
        for stmt in classdef.body:
            if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                continue
            target = stmt.targets[0]
            if not isinstance(target, ast.Name) or target.id.startswith("_"):
                continue
            if isinstance(stmt.value, ast.Constant):
                key = f"{type(stmt.value.value).__name__}:{stmt.value.value!r}"
                if key in by_value:
                    # An alias of an already-counted member.
                    continue
                by_value[key] = target.id
            names.add(target.id)
        members[classdef.name] = frozenset(names)
    return members


def _grown_dict_names(tree: ast.Module) -> frozenset[str]:
    """Collect names of dicts that are grown after their literal is written.

    `HANDLERS.update(...)`, `HANDLERS.setdefault(k, v)` and `HANDLERS[k] = v`
    all mean the literal is a starting point rather than the whole map, so its
    key count says nothing about coverage.

    Returns:
        The set of names that are extended somewhere in the module.

    """
    grown: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Call(func=ast.Attribute(value=ast.Name(id=name), attr=attr)) if attr in _DICT_GROWING_METHODS:
                grown.add(name)
            case ast.Assign(targets=targets):
                grown.update(
                    subscript.value.id
                    for subscript in targets
                    if isinstance(subscript, ast.Subscript) and isinstance(subscript.value, ast.Name)
                )
            case _:
                pass
    return frozenset(grown)


def _incomplete_dispatch_map(
    node: ast.Assign | ast.AnnAssign,
    enum_members: dict[str, frozenset[str]],
    grown_maps: frozenset[str],
) -> tuple[str, int, int, str] | None:
    """Return the shortfall when `node` binds a handler dict that misses enum members.

    Requires a single `Name` target, a `dict` literal value with no `**` spread,
    at least `_MIN_ARMS` keys that are ALL members of one module-scope enum, all
    values handler-shaped (name / attribute / lambda), and a name that is never
    grown elsewhere in the module.

    Returns:
        `(enum name, covered, total, missing members)`, or None when the
        assignment is not an incomplete dispatch map.

    """
    target = _single_name_target(node)
    if target is None or target in grown_maps or not isinstance(node.value, ast.Dict):
        return None
    mapping = node.value
    if any(key is None for key in mapping.keys):
        # `**other` — the real key set is not visible here.
        return None
    if len(mapping.keys) < _MIN_ARMS:
        return None
    if not all(_is_handler_value(value) for value in mapping.values):
        return None
    owners = {_member_owner(key) for key in mapping.keys}
    if len(owners) != 1:
        return None
    owner = next(iter(owners))
    if owner is None or owner not in enum_members:
        return None
    declared = enum_members[owner]
    covered = {key.attr for key in mapping.keys if isinstance(key, ast.Attribute) and key.attr in declared}
    if len(covered) != len(mapping.keys) or not covered < declared:
        return None
    missing = ", ".join(f"{owner}.{name}" for name in sorted(declared - covered))
    return owner, len(covered), len(declared), missing


def _single_name_target(node: ast.Assign | ast.AnnAssign) -> str | None:
    """Return the bound name when `node` assigns to exactly one plain name.

    Returns:
        The target name, or None for tuple/attribute/subscript targets.

    """
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    if len(targets) != 1:
        return None
    target = targets[0]
    return target.id if isinstance(target, ast.Name) else None


def _is_handler_value(value: ast.expr | None) -> bool:
    """Report whether a dict value looks like a handler rather than data.

    A literal value makes the dict a data table, where a partial mapping is
    routinely deliberate; a name, attribute or lambda makes it a dispatch table.

    Returns:
        True when the value is handler-shaped.

    """
    return isinstance(value, (ast.Name, ast.Attribute, ast.Lambda))


def _member_owner(key: ast.expr | None) -> str | None:
    """Return the class name in a `Owner.MEMBER` dict key.

    Returns:
        The owner name, or None when the key is not simple member access.

    """
    match key:
        case ast.Attribute(value=ast.Name(id=owner)):
            return owner
        case _:
            return None


def _importfrom_bound_names(tree: ast.Module) -> frozenset[str]:
    """Collect names bound by `from x import Name [as Alias]` statements.

    A `from`-imported name is the shape that binds a class directly, so
    `Kind.MEMBER` on such a name can be member access on a closed set. Names
    bound by plain `import module` are module objects — attribute access on
    them (`constants.CREATED`) reaches loose module-level constants, never an
    owned member set — so they are deliberately NOT collected.

    Returns:
        The set of from-import bound names.

    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
    return frozenset(names)


def _silent_closed_set_wildcard(
    node: ast.Match, local_classes: frozenset[str], member_owners: frozenset[str]
) -> ast.match_case | None:
    """Return the final `case _:` when it silently swallows a closed-set dispatch.

    Requires >= 2 real unguarded closed-set arms before it, a bare unguarded
    uncaptured wildcard, and a wildcard body that is exactly `pass` / bare
    `return` / `return None`.

    Returns:
        The offending wildcard case, or None when the match does not qualify.

    """
    if len(node.cases) < _MIN_ARMS + 1:
        return None
    last = node.cases[-1]
    pattern = last.pattern
    if not (isinstance(pattern, ast.MatchAs) and pattern.pattern is None and pattern.name is None):
        return None
    if last.guard is not None or not _is_silent_body(last.body):
        return None
    real_arms = node.cases[:-1]
    if any(case.guard is not None for case in real_arms):
        # A guarded arm deliberately lets its own pattern fall through.
        return None
    if all(_is_assignment_only(case.body) for case in real_arms):
        # Default-then-refine: the wildcard keeps pre-set defaults, by design.
        return None
    all_local_class_arms = bool(local_classes) and all(
        _is_local_class_pattern(case.pattern, local_classes) for case in real_arms
    )
    if _all_one_owner_member_arms(real_arms, member_owners) or all_local_class_arms:
        return last
    return None


def _is_assignment_only(body: list[ast.stmt]) -> bool:
    return all(isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)) for stmt in body)


def _is_silent_body(body: list[ast.stmt]) -> bool:
    """Report whether `body` is exactly one None-shaped no-op statement.

    Only `pass`, bare `return`, and `return None` qualify. A value-returning
    default (`return False`, `return ""`) is a legitimate answer, and any other
    statement (log call, raise, assignment) is deliberate handling.

    Returns:
        True when the body silently produces nothing.

    """
    if len(body) != 1:
        return False
    match body[0]:
        case ast.Pass():
            return True
        case ast.Return(value=None):
            return True
        case ast.Return(value=ast.Constant(value=None)):
            return True
        case _:
            return False


def _all_one_owner_member_arms(cases: list[ast.match_case], member_owners: frozenset[str]) -> bool:
    """Report whether every arm matches enum-member values of one owner class.

    The owner must be a name that can actually bind a class here: defined by a
    module-scope `class` statement or bound by `from x import Cls`. A plain
    variable or a name bound by `import constants` (a module object) never
    counts.

    Returns:
        True when all arms are `Cls.MEMBER`-style values of a single `Cls`.

    """
    owners = {_member_pattern_owner(case.pattern) for case in cases}
    if len(owners) != 1 or None in owners:
        return False
    (owner,) = owners
    return owner in member_owners


def _member_pattern_owner(pattern: ast.pattern) -> str | None:
    """Resolve the owner class of a `Cls.MEMBER` value pattern (or an or-pattern of them).

    Returns:
        The owner class name, or None when the pattern is not member-shaped.

    """
    match pattern:
        case ast.MatchValue(value=ast.Attribute(value=ast.Name(id=owner))):
            return owner
        case ast.MatchOr(patterns=subpatterns):
            owners = {_member_pattern_owner(sub) for sub in subpatterns}
            if len(owners) == 1 and None not in owners:
                return owners.pop()
            return None
        case _:
            return None


def _is_local_class_pattern(pattern: ast.pattern, local_classes: frozenset[str]) -> bool:
    match pattern:
        case ast.MatchClass(cls=ast.Name(id=name)):
            return name in local_classes
        case ast.MatchAs(pattern=ast.pattern() as inner):
            return _is_local_class_pattern(inner, local_classes)
        case ast.MatchOr(patterns=subpatterns):
            return all(_is_local_class_pattern(sub, local_classes) for sub in subpatterns)
        case _:
            return False


def _silent_enum_chain(head: ast.If, local_enums: frozenset[str], consumed_elifs: set[int]) -> str | None:
    """Parse `head` as an ==/in chain over one local enum with a silent `else`.

    Each nested `elif` that genuinely continues the chain (same target, same
    enum) is recorded in `consumed_elifs` so the caller does not re-check it as
    a chain head of its own. An `elif` that does NOT continue the chain (or any
    `elif` behind a non-matching head) is deliberately left unconsumed: the
    sub-chain starting there is a dispatch in its own right and gets its own
    check — a null-check head must not shield the enum chain behind it.

    Returns:
        The enum class name when the chain qualifies, else None.

    """
    if not local_enums:
        return None
    first_target: ast.expr | None = None
    enum_name: str | None = None
    arm_bodies: list[list[ast.stmt]] = []
    current = head
    while True:
        parsed = _enum_comparison(current.test, local_enums)
        if parsed is None:
            return None
        target, cls_name = parsed
        if first_target is None:
            first_target = target
            enum_name = cls_name
        elif ast.dump(target) != ast.dump(first_target) or cls_name != enum_name:
            return None
        if current is not head:
            consumed_elifs.add(id(current))
        arm_bodies.append(current.body)
        orelse = current.orelse
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            current = orelse[0]
            continue
        if len(arm_bodies) < _MIN_ARMS or not orelse or not _is_silent_body(orelse):
            return None
        if all(_is_assignment_only(body) for body in arm_bodies):
            # Default-then-refine: the silent else keeps pre-set defaults, by design.
            return None
        return enum_name


def _enum_comparison(test: ast.expr, local_enums: frozenset[str]) -> tuple[ast.expr, str] | None:
    """Parse `test` as `x == Cls.MEMBER` or `x in (Cls.A, Cls.B, ...)`.

    Every compared value must be a member attribute of the SAME local enum class.

    Returns:
        The (target, class_name) pair, or None when `test` is not such a comparison.

    """
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1):
        return None
    target = test.left
    comparator = test.comparators[0]
    match test.ops[0]:
        case ast.Eq():
            cls_name = _enum_member_class(comparator, local_enums)
        case ast.In():
            cls_name = _enum_member_container_class(comparator, local_enums)
        case _:
            return None
    if cls_name is None:
        return None
    return target, cls_name


def _enum_member_class(expr: ast.expr, local_enums: frozenset[str]) -> str | None:
    match expr:
        case ast.Attribute(value=ast.Name(id=cls_name)) if cls_name in local_enums:
            return cls_name
        case _:
            return None


def _enum_member_container_class(expr: ast.expr, local_enums: frozenset[str]) -> str | None:
    if not isinstance(expr, (ast.Tuple, ast.List, ast.Set)) or not expr.elts:
        return None
    names = {_enum_member_class(elt, local_enums) for elt in expr.elts}
    if len(names) != 1:
        return None
    return names.pop()
