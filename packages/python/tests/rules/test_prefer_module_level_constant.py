from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_immutable_module_constant import PreferImmutableModuleConstant
from sarj_python_lint.rules.prefer_module_level_constant import PreferModuleLevelConstant


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


SRC_PATH = "python/app/app/calls/service.py"
EIGHT_LIST = '["a", "b", "c", "d", "e", "f", "g", "h"]'


def _check(source: str, path: str = SRC_PATH) -> list[Diagnostic]:
    return PreferModuleLevelConstant().check(Path(path), source)


_PUBLIC_EXAMPLES = PreferModuleLevelConstant.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def test_public_accept_example_is_immutable_and_preserves_unhashable_membership() -> None:
    example = next(example for example in _PUBLIC_EXAMPLES if example.expected_count == 0)
    source = example.focus_file.source
    namespace: dict[str, object] = {}

    exec(compile(source, str(example.focus_file.path), "exec"), namespace)  # ruff: ignore[exec-builtin] - executable rule fixture

    handle = namespace["handle"]
    assert callable(handle)
    assert handle([]) is False
    assert PreferImmutableModuleConstant().check(Path(example.focus_file.path), source) == []


def _fn(body: str) -> str:
    indented = "\n".join(f"    {line}" if line else "" for line in body.splitlines())
    return f"def handle(payload):\n{indented}\n"


# Positive: constant-only displays and compiled regexes inside a function.     #


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        (EIGHT_LIST, "list"),
        ('{"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 7, "h": 8}', "dict"),
        ('{"a", "b", "c", "d", "e", "f", "g", "h"}', "set"),
        ('frozenset(["a", "b", "c", "d", "e", "f", "g", "h"])', "frozenset"),
        ("[1, -2, 3.5, 4, 5, 6, 7, 8]", "list"),
        ('[True, False, None, b"x", 1, 2, 3, 4]', "list"),
    ],
)
def test_flags_constant_only_displays(value: str, kind: str):
    diags = _check(_fn(f"allowed = {value}\nreturn len(allowed)"))
    assert len(diags) == 1
    assert diags[0].code == "SARJ039"
    assert kind in diags[0].message
    assert "`allowed`" in diags[0].message


@pytest.mark.parametrize(
    "value",
    [
        're.compile(r"^[a-z]+$")',
        're.compile("^[a-z]+$", re.IGNORECASE)',
        're.compile(r"\\d+", re.IGNORECASE | re.MULTILINE)',
        're.compile(rb"\\d+")',
        're.compile("x", 0)',
    ],
)
def test_flags_constant_regex(value: str):
    diags = _check("import re\n\n" + _fn(f"pattern = {value}\nreturn pattern.match(payload) is not None"))
    assert len(diags) == 1
    assert "regex-cache lookup on every call" in diags[0].message


@pytest.mark.parametrize(
    "usage",
    [
        "return pattern.match(payload)",
        "return pattern.search(payload)",
        "return pattern.fullmatch(payload)",
        "return pattern.findall(payload)",
        "return list(pattern.finditer(payload))",
        "return pattern.split(payload)",
        'return pattern.sub("", payload)',
        'return pattern.subn("", payload)',
    ],
)
def test_fires_for_immutable_regex_reads(usage: str):
    assert len(_check("import re\n\n" + _fn(f'pattern = re.compile("^x$")\n{usage}'))) == 1


@pytest.mark.parametrize(
    "usage",
    [
        "return pattern",
        "return pattern.pattern",
        "consume(pattern)",
        "return pattern.frobnicate()",
    ],
)
def test_ignores_escaping_or_unknown_regex_usage(usage: str):
    assert _check(_fn(f'pattern = re.compile("^x$")\n{usage}')) == []


def test_flags_annotated_assignment():
    src = _fn(f"allowed: list[str] = {EIGHT_LIST}\nreturn len(allowed)")
    assert len(_check(src)) == 1


