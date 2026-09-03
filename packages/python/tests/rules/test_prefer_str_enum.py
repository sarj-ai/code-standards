from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import main
from sarj_python_lint.rule_base import RuleExample, Severity
from sarj_python_lint.rules.prefer_str_enum import PreferStrEnum


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "<t>.py") -> list[Diagnostic]:
    return PreferStrEnum().check(Path(path), source)


_PUBLIC_EXAMPLES = PreferStrEnum.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferStrEnum().check(Path(focus.path), focus.source)) == example.expected_count


def test_flags_choice_attr_with_str_field():
    src = """
from pydantic import BaseModel

class Order(BaseModel):
    statuses = ("pending", "shipped", "delivered")
    status: str = "pending"
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize("attr", ["choices", "values", "allowed"])
def test_all_choices_attr_names_corroborate_free_name(attr: str):
    src = f"""
from pydantic import BaseModel

class Rec(BaseModel):
    {attr} = ("a", "b")
    label: str = "a"
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(("attr", "field"), [("states", "state"), ("statuses", "status")])
def test_role_named_choice_collections_only_corroborate_the_matching_field(attr: str, field: str):
    src = f"""
class Rec:
    {attr} = ("a", "b")
    label: str = "a"
    {field}: str = "a"
"""
    [diag] = _check(src)
    assert f"`{field}: str`" in diag.message


@pytest.mark.parametrize("coll", ['["a", "b"]', '("a", "b")', '{"a", "b"}'])
def test_choices_collection_list_tuple_set(coll: str):
    src = f"""
from pydantic import BaseModel

class Rec(BaseModel):
    choices = {coll}
    label: str = "a"
"""
    assert len(_check(src)) == 1


def test_django_choice_pairs_ignore_the_none_blank_sentinel():
    src = """
class Record:
    status: str
    status_choices = ((None, "---"), ("active", "Active"), ("disabled", "Disabled"))
"""
    assert len(_check(src)) == 1


def test_django_choice_mapping_ignores_the_none_blank_sentinel():
    src = """
class Record:
    status: str
    status_choices = {None: "---", "active": "Active", "disabled": "Disabled"}
"""
    assert len(_check(src)) == 1


def test_choice_field_accepts_a_local_structural_string_alias():
    src = """
Text = str
class Record:
    status: Text
    status_choices = ("active", "disabled")
"""
    assert len(_check(src)) == 1


def test_choice_field_and_comparison_cluster_report_once():
    src = """
class Record:
    status: str
    status_choices = ("active", "disabled")
    def enabled(self) -> bool:
        return self.status == "active" or self.status == "disabled"
"""
    assert len(_check(src)) == 1


def test_choices_attr_name_is_case_insensitive():
    src = """
from pydantic import BaseModel

class Rec(BaseModel):
    CHOICES = ["a", "b"]
    label: str = "a"
"""
    assert len(_check(src)) == 1


def test_choices_attr_annassign_form_corroborates():
    src = """
from pydantic import BaseModel

class Rec(BaseModel):
    choices: list = ["a", "b"]
    label: str = "a"
"""
    assert len(_check(src)) == 1


def test_empty_choices_collection_is_not_evidence():
    src = """
from pydantic import BaseModel

class Rec(BaseModel):
    choices = []
    label: str
"""
    assert _check(src) == []


def test_choices_does_not_fan_out_to_unrelated_fields():
    src = """
from pydantic import BaseModel

class Rec(BaseModel):
    choices = ["a", "b"]
    label: str
    caption: str
"""
    assert _check(src) == []


def test_non_string_collection_does_not_corroborate():
    src = """
from pydantic import BaseModel

class Rec(BaseModel):
    choices = [1, 2, 3]
    label: str
"""
    assert _check(src) == []


def test_scalar_string_choices_does_not_corroborate():
    src = """
from pydantic import BaseModel

class Rec(BaseModel):
    choices = "active"
    label: str
"""
    assert _check(src) == []


def test_unrecognised_collection_attr_does_not_corroborate():
    src = """
from pydantic import BaseModel

class Rec(BaseModel):
    options = ["a", "b"]
    label: str
"""
    assert _check(src) == []


def test_choices_attr_without_str_field_is_silent():
    src = """
from pydantic import BaseModel

class Rec(BaseModel):
    choices = ["a", "b"]
    count: int
"""
    assert _check(src) == []


def test_field_col_offset_is_reported():
    src = """
from pydantic import BaseModel

class Rec(BaseModel):
    choices = ["a", "b"]
    status: str = "a"
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 6
    assert diags[0].col == 5


@pytest.mark.parametrize("ann", ["list[str]", "dict[str, str]", "tuple[str, ...]"])
def test_non_bare_str_annotation_not_flagged(ann: str):
    src = f"""
from pydantic import BaseModel
from typing import Optional

class Rec(BaseModel):
    choices = ["a", "b"]
    status: {ann}
"""
    assert _check(src) == []


@pytest.mark.parametrize("ann", ["str | None", "Optional[str]", "Annotated[str, Meta()]"])
def test_optional_or_annotated_choice_field_still_flags(ann: str):
    src = f"""
from typing import Annotated, Optional

class Rec:
    choices = ["a", "b"]
    status: {ann} = "a"
"""
    assert len(_check(src)) == 1


def test_stringized_str_annotation_choice_field_should_flag():
    src = """
