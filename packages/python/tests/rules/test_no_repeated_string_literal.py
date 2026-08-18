from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_repeated_string_literal import NoRepeatedStringLiteral


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample

_LONG_SQL = "\n                SELECT id, name, created_at FROM organization\n            "
assert len(_LONG_SQL) >= 40


def _check(source: str, filename: str = "module.py") -> list[Diagnostic]:
    return NoRepeatedStringLiteral().check(Path(filename), source)


_PUBLIC_EXAMPLES = NoRepeatedStringLiteral.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def test_flags_structured_sql_repeated_across_functions():
    src = f'''
def insert():
    return """{_LONG_SQL}"""

def fetch():
    return """{_LONG_SQL}"""

def upsert():
    return """{_LONG_SQL}"""
'''
    diags = _check(src)
    assert len(diags) == 2
    assert diags[0].code == "SARJ024"
    assert "first use at line 3" in diags[0].message


def test_flags_each_repeat_beyond_the_first():
    src = f'''
A = 0
def a():
    return """{_LONG_SQL}"""
def b():
    return """{_LONG_SQL}"""
def c():
    return """{_LONG_SQL}"""
'''
    diags = _check(src)
    assert len(diags) == 2


def test_two_distinct_functions_is_enough():
    two = f'''
def a():
    return """{_LONG_SQL}"""
def b():
    return """{_LONG_SQL}"""
'''
    assert len(_check(two)) == 1
    three = f'''
def a():
    return """{_LONG_SQL}"""
def b():
    return """{_LONG_SQL}"""
def c():
    return """{_LONG_SQL}"""
'''
    assert len(_check(three)) == 2


def test_flags_constraint_name_across_methods():
    constraint = "custom_scenario_organization_id_name_key"
    assert len(constraint) >= 40
    src = f"""
class Store:
    def upsert(self):
        return "{constraint}"
    def update(self):
        return "{constraint}"
    def delete(self):
        return "{constraint}"
"""
    assert len(_check(src)) == 2


def test_allows_single_occurrence():
    src = f'def x():\n    return """{_LONG_SQL}"""\n'
    assert _check(src) == []


def test_allows_repeated_short_literal():
    src = """
def a():
    return "utf-8"
def b():
    return "utf-8"
"""
    assert _check(src) == []


def test_ignores_unstructured_prose_across_functions():
    msg = "Phone number must contain only digits and an optional leading plus sign"
    assert len(msg) >= 40
    src = f"""
def a():
    raise ValueError("{msg}")
def b():
    raise ValueError("{msg}")
"""
    assert _check(src) == []


def test_ignores_coincidental_error_message_pair_same_function():
    shared = "The AI generated an invalid response format. Please try again."
    src = f"""
def get_user_error_message(code):
    return {{
        "JSON_PARSE_ERROR": "{shared}",
        "VALIDATION_FAILED": "{shared}",
    }}[code]
"""
    assert _check(src) == []


def test_ignores_lowercase_from_in_prose():
    prose = "Extract success criteria from the system prompt and evaluate them"
    assert len(prose) >= 40
    src = f"""
def a():
    return "{prose}"
def b():
    return "{prose}"
"""
    assert _check(src) == []


def test_ignores_same_function_duplicate():
    src = f'''
def only_here():
    first = """{_LONG_SQL}"""
    second = """{_LONG_SQL}"""
    return first, second
'''
    assert _check(src) == []


def test_ignores_module_level_only_duplicate():
    src = f'''
A = """{_LONG_SQL}"""
B = """{_LONG_SQL}"""
'''
    assert _check(src) == []


def test_allows_repeated_fstring_fragments():
    src = """
def a(x):
    return f"SELECT * FROM task WHERE organization_id = {x} AND status = 'x'"

def b(x):
    return f"SELECT * FROM task WHERE organization_id = {x} AND status = 'x'"
"""
    assert _check(src) == []


def test_flags_repeated_format_template_across_functions():
    template = "SELECT {fields} FROM task WHERE organization_id = %(org)s"
    src = f"""
def get():
    return "{template}".format(fields="id")

def list_all():
    return "{template}".format(fields="id, status")

def count():
    return "{template}".format(fields="count(*)")
"""
    assert len(_check(src)) == 2


def test_excludes_function_docstrings():
    doc = "SELECT id, name, created_at FROM organization WHERE active = true"
    src = f'''
def a():
    """{doc}"""

def b():
    """{doc}"""
'''
    assert _check(src) == []


