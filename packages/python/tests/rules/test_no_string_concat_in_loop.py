from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_string_concat_in_loop import NoStringConcatInLoop


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "<t>.py") -> list[Diagnostic]:
    return NoStringConcatInLoop().check(Path(path), source)


def _count(source: str) -> int:
    return len(_check(source))


_PUBLIC_EXAMPLES = NoStringConcatInLoop.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoStringConcatInLoop().check(Path(focus.path), focus.source)) == example.expected_count


def test_reports_one_diagnostic_per_accumulator_per_loop() -> None:
    source = """
def render(items):
    output = ""
    for item in items:
        output += "<li>"
        output += str(item)
        output += "</li>"
    return output
"""
    assert _count(source) == 1


# Positive — obviously-string RHS accumulated with `+=` fires exactly once.    #


_STRINGISH_RHS = [
    pytest.param('"literal"', id="rhs-str-constant"),
    pytest.param('f"row {x}"', id="rhs-fstring"),
    pytest.param('"prefix " + str(x)', id="rhs-binop-const-left"),
    pytest.param('str(x) + " suffix"', id="rhs-binop-const-right"),
    pytest.param('"a" + "b" + str(x)', id="rhs-binop-nested"),
    pytest.param('prefix + "x"', id="rhs-binop-name-plus-const"),
    pytest.param('"a" if x else "b"', id="rhs-ternary-both-str"),
    pytest.param('"row %s" % x', id="rhs-percent-format"),
    pytest.param('(y := f"{x}")', id="rhs-walrus-fstring"),
]


@pytest.mark.parametrize("rhs", _STRINGISH_RHS)
def test_flags_stringish_rhs_in_for(rhs: str):
    src = f"""
def f(items, dt, bits, prefix):
    s = ""
    for x in items:
        s += {rhs}
"""
    assert _count(src) == 1


@pytest.mark.parametrize("rhs", _STRINGISH_RHS)
def test_flags_stringish_rhs_in_while(rhs: str):
    src = f"""
def f(items, dt, bits, prefix):
    s = ""
    x = 0
    while x < 10:
        s += {rhs}
        x += 1
"""
    assert _count(src) == 1


# A proven string accumulator grows regardless of how each string is rendered. #


_NON_ACCUMULATION_RHS = [
    pytest.param("str(x)", id="rhs-str-call"),
    pytest.param("repr(x)", id="rhs-repr-call"),
    pytest.param("format(x)", id="rhs-format-builtin"),
    pytest.param('"{}".format(x)', id="rhs-format-method"),
    pytest.param('dt.strftime("%Y")', id="rhs-strftime-method"),
    pytest.param('",".join(bits)', id="rhs-join-method"),
    pytest.param("os.path.join(root, x)", id="rhs-ospath-join"),
]


@pytest.mark.parametrize("rhs", _NON_ACCUMULATION_RHS)
def test_flags_rendered_string_rhs_in_loop(rhs: str):
    src = f"""
def f(items, dt, bits, prefix, root, os):
    s = ""
    for x in items:
        s += {rhs}
"""
    assert _count(src) == 1


def test_unknown_name_and_attribute_targets_are_allowed() -> None:
    src = """
def f(self, items, fragment):
    for x in items:
        accumulator += fragment
        self.buf += f"{x}"
"""
    assert _check(src) == []


def test_class_initialized_string_attribute_is_flagged() -> None:
    src = """
class Renderer:
    def __init__(self):
        self.buf = ""

    def render(self, items):
        for item in items:
            self.buf += str(item)
"""
    assert _count(src) == 1


def test_nested_class_does_not_prove_outer_attribute_type() -> None:
    src = """
class Renderer:
    class Buffer:
        def __init__(self):
            self.buf = ""

    def render(self, items):
        for item in items:
            self.buf += str(item)
"""
    assert _check(src) == []


_SUBSCRIPT_TARGETS = [
    pytest.param('acc["k"]', id="target-subscript"),
    pytest.param("obj.rows[i]", id="target-attr-subscript"),
]


@pytest.mark.parametrize("target", _SUBSCRIPT_TARGETS)
def test_allows_subscript_targets(target: str):
    src = f"""
def f(items, acc, obj, i):
    for x in items:
        {target} += f"{{x}}"
"""
    assert _check(src) == []


def test_flags_for_over_comprehension_iterable():
    src = """
def f(items):
    s = ""
    for x in [i for i in items]:
        s += f"{x}"
    return s
"""
    assert _count(src) == 1


def test_allows_concat_in_for_else_clause():
    src = """
def f(items):
    s = ""
    for x in items:
        pass
    else:
        s += "done"
"""
    assert _check(src) == []