from pydantic import BaseModel

class Rec(BaseModel):
    choices = ["a", "b"]
    status: "str" = "a"
"""
    assert len(_check(src)) == 1


def test_bare_assignment_without_annotation_not_flagged():
    src = """
from pydantic import BaseModel

class Rec(BaseModel):
    choices = ["a", "b"]
    status = "pending"
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "field",
    ["status", "state", "kind", "role", "priority", "severity", "direction", "tier", "stage", "type", "mode"],
)
def test_bare_choice_like_name_alone_not_flagged(field: str):
    src = f"""
from pydantic import BaseModel

class Config(BaseModel):
    {field}: str
"""
    assert _check(src) == []


def test_bare_status_suffix_name_not_flagged():
    src = """
from pydantic import BaseModel

class Call(BaseModel):
    payment_status: str
    call_direction: str
"""
    assert _check(src) == []


@pytest.mark.parametrize("field", ["name", "email", "provider_name", "description", "url"])
def test_free_text_names_not_flagged(field: str):
    src = f"""
from pydantic import BaseModel

class User(BaseModel):
    {field}: str
"""
    assert _check(src) == []


def test_allows_literal_type():
    src = """
from pydantic import BaseModel
from typing import Literal

class Order(BaseModel):
    status: Literal["pending", "shipped", "delivered"]
"""
    assert _check(src) == []


def test_does_not_flag_enum_class():
    src = """
from enum import StrEnum

class Status(StrEnum):
    pending = "pending"
"""
    assert _check(src) == []


@pytest.mark.parametrize("base", ["Enum", "StrEnum", "IntEnum", "enum.StrEnum", "enum.Enum"])
def test_enum_bases_are_all_skipped(base: str):
    src = f"""
class Status({base}):
    choices = ["a", "b"]
    state: str
    active = "active"
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "declaration",
    [
        "from enum import Enum as E\nclass Status(str, E):",
        "from enum import Flag as E\nclass Status(str, E):",
        "from enum import IntFlag as E\nclass Status(str, E):",
        "from enum import ReprEnum as E\nclass Status(str, E):",
        "import enum as e\nclass Status(str, e.Enum):",
        "from enum import Enum\nE = Enum\nclass Status(str, E):",
        "from enum import Enum\nE = Enum\nE2 = E\nclass Status(str, E2):",
        "from enum import Enum\nclass Base(str, Enum):\n    pass\nclass Status(Base):",
        "from company import StringEnum\nclass Status(StringEnum):",
        "from company import StringEnum as ChoicesBase\nclass Status(ChoicesBase):",
        "import company as shared\nclass Status(shared.BaseEnum):",
    ],
)
def test_imported_aliased_and_inherited_enum_bases_are_skipped(declaration: str):
    src = f"""{declaration}
    choices = ["a", "b"]
    state: str = "a"
"""
    assert _check(src) == []


def test_nested_stdlib_enum_alias_is_skipped():
    src = """
def build():
    from enum import Enum as E

    class Status(str, E):
        choices = ["a", "b"]
        state: str = "a"
"""
    assert _check(src) == []


def test_explicit_stub_file_is_skipped():
    src = """
class Record:
    choices = ["a", "b"]
    state: str = "a"
"""
    assert _check(src, "models.pyi") == []


def test_allows_single_comparison():
    src = """
def handle(status: str) -> bool:
    return status == "active"
"""
    assert _check(src) == []


def test_allows_repeated_same_literal():
    src = """
def handle(status: str) -> bool:
    if status == "active":
        pass
    return status == "active"
"""
    assert _check(src) == []


def test_allows_uppercase_literal_cluster():
    src = """
def handle(code: str) -> int:
    if code == "ACTIVE":
        return 1
    if code == "INACTIVE":
        return 2
    return 0
"""
    assert _check(src) == []


def test_allows_long_literal_cluster():
    src = """
def handle(msg: str) -> int:
    if msg == "this-is-a-very-long-free-text-message-not-a-token":
        return 1
    if msg == "another-extremely-long-free-text-message-here-too":
        return 2
    return 0
"""
    assert _check(src) == []


def test_one_bad_literal_disqualifies_the_cluster():
    src = """
def handle(status: str) -> int:
    if status == "active":
        return 1
    if status == "Not A Token!":
        return 2
    if status == "inactive":
        return 3
    return 0
"""
    assert _check(src) == []


def test_ignores_fstring_and_attribute_comparands():
    src = """
def handle(status: str, expected: str) -> int:
    if status == f"{expected}-suffix":
        return 1
    if status == Status.ACTIVE:
        return 2
    return 0
"""
    assert _check(src) == []


def test_ignores_subscripted_left_hand_side():
    src = """
def handle(payload: dict) -> int:
    if payload["status"] == "active":
        return 1
    if payload["status"] == "inactive":
        return 2
    return 0
"""
    assert _check(src) == []


def test_distinct_variables_do_not_form_a_cluster():
    src = """
def handle(a: str, b: str) -> int:
    if a == "active":
        return 1
    if b == "inactive":
        return 2
    return 0
"""
    assert _check(src) == []


def test_clusters_do_not_span_functions():
    src = """
def first(status: str) -> bool:
    return status == "active"

def second(status: str) -> bool:
    return status == "inactive"
"""
    assert _check(src) == []


def test_module_level_comparisons_not_flagged():
    src = """
import sys

if sys.platform == "linux":
    X = 1
