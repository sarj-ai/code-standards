from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_str_enum import PreferStrEnum


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "<t>.py") -> list[Diagnostic]:
    return PreferStrEnum().check(Path(path), source)


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
    """A field name alone is too weak — a free-form `status: str` must not fire."""
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


def test_field_corroborated_by_cluster_on_same_name():
    src = """
from pydantic import BaseModel

class Order(BaseModel):
    kind: str

def route(kind: str) -> int:
    if kind == "menu":
        return 1
    if kind == "submenu":
        return 2
    return 0
"""
    diags = _check(src)
    assert len(diags) == 1
    assert [d.line for d in diags] == sorted(d.line for d in diags)


def test_field_not_corroborated_when_cluster_is_on_a_different_name():
    src = """
from pydantic import BaseModel

class Order(BaseModel):
    status: str

def route(kind: str) -> int:
    if kind == "menu":
        return 1
    if kind == "submenu":
        return 2
    return 0
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "kind" in diags[0].message


def test_flags_comparison_cluster():
    src = """
def handle(status: str) -> int:
    if status == "active":
        return 1
    if status == "inactive":
        return 2
    return 0
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3
    assert "status" in diags[0].message
    assert "StrEnum" in diags[0].message


def test_local_kind_dispatch_single_char_fires():
    """The must-preserve true positive: a genuine two-way dispatch on a local."""
    src = """
def route(kind: str) -> int:
    if kind == "a":
        return 1
    elif kind == "b":
        return 2
    return 0
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "kind" in diags[0].message


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


def test_yoda_comparisons_count():
    src = """
def handle(status: str) -> int:
    if "active" == status:
        return 1
    if "inactive" == status:
        return 2
    return 0
"""
    assert len(_check(src)) == 1


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
    """Only the comparison-cluster trigger is test-file-scoped."""
    src = """
from pydantic import BaseModel

class Order(BaseModel):
    choices = ["a", "b"]
    payment_status: str = "a"
"""
    assert len(_check(src, path="test_models.py")) == 1


def test_pure_not_equal_cluster():
    src = """
def handle(status: str) -> int:
    if status != "active":
        return 1
    if status != "inactive":
        return 2
    return 0
"""
    assert len(_check(src)) == 1


def test_mixed_eq_and_in_operators_form_one_cluster():
    """Merge a membership test and an equality comparison into one cluster."""
    src = """
def handle(status: str) -> int:
    if status == "active":
        return 1
    if status in ("pending", "queued"):
        return 2
    return 0
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "status" in diags[0].message


def test_exactly_two_distinct_literals_is_the_boundary():
    src = """
def handle(status: str) -> int:
    if status == "on":
        return 1
    if status == "off":
        return 2
    return 0
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize("lit", ["in-progress", "not_started", "v2", "a-b-c_d"])
def test_hyphen_and_underscore_tokens_still_cluster(lit: str):
    src = f"""
def handle(status: str) -> int:
    if status == "{lit}":
        return 1
    if status == "done":
        return 2
    return 0
"""
    assert len(_check(src)) == 1


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


def test_thirtyone_char_token_clusters():
    t1 = "a" + "b" * 30
    t2 = "c" + "d" * 30
    assert len(t1) == 31
    src = f"""
def handle(s: str) -> int:
    if s == "{t1}":
        return 1
    if s == "{t2}":
        return 2
    return 0
"""
    assert len(_check(src)) == 1


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
    """Httpx `_config.py`: `url.scheme not in ("http", "https", "socks5", ...)`."""
    src = """
def build(url) -> None:
    if url.scheme not in ("http", "https", "socks5", "socks5h"):
        raise ValueError()
"""
    assert _check(src) == []


def test_external_attribute_equality_cluster_not_flagged():
    """Fastapi `_compat/v2.py`: `field.mode == "validation"` — pydantic-core attr."""
    src = """
def read(field) -> int:
    if field.mode == "validation":
        return 1
    if field.mode == "serialization":
        return 2
    return 0
"""
    assert _check(src) == []


def test_owned_self_attribute_cluster_flags():
    src = """
class Worker:
    def run(self) -> int:
        if self.status == "active":
            return 1
        if self.status == "inactive":
            return 2
        return 0
"""
    assert len(_check(src)) == 1


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
    """Httpx `_main.py`: `name in ("subject", "issuer")` over an ssl cert dict."""
    src = """
def show(cert) -> None:
    for name in cert:
        if name in ("subject", "issuer"):
            print(name)