def test_flags_concat_after_walrus_condition():
    src = """
def f(it):
    s = ""
    while (n := next(it, None)) is not None:
        s += f"{n}"
    return s
"""
    assert _count(src) == 1


# Nesting — each concat is flagged once, never once per ancestor loop.         #


def test_nested_for_for_reports_once():
    src = """
def f(rows):
    s = ""
    for row in rows:
        for cell in row:
            s += f"{cell}"
    return s
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ002"


def test_nested_while_for_reports_once():
    src = """
def f(rows, n):
    s = ""
    while n > 0:
        for cell in rows:
            s += f"{cell}"
        n -= 1
"""
    assert _count(src) == 1


def test_deeply_nested_three_levels_reports_once():
    src = """
def f(a):
    s = ""
    for i in a:
        for j in a:
            for k in a:
                s += f"{k}"
    return s
"""
    assert _count(src) == 1


def test_two_sibling_loops_report_two_diagnostics():
    src = """
def f(a, b):
    s = ""
    for x in a:
        s += f"{x}"
    for y in b:
        s += f"{y}"
    return s
"""
    assert _count(src) == 2


def test_multiple_concats_in_one_loop_flag_each():
    src = """
def f(items):
    s = ""
    t = ""
    for x in items:
        s += f"{x}"
        t += f"{x!r}"
    return s, t
"""
    assert _count(src) == 2


# Diagnostic content — line, col (1-based), code, message.                     #


def test_reports_line_and_one_based_column():
    src = 'def f(it):\n    s = ""\n    for x in it:\n        s += f"{x}"\n'
    (diag,) = _check(src)
    assert (diag.line, diag.col) == (4, 9)
    assert diag.code == "SARJ002"
    assert "can become quadratic" in diag.message


def test_reports_distinct_positions_in_source_order():
    src = 'def f(a, b):\n    s = ""\n    for x in a:\n        s += f"{x}"\n    for y in b:\n        s += f"{y}"\n'
    positions = [(d.line, d.col) for d in _check(src)]
    assert positions == [(4, 9), (6, 9)]


# Recall — bare-name accumulation of a string-typed accumulator now fires.     #


def test_flags_bare_name_augassign_when_target_is_string():
    src = """
def f(lines):
    buf = ""
    for line in lines:
        buf += line
    return buf
"""
    assert _count(src) == 1


def test_flags_bare_name_self_add_when_target_is_string():
    src = """
def f(chunks):
    out = ""
    for chunk in chunks:
        out = out + chunk
    return out
"""
    assert _count(src) == 1


def test_allows_bare_name_augassign_when_target_is_numeric():
    src = """
def f(items):
    total = 0
    for x in items:
        total += x
    return total
"""
    assert _check(src) == []


def test_allows_bare_name_augassign_with_unknown_target_type():
    src = """
def f(items, chunk, s):
    for x in items:
        s += chunk
    return s
"""
    assert _check(src) == []


@pytest.mark.parametrize("annotation", ["str", "builtins.str", "Annotated[str, 'text']"])
def test_flags_annotated_string_parameter_with_unknown_fragment(annotation: str) -> None:
    src = f"""
def render(seed: {annotation}, parts):
    for part in parts:
        seed += part
    return seed
"""
    assert _count(src) == 1


def test_flags_stably_annotated_string_local_with_unknown_fragment() -> None:
    src = """
def render(parts):
    output: str = make_prefix()
    for part in parts:
        output += part
    return output
"""
    assert _count(src) == 1


@pytest.mark.parametrize("annotation", ["bytes", "object", "Any"])
def test_allows_non_string_annotated_parameter_with_unknown_fragment(annotation: str) -> None:
    src = f"""
def render(seed: {annotation}, parts):
    for part in parts:
        seed += part
    return seed
"""
    assert _check(src) == []


def test_allows_string_parameter_rebound_before_loop() -> None:
    src = """
def render(seed: str, parts):
    seed = make_accumulator()
    for part in parts:
        seed += part
    return seed
"""
    assert _check(src) == []


# Real-world false-positive regressions (Flask / requests / Django sweep).     #


def test_allows_join_reassignment_in_loop():
    src = """
def f(parts):
    url = ""
    for scheme in parts:
        url = ":".join([scheme, url])
    return url
"""
    assert _check(src) == []


def test_allows_os_path_join_reassignment_in_loop():
    src = """
def build(segments):
    import os
    f = ""
    for root in segments:
        f = os.path.join(root, f)
    return f
"""
    assert _check(src) == []


def test_allows_str_coercion_reassignment_in_loop():
    src = """