def test_message_points_at_module_scope():
    diags = _check(_fn(f"allowed = {EIGHT_LIST}\nreturn len(allowed)"))
    assert "module scope" in diags[0].message


def test_line_and_col():
    diags = _check(_fn(f"allowed = {EIGHT_LIST}\nreturn len(allowed)"))
    assert (diags[0].line, diags[0].col) == (2, 5)


# Negative: scope and size gates.                                             #


def test_ignores_module_scope():
    assert _check('ALLOWED = ["a", "b", "c"]\n') == []


def test_ignores_class_body_at_module_scope():
    assert _check('class Config:\n    ALLOWED = ["a", "b", "c"]\n') == []


def test_ignores_class_body_inside_function():
    src = _fn('class Config:\n    ALLOWED = ["a", "b", "c"]\nreturn Config')
    assert _check(src) == []


@pytest.mark.parametrize("value", ['["a"]', '["a", "b"]', '{"a": 1, "b": 2}', "frozenset([1, 2])", "()"])
def test_ignores_displays_below_min_elements(value: str):
    assert _check(_fn(f"allowed = {value}\nreturn len(allowed)")) == []


@pytest.mark.parametrize("value", ['("a", "b", "c")', "((1, 2), (3, 4), (5, -6))"])
def test_ignores_immutable_literal_tuples(value: str):
    assert _check(_fn(f"allowed = {value}\nreturn len(allowed)")) == []


def test_min_elements_boundary_is_eight():
    assert _check(_fn('allowed = ["a", "b", "c", "d", "e", "f", "g"]\nreturn len(allowed)')) == []
    assert len(_check(_fn(f"allowed = {EIGHT_LIST}\nreturn len(allowed)"))) == 1


# Negative: the constant-only leaf gate.                                      #


@pytest.mark.parametrize(
    "value",
    [
        # Closes over a parameter — hoisting this is a NameError, not a style nit.
        '[payload, "b", "c"]',
        '{"user": payload, "b": 2, "c": 3}',
        '{payload: 1, "b": 2, "c": 3}',
        "[payload.id, 1, 2]",
        # Calls, comprehensions, f-strings, spreads.
        '[str(payload), "b", "c"]',
        '[x for x in ("a", "b", "c")]',
        '{x: 1 for x in "abc"}',
        '[f"{payload}", "b", "c"]',
        '[*payload, "b", "c"]',
        '{**payload, "b": 2, "c": 3}',
        'frozenset([payload, "b", "c"])',
        "frozenset(payload)",
        "[DEFAULT, 1, 2]",
        '[["a", payload], ["c"], ["d"]]',
        '{"a": {"nested": [payload]}, "b": 2, "c": 3}',
    ],
)
def test_ignores_non_constant_leaves(value: str):
    assert _check(_fn(f"allowed = {value}\nreturn len(allowed)")) == []


@pytest.mark.parametrize(
    "value",
    [
        "re.compile(payload)",
        're.compile(f"^{payload}$")',
        're.compile("^x$", flags)',
        "re.compile()",
        'compile("^x$")',
        'regex.compile("^x$")',
        're.escape("^x$")',
        'other(["a", "b", "c"])',
        'set(["a", "b", "c"])',
    ],
)
def test_ignores_non_qualifying_calls(value: str):
    assert _check(_fn(f"pattern = {value}\nreturn pattern")) == []


def test_ignores_deeply_nested_displays():
    value = "[[[[[1]]]], 2, 3]"
    assert _check(_fn(f"allowed = {value}\nreturn len(allowed)")) == []


def test_accepts_deeply_immutable_tuple_elements():
    value = "[((1,),), 2, 3, 4, 5, 6, 7, 8]"
    assert len(_check(_fn(f"allowed = {value}\nreturn len(allowed)"))) == 1


# Negative: mutation shapes.                                                  #