def test_module_and_class_docstrings_do_not_add_occurrences():
    src = f'''"""{_LONG_SQL}"""
class Store:
    """{_LONG_SQL}"""

def a():
    return """{_LONG_SQL}"""

def b():
    return """{_LONG_SQL}"""
'''
    diags = _check(src)
    assert len(diags) == 1


def test_excludes_description_scaffolding_across_functions():
    desc = "Tool identifier. Valid values: transfer-to-human, end-call, custom-api"
    src = f"""
def a():
    return Field(description="{desc}")

def b():
    return Field(description="{desc}")
"""
    assert _check(src) == []


def test_excludes_examples_scaffolding_across_functions():
    src = f"""
def a():
    return Field(examples=["{_LONG_SQL}"])

def b():
    return Field(examples=["{_LONG_SQL}"])
"""
    assert _check(src) == []


def test_excludes_title_and_summary_scaffolding_across_functions():
    text = "SELECT id FROM organization ORDER BY created_at DESC"
    src = f"""
def a():
    return Field(title="{text}")

def b():
    return Field(title="{text}")

def c():
    return Field(summary="{text}")

def d():
    return Field(summary="{text}")
"""
    assert _check(src) == []


def test_skips_test_files_and_conftest():
    src = f'''
def a():
    return """{_LONG_SQL}"""
def b():
    return """{_LONG_SQL}"""
'''
    assert _check(src, filename="test_module.py") == []
    assert _check(src, filename="conftest.py") == []
    assert _check(src, filename="tests/factories.py") == []


def test_skips_generated_files_by_header_and_path():
    src = f'''
def a():
    return """{_LONG_SQL}"""
def b():
    return """{_LONG_SQL}"""
'''
    assert _check(f"# Code generated by protoc. DO NOT EDIT.\n{src}") == []
    assert _check(src, filename="src/generated/client.py") == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("def broken(:\n") == []


def test_message_previews_are_truncated():
    long_value = "SELECT " + "x" * 120
    src = f"""
def a():
    return "{long_value}"
def b():
    return "{long_value}"
def c():
    return "{long_value}"
"""
    diags = _check(src)
    assert len(diags) == 2
    assert "x" * 41 not in diags[0].message


def test_flags_newline_sql_across_two_methods():
    src = f'''
class Store:
    def a(self):
        return """{_LONG_SQL}"""
    def b(self):
        return """{_LONG_SQL}"""
    def c(self):
        return """{_LONG_SQL}"""
'''
    assert len(_check(src)) == 2


def test_flags_dotted_identifier_across_functions():
    ident = "organization.custom_scenario.name_index.key_x"
    assert len(ident) >= 40
    src = f"""
def a():
    return "{ident}"
def b():
    return "{ident}"
def c():
    return "{ident}"
"""
    assert len(_check(src)) == 2


def test_flags_long_route_template_across_functions():
    route = "/api/v2/organizations/{organization_id}/memberships"
    assert len(route) >= 40
    src = f"""\
def get_memberships():
    return "{route}"

def replace_memberships():
    return "{route}"
"""
    assert len(_check(src)) == 1


def test_route_like_prose_with_whitespace_is_not_structured():
    text = "/api routes are intentionally described here for callers"
    assert len(text) >= 40
    src = f"""\
def first():
    return "{text}"

def second():
    return "{text}"
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("/" * 45, id="punctuation-divider"),
        pytest.param("a" * 39, id="identifier-below-length-floor"),
    ],
)
def test_unstructured_or_short_value_is_not_flagged(value: str):
    src = f"""\
def first():
    return "{value}"

def second():
    return "{value}"
"""
    assert _check(src) == []


def test_flags_lambda_bodies_in_two_functions():
    src = f'''
def a():
    return (lambda: """{_LONG_SQL}""")()
def b():
    return (lambda: """{_LONG_SQL}""")()
def c():
    return (lambda: """{_LONG_SQL}""")()
'''
    assert len(_check(src)) == 2


def test_flags_nested_function_versus_outer_body():
    src = f'''
def outer():
    def inner():
        return """{_LONG_SQL}"""
    return inner, """{_LONG_SQL}"""
def sibling():
    return """{_LONG_SQL}"""
'''
    assert len(_check(src)) == 2


def test_allows_two_module_level_lambdas():
    src = f'''
f = lambda: """{_LONG_SQL}"""
g = lambda: """{_LONG_SQL}"""
'''
    assert _check(src) == []


def test_scaffolding_exclusion_is_per_occurrence_not_per_value():
    text = "SELECT id FROM organization ORDER BY created_at DESC"
    src = f"""