def f(rows):
    val = ""
    for _ in rows:
        val = str(val)
    return val
"""
    assert _check(src) == []


def test_allows_loop_local_target_rebound_before_concat():
    src = """
def f(objs):
    for obj in objs:
        desc = obj.__class__.__name__
        if obj:
            desc += f": {obj.entity_id}"
        emit(desc)
"""
    assert _check(src) == []


def test_allows_loop_local_target_from_tuple_unpack():
    src = """
def f(q):
    while q:
        obj, obj_path = q.popleft()
        obj_path += f"({obj})"
        emit(obj_path)
"""
    assert _check(src) == []


def test_flags_before_loop_accumulator_not_rebound_in_body():
    src = """
def f(lines):
    msg = ""
    for line in lines:
        msg += line
    return msg
"""
    assert _count(src) == 1


def test_flags_inner_loop_accumulator_reset_in_outer_body_only():
    src = """
def f(rows):
    for row in rows:
        buf = ""
        for cell in row:
            buf += f"{cell}"
        emit(buf)
"""
    assert _count(src) == 1


def test_allows_when_rebind_comes_after_concat_before_backedge():
    src = """
def f(items):
    s = ""
    for x in items:
        s += f"{x}"
        s = base()
    return s
"""
    assert _check(src) == []


def test_allows_subscript_fstring_write_in_loop():
    src = """
def f(parts):
    for i in range(len(parts)):
        parts[i] = f"%{parts[i]}"
    return parts
"""
    assert _check(src) == []


# Negative / exempt — the correct patterns and out-of-scope shapes.            #


def test_allows_concat_outside_any_loop():
    src = """
def f(a, b):
    s = ""
    s += f"{a}"
    s += f"{b}"
    return s
"""
    assert _check(src) == []


def test_allows_module_level_concat():
    assert _check('s = "a"\ns += "b"\n') == []


@pytest.mark.parametrize(
    ("path", "header"),
    [
        pytest.param("app/service.py", "# Code generated by protoc. DO NOT EDIT.\n", id="header"),
        pytest.param("src/generated/service.py", "", id="generated-directory"),
    ],
)
def test_allows_generated_files(path: str, header: str):
    src = header + 's = ""\nfor x in items:\n    s += f"{x}"\n'
    assert _check(src, path) == []


def test_allows_list_append_in_loop():
    src = """
def f(items):
    parts = []
    for x in items:
        parts.append(str(x))
    return "".join(parts)
"""
    assert _check(src) == []


def test_allows_set_add_in_loop():
    src = """
def f(items):
    seen = set()
    for x in items:
        seen.add(str(x))
    return seen
"""
    assert _check(src) == []


_NON_STRING_AUGASSIGN = [
    pytest.param("total += 1", id="int-literal"),
    pytest.param("total += x", id="name-rhs-numeric-target"),
    pytest.param("total += len(x)", id="len-call-rhs"),
    pytest.param("total += x * 2", id="binop-mult-rhs"),
    pytest.param("acc += [x]", id="list-literal-rhs"),
    pytest.param('buf += b"x"', id="bytes-literal-rhs"),
    pytest.param("acc += (x,)", id="tuple-rhs"),
    pytest.param("total += 1.5", id="float-literal"),
]


@pytest.mark.parametrize("stmt", _NON_STRING_AUGASSIGN)
def test_allows_non_string_augassign_in_loop(stmt: str):
    src = f"""
def f(items):
    total = 0
    acc = []
    buf = b""
    for x in items:
        {stmt}
    return total
"""
    assert _check(src) == []


def test_allows_string_repeat_augassign():
    src = """
def f(items):
    s = "-"
    for _ in items:
        s *= 2
    return s
"""
    assert _check(src) == []


def test_allows_fresh_binop_assignment_each_iteration():
    src = """
def f(items):
    for x in items:
        line = "row " + str(x)
        emit(line)
"""
    assert _check(src) == []


# Edge — parse failures, empty input, comments-only.                          #


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("", id="empty"),
        pytest.param("   \n\t\n", id="whitespace-only"),
        pytest.param("# just a comment\n", id="comment-only"),
        pytest.param("def f(:\n    pass\n", id="syntax-error-signature"),
        pytest.param("for x in items\n    s += str(x)\n", id="syntax-error-missing-colon"),
        pytest.param("s += (\n", id="syntax-error-unclosed"),
    ],
)
def test_non_parseable_or_trivial_sources_yield_no_diagnostics(source: str):
    assert _check(source) == []


# False-positive guards — accumulators that only look adjacent to strings.     #


def test_numeric_accumulation_alongside_string_append_is_clean():
    src = """