@pytest.mark.parametrize(
    "usage",
    [
        'allowed.append("d")',
        'allowed.extend(["d"])',
        'allowed.insert(0, "d")',
        'allowed.remove("a")',
        "allowed.pop()",
        "allowed.clear()",
        "allowed.sort()",
        "allowed.reverse()",
        'allowed.update({"d": 4})',
        'allowed.add("d")',
        'allowed.discard("a")',
        'allowed.setdefault("d", 4)',
        "allowed.popitem()",
        'allowed.__setitem__("d", 4)',
        # Unrecognised method — default-deny.
        "allowed.frobnicate()",
        "allowed.merge_in(other)",
        # Subscript / attribute stores and deletes.
        'allowed[0] = "d"',
        "del allowed[0]",
        "del allowed",
        "allowed.attr = 1",
        # Rebinds.
        'allowed += ["d"]',
        'allowed = ["x", "y", "z"]',
        "for allowed in rows:\n    pass",
        "with open(payload) as allowed:\n    pass",
        "global allowed",
        "if (allowed := load()):\n    pass",
    ],
)
def test_ignores_mutation_and_rebinding(usage: str):
    src = _fn(f'allowed = ["a", "b", "c"]\n{usage}')
    assert _check(src) == []


def test_ignores_except_as_rebind():
    src = _fn('allowed = ["a", "b", "c"]\ntry:\n    work()\nexcept ValueError as allowed:\n    pass')
    assert _check(src) == []


def test_ignores_comprehension_target_rebind():
    src = _fn('allowed = ["a", "b", "c"]\nreturn [allowed for allowed in rows]')
    assert _check(src) == []


def test_ignores_nonlocal_declaration():
    src = 'def outer():\n    def inner():\n        nonlocal allowed\n        allowed = ["a", "b", "c"]\n    return inner\n'
    assert _check(src) == []


def test_ignores_parameter_shadowing():
    src = 'def handle(allowed):\n    allowed = ["a", "b", "c"]\n    return len(allowed)\n'
    assert _check(src) == []


def test_ignores_list_used_as_a_subscript_selector() -> None:
    source = _fn('columns = ["name", "status", "score"]\nreturn frame[columns]')

    assert _check(source) == []


def test_ignores_collection_nested_as_a_dict_keyword_value() -> None:
    source = _fn('labels = {"a": "A", "b": "B", "c": "C"}\nreturn dict(labels=labels)')

    assert _check(source) == []


def test_ignores_import_as_rebind():
    src = _fn('allowed = ["a", "b", "c"]\nimport json as allowed\nreturn allowed')
    assert _check(src) == []


@pytest.mark.parametrize(
    "statement",
    [
        "import allowed",
        "import allowed.tools",
        "from package import allowed",
    ],
)
def test_ignores_import_rebind_without_alias(statement: str):
    src = _fn(f'allowed = ["a", "b", "c"]\n{statement}\nreturn allowed')
    assert _check(src) == []


@pytest.mark.parametrize(
    "definition",
    [
        "def allowed():\n    pass",
        "async def allowed():\n    pass",
        "class allowed:\n    pass",
    ],
)
def test_ignores_same_named_nested_definition(definition: str):
    src = _fn(f'allowed = ["a", "b", "c"]\n{definition}\nreturn allowed')
    assert _check(src) == []


@pytest.mark.parametrize(
    "pattern",
    [
        "allowed",
        "[*allowed]",
        '{"value": value, **allowed}',
    ],
)
def test_ignores_match_capture_rebind(pattern: str):
    src = _fn(f'allowed = ["a", "b", "c"]\nmatch payload:\n    case {pattern}:\n        pass\nreturn allowed')
    assert _check(src) == []


# Negative: escape shapes.                                                    #