elif sys.platform == "darwin":
    X = 2
"""
    assert _check(src) == []


@pytest.mark.parametrize("path", ["test_handlers.py", "pkg/tests/handlers.py"])
def test_comparison_cluster_skipped_in_test_files(path: str):
    src = """
def handle(status: str) -> int:
    if status == "active":
        return 1
    if status == "inactive":
        return 2
    return 0
"""
    assert _check(src, path=path) == []


def test_sibling_choices_still_applies_in_test_files():
    src = """
from pydantic import BaseModel

class Order(BaseModel):
    choices = ["a", "b"]
    payment_status: str = "a"
"""
    assert len(_check(src, path="test_models.py")) == 1


def test_mid_uppercase_literal_disqualifies_cluster():
    src = """
def handle(status: str) -> int:
    if status == "activeState":
        return 1
    if status == "inactive":
        return 2
    return 0
"""
    assert _check(src) == []


def test_thirtytwo_char_token_disqualifies_cluster():
    long = "a" + "b" * 31
    assert len(long) == 32
    src = f"""
def handle(s: str) -> int:
    if s == "active":
        return 1
    if s == "{long}":
        return 2
    return 0
"""
    assert _check(src) == []


def test_external_attribute_membership_not_flagged():
    src = """
def build(url) -> None:
    if url.scheme not in ("http", "https", "socks5", "socks5h"):
        raise ValueError()
"""
    assert _check(src) == []


def test_external_attribute_equality_cluster_not_flagged():
    src = """
def read(field) -> int:
    if field.mode == "validation":
        return 1
    if field.mode == "serialization":
        return 2
    return 0
"""
    assert _check(src) == []


def test_deep_attribute_chain_not_flagged():
    src = """
def handle(ctx) -> int:
    if ctx.call.direction == "inbound":
        return 1
    if ctx.call.direction == "outbound":
        return 2
    return 0
"""
    assert _check(src) == []


def test_reflection_key_membership_not_flagged():
    src = """
def show(cert) -> None:
    for name in cert:
        if name in ("subject", "issuer"):
            print(name)
"""
    assert _check(src) == []


def test_reflection_dunder_dict_membership_not_flagged():
    src = """
def copy(self) -> None:
    for name in self.__dict__:
        if name not in ["extensions", "stream"]:
            continue
"""
    assert _check(src) == []


def test_file_mode_membership_not_flagged():
    src = """
def opener(mode: str) -> None:
    if mode not in {"r", "rt", "rb"}:
        raise ValueError()
"""
    assert _check(src) == []


def test_lone_membership_in_tuple_not_flagged():
    src = """
def handle(status: str) -> bool:
    return status in ("active", "pending")
"""
    assert _check(src) == []


@pytest.mark.parametrize("coll", ['["active", "pending"]', '{"active", "pending"}', '("active", "pending")'])
def test_lone_membership_all_containers_not_flagged(coll: str):
    src = f"""
def handle(status: str) -> bool:
    return status in {coll}
"""
    assert _check(src) == []


def test_lone_not_in_membership_not_flagged():
    src = """
def handle(status: str) -> bool:
    return status not in {"active", "pending"}
"""
    assert _check(src) == []


def test_upstream_role_membership_not_flagged():
    src = """
def route(role: str) -> int:
    if role in ("user", "assistant", "system"):
        return 1
    return 0
"""
    assert _check(src) == []


def test_metric_field_name_membership_not_flagged():
    src = """
def prune(k: str) -> bool:
    return k not in ["diff_ms", "total_ms"]
"""
    assert _check(src) == []


def test_in_single_literal_below_boundary():
    src = """
def handle(status: str) -> bool:
    return status in ("active",)
"""
    assert _check(src) == []


def test_empty_membership_container_not_flagged():
    src = """
def handle(status: str) -> bool:
    return status in ()
"""
    assert _check(src) == []


def test_membership_against_a_variable_collection_not_flagged():
    src = """
def handle(status: str, allowed) -> bool:
    return status in allowed
"""
    assert _check(src) == []


def test_membership_against_non_literal_elements_not_flagged():
    src = """
def handle(status: str, a, b) -> bool:
    return status in (a, b)
"""
    assert _check(src) == []


def test_duplicate_literals_inside_in_tuple_do_not_reach_threshold():
    src = """
def handle(status: str) -> bool:
    return status in ("active", "active")
"""
    assert _check(src) == []


def test_single_char_scanner_cluster_not_flagged():
    src = """
def stem(last_char: str) -> int:
    if last_char == "g":
        return 1
    if last_char == "y":
        return 2
    return 0
"""
    assert _check(src) == []


def test_language_keyword_tokenizer_not_flagged():
    src = """
def parse(token: str) -> int:
    if token == "is":
        return 1
    if token == "not":
        return 2
    if token == "in":
        return 3
    return 0
"""
    assert _check(src) == []


def test_module_alias_literal_param_not_flagged():
    src = """
from typing import Literal

Mode = Literal["left", "center", "right"]

def render(align: Mode) -> int:
    if align == "left":
        return 1
    if align == "center":
        return 2
    if align == "right":
        return 3
    return 0
"""
    assert _check(src) == []


def test_module_alias_literal_valueset_not_flagged():
    src = """
from typing import Literal

AlignMethod = Literal["left", "center", "right"]