def f(items):
    total = 0
    parts = []
    for x in items:
        total += len(x)
        parts.append(str(x))
    return total, "".join(parts)
"""
    assert _check(src) == []


def test_list_building_with_plus_equals_list_is_clean():
    src = """
def f(chunks):
    out = []
    for c in chunks:
        out += list(c)
    return out
"""
    assert _check(src) == []


def test_bytes_accumulation_is_clean():
    src = """
def f(frames):
    buf = b""
    for frame in frames:
        buf += frame.data
    return buf
"""
    assert _check(src) == []


# Previously known gaps — now fixed and asserted directly.                     #


def test_flags_string_concat_in_async_for():
    src = """
async def f(stream):
    s = ""
    async for chunk in stream:
        s += f"{chunk}"
    return s
"""
    assert _count(src) == 1


def test_flags_plain_reassignment_concat_in_loop():
    src = """
def f(items):
    s = ""
    for x in items:
        s = s + f"{x}"
    return s
"""
    assert _count(src) == 1


def test_ignores_concat_in_function_nested_in_loop():
    src = """
def f(items):
    for x in items:
        def build():
            s = ""
            s += str(x)
            return s
        build()
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "nested_scope",
    [
        pytest.param("def consume():\n            return s", id="function"),
        pytest.param("consume = lambda: s", id="lambda"),
    ],
)
def test_nested_scope_read_does_not_make_accumulator_a_probe(nested_scope: str):
    src = f"""
def f(items):
    s = ""
    for x in items:
        {nested_scope}
        s += f"{{x}}"
    return s
"""
    assert _count(src) == 1


@pytest.mark.parametrize(
    ("nested_scope", "expected"),
    [
        pytest.param("for value in values:\n            s = value", 0, id="loop-may-rebind-type"),
        pytest.param("class Holder:\n            s = value", 1, id="class-has-separate-scope"),
    ],
)
def test_nested_scope_rebind_affects_type_only_when_it_shares_scope(nested_scope: str, expected: int):
    src = f"""
def f(items, values, value):
    s = ""
    for x in items:
        {nested_scope}
        s += f"{{x}}"
    return s
"""
    assert _count(src) == expected


# Adversarial coverage — compound statements wrapping an in-loop concat.        #
# The visitor recurses via generic_visit, so loop_depth stays > 0 inside any    #
# nested block and the concat must still fire.                                  #


_WRAPPED_CONCAT_BODIES = [
    pytest.param(
        '        if x:\n            s += f"{x}"',
        id="if-guarded",
    ),
    pytest.param(
        '        if not x:\n            pass\n        else:\n            s += f"{x}"',
        id="else-guarded",
    ),
    pytest.param(
        '        try:\n            s += f"{x}"\n        except Exception:\n            pass',
        id="try-body",
    ),
    pytest.param(
        '        try:\n            pass\n        except Exception:\n            s += f"{x}"',
        id="except-body",
    ),
    pytest.param(
        '        try:\n            pass\n        finally:\n            s += f"{x}"',
        id="finally-body",
    ),
    pytest.param(
        "        with open('p') as _fh:\n            s += f\"{x}\"",
        id="with-body",
    ),
]


@pytest.mark.parametrize("body", _WRAPPED_CONCAT_BODIES)
def test_flags_concat_wrapped_in_compound_statement(body: str):
    src = f"""
def f(items):
    s = ""
    for x in items:
{body}
    return s
"""
    assert _count(src) == 1


def test_reports_accumulator_once_across_match_case_bodies_in_loop():
    src = """
def f(items):
    s = ""
    for x in items:
        match x:
            case 0:
                s += "zero"
            case _:
                s += f"{x}"
    return s
"""
    assert _count(src) == 1


def test_flags_concat_in_inner_while_in_for():
    src = """
def f(items):
    s = ""
    for x in items:
        while x:
            s += f"{x}"
            x -= 1
    return s
"""
    assert _count(src) == 1


def test_allows_concat_in_single_iteration_while_true_loop():
    src = """
def f(items):
    s = ""
    while True:
        s += f"{items}"
        break
    return s
"""
    assert _check(src) == []


def test_flags_concat_over_generator_expression_iterable():
    src = """
def f(gen):
    s = ""
    for x in (i for i in gen):
        s += f"{x}"
    return s
"""
    assert _count(src) == 1


def test_flags_async_for_concat_when_nested_in_sync_for():
    src = """
async def f(rows):
    s = ""
    for row in rows:
        async for cell in row:
            s += f"{cell}"
    return s
"""
    assert _count(src) == 1