"""
    assert _check(src) == []


def test_reflection_dunder_dict_membership_not_flagged():
    """Httpx `_models.py`: `name not in ["extensions", "stream"]` over __dict__."""
    src = """
def copy(self) -> None:
    for name in self.__dict__:
        if name not in ["extensions", "stream"]:
            continue
"""
    assert _check(src) == []


def test_file_mode_membership_not_flagged():
    """Flask `blueprints.py` / `app.py`: `mode not in {"r", "rt", "rb"}`."""
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
    """An LLM message-role membership check is a lone guard, not an app enum."""
    src = """
def route(role: str) -> int:
    if role in ("user", "assistant", "system"):
        return 1
    return 0
"""
    assert _check(src) == []


def test_metric_field_name_membership_not_flagged():
    """Metric/log field-name keys are not a value enum."""
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
    """Django `defaultfilters`: `last_char == "g"` is a char scan, not an enum."""
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
    """Django `smartif`: `token == "is" / "not" / "in"` is a keyword vocabulary."""
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


def test_non_scanner_single_char_cluster_still_fires():
    """A single-char dispatch on a non-scanner variable (grades) is a real enum."""
    src = """
def grade(g: str) -> int:
    if g == "a":
        return 4
    if g == "b":
        return 3
    return 0
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "g" in diags[0].message


def test_module_alias_literal_param_not_flagged():
    """A param annotated with a module-level `Literal` alias is already closed."""
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
    """Rich `align.py`: `align = self.align` compared against the alias's values."""
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
    """Home Assistant `language.py`: `if language == "en": elif language == "zh":`."""
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


def test_genuine_closed_choice_cluster_still_fires_alongside_alias():
    """An unrelated closed-choice dispatch still fires when an alias exists."""
    src = """
from typing import Literal

AlignMethod = Literal["left", "center", "right"]

def route(kind: str) -> int:
    if kind == "menu":
        return 1
    if kind == "submenu":
        return 2
    return 0
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "kind" in diags[0].message


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


def test_yoda_form_joins_the_same_cluster():
    src = """
def handle(status: str) -> int:
    if "active" == status:
        return 1
    if status == "inactive":
        return 2
    return 0
"""
    assert len(_check(src)) == 1


def test_not_equal_pair_enumerates_the_domain():
    src = """
def handle(status: str) -> int:
    if status != "active" and status != "inactive":
        return 0
    return 1
"""
    assert len(_check(src)) == 1


def test_comparison_reports_first_line_and_col():
    src = """
def handle(status: str) -> int:
    if status == "active":
        return 1
    if status == "inactive":
        return 2
    return 0
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3
    assert diags[0].col == 8


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


def test_nested_function_has_its_own_cluster():
    src = """
def outer() -> int:
    def inner(status: str) -> int:
        if status == "active":
            return 1
        if status == "inactive":
            return 2
        return 0
    return inner("active")
"""
    assert len(_check(src)) == 1


def test_lambda_comparisons_are_not_attributed():
    src = """
def build():
    return lambda s: 1 if s == "active" else (2 if s == "inactive" else 0)
"""
    assert _check(src) == []


def test_async_function_cluster():
    src = """
async def handle(status: str) -> int:
    if status == "active":
        return 1
    if status == "inactive":
        return 2
    return 0
"""
    assert len(_check(src)) == 1


def test_method_plain_local_cluster_fires():
    src = """
class Worker:
    def run(self, status: str) -> int:
        if status == "active":
            return 1
        if status == "inactive":
            return 2
        return 0
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "status" in diags[0].message


def test_method_accumulates_across_a_nested_helper_def():
    src = """
class W:
    def run(self, status: str) -> int:
        if status == "active":
            return 1
        def helper(status: str) -> int:
            if status == "inactive":
                return 2
            return 0
        if status == "pending":
            return 3
        return 0
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 4
    assert "status" in diags[0].message


def test_class_nested_in_function_resets_the_cluster_scope():
    src = """
def outer(status):
    class C:
        y = status == "active"
    if status == "inactive":
        return 2
"""
    assert _check(src) == []


def test_comprehension_condition_clusters_within_its_function():
    src = """
def f(items):
    return [x for x in items if x == "active" or x == "inactive"]
"""
    assert len(_check(src)) == 1


def test_decorator_expression_comparisons_attribute_to_decorated_function():
    src = """
def outer(status):
    @deco(status == "active" or status == "inactive")
    def inner():
        return 1
    return inner
"""
    assert len(_check(src)) == 1


def test_match_case_string_patterns_should_cluster():
    src = """
def handle(status: str) -> int:
    match status:
        case "active":
            return 1
        case "inactive":
            return 2
    return 0
"""
    assert len(_check(src)) == 1