class Align:
    def render(self):
        align = self.align
        def emit():
            if align == "left":
                return 1
            elif align == "center":
                return 2
            elif align == "right":
                return 3
            return 0
        return emit
"""
    assert _check(src) == []


def test_inline_literal_param_cluster_not_flagged():
    src = """
from typing import Literal

def handle(status: Literal["active", "inactive"]) -> int:
    if status == "active":
        return 1
    if status == "inactive":
        return 2
    return 0
"""
    assert _check(src) == []


def test_typealias_statement_literal_not_flagged():
    src = """
from typing import Literal

type Mode = Literal["on", "off"]

def toggle(mode: Mode) -> int:
    if mode == "on":
        return 1
    if mode == "off":
        return 2
    return 0
"""
    assert _check(src) == []


@pytest.mark.parametrize("name", ["language", "lang", "country", "currency", "timezone", "locale", "region", "code"])
def test_open_domain_code_cluster_not_flagged(name: str):
    src = f"""
def regions({name}: str) -> int:
    if {name} == "en":
        return 1
    if {name} == "zh":
        return 2
    if {name} == "es":
        return 3
    return 0
"""
    assert _check(src) == []


def test_open_domain_field_not_flagged_via_cluster():
    src = """
from pydantic import BaseModel

class Prefs(BaseModel):
    language: str

def pick(language: str) -> int:
    if language == "en":
        return 1
    if language == "ar":
        return 2
    return 0
"""
    assert _check(src) == []


def test_truthy_fallback_that_consumes_subject_keeps_domain_open() -> None:
    src = """
def section(chip: str | None = None) -> str:
    if chip == "national":
        return "National"
    elif chip == "no-year":
        return "No year"
    elif chip:
        return render(chip)
    return ""
"""
    assert _check(src) == []


def test_inherited_self_attribute_is_not_treated_as_locally_owned() -> None:
    src = """
class View(ModelViewSet):
    def select(self):
        if self.action == "list":
            return ListSerializer
        if self.action == "retrieve":
            return DetailSerializer
        return DefaultSerializer
"""
    assert _check(src) == []


def test_call_comparand_excluded():
    src = """
def handle(status: str) -> int:
    if status == default():
        return 1
    if status == fallback():
        return 2
    return 0
"""
    assert _check(src) == []


def test_non_string_constant_comparand_excluded():
    src = """
def handle(code: str) -> int:
    if code == 1:
        return 1
    if code == 2:
        return 2
    return 0
"""
    assert _check(src) == []


def test_chained_comparison_excluded():
    src = """
def handle(status: str) -> bool:
    return "active" == status == "inactive"
"""
    assert _check(src) == []


def test_subscript_on_right_hand_side_excluded():
    src = """
def handle(status: str, data: dict) -> int:
    if status == data["x"]:
        return 1
    if status == data["y"]:
        return 2
    return 0
"""
    assert _check(src) == []


def test_empty_string_literal_disqualifies_cluster():
    src = """
def handle(status: str) -> int:
    if status == "":
        return 1
    if status == "active":
        return 2
    return 0
"""
    assert _check(src) == []


def test_walrus_target_in_comparison_is_not_clustered():
    src = """
def handle(get) -> int:
    if (s := get()) == "active":
        return 1
    if s == "inactive":
        return 2
    return 0
"""
    assert _check(src) == []


def test_nested_function_isolates_outer_cluster():
    src = """
def outer(status: str) -> int:
    if status == "active":
        return 1
    def inner(status: str) -> int:
        if status == "inactive":
            return 2
        return 0
    return inner(status)
"""
    assert _check(src) == []


def test_lambda_comparisons_are_not_attributed():
    src = """
def build():
    return lambda s: 1 if s == "active" else (2 if s == "inactive" else 0)
"""
    assert _check(src) == []


def test_class_nested_in_function_resets_the_cluster_scope():
    src = """
def outer(status):
    class C:
        y = status == "active"
    if status == "inactive":
        return 2
"""
    assert _check(src) == []


def test_wildcard_capture_still_keeps_the_match_domain_open():
    src = """
def handle(status: str) -> str:
    match status:
        case "active" as selected:
            return selected
        case unknown:
            return unknown
"""
    assert _check(src) == []


def test_match_as_class_pattern_is_not_a_string_domain():
    src = """
def handle(status: str) -> str:
    match status:
        case Status() as selected:
            return str(selected)
        case OtherStatus() as selected:
            return str(selected)
"""
    assert _check(src) == []


def test_match_with_ordinary_wildcard_fallback_keeps_domain_open() -> None:
    src = """
def render(content_type: str, payload: dict[str, str]) -> str:
    match content_type:
        case "text":
            return payload["text"]
        case "image" | "video":
            return f"[{content_type}]"
        case _:
            return payload.get("content", "")
"""
    assert _check(src) == []


def test_match_with_capture_fallback_keeps_domain_open() -> None:
    src = """
def render(kind: str) -> str:
    match kind:
        case "text":
            return "Text"
        case "image":
            return "Image"
        case unknown:
            return unknown.title()
"""
    assert _check(src) == []


def test_match_with_raising_wildcard_remains_a_closed_domain() -> None:
    src = """
def render(kind: str) -> str:
    match kind:
        case "text":
            return "Text"
        case "image":
            return "Image"
        case _:
            raise ValueError(kind)
"""
    assert len(_check(src)) == 1


def test_match_with_assert_never_wildcard_remains_a_closed_domain() -> None:
    src = """
