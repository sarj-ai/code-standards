from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_isinstance_union_chain import NoIsinstanceUnionChain


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


# Kept in sync with `_EXCLUDED_TYPE_NAMES` in the rule module. Copied rather than
# imported so the test exercises the rule's public surface only.
EXCLUDED_TYPE_NAMES = (
    "bool",
    "bytearray",
    "bytes",
    "complex",
    "dict",
    "float",
    "frozenset",
    "int",
    "list",
    "object",
    "set",
    "str",
    "tuple",
    "type",
    "BaseException",
    "Exception",
    "NoneType",
    "Unset",
    "date",
    "datetime",
    "time",
    "timedelta",
    "Callable",
    "Collection",
    "Container",
    "Hashable",
    "Iterable",
    "Iterator",
    "Mapping",
    "MutableMapping",
    "MutableSequence",
    "Sequence",
    "Set",
)


def _check(source: str) -> list[Diagnostic]:
    return NoIsinstanceUnionChain().check(Path("<t>.py"), source)


def _classdefs(*names: str) -> str:
    return "\n".join(f"class {n}: ..." for n in dict.fromkeys(names))


def _chain(
    target: str,
    *type_names: str,
    terminal: str = "raise ValueError()",
) -> str:
    """Render a local-closed-union dispatch over `target`.

    Emits the class defs, then an if/elif isinstance chain over `target` with an
    exhaustive terminal `else`.

    Returns:
        The rendered dispatch source.

    """
    lines: list[str] = [_classdefs(*type_names), "", "def handle(subject, other):"]
    for i, name in enumerate(type_names):
        kw = "if" if i == 0 else "elif"
        lines.extend(
            [
                f"    {kw} isinstance({target}, {name}):",
                f"        branch_{i}()",
            ]
        )
    lines.extend(["    else:", f"        {terminal}"])
    return "\n".join(lines) + "\n"


def _two_arm(
    test0: str,
    test1: str,
    *,
    terminal: str = "raise ValueError()",
    classes: tuple[str, ...] = ("Foo", "Bar", "Baz"),
) -> str:
    """Render a two-arm dispatch with local classes and an exhaustive terminal.

    For target-equality adversarial cases where `test0`/`test1` carry the
    interesting target expressions.

    Returns:
        The rendered dispatch source.

    """
    return (
        f"{_classdefs(*classes)}\n"
        "def handle(o, a, b):\n"
        f"    if {test0}:\n        x()\n"
        f"    elif {test1}:\n        y()\n"
        f"    else:\n        {terminal}\n"
    )


# --------------------------------------------------------------------------- #
# Positive: chains that SHOULD be flagged                                      #
# --------------------------------------------------------------------------- #


def test_flags_two_branch_chain_over_local_classes():
    src = """
class ApiKeySubject: ...
class JwtSubject: ...

def handle(subject):
    if isinstance(subject, ApiKeySubject):
        a()
    elif isinstance(subject, JwtSubject):
        b()
    else:
        raise ValueError()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ003"
    assert "2 local classes" in diags[0].message


def test_flags_three_branch_chain_with_assert_never_terminal():
    src = """
class DraftScenario: ...
class PublishedScenario: ...
class ArchivedScenario: ...

def handle(node):
    if isinstance(node, DraftScenario):
        a()
    elif isinstance(node, PublishedScenario):
        b()
    elif isinstance(node, ArchivedScenario):
        c()
    else:
        assert_never(node)
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "3 local classes" in diags[0].message


def test_flags_chain_terminated_by_typing_assert_never_attribute():
    src = """
import typing
class Foo: ...
class Bar: ...

def handle(x):
    if isinstance(x, Foo):
        a()
    elif isinstance(x, Bar):
        b()
    else:
        typing.assert_never(x)
"""
    assert len(_check(src)) == 1