def test_match_case_or_patterns_cluster():
    src = """
def handle(status: str) -> int:
    match status:
        case "active" | "pending":
            return 1
        case "closed":
            return 2
    return 0
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


def test_match_case_combines_with_compare_on_same_subject():
    src = """
def handle(status: str) -> int:
    if status == "active":
        return 3
    match status:
        case "inactive":
            return 2
    return 0
"""
    assert len(_check(src)) == 1


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


def test_field_and_cluster_coexist_and_sort_by_position():
    src = """
from pydantic import BaseModel

class Order(BaseModel):
    choices = ["a", "b"]
    status: str = "a"

def route(kind: str) -> int:
    if kind == "a":
        return 1
    if kind == "b":
        return 2
    return 0
"""
    diags = _check(src)
    assert len(diags) == 2
    assert [diagnostic.line for diagnostic in diags] == sorted(diagnostic.line for diagnostic in diags)


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


def test_comprehension_shadow_does_not_inherit_outer_foreign_opacity():
    src = """
def route(kind: Status, values: list[str]) -> list[bool]:
    return [kind == "a" or kind == "b" for kind in values]
"""
    assert len(_check(src)) == 1


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


@pytest.mark.parametrize("declaration", ["Status = str", "Status = TypeAliasType('Status', str)"])
def test_structural_string_alias_remains_an_open_string(declaration: str):
    src = f"""
{declaration}
def route(status: Status) -> int:
    if status == "a":
        return 1
    if status == "b":
        return 2
    return 0
"""
    assert len(_check(src)) == 1


# FP-hardening (famous-repo sweep): wire-bound variables (subscript / .get()). #


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


def test_walrus_subscript_bound_variable_is_exempt():
    src = """
def walk(inner_schema):
    if (inner_schema_type := inner_schema['type']) == 'list':
        return 1
    if inner_schema_type == 'json-or-python':
        return 2
"""
    assert _check(src) == []


def test_plain_parameter_cluster_still_fires():
    src = """
def dispatch(kind):
    if kind == 'ingest':
        return 1
    elif kind == 'export':
        return 2
"""
    assert len(_check(src)) == 1


# FP-hardening (famous-repo sweep): domains defined somewhere else.           #


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


@pytest.mark.parametrize("annotation", ["str", '"str"', "str | None", "Optional[str]"])
def test_str_annotated_parameter_still_fires(annotation: str):
    src = f"""
def handle(status: {annotation}) -> int:
    if status == "active":
        return 1
    elif status == "inactive":
        return 2
    return 0
"""
    assert len(_check(src)) == 1


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


def test_value_from_an_untyped_local_function_still_fires():
    src = """
def classify(ref):
    return 'inline'


def finalize(ref) -> int:
    behavior = classify(ref)
    if behavior == 'inline':
        return 1
    if behavior == 'keep':
        return 2
    return 0
"""
    assert len(_check(src)) == 1


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


def test_local_bound_from_an_own_attribute_still_fires():
    # `self.kind` is this class's own field — a StrEnum here is actionable.
    src = """
def render(self) -> int:
    kind = self.kind
    if kind == "text":
        return 1
    elif kind == "break":
        return 2
    return 0
"""
    assert len(_check(src)) == 1


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


def test_loop_target_over_a_local_list_still_fires():
    src = """
def walk(kinds) -> int:
    for kind in kinds:
        if kind == "ingest":
            return 1
        elif kind == "export":
            return 2
    return 0
"""
    assert len(_check(src)) == 1


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


def test_mode_with_word_values_still_fires():
    src = """
def render(mode: str) -> int:
    if mode == "strict":
        return 1
    elif mode == "lenient":
        return 2
    return 0
"""
    assert len(_check(src)) == 1


def test_single_char_enum_on_a_non_mode_variable_still_fires():
    # The file-mode carve-out keys off the NAME as well as the shape.
    src = """
def grade(g: str) -> int:
    if g == "a":
        return 4
    elif g == "b":
        return 3
    return 0
"""
    assert len(_check(src)) == 1


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


def test_membership_set_corroborates_a_single_equality():
    # Minimized from fastapi/fastapi/routing.py:6367 — the `in` assertion spells
    # out the closed domain the `==` then dispatches over.
    src = """
def add_event_handler(self, event_type: str, func) -> None:
    assert event_type in ("startup", "shutdown")
    if event_type == "startup":
        self.on_startup.append(func)
"""
    assert len(_check(src)) == 1