from typing import assert_never

def render(kind: str) -> str:
    match kind:
        case "text":
            return "Text"
        case "image":
            return "Image"
        case _:
            assert_never(kind)
"""
    assert len(_check(src)) == 1


def test_match_case_single_string_pattern_does_not_cluster():
    src = """
def handle(status: str) -> int:
    match status:
        case "active":
            return 1
        case _:
            return 0
"""
    assert _check(src) == []


def test_match_case_class_patterns_do_not_cluster():
    src = """
def handle(event: object) -> int:
    match event:
        case Foo():
            return 1
        case Bar():
            return 2
    return 0
"""
    assert _check(src) == []


def test_match_on_attribute_subject_not_flagged():
    src = """
def handle(obj) -> int:
    match obj.kind:
        case "active":
            return 1
        case "inactive":
            return 2
    return 0
"""
    assert _check(src) == []


def test_empty_source_returns_empty():
    assert _check("") == []


def test_syntax_error_returns_empty():
    assert _check("def broken(:\n    pass\n") == []


@pytest.mark.parametrize("path", ["app/generated/client.py", "app/vendor/client.py"])
def test_generated_or_vendored_files_are_exempt(path: str):
    src = 'def route(kind: str):\n    return 1 if kind == "a" else 2 if kind == "b" else 0\n'
    assert _check(src, path=path) == []


def test_generated_banner_is_exempt():
    src = '# This file is auto-generated. Do not edit.\ndef route(kind: str):\n    return kind == "a" or kind == "b"\n'
    assert _check(src) == []


def test_destructured_wire_values_remain_open_vocabulary():
    src = """
def route(payload: dict[str, object]) -> int:
    kind, value = payload["pair"]
    if kind == "a":
        return 1
    if kind == "b":
        return 2
    return 0
"""
    assert _check(src) == []


def test_chained_wire_assignment_remains_open_vocabulary():
    src = """
def route(payload: dict[str, object]) -> int:
    kind = alias = payload.get("kind")
    if kind == "a":
        return 1
    if kind == "b":
        return 2
    return 0
"""
    assert _check(src) == []


def test_transformed_wire_value_remains_open_vocabulary():
    src = """
def route(payload: dict[str, object]) -> int:
    kind = payload.get("kind").strip().lower()
    if kind == "a":
        return 1
    if kind == "b":
        return 2
    return 0
"""
    assert _check(src) == []


def test_string_coerced_wire_value_remains_open_vocabulary():
    src = """
def route(item: dict[str, object]) -> int:
    kind = str(item.get("kind"))
    if kind == "a":
        return 1
    if kind == "b":
        return 2
    return 0
"""
    assert _check(src) == []


def test_cast_wire_value_remains_open_vocabulary():
    src = """
from typing import cast

def route(item: dict[str, object]) -> int:
    kind = cast(str, item.get("kind"))
    if kind == "a":
        return 1
    if kind == "b":
        return 2
    return 0
"""
    assert _check(src) == []


def test_transformed_foreign_call_remains_open_vocabulary():
    src = """
import platform

def route() -> int:
    os_type = platform.system().lower()
    if os_type == "windows":
        return 1
    if os_type == "darwin":
        return 2
    return 0
"""
    assert _check(src) == []


def test_annotated_nominal_enum_parameter_is_not_retreated_as_a_string():
    src = """
from typing import Annotated

def route(status: Annotated[Status, Meta()]) -> int:
    if status == "a":
        return 1
    if status == "b":
        return 2
    return 0
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "annotation",
    ["Literal['a', 'b'] | None", "Annotated[Literal['a', 'b'], Meta()]", "Union[Literal['a'], Literal['b']]"],
)
def test_wrapped_literal_annotation_is_already_closed(annotation: str):
    src = f"""
def route(status: {annotation}) -> int:
    if status == "a":
        return 1
    if status == "b":
        return 2
    return 0
"""
    assert _check(src) == []


def test_wire_provenance_survives_fallback_expression():
    src = """
def route(payload) -> int:
    kind = payload.kind or "unknown"
    if kind == "a":
        return 1
    if kind == "b":
        return 2
    return 0
"""
    assert _check(src) == []


def test_comprehension_target_does_not_merge_with_enclosing_name():
    src = """
def route(kind: str, values: list[str]) -> bool:
    outer = kind == "outer"
    inner = [kind == "inner" for kind in values]
    return outer or any(inner)
"""
    assert _check(src) == []


def test_generic_choices_do_not_fan_out_by_shared_default_value():
    src = """
class Widget:
    choices = ["small", "large"]
    label: str = "small"
    status: str = "small"
"""
    assert _check(src) == []


def test_named_status_choices_associate_with_status_only():
    src = """
class Widget:
    STATUS_CHOICES = ["small", "large"]
    label: str = "small"
    status: str = "small"
"""
    [diag] = _check(src)
    assert diag.line == 5


def test_named_status_choices_associate_without_a_literal_default():
    src = """
class Widget:
    STATUS_CHOICES = ["small", "large"]
    status: str
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "choices",
    ["[('draft', 'Draft'), ('live', 'Live')]", "{'draft': 'Draft', 'live': 'Live'}"],
)
def test_named_django_choice_shapes_associate_with_the_field(choices: str):
    src = f"""
class Widget:
    STATUS_CHOICES = {choices}
    status: str