def test_flags_chain_terminated_by_return():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if isinstance(x, Foo):
        return a()
    elif isinstance(x, Bar):
        return b()
    else:
        return None
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize("branches", [2, 3, 4, 5, 6, 8])
def test_flags_chains_of_every_length_and_reports_count(branches: int):
    type_names = tuple(f"Variant{i}" for i in range(branches))
    diags = _check(_chain("subject", *type_names))
    assert len(diags) == 1
    assert f"{branches} local classes" in diags[0].message


def test_flags_chain_on_attribute_target():
    src = """
class TextBody: ...
class BinaryBody: ...

def handle(msg):
    if isinstance(msg.payload, TextBody):
        a()
    elif isinstance(msg.payload, BinaryBody):
        b()
    else:
        raise ValueError()
"""
    assert len(_check(src)) == 1


def test_flags_chain_on_subscript_target():
    src = """
class Foo: ...
class Bar: ...

def handle(items):
    if isinstance(items[0], Foo):
        a()
    elif isinstance(items[0], Bar):
        b()
    else:
        raise ValueError()
"""
    assert len(_check(src)) == 1


def test_flags_chain_on_call_target_with_identical_dump():
    src = """
class Foo: ...
class Bar: ...

def handle():
    if isinstance(get(), Foo):
        a()
    elif isinstance(get(), Bar):
        b()
    else:
        raise ValueError()
"""
    assert len(_check(src)) == 1


def test_flags_chain_with_parenthesized_tests():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if (isinstance(x, Foo)):
        a()
    elif (isinstance(x, Bar)):
        b()
    else:
        raise ValueError()
"""
    assert len(_check(src)) == 1


def test_flags_chain_written_as_else_nested_if():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if isinstance(x, Foo):
        a()
    else:
        if isinstance(x, Bar):
            b()
        else:
            raise ValueError()
"""
    assert len(_check(src)) == 1


def test_flags_chain_with_bodies_that_reassign_target():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if isinstance(x, Foo):
        x = adapt(x)
    elif isinstance(x, Bar):
        x = adapt(x)
    else:
        raise ValueError()
"""
    assert len(_check(src)) == 1


def test_flags_chain_over_locally_nested_classes():
    src = """
def make():
    class Foo: ...
    class Bar: ...

def handle(x):
    if isinstance(x, Foo):
        a()
    elif isinstance(x, Bar):
        b()
    else:
        raise ValueError()
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Multiple independent chains: count + ordering                               #
# --------------------------------------------------------------------------- #


def test_two_sibling_chains_each_flagged():
    src = """
class Foo: ...
class Bar: ...
class Baz: ...
class Qux: ...

def handle(a, b):
    if isinstance(b, Foo):
        x()
    elif isinstance(b, Bar):
        y()
    else:
        raise ValueError()
    if isinstance(a, Baz):
        x()
    elif isinstance(a, Qux):
        y()
    else:
        raise ValueError()
"""
    diags = _check(src)
    assert len(diags) == 2


def test_sibling_chains_reported_in_source_order():
    src = """
class Foo: ...
class Bar: ...
class Baz: ...
class Qux: ...

def handle(a, b):
    if isinstance(b, Foo):
        x()
    elif isinstance(b, Bar):
        y()
    else:
        raise ValueError()
    if isinstance(a, Baz):
        x()
    elif isinstance(a, Qux):
        y()
    else:
        raise ValueError()
"""
    lines = [d.line for d in _check(src)]
    assert lines == sorted(lines)


def test_nested_chain_inside_branch_body_also_flagged():
    src = """
class Outer1: ...
class Outer2: ...
class Inner1: ...
class Inner2: ...

def handle(x, y):
    if isinstance(x, Outer1):
        if isinstance(y, Inner1):
            a()
        elif isinstance(y, Inner2):
            b()
        else:
            raise ValueError()
    elif isinstance(x, Outer2):
        c()
    else:
        raise ValueError()
"""
    diags = _check(src)
    assert len(diags) == 2