@pytest.mark.parametrize(
    "usage",
    [
        "return allowed",
        "yield allowed",
        "return allowed, 1",
        "consume(allowed)",
        "consume(key=allowed)",
        "self.allowed = allowed",
        "registry[key] = allowed",
        "return [allowed]",
        'return {"allowed": allowed}',
        "return {allowed}",
        "consume(*allowed)",
        "consume(**allowed)",
        "alias = allowed",
        "return allowed.copy",
        "return allowed()",
        "await consume(allowed)",
    ],
)
def test_ignores_escapes(usage: str):
    src = _fn(f'allowed = ["a", "b", "c"]\n{usage}')
    assert _check(src) == []


@pytest.mark.parametrize(
    "closure",
    [
        "def inner():\n    return allowed",
        "def inner():\n    allowed.append(1)",
        "inner = lambda: allowed",
        "class Inner:\n    values = allowed",
    ],
)
def test_ignores_capture_by_inner_scope(closure: str):
    src = _fn(f'allowed = ["a", "b", "c"]\n{closure}')
    assert _check(src) == []


# Positive: safe consumers still fire.                                        #


@pytest.mark.parametrize(
    "usage",
    [
        "return len(allowed)",
        "return sorted(allowed)",
        "return set(allowed)",
        "return list(allowed)",
        "return dict(allowed)",
        "return any(allowed)",
        "return all(allowed)",
        "return min(allowed)",
        "return max(allowed)",
        "return sum(allowed)",
        "return sorted(allowed, key=str)",
        "return allowed.index(payload)",
        "return allowed.count(payload)",
        "return payload in allowed",
        "return payload not in allowed",
        "return allowed[0]",
        "return allowed[payload]",
        "for item in allowed:\n    emit(item)",
        "return [item for item in allowed]",
        "async for item in allowed:\n    emit(item)",
    ],
)
def test_fires_for_safe_consumers(usage: str):
    src = f"async def handle(payload):\n    allowed = {EIGHT_LIST}\n"
    src += "\n".join(f"    {line}" for line in usage.splitlines()) + "\n"
    diags = _check(src)
    assert len(diags) == 1, usage


def test_sorted_copies_but_sort_mutates():
    assert len(_check(_fn(f"allowed = {EIGHT_LIST}\nreturn sorted(allowed)"))) == 1
    assert _check(_fn(f"allowed = {EIGHT_LIST}\nallowed.sort()\nreturn allowed")) == []


def test_ignores_binding_the_function_never_reads():
    # Sweep evidence: rich/examples/log.py:54 binds `foo = (1, 2, 3)` and never
    # reads it — Console(log_locals=True) picks it up by frame inspection, so
    # the hoist would both serve no use site and empty the frame it renders.
    assert _check(_fn('allowed = ["a", "b", "c"]\nreturn payload')) == []


def test_fires_on_multiple_safe_reads():
    src = _fn(f'allowed = {EIGHT_LIST}\nif payload in allowed:\n    return len(allowed)\nreturn allowed.index("a")')
    assert len(_check(src)) == 1


# Nesting: inner functions, methods, loops.                                   #


def test_fires_inside_nested_function():
    src = f"def outer():\n    def inner(payload):\n        allowed = {EIGHT_LIST}\n        return payload in allowed\n    return inner\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3


def test_fires_inside_method():
    src = f"class Service:\n    def handle(self, payload):\n        allowed = {EIGHT_LIST}\n        return payload in allowed\n"
    assert len(_check(src)) == 1


def test_fires_inside_async_method():
    src = f"class Service:\n    async def handle(self, payload):\n        allowed = {EIGHT_LIST}\n        return payload in allowed\n"
    assert len(_check(src)) == 1


def test_fires_inside_a_loop_body():
    src = _fn("for row in payload:\n    allowed = ['a', 'b', 'c']\n    emit(row in allowed)")
    assert len(_check(src)) == 1


def test_reports_each_function_once():
    src = (
        "def a(payload):\n"
        f"    allowed = {EIGHT_LIST}\n"
        "    return payload in allowed\n"
        "\n"
        "def b(payload):\n"
        f"    allowed = {EIGHT_LIST}\n"
        "    return payload in allowed\n"
    )
    assert len(_check(src)) == 2