def a():
    return Field(description="{text}")
def b():
    return "{text}"
def c():
    return "{text}"
def d():
    return "{text}"
"""
    assert len(_check(src)) == 2


def test_scaffolding_copy_plus_single_plain_copy_is_not_flagged():
    text = "SELECT id FROM organization ORDER BY created_at DESC"
    src = f"""
def a():
    return Field(description="{text}")
def b():
    return "{text}"
"""
    assert _check(src) == []


def test_length_alone_is_insufficient_without_structure():
    unstructured = "SomeMixedCaseThingWithoutSpacesFortyPlusXX"
    assert len(unstructured) >= 40
    src = f"""
def a():
    return "{unstructured}"
def b():
    return "{unstructured}"
"""
    assert _check(src) == []


def test_identifier_at_length_floor_is_flagged():
    ident40 = "a" * 40
    src = f"""
def a():
    return "{ident40}"
def b():
    return "{ident40}"
def c():
    return "{ident40}"
"""
    assert len(_check(src)) == 2


def test_module_level_plus_single_function_should_not_flag():
    src = f'''
A = """{_LONG_SQL}"""
def f():
    return """{_LONG_SQL}"""
'''
    assert _check(src) == []


_FORWARD_REF = "pkg.subpkg.models.orders.line_item_snapshot"
assert len(_FORWARD_REF) >= 40


def test_excludes_doc_metadata_in_parameter_annotations():
    src = f'''
def get(response_model: Annotated[str, Doc("""{_LONG_SQL}""")] = None): ...
def put(response_model: Annotated[str, Doc("""{_LONG_SQL}""")] = None): ...
def post(response_model: Annotated[str, Doc("""{_LONG_SQL}""")] = None): ...
'''
    assert _check(src) == []


def test_excludes_deprecated_metadata_in_parameter_annotations():
    src = f'''
def query(regex: Annotated[str, deprecated("""{_LONG_SQL}""")] = None): ...
def header(regex: Annotated[str, deprecated("""{_LONG_SQL}""")] = None): ...
'''
    assert _check(src) == []


def test_excludes_annotated_metadata_under_dotted_typing_alias():
    src = f'''
def a(x: typing.Annotated[str, Doc("""{_LONG_SQL}""")] = None): ...
def b(x: typing.Annotated[str, Doc("""{_LONG_SQL}""")] = None): ...
'''
    assert _check(src) == []


def test_excludes_annotated_metadata_in_return_annotations():
    src = f'''
def a() -> Annotated[str, Doc("""{_LONG_SQL}""")]: ...
def b() -> Annotated[str, Doc("""{_LONG_SQL}""")]: ...
'''
    assert _check(src) == []


def test_excludes_annotated_metadata_in_variable_annotations():
    src = f'''
def a():
    x: Annotated[str, Doc("""{_LONG_SQL}""")] = ""
def b():
    x: Annotated[str, Doc("""{_LONG_SQL}""")] = ""
'''
    assert _check(src) == []


def test_excludes_annotated_metadata_in_module_type_aliases():
    src = f'''
First = Annotated[str, Doc("""{_LONG_SQL}""")]
Second = Annotated[str, Doc("""{_LONG_SQL}""")]

def a():
    return """{_LONG_SQL}"""
'''
    assert _check(src) == []


def test_excludes_string_forward_reference_annotations():
    src = f"""
def a(x: "{_FORWARD_REF}"): ...
def b(x: "{_FORWARD_REF}"): ...
"""
    assert _check(src) == []


def test_annotation_guard_does_not_exempt_the_same_value_used_at_runtime():
    src = f'''
def a(x: Annotated[str, Doc("""{_LONG_SQL}""")] = None):
    return """{_LONG_SQL}"""
def b():
    return """{_LONG_SQL}"""
'''
    assert len(_check(src)) == 1


def test_annotation_guard_does_not_exempt_parameter_defaults():
    src = f'''
def a(sql: Annotated[str, Doc("doc")] = """{_LONG_SQL}"""): ...
def b(sql: Annotated[str, Doc("doc")] = """{_LONG_SQL}"""): ...
'''
    assert len(_check(src)) == 1


def test_annotation_guard_does_not_exempt_a_forward_ref_used_as_a_key():
    src = f"""