def test_flags_sync_for_concat_when_nested_in_async_for():
    src = """
async def f(rows):
    s = ""
    async for row in rows:
        for cell in row:
            s += f"{cell}"
    return s
"""
    assert _count(src) == 1


def test_flags_implicit_adjacent_string_literal_concat():
    src = """
def f(items):
    s = ""
    for x in items:
        s += "a" "b"
    return s
"""
    assert _count(src) == 1


def test_allows_bytes_encode_call_in_loop():
    src = """
def f(items):
    buf = b""
    for x in items:
        buf += f"{x}".encode()
    return buf
"""
    assert _check(src) == []


def test_allows_numeric_modulo_augassign_in_loop():
    src = """
def f(items):
    total = 0
    for n in items:
        total += n % 2
    return total
"""
    assert _check(src) == []


# Previously undetected string-valued RHS shapes — now recognised.             #


def test_flags_ternary_string_rhs_in_loop():
    src = """
def f(items, c):
    s = ""
    for x in items:
        s += "a" if c else "b"
    return s
"""
    assert _count(src) == 1


def test_flags_percent_format_string_rhs_in_loop():
    src = """
def f(items):
    s = ""
    for x in items:
        s += "row %s" % x
    return s
"""
    assert _count(src) == 1


def test_flags_walrus_wrapped_string_rhs_in_loop():
    src = """
def f(items):
    s = ""
    for x in items:
        s += (y := f"{x}")
    return s
"""
    assert _count(src) == 1


# FP-hardening (famous-repo sweep): while-loop probe targets are not O(n²)     #
# accumulators — the test reads the target, so join cannot express the loop.   #


def test_while_probe_target_is_exempt():
    # Minimized from pydantic's unique-name generation
    # (`_internal/_signature.py` / `v1/utils.py`).
    src = """
def merge(var_kw_name, fields):
    while var_kw_name in fields:
        var_kw_name += '_'
    return var_kw_name
"""
    assert _check(src) == []


def test_while_probe_setdefault_walk_is_exempt():
    # Minimized from pydantic's `create_model` reference-name walk.
    src = """
def register(reference_name, module_globals, created_model):
    object_by_reference = None
    while object_by_reference is not created_model:
        object_by_reference = module_globals.setdefault(reference_name, created_model)
        reference_name += '_'
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "read",
    [
        pytest.param("emit(s)", id="call-argument"),
        pytest.param("emit(cache[s])", id="subscript-key"),
        pytest.param("emit(s == expected)", id="comparison"),
    ],
)
def test_body_read_makes_target_a_probe(read: str):
    src = f"""
def f(items, cache, expected):
    s = ""
    for x in items:
        {read}
        s += "_"
    return s
"""
    assert _check(src) == []


def test_while_loop_not_reading_target_still_fires():
    src = """
def f(n):
    s = ''
    i = 0
    while i < n:
        s += 'x'
        i += 1
    return s
"""
    assert len(_check(src)) == 1


def test_for_loop_accumulation_still_fires_from_trio_shape():
    # Distilled TP from trio's _raises_group repr assembly: a for-loop growing
    # one string across iterations is the classic O(n²) shape.
    src = """
def render(failed, indent_1):
    s = ''
    for item in failed:
        s += f'{indent_1}{item}'
    return s
"""
    assert len(_check(src)) == 1


def test_latest_definition_must_still_be_string() -> None:
    src = """
def collect(items):
    result = ""
    result = []
    for item in items:
        result += "ab"
"""
    assert _check(src) == []


def test_future_string_assignment_does_not_retype_earlier_loop() -> None:
    src = """
def collect(items, builder):
    result = builder
    for item in items:
        result += "ab"
    result = ""
"""
    assert _check(src) == []


def test_conditional_reset_does_not_hide_loop_carried_growth() -> None:
    src = """
def render(items, reset):
    result = ""
    for item in items:
        if reset:
            result = ""
        result += str(item)
"""
    assert _count(src) == 1


def test_nested_self_add_tree_is_reported() -> None:
    src = """
def render(items):
    result = ""
    for item in items:
        result = "[" + result + "]"
"""
    assert _count(src) == 1


@pytest.mark.parametrize("iterable", ["range(0)", "range(1)", "[]", "[item]"])
def test_statically_single_iteration_loops_are_allowed(iterable: str) -> None:
    src = f"""
def render(item):
    result = ""
    for value in {iterable}:
        result += str(value)
"""
    assert _check(src) == []


def test_known_numeric_rhs_is_not_string_growth() -> None:
    src = """
def render(items):
    result = ""
    for item in items:
        result += len(item)
"""
    assert _check(src) == []