"""
    assert len(_check(src)) == 1


def test_captured_literal_annotation_stays_closed_in_nested_function():
    src = """
def outer(status: Literal["a", "b"]):
    def inner() -> int:
        if status == "a":
            return 1
        if status == "b":
            return 2
        return 0
    return inner()
"""
    assert _check(src) == []


@pytest.mark.parametrize("element", ["Status", "Literal['a', 'b']"])
def test_comprehension_target_inherits_closed_iterable_element_type(element: str):
    src = f"""
def route(values: list[{element}]) -> list[bool]:
    return [status == "a" or status == "b" for status in values]
"""
    assert _check(src) == []


def test_flattened_pep604_literal_union_is_already_closed():
    src = """
def route(status: Literal["a"] | Literal["b"] | None) -> int:
    if status == "a":
        return 1
    if status == "b":
        return 2
    return 0
"""
    assert _check(src) == []


def test_subscript_bound_variable_is_exempt():
    # Minimized from pydantic's _schema_gather.py: `schema['type']` is another
    # system's wire format — a StrEnum cannot be imposed on it.
    src = """
def traverse(schema):
    schema_type = schema['type']
    if schema_type == 'definition-ref':
        return 1
    elif schema_type == 'definitions':
        return 2
"""
    assert _check(src) == []


def test_get_bound_variable_is_exempt():
    # Minimized from pydantic's json_schema.py `extra_fields_behavior` read.
    src = """
def handle(schema):
    extra = schema.get('config', {}).get('extra_fields_behavior')
    if extra == 'forbid':
        return False
    elif extra == 'allow':
        return True
"""
    assert _check(src) == []


def test_wire_compatibility_helper_bound_variable_is_exempt():
    src = """
def handle(message):
    item_type = get_mapping_or_attr(message, "type")
    if item_type == "program":
        return 1
    elif item_type == "program_output":
        return 2
"""
    assert _check(src) == []


def test_walrus_subscript_bound_variable_is_exempt():
    src = """
def walk(inner_schema):
    if (inner_schema_type := inner_schema['type']) == 'list':
        return 1
    if inner_schema_type == 'json-or-python':
        return 2
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "annotation",
    ["JustifyMethod", '"JustifyMethod"', "AlignMethod | None", "Optional[AlignMethod]", "rich.AlignMethod"],
)
def test_separately_typed_parameter_is_exempt(annotation: str):
    # Minimized from rich/rich/containers.py:129 — `JustifyMethod` is a Literal
    # alias declared in rich/console.py and imported here, so the closed set
    # already exists at a definition site this module does not own.
    src = f"""
def justify(text, justify: {annotation}) -> int:
    if justify == "left":
        return 1
    elif justify == "center":
        return 2
    return 0
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "annotation",
    [
        'Literal["auto", "required", "none"] | str',
        'Literal["auto", "required", "none"] | str | None',
        'Union[Literal["auto", "required", "none"], str, None]',
    ],
)
def test_literal_plus_arbitrary_str_annotation_is_an_explicitly_open_domain(annotation: str):
    src = f"""
def convert(tool_choice: {annotation}) -> str:
    if tool_choice == "auto":
        return "automatic"
    if tool_choice == "required":
        return "forced"
    if tool_choice == "none":
        return "disabled"
    return tool_choice
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "name",
    ["name", "attr", "attribute", "action_name", "event_name", "extension", "key", "tool_name", "user_input"],
)
def test_generic_open_domain_names_are_not_inferred_as_enums(name: str):
    src = f"""
def inspect({name}: str) -> str:
    if {name} == "source_agent":
        return "source"
    if {name} == "target_agent":
        return "target"
    return {name}
"""
    assert _check(src) == []


def test_value_derived_from_a_typed_name_is_exempt():
    # Minimized from rich/rich/text.py:874.
    src = """
def truncate(self, overflow: OverflowMethod | None = None) -> int:
    _overflow = overflow or self.overflow or DEFAULT_OVERFLOW
    if _overflow != "ignore":
        return 1
    if _overflow == "ellipsis":
        return 2
    return 0
"""
    assert _check(src) == []


def test_value_from_a_literal_returning_local_function_is_exempt():
    # Minimized from pydantic/pydantic/_internal/_generate_schema.py:2833.
    src = """
def _inlining_behavior(ref) -> Literal['inline', 'keep', 'preserve_metadata']:
    return 'keep'


def finalize(ref) -> int:
    behavior = _inlining_behavior(ref)
    if behavior == 'inline':
        return 1
    if behavior == 'preserve_metadata':
        return 2
    return 0
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    ("binding", "var"),
    [
        ("node_type = token.type", "node_type"),
        ("node_type = leaf.value", "node_type"),
        ("node_type = cls.__config__.node_type", "node_type"),
        ('node_type = os.getenv("NODE_TYPE")', "node_type"),
        ('node_type = next(tokens, "")', "node_type"),
        ("node_type = tokens.pop(0)", "node_type"),
    ],
)
def test_locals_bound_from_a_foreign_read_are_exempt(binding: str, var: str):
    # The direct form (`token.type == "text"`) never fired; aliasing it to a
    # local must not change the answer.
    src = f"""
