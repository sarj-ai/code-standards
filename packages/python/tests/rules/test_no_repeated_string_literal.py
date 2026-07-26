from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_repeated_string_literal import NoRepeatedStringLiteral


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic

_LONG_SQL = "\n                SELECT id, name, created_at FROM organization\n            "
assert len(_LONG_SQL) >= 40


def _check(source: str, filename: str = "module.py") -> list[Diagnostic]:
    return NoRepeatedStringLiteral().check(Path(filename), source)


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
    """Cross-function drift begins at two copies; there is no separate occurrence count."""
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
    """The JSON_PARSE_ERROR / VALIDATION_FAILED coincidental-coupling regression."""
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
    """SQL keyword match is case-sensitive so prose containing 'from' is not structural."""
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


def test_allows_repeated_docstring():
    doc = "This docstring is deliberately identical across both functions here."
    src = f'''
def a():
    """{doc}"""

def b():
    """{doc}"""
'''
    assert _check(src) == []


def test_excludes_field_description_scaffolding():
    desc = "Tool identifier. Valid values: transfer-to-human, end-call, custom-api"
    src = f"""
class A(BaseModel):
    slug: str = Field(description="{desc}")

class B(BaseModel):
    slug: str = Field(description="{desc}")
"""
    assert _check(src) == []


def test_excludes_field_examples_scaffolding():
    src = f"""
class A(BaseModel):
    id: str = Field(examples=["{_LONG_SQL}"])

class B(BaseModel):
    id: str = Field(examples=["{_LONG_SQL}"])
"""
    assert _check(src) == []


def test_excludes_title_and_summary_scaffolding():
    text = "SELECT id FROM organization ORDER BY created_at DESC"
    src = f"""
class A(BaseModel):
    a: str = Field(title="{text}")
    b: str = Field(summary="{text}")
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


def test_flags_lambda_bodies_in_two_functions():
    """Lambda does not push a scope; each lambda inherits its enclosing function, so two distinct enclosers still flag."""
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
    """Module-level lambdas share the module scope, so they are excluded like module constants."""
    src = f'''
f = lambda: """{_LONG_SQL}"""
g = lambda: """{_LONG_SQL}"""
'''
    assert _check(src) == []


def test_scaffolding_exclusion_is_per_occurrence_not_per_value():
    """A description= copy is dropped, but two plain copies of the same literal still couple and flag."""
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


def test_identifier_below_length_floor_not_flagged():
    ident39 = "a" * 39
    src = f"""
def a():
    return "{ident39}"
def b():
    return "{ident39}"
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
    """FastAPI copies the same Doc() paragraph onto every verb; 494 of 499 corpus findings."""
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


def test_excludes_string_forward_reference_annotations():
    src = f"""
def a(x: "{_FORWARD_REF}"): ...
def b(x: "{_FORWARD_REF}"): ...
"""
    assert _check(src) == []


def test_annotation_guard_does_not_exempt_the_same_value_used_at_runtime():
    """The Doc() copy is dropped, but two runtime copies of the same literal still couple."""
    src = f'''
def a(x: Annotated[str, Doc("""{_LONG_SQL}""")] = None):
    return """{_LONG_SQL}"""
def b():
    return """{_LONG_SQL}"""
'''
    assert len(_check(src)) == 1


def test_annotation_guard_does_not_exempt_parameter_defaults():
    """A default sits in `arguments.defaults`, beside the annotation, not inside it."""
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