def test_chain_reported_once_at_head_not_per_arm():
    diags = _check(_chain("subject", "A", "B", "C", "D"))
    assert len(diags) == 1


# --------------------------------------------------------------------------- #
# Line / column precision                                                      #
# --------------------------------------------------------------------------- #


def test_line_and_col_at_module_level():
    src = (
        "if isinstance(x, Foo):\n    a()\n"
        "elif isinstance(x, Bar):\n    b()\n"
        "else:\n    raise ValueError()\n"
        "class Foo: ...\nclass Bar: ...\n"
    )
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 1
    assert diags[0].col == 1


def test_line_and_col_for_indented_chain():
    src = """
def handle(x):
    if isinstance(x, Foo):
        a()
    elif isinstance(x, Bar):
        b()
    else:
        raise ValueError()
class Foo: ...
class Bar: ...
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3
    assert diags[0].col == 5


def test_col_tracks_deeper_nesting():
    src = """
class C:
    def handle(self, x):
        if isinstance(x, Foo):
            a()
        elif isinstance(x, Bar):
            b()
        else:
            raise ValueError()
class Foo: ...
class Bar: ...
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 4
    assert diags[0].col == 9


# --------------------------------------------------------------------------- #
# Negative: the local-union gate — non-local / open-set type probes            #
# --------------------------------------------------------------------------- #


def test_property_cached_property_probe_not_flagged():
    # pydantic/fields.py-shaped false positive: both are stdlib open-set types the module
    # does not own, so this is a runtime probe, not a closed local-union dispatch.
    src = """
from functools import cached_property

def resolve(property_):
    if isinstance(property_, property):
        a()
    elif isinstance(property_, cached_property):
        b()
    else:
        raise ValueError()
"""
    assert _check(src) == []


def test_dotted_dataclasses_field_probe_not_flagged():
    src = """
import dataclasses

def resolve(f):
    if isinstance(f, dataclasses.Field):
        a()
    elif isinstance(f, Other):
        b()
    else:
        raise ValueError()
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "type_name",
    ["Path", "Decimal", "UUID", "Enum", "IntEnum", "partial", "PathLike", "IOBase"],
)
def test_common_stdlib_probe_not_flagged(type_name: str):
    src = f"""
class LocalVariant: ...

def resolve(x):
    if isinstance(x, LocalVariant):
        a()
    elif isinstance(x, {type_name}):
        b()
    else:
        raise ValueError()
"""
    assert _check(src) == []


def test_imported_class_not_defined_locally_not_flagged():
    src = """
from other.module import ApiKeySubject, JwtSubject

def handle(subject):
    if isinstance(subject, ApiKeySubject):
        a()
    elif isinstance(subject, JwtSubject):
        b()
    else:
        raise ValueError()
"""
    assert _check(src) == []


def test_dotted_class_refs_not_flagged():
    src = """
def handle(evt):
    if isinstance(evt, events.Created):
        a()
    elif isinstance(evt, events.Deleted):
        b()
    else:
        raise ValueError()
"""
    assert _check(src) == []


def test_mixed_local_and_dotted_not_flagged():
    src = """
class Foo: ...
class Baz: ...

def handle(x):
    if isinstance(x, Foo):
        a()
    elif isinstance(x, pkg.mod.Bar):
        b()
    elif isinstance(x, Baz):
        c()
    else:
        raise ValueError()
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: the exhaustiveness gate — open chains / permissive fall-through     #
# --------------------------------------------------------------------------- #


def test_open_chain_without_else_not_flagged():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if isinstance(x, Foo):
        a()
    elif isinstance(x, Bar):
        b()
"""
    assert _check(src) == []


def test_permissive_else_that_falls_through_not_flagged():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if isinstance(x, Foo):
        a()
    elif isinstance(x, Bar):
        b()
    else:
        log_unknown(x)
"""
    assert _check(src) == []