def render(token, tokens, cls) -> int:
    {binding}
    if {var} == "text":
        return 1
    elif {var} == "hardbreak":
        return 2
    return 0
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "loop",
    [
        "for k, _v in obj.items():",
        "for k in obj.keys():",
        "for _i, (k, _v) in enumerate(obj.items()):",
        "for _arg, k in zip(obj.args, obj.arg_names):",
        "for k in sorted(obj._fields):",
        "for k in obj.field_names:",
    ],
)
def test_loop_targets_over_foreign_iterables_are_exempt(loop: str):
    # Minimized from pydantic/pydantic/_internal/_core_utils.py:117,
    # pydantic/pydantic/mypy.py:1096 and black/src/black/parsing.py:218.
    src = f"""
def walk(obj) -> int:
    {loop}
        if k == "metadata":
            return 1
        elif k == "targets":
            return 2
    return 0
"""
    assert _check(src) == []


@pytest.mark.parametrize("name", ["mode", "_mode", "file_mode", "open_mode"])
def test_open_mode_vocabulary_is_exempt(name: str):
    # Minimized from flask/src/flask/app.py:437 and rich/rich/progress.py:1345.
    src = f"""
def open_resource({name}: str = "rb"):
    if {name} not in {{"r", "rt", "rb"}}:
        raise ValueError({name})
    if {name} == "rb":
        return 1
    return 2
"""
    assert _check(src) == []


def test_self_and_cls_comparison_is_reflection():
    # Minimized from pydantic/pydantic/v1/class_validators.py:268.
    src = """
def make_validator(args) -> int:
    first_arg = args[0]
    if first_arg == 'self':
        raise ConfigError('no self')
    elif first_arg == 'cls':
        return 1
    return 0
"""
    assert _check(src) == []


def test_equality_and_inequality_on_different_literals_do_not_enumerate():
    # Minimized from fastapi/docs_src/dependencies/tutorial008c_py310.py:19 —
    # two independent guards, not a dispatch over a domain.
    src = """
def get_item(item_id: str) -> int:
    if item_id == "portal-gun":
        raise InternalError(item_id)
    if item_id != "plumbus":
        raise HTTPException(status_code=404)
    return 1
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "name",
    [
        "ext",
        "media_ext",
        "encoding",
        "fs_encoding",
        "protocol",
        "username",
        "date_str",
        "default_search",
        "format_key",
    ],
)
def test_standard_open_vocabulary_names_are_not_inferred_as_enums(name: str):
    src = f"""
def inspect({name}: str) -> str:
    if {name} == "first":
        return "one"
    if {name} == "second":
        return "two"
    return {name}
"""
    assert _check(src) == []


def test_runtime_membership_proves_the_domain_is_dynamic():
    src = """
def select(client: str, allowed_clients: set[str]) -> str:
    if client == "default":
        return "web"
    if client == "all":
        return "every"
    if client not in allowed_clients:
        return "unsupported"
    return client
"""
    assert _check(src) == []


def test_traverse_obj_result_remains_a_wire_domain():
    src = """
def parse(payload) -> str:
    item_type = traverse_obj(payload, "type")
    if item_type == "video":
        return "movie"
    if item_type == "youtube":
        return "embed"
    return "other"
"""
    assert _check(src) == []


def test_traverse_obj_loop_targets_remain_wire_domains():
    src = """
def parse(payload) -> str:
    for item_type, item in traverse_obj(payload, ("items", {dict.items}, ...)):
        if item_type == "video":
            return item
        if item_type == "youtube":
            return item
    return ""
"""
    assert _check(src) == []


def test_regex_extractor_result_remains_a_wire_domain():
    src = r"""
def parse(html: str) -> str:
    provider = r1(r"type=(\w+)", html)
    if provider == "youku":
        return "one"
    if provider == "tudou":
        return "two"
    return provider
"""
    assert _check(src) == []


def test_literal_typed_class_attribute_is_already_closed():
    src = """
from typing import Literal

class McpConfig:
    transport: Literal["streamable-http", "stdio"] = "streamable-http"

    def validate(self) -> None:
        if self.transport == "stdio":
            return
        if self.transport == "streamable-http":
            return
"""
    assert _check(src) == []


def test_if_chain_with_rejecting_else_reports_warning() -> None:
    src = """
def render(kind: str) -> str:
    if kind == "text":
        return "Text"
    elif kind == "image":
        return "Image"
    else:
        log_error(kind)
        raise ValueError(kind)
"""
    [diagnostic] = _check(src)
    assert diagnostic.severity is Severity.WARNING
    assert "named `Literal` alias or `StrEnum`" in diagnostic.message


def test_if_chain_with_open_fallback_is_excluded() -> None:
    src = """
def render(kind: str) -> str:
    if kind == "text":
        return "Text"
    elif kind == "image":
        return "Image"
    return render_plugin(kind)
"""
    assert _check(src) == []


def test_truthy_fallback_is_open_even_when_body_ignores_subject() -> None:
    src = """
def render(kind: str) -> str:
    if kind == "text":
        return "Text"
    elif kind == "image":
        return "Image"
    elif kind:
        return "Plugin"
    return "Default"
"""
    assert _check(src) == []


def test_pure_inequality_does_not_prove_an_accepted_domain() -> None:
    src = """
def valid(kind: str) -> bool:
    if kind != "text":
        return False
    if kind != "image":
        return False
    raise ValueError(kind)
"""
    assert _check(src) == []


def test_match_without_wildcard_is_not_proven_closed() -> None:
    src = """