def a():
    return "{_FORWARD_REF}"
def b():
    return "{_FORWARD_REF}"
"""
    assert len(_check(src)) == 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        "WONTFIX (precision): a lone uppercase SQL keyword in prose ('...FROM the menu...') "
        "reads as structural. Tightening to require SQL-ish adjacency would create real-SQL "
        "false-negatives for bare 'GROUP BY col' / 'ORDER BY col' / single-clause fragments, "
        "so the FP is kept over risking missed real drift."
    ),
)
def test_uppercase_sql_keyword_in_prose_should_not_flag():
    prose = "Please choose one option FROM the menu list below now"
    assert len(prose) >= 40
    src = f"""
def a():
    return "{prose}"
def b():
    return "{prose}"
def c():
    return "{prose}"
"""
    assert _check(src) == []


# Cross-package parity with the TS twin                                        # (`packages/typescript/src/rules/no-repeated-string-literal.ts`).


def test_exactly_two_occurrences_in_two_functions_fires():
    src = f'''
def submit_financial_info():
    return """{_LONG_SQL}"""

def submit_legal_info():
    return """{_LONG_SQL}"""
'''
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ024"


def test_two_occurrences_inside_one_function_does_not_fire():
    src = f'''
def only_one():
    a = """{_LONG_SQL}"""
    b = """{_LONG_SQL}"""
    return a, b
'''
    assert _check(src) == []


def test_reuses_unique_public_module_constant_from_one_function():
    src = f'''QUERY = """{_LONG_SQL}"""

def load():
    return execute("""{_LONG_SQL}""")
'''
    [diagnostic] = _check(src)
    assert diagnostic.line == 6
    assert "`QUERY`" in diagnostic.message
    assert "reuse the canonical constant" in diagnostic.message


def test_annotated_public_module_constant_is_canonical():
    src = f'''QUERY: Final[str] = """{_LONG_SQL}"""

def load():
    return execute("""{_LONG_SQL}""")
'''
    [diagnostic] = _check(src)
    assert diagnostic.line == 6
    assert "`QUERY`" in diagnostic.message


def test_canonical_constant_may_be_declared_after_the_function():
    src = f'''def load():
    return execute("""{_LONG_SQL}""")

QUERY = """{_LONG_SQL}"""
'''
    [diagnostic] = _check(src)
    assert diagnostic.line == 2


def test_every_function_copy_reuses_the_canonical_constant():
    src = f'''QUERY = """{_LONG_SQL}"""

def one():
    return execute("""{_LONG_SQL}""")

def two():
    return execute("""{_LONG_SQL}""")
'''
    diagnostics = _check(src)
    assert [diagnostic.line for diagnostic in diagnostics] == [6, 11]
    assert all("`QUERY`" in diagnostic.message for diagnostic in diagnostics)


@pytest.mark.parametrize("name", ["_QUERY", "query", "Query", "QUERY_"])
def test_non_public_or_non_upper_snake_binding_is_not_canonical(name: str):
    src = f'''{name} = """{_LONG_SQL}"""

def load():
    return execute("""{_LONG_SQL}""")
'''
    assert _check(src) == []


def test_ambiguous_canonical_constant_names_are_not_guessed():
    src = f'''QUERY = """{_LONG_SQL}"""
FALLBACK_QUERY = """{_LONG_SQL}"""

def load():
    return execute("""{_LONG_SQL}""")
'''
    assert _check(src) == []


def test_constant_inside_control_flow_is_not_a_module_canonical():
    src = f'''if enabled:
    QUERY = """{_LONG_SQL}"""

def load():
    return execute("""{_LONG_SQL}""")
'''
    assert _check(src) == []


def test_class_constant_is_not_a_module_canonical():
    src = f'''class Queries:
    QUERY = """{_LONG_SQL}"""

def load():
    return execute("""{_LONG_SQL}""")
'''
    assert _check(src) == []


def test_unstructured_public_constant_does_not_arm_reuse():
    value = "a deliberately long but otherwise ordinary prose sentence here"
    assert len(value) >= 40
    src = f"""MESSAGE = "{value}"

def load():
    return emit("{value}")
"""
    assert _check(src) == []