def test_single_arm_with_terminal_else_not_flagged():
    src = """
class CustomScenario: ...

def handle(x):
    if isinstance(x, CustomScenario):
        a()
    else:
        raise ValueError()
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: excluded builtin / stdlib / sentinel names (belt-and-suspenders)   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("excluded", sorted(EXCLUDED_TYPE_NAMES))
def test_excluded_type_in_second_arm_suppresses_chain(excluded: str):
    src = _chain("x", "LocalVariant", excluded)
    assert _check(src) == []


@pytest.mark.parametrize("excluded", sorted(EXCLUDED_TYPE_NAMES))
def test_excluded_type_in_first_arm_suppresses_chain(excluded: str):
    src = _chain("x", excluded, "LocalVariant")
    assert _check(src) == []


def test_excluded_type_in_middle_arm_suppresses_whole_chain():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if isinstance(x, Foo):
        a()
    elif isinstance(x, str):
        b()
    elif isinstance(x, Bar):
        c()
    else:
        raise ValueError()
"""
    assert _check(src) == []


def test_local_class_colliding_with_excluded_name_suppresses_chain():
    # A local domain class named like an ABC (`Sequence`) is treated as excluded, so this
    # real 2-type dispatch is intentionally not flagged (belt-and-suspenders denylist).
    assert _check(_chain("x", "Node", "Sequence")) == []


# --------------------------------------------------------------------------- #
# Negative: not a closed-union dispatch chain                                  #
# --------------------------------------------------------------------------- #


def test_allows_tuple_membership_check():
    src = """
class ApiKeySubject: ...
class JwtSubject: ...

def handle(x):
    if isinstance(x, (ApiKeySubject, JwtSubject)):
        a()
    else:
        b()
"""
    assert _check(src) == []


def test_allows_tuple_membership_arm_inside_chain():
    src = """
class Foo: ...
class Bar: ...
class Baz: ...

def handle(x):
    if isinstance(x, (Foo, Bar)):
        a()
    elif isinstance(x, Baz):
        b()
    else:
        raise ValueError()
"""
    assert _check(src) == []


def test_allows_chain_on_different_name_targets():
    src = _two_arm("isinstance(x, Foo)", "isinstance(y, Bar)")
    assert _check(src) == []


def test_allows_chain_on_different_attribute_targets():
    src = _two_arm("isinstance(o.a, Foo)", "isinstance(o.b, Bar)")
    assert _check(src) == []


def test_allows_chain_on_different_subscript_indices():
    src = _two_arm("isinstance(o[0], Foo)", "isinstance(o[1], Bar)")
    assert _check(src) == []


def test_allows_isinstance_joined_by_and():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if isinstance(x, Foo) and isinstance(x, Bar):
        a()
    else:
        raise ValueError()
"""
    assert _check(src) == []


def test_allows_isinstance_joined_by_or_within_one_test():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if isinstance(x, Foo) or isinstance(x, Bar):
        a()
    else:
        raise ValueError()
"""
    assert _check(src) == []


def test_allows_isinstance_combined_with_boolean_attr():
    src = _two_arm("isinstance(x, Foo) and x.ready", "isinstance(x, Bar)")
    assert _check(src) == []


def test_allows_negated_isinstance_chain():
    src = _two_arm("not isinstance(x, Foo)", "not isinstance(x, Bar)")
    assert _check(src) == []


def test_allows_mixed_isinstance_and_hasattr_guard():
    src = """
class Foo: ...

def handle(first_mapping):
    if hasattr(first_mapping, "scenario_id"):
        a()
    elif isinstance(first_mapping, Foo):
        b()
    else:
        raise ValueError()
"""
    assert _check(src) == []


def test_allows_isinstance_mixed_with_comparison():
    src = _two_arm("isinstance(x, Foo)", "x == SENTINEL")
    assert _check(src) == []


def test_allows_isinstance_with_keyword_arguments():
    src = _two_arm("isinstance(x, Foo)", "isinstance(obj=x, class_or_tuple=Bar)")
    assert _check(src) == []