def render(kind: str) -> str:
    match kind:
        case "text":
            return "Text"
        case "image":
            return "Image"
    return render_plugin(kind)
"""
    assert _check(src) == []


def test_match_with_rejecting_wildcard_reports() -> None:
    src = """
def render(kind: str) -> str:
    match kind:
        case "text":
            return "Text"
        case "image":
            return "Image"
        case _:
            logger.error("unsupported")
            raise ValueError(kind)
"""
    assert len(_check(src)) == 1


def test_match_with_proven_assert_never_reports() -> None:
    src = """
from typing import assert_never

def render(kind: str) -> str:
    match kind:
        case "text":
            return "Text"
        case "image":
            return "Image"
        case _:
            assert_never(kind)
"""
    assert len(_check(src)) == 1


def test_shadowed_assert_never_does_not_prove_rejection() -> None:
    src = """
def assert_never(value):
    return value

def render(kind: str) -> str:
    match kind:
        case "text":
            return "Text"
        case "image":
            return "Image"
        case _:
            assert_never(kind)
"""
    assert _check(src) == []


def test_rejecting_not_in_guard_reports() -> None:
    src = """
def render(kind: str) -> str:
    if kind not in {"text", "image"}:
        raise ValueError(kind)
    return kind
"""
    assert len(_check(src)) == 1


def test_rejecting_if_chain_nested_under_optional_guard_is_open() -> None:
    src = """
def render(kind: str, strict: bool) -> str:
    if strict:
        if kind == "text":
            return "Text"
        elif kind == "image":
            return "Image"
        else:
            raise ValueError(kind)
    return render_plugin(kind)
"""
    assert _check(src) == []


def test_rejecting_match_nested_under_optional_guard_is_open() -> None:
    src = """
def render(kind: str, strict: bool) -> str:
    if strict:
        match kind:
            case "text":
                return "Text"
            case "image":
                return "Image"
            case _:
                raise ValueError(kind)
    return render_plugin(kind)
"""
    assert _check(src) == []


def test_caught_rejecting_if_chain_is_open() -> None:
    src = """
def render(kind: str) -> str:
    try:
        if kind == "text":
            return "Text"
        elif kind == "image":
            return "Image"
        else:
            raise ValueError(kind)
    except ValueError:
        return render_plugin(kind)
"""
    assert _check(src) == []


def test_caught_rejecting_membership_guard_is_open() -> None:
    src = """
def render(kind: str) -> str:
    try:
        if kind not in {"text", "image"}:
            raise ValueError(kind)
    except ValueError:
        return render_plugin(kind)
    return kind
"""
    assert _check(src) == []


def test_rejecting_membership_guard_after_open_return_is_open() -> None:
    src = """
def render(kind: str) -> str:
    if plugin(kind):
        return forward(kind)
    if kind not in {"text", "image"}:
        raise ValueError(kind)
    return kind
"""
    assert _check(src) == []


def test_rejecting_if_chain_after_open_return_is_open() -> None:
    src = """
def render(kind: str) -> str:
    if plugin(kind):
        return forward(kind)
    if kind == "text":
        return "Text"
    elif kind == "image":
        return "Image"
    else:
        raise ValueError(kind)
"""
    assert _check(src) == []


def test_rejecting_match_after_open_return_is_open() -> None:
    src = """
def render(kind: str) -> str:
    if plugin(kind):
        return forward(kind)
    match kind:
        case "text":
            return "Text"
        case "image":
            return "Image"
        case _:
            raise ValueError(kind)
"""
    assert _check(src) == []


def test_closed_domain_dominance_scans_a_long_prefix_linearly(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def counted_fallthrough(_statement: object) -> bool:
        nonlocal calls
        calls += 1
        return True

    monkeypatch.setattr(
        "sarj_python_lint.rules.prefer_str_enum._statement_always_falls_through",
        counted_fallthrough,
    )
    prefix = "\n".join(f"    value_{index} = {index}" for index in range(250))
    src = f"""
def render(kind: str) -> str:
{prefix}
    if kind == "text":
        return "Text"
    elif kind == "image":
        return "Image"
    else:
        raise ValueError(kind)
    """

    assert len(_check(src)) == 1
    assert calls == 251


def test_shadowed_str_annotation_is_excluded() -> None:
    src = """
str = int

class Order:
    statuses = ("pending", "shipped")
    status: str = 1
"""
    assert _check(src) == []


def test_proven_string_alias_choice_field_reports() -> None:
    src = """
Text = str

class Order:
    statuses = ("pending", "shipped")
    status: Text = "pending"
"""
    assert len(_check(src)) == 1


def test_rebound_string_alias_choice_field_is_excluded() -> None:
    src = """
Text = str
Text = int

class Order:
    statuses = ("pending", "shipped")
    status: Text = "pending"
"""
    assert _check(src) == []


def test_exact_suppression_is_honored() -> None:
    src = """
class Order:
    statuses = ("pending", "shipped")
    status: str = "pending"  # sarj-noqa: SARJ006
"""
    assert _check(src) == []


def test_cli_reports_nonblocking_warning(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "order.py"
    target.write_text(
        'class Order:\n    statuses = ("pending", "shipped")\n    status: str = "pending"\n',
        encoding="utf-8",
    )

    assert main(["check", "--rule", "prefer-str-enum", str(target)]) == 0
    assert "SARJ006 warning:" in capsys.readouterr().out
