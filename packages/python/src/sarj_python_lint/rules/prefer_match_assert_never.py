"""SARJ032 — Silent fall-through on closed-set dispatch — prefer `assert_never`.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_match_assert_never.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes


if TYPE_CHECKING:
    from pathlib import Path


# A dispatch needs at least this many real (non-wildcard) arms to be flagged.
_MIN_ARMS = 2

_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag", "ReprEnum"})

# Methods that grow a dict in place — a map built in pieces is not incomplete.
_DICT_GROWING_METHODS = frozenset({"update", "setdefault"})


@final
class PreferMatchAssertNever(Rule):
    id: str = "prefer-match-assert-never"
    code: str = "SARJ032"
    documentation = RuleDocumentation(
        summary="Closed-set dispatch should fail explicitly when a variant is unhandled.",
        rationale="A silent wildcard, `else`, or incomplete dispatch map lets newly added variants pass unnoticed.",
        remediation="Handle every variant and use `assert_never` or an explicit exception for the unreachable fallthrough.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule recognizes closed sets from local classes, enums, imported member owners, and static handler maps.",
            "Guarded matches, dynamically grown maps, and open-ended value domains are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="silent-closed-set-wildcard",
                title="Closed-set match silently ignores a variant",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "dispatch.py",
                        "from kinds import Kind\n\ndef handle(kind):\n    match kind:\n        case Kind.A:\n            handle_a()\n        case Kind.B:\n            handle_b()\n        case _:\n            pass\n",
                    ),
                ),
                focus_path=PurePosixPath("dispatch.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-closed-set-failure",
                title="Closed-set match rejects an unhandled variant",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "dispatch.py",
                        "from kinds import Kind\n\ndef handle(kind):\n    match kind:\n        case Kind.A:\n            handle_a()\n        case Kind.B:\n            handle_b()\n        case _:\n            raise AssertionError(kind)\n",
                    ),
                ),
                focus_path=PurePosixPath("dispatch.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

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
        for node in nodes(tree, ast.Match, ast.If, ast.Assign, ast.AnnAssign):
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
            else:
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
    """Collect class definitions at module scope (including class-nested ones)."""
    found: list[ast.ClassDef] = []
    stack: list[ast.stmt] = list(tree.body)
    while stack:
        stmt = stack.pop()
        if isinstance(stmt, ast.ClassDef):
            found.append(stmt)
            stack.extend(stmt.body)
    return found


def _enum_member_names(classdefs: list[ast.ClassDef], local_enums: frozenset[str]) -> dict[str, frozenset[str]]:
    """Map each module-scope enum's name to the member names it declares."""
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
    """Collect names of dicts that are grown after their literal is written."""
    grown: set[str] = set()
    for node in nodes(tree, ast.Call, ast.Assign):
        match node:
            case ast.Call(func=ast.Attribute(value=ast.Name(id=name), attr=attr)) if attr in _DICT_GROWING_METHODS:
                grown.add(name)
            case ast.Assign(targets=targets):
                grown.update(
                    val.id
                    for subscript in targets
                    if isinstance(subscript, ast.Subscript) and isinstance(val := subscript.value, ast.Name)
                )
            case _:
                pass
    return frozenset(grown)


def _incomplete_dispatch_map(
    node: ast.Assign | ast.AnnAssign,
    enum_members: dict[str, frozenset[str]],
    grown_maps: frozenset[str],
) -> tuple[str, int, int, str] | None:
    """Return the shortfall when `node` binds a handler dict that misses enum members."""
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
    covered = {attr for key in mapping.keys if isinstance(key, ast.Attribute) and (attr := key.attr) in declared}
    if len(covered) != len(mapping.keys) or not covered < declared:
        return None
    missing = ", ".join(f"{owner}.{name}" for name in sorted(declared - covered))
    return owner, len(covered), len(declared), missing


def _single_name_target(node: ast.Assign | ast.AnnAssign) -> str | None:
    """Return the bound name when `node` assigns to exactly one plain name."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    if len(targets) != 1:
        return None
    target = targets[0]
    return target.id if isinstance(target, ast.Name) else None


def _is_handler_value(value: ast.expr | None) -> bool:
    """Report whether a dict value looks like a handler rather than data."""
    return isinstance(value, (ast.Name, ast.Attribute, ast.Lambda))


def _member_owner(key: ast.expr | None) -> str | None:
    """Return the class name in a `Owner.MEMBER` dict key."""
    match key:
        case ast.Attribute(value=ast.Name(id=owner)):
            return owner
        case _:
            return None


def _importfrom_bound_names(tree: ast.Module) -> frozenset[str]:
    """Collect names bound by `from x import Name [as Alias]` statements."""
    return frozenset(
        alias.asname or alias.name for node in nodes(tree, ast.ImportFrom) for alias in node.names if alias.name != "*"
    )


def _silent_closed_set_wildcard(
    node: ast.Match, local_classes: frozenset[str], member_owners: frozenset[str]
) -> ast.match_case | None:
    """Return the final `case _:` when it silently swallows a closed-set dispatch."""
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
    """Report whether `body` is exactly one None-shaped no-op statement."""
    if len(body) != 1:
        return False
    match body[0]:
        case ast.Pass() | ast.Return(value=None) | ast.Return(value=ast.Constant(value=None)):
            return True
        case _:
            return False


def _all_one_owner_member_arms(cases: list[ast.match_case], member_owners: frozenset[str]) -> bool:
    """Report whether every arm matches enum-member values of one owner class."""
    owners = {_member_pattern_owner(case.pattern) for case in cases}
    if len(owners) != 1 or None in owners:
        return False
    (owner,) = owners
    return owner in member_owners


def _member_pattern_owner(pattern: ast.pattern) -> str | None:
    """Resolve the owner class of a `Cls.MEMBER` value pattern (or an or-pattern of them)."""
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
    """Parse `head` as an ==/in chain over one local enum with a silent `else`."""
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
    """Parse `test` as `x == Cls.MEMBER` or `x in (Cls.A, Cls.B, ...)`."""
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