def test_allows_three_argument_pseudo_isinstance():
    src = _two_arm("isinstance(x, Foo, extra)", "isinstance(x, Bar)")
    assert _check(src) == []


def test_allows_attribute_call_named_isinstance():
    src = _two_arm("obj.isinstance(x, Foo)", "obj.isinstance(x, Bar)")
    assert _check(src) == []


def test_allows_already_using_match():
    src = """
from typing import assert_never

class ApiKeySubject: ...
class JwtSubject: ...

def handle(subject):
    match subject:
        case ApiKeySubject():
            a()
        case JwtSubject():
            b()
        case _:
            assert_never(subject)
"""
    assert _check(src) == []


def test_broken_chain_reset_by_non_isinstance_middle_not_flagged():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if isinstance(x, Foo):
        a()
    elif x is None:
        b()
    elif isinstance(x, Bar):
        c()
    else:
        raise ValueError()
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Edge cases: comprehensions, lambdas, empty, syntax errors                    #
# --------------------------------------------------------------------------- #


def test_empty_source_returns_empty():
    assert _check("") == []


def test_whitespace_only_source_returns_empty():
    assert _check("\n   \n\t\n") == []


def test_syntax_error_returns_empty():
    assert _check("def broken(:\n") == []


def test_syntax_error_amid_valid_chain_returns_empty():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if isinstance(x, Foo):
        a()
    elif isinstance(x, Bar):
        b(
"""
    assert _check(src) == []


def test_isinstance_in_comprehension_not_flagged():
    src = "result = [y for y in xs if isinstance(y, Foo) or isinstance(y, Bar)]\n"
    assert _check(src) == []


def test_isinstance_in_lambda_not_flagged():
    src = "pred = lambda x: isinstance(x, Foo) or isinstance(x, Bar)\n"
    assert _check(src) == []


def test_ternary_isinstance_not_flagged():
    src = "value = a() if isinstance(x, Foo) else b()\n"
    assert _check(src) == []


def test_nested_boolean_ops_in_single_test_not_flagged():
    src = _two_arm("(isinstance(x, Foo) or isinstance(x, Bar)) and x.ready", "isinstance(x, Baz)")
    assert _check(src) == []


def test_two_branch_chain_is_the_minimum_flagged():
    two = _chain("subject", "A", "B")
    one = _chain("subject", "A")
    assert len(_check(two)) == 1
    assert _check(one) == []


# --------------------------------------------------------------------------- #
# Diagnostic metadata                                                          #
# --------------------------------------------------------------------------- #


def test_diagnostic_carries_path_and_code():
    src = _chain("subject", "A", "B")
    diags = NoIsinstanceUnionChain().check(Path("svc/dispatch.py"), src)
    assert len(diags) == 1
    assert diags[0].path == Path("svc/dispatch.py")
    assert diags[0].code == "SARJ003"


def test_check_does_not_honor_inline_suppression_comment():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if isinstance(x, Foo):  # sarj-noqa: SARJ003 — boundary
        a()
    elif isinstance(x, Bar):
        b()
    else:
        raise ValueError()
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Adversarial: `_ast_equal` must match `ast.dump` EXACTLY — equal targets      #
# (structurally identical -> same target -> chain IS flagged)                  #
# --------------------------------------------------------------------------- #


def test_deep_attribute_target_equal_flagged():
    src = _two_arm("isinstance(o.a.b.c, Foo)", "isinstance(o.a.b.c, Bar)")
    assert len(_check(src)) == 1


def test_subscript_hex_and_decimal_index_are_equal_value_flagged():
    src = _two_arm("isinstance(o[0x1], Foo)", "isinstance(o[1], Bar)")
    assert len(_check(src)) == 1


def test_subscript_string_quote_styles_equal_flagged():
    src = _two_arm('isinstance(o["k"], Foo)', "isinstance(o['k'], Bar)")
    assert len(_check(src)) == 1


def test_negative_index_target_equal_flagged():
    src = _two_arm("isinstance(o[-1], Foo)", "isinstance(o[-1], Bar)")
    assert len(_check(src)) == 1


def test_call_target_with_identical_args_and_kwargs_flagged():
    src = _two_arm("isinstance(get(1, k=2), Foo)", "isinstance(get(1, k=2), Bar)")
    assert len(_check(src)) == 1


def test_walrus_target_equal_flagged():
    src = _two_arm("isinstance((y := f()), Foo)", "isinstance((y := f()), Bar)")
    assert len(_check(src)) == 1


def test_boolop_target_equal_flagged():
    src = _two_arm("isinstance(a and b, Foo)", "isinstance(a and b, Bar)")
    assert len(_check(src)) == 1


def test_fstring_target_equal_flagged():
    src = _two_arm("isinstance(f'{a}', Foo)", "isinstance(f'{a}', Bar)")
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Adversarial: `_ast_equal` must match `ast.dump` EXACTLY — distinct targets   #
# (equal-repr-but-different / different-value -> NOT the same target -> no flag)#
# --------------------------------------------------------------------------- #


def test_subscript_int_vs_float_index_not_flagged():
    src = _two_arm("isinstance(o[1], Foo)", "isinstance(o[1.0], Bar)")
    assert _check(src) == []


def test_subscript_int_vs_bool_index_not_flagged():
    src = _two_arm("isinstance(o[1], Foo)", "isinstance(o[True], Bar)")
    assert _check(src) == []


def test_subscript_str_vs_bytes_index_not_flagged():
    src = _two_arm('isinstance(o["a"], Foo)', 'isinstance(o[b"a"], Bar)')
    assert _check(src) == []


def test_negative_vs_positive_constant_index_not_flagged():
    src = _two_arm("isinstance(o[-1], Foo)", "isinstance(o[1], Bar)")
    assert _check(src) == []


def test_unary_minus_vs_unary_plus_index_not_flagged():
    src = _two_arm("isinstance(o[-1], Foo)", "isinstance(o[+1], Bar)")
    assert _check(src) == []


def test_walrus_different_binding_name_not_flagged():
    src = _two_arm("isinstance((y := f()), Foo)", "isinstance((z := f()), Bar)")
    assert _check(src) == []


def test_call_target_different_keyword_value_not_flagged():
    src = _two_arm("isinstance(get(k=1), Foo)", "isinstance(get(k=2), Bar)")
    assert _check(src) == []


def test_boolop_different_operator_not_flagged():
    src = _two_arm("isinstance(a and b, Foo)", "isinstance(a or b, Bar)")
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Adversarial: heuristic boundaries — match/case, elif resets                  #
# --------------------------------------------------------------------------- #


def test_two_valid_arms_before_non_isinstance_reset_not_flagged():
    src = """
class Foo: ...
class Bar: ...
class Baz: ...

def handle(x):
    if isinstance(x, Foo):
        a()
    elif isinstance(x, Bar):
        b()
    elif x is None:
        c()
    elif isinstance(x, Baz):
        d()
    else:
        raise ValueError()
"""
    assert _check(src) == []


def test_none_guard_head_before_isinstance_dispatch_not_flagged():
    src = """
class Foo: ...
class Bar: ...

def handle(x):
    if x is None:
        a()
    elif isinstance(x, Foo):
        b()
    elif isinstance(x, Bar):
        c()
    else:
        raise ValueError()
"""
    assert _check(src) == []


def test_match_with_class_patterns_and_guard_not_flagged():
    src = """
class ApiKeySubject: ...
class JwtSubject: ...

def handle(subject):
    match subject:
        case ApiKeySubject() if subject.active:
            a()
        case JwtSubject():
            b()
        case _:
            c()
"""
    assert _check(src) == []


def test_nested_boolop_walrus_mixed_guard_not_flagged():
    src = _two_arm("isinstance(x, Foo) and (y := x.v)", "isinstance(x, Bar)")
    assert _check(src) == []