def test_multiple_hits_sorted():
    src = "import re\n\n" + _fn(
        'lookup = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 7, "h": 8}\n'
        'pattern = re.compile("^x$")\n'
        f"allowed = {EIGHT_LIST}\n"
        "return len(lookup) + len(allowed) + len(pattern.findall(payload))"
    )
    diags = _check(src)
    assert len(diags) == 3
    assert [(d.line, d.col) for d in diags] == sorted((d.line, d.col) for d in diags)


# File-scope exemptions and edge cases.                                       #


_HIT = f"def handle(payload):\n    allowed = {EIGHT_LIST}\n    return payload in allowed\n"


@pytest.mark.parametrize(
    "path",
    [
        "tests/rules/test_service.py",
        "test_service.py",
        "service_test.py",
        "conftest.py",
        "python/app/tests/helpers/seed.py",
    ],
)
def test_skips_test_paths(path: str):
    assert _check(_HIT, path) == []


@pytest.mark.parametrize(
    "header",
    [
        "# Autogenerated by protoc. Do not edit.\n",
        "# This file was generated by openapi-python-client.\n",
        '"""DO NOT EDIT — generated."""\n',
    ],
)
def test_skips_generated_sources(header: str):
    assert _check(header + _HIT) == []


def test_fires_in_production_path():
    assert len(_check(_HIT)) == 1


@pytest.mark.parametrize("source", ["", "  ", "# comment\n"])
def test_empty_or_trivial_source(source: str):
    assert _check(source) == []


def test_syntax_error_returns_empty():
    assert _check("def f(:\n    pass") == []


# FP-hardening: frame reflection (famous-repo sweep).                         #


@pytest.mark.parametrize(
    "reflection",
    [
        "print(locals())",
        "return render_scope(locals(), title='locals')",
        "return vars()",
    ],
)
def test_ignores_function_that_reflects_over_its_frame(reflection: str):
    # Minimized from rich/rich/scope.py:82-83, where `list_of_things` /
    # `dict_of_things` exist only to be rendered by `render_scope(locals())`.
    src = _fn(f"allowed = ['a', 'b', 'c']\n{reflection}\nreturn len(allowed)")
    assert _check(src) == []


def test_vars_with_an_argument_is_not_frame_reflection():
    # `vars(obj)` reads someone else's __dict__ — it does not expose this frame.
    src = _fn(f"allowed = {EIGHT_LIST}\nemit(vars(payload))\nreturn len(allowed)")
    assert len(_check(src)) == 1


def test_read_by_a_safe_consumer_still_fires():
    # The opposite case for the zero-read guard: one recognised read is enough.
    assert len(_check(_fn(f"allowed = {EIGHT_LIST}\nreturn len(allowed)"))) == 1


def test_regex_bound_but_never_used_is_ignored():
    src = "import re\n\n" + _fn('pattern = re.compile(r"^[a-z]+$")\nreturn payload')
    assert _check(src) == []


def test_diagnostic_is_advisory() -> None:
    diagnostic = _check(_fn(f"allowed = {EIGHT_LIST}\nreturn payload in allowed"))[0]

    assert diagnostic.severity.value == "warning"


@pytest.mark.parametrize(
    "source",
    [
        _fn('pattern = re.compile("x")\nreturn pattern.search(payload)'),
        "import fake as re\n\n" + _fn('pattern = re.compile("x")\nreturn pattern.search(payload)'),
        "import re\n\ndef handle(re, payload):\n    pattern = re.compile('x')\n    return pattern.search(payload)\n",
        "import re\n\ndef handle(payload):\n    import fake as re\n    pattern = re.compile('x')\n    return pattern.search(payload)\n",
        "import re\n\n" + _fn('pattern = re.compile("x", re.DEBUG)\nreturn pattern.search(payload)'),
        "import re\n\n" + _fn('pattern = re.compile("x", 128)\nreturn pattern.search(payload)'),
        "import re\n\n" + _fn('pattern = re.compile("x", 130)\nreturn pattern.search(payload)'),
        "import re\nre.compile = custom_compile\n\n" + _fn('pattern = re.compile("x")\nreturn pattern.search(payload)'),
        "import re\nre.IGNORECASE = re.DEBUG\n\n"
        + _fn('pattern = re.compile("x", re.IGNORECASE)\nreturn pattern.search(payload)'),
    ],
    ids=(
        "missing-import",
        "foreign-module",
        "parameter-shadow",
        "nested-import-shadow",
        "symbolic-debug",
        "numeric-debug",
        "combined-numeric-debug",
        "compile-monkeypatch",
        "flag-monkeypatch",
    ),
)
def test_ignores_unproven_or_observable_regex_construction(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    ("header", "call"),
    [
        ("import re as regex\n\n", 'regex.compile("x")'),
        ("from re import compile as compile_pattern\n\n", 'compile_pattern("x")'),
    ],
)
def test_flags_proven_regex_aliases(header: str, call: str) -> None:
    source = header + _fn(f"pattern = {call}\nreturn pattern.search(payload)")

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "usage",
    [
        "return allowed == other",
        "return allowed is other",
        'return f"{allowed}"',
        "return repr(allowed)",
        "return allowed.copy()",
        "return allowed[:]",
        "return allowed[1:3]",
        "return json.dumps(allowed)",
        "return iter(allowed)",
        "return reversed(allowed)",
        "return enumerate(allowed)",
        "return tuple(allowed)",
        "return frozenset(allowed)",
    ],
)
def test_ignores_representation_sensitive_reads(usage: str) -> None:
    source = _fn(f"allowed = {EIGHT_LIST}\n{usage}")

    assert _check(source) == []


@pytest.mark.parametrize("usage", ["return list(allowed)", "for item in allowed:\n    emit(item)"])
def test_ignores_set_reads_that_expose_iteration_order(usage: str) -> None:
    source = _fn('allowed = {"a", "b", "c", "d", "e", "f", "g", "h"}\n' + usage)

    assert _check(source) == []


@pytest.mark.parametrize(
    "value",
    [
        '[["a"], ["b"], ["c"], ["d"], ["e"], ["f"], ["g"], ["h"]]',
        '{"a": {"total": 0}, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 7, "h": 8}',
        '(["a"], ["b"], ["c"], ["d"], ["e"], ["f"], ["g"], ["h"])',
    ],
)
def test_ignores_nested_mutable_values(value: str) -> None:
    assert _check(_fn(f"allowed = {value}\nreturn len(allowed)")) == []


def test_ignores_corpus_nested_accumulator() -> None:
    source = _fn(
        'stats = {"a": {"total": 0}, "b": {"total": 0}, "c": {"total": 0}, "d": {"total": 0}, '
        '"e": {"total": 0}, "f": {"total": 0}, "g": {"total": 0}, "h": {"total": 0}}\n'
        'for row in payload:\n    stats[row]["total"] += 1\nreturn len(stats)'
    )

    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        f"def handle(len, payload):\n    allowed = {EIGHT_LIST}\n    return len(allowed)\n",
        f"def len(value):\n    return 8\n\ndef handle(payload):\n    allowed = {EIGHT_LIST}\n    return len(allowed)\n",
        f"def handle(payload):\n    import fake as len\n    allowed = {EIGHT_LIST}\n    return len(allowed)\n",
        f"from fake import *\n\ndef handle(payload):\n    allowed = {EIGHT_LIST}\n    return len(allowed)\n",
    ],
)
def test_ignores_unproven_builtin_consumer(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        "Tests/service.py",
        "Testing/smoke_test_utils.py",
        "python/common/testing/builders.py",
        "python/app/fakes/service.py",
    ],
)
def test_skips_case_insensitive_test_support_paths(path: str) -> None:
    assert _check(_HIT, path) == []
