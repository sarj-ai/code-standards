from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_match_assert_never import PreferMatchAssertNever


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "python/bulbul/bulbul/calls/dispatch.py") -> list[Diagnostic]:
    return PreferMatchAssertNever().check(Path(path), source)


_ENUM_PREAMBLE = """
from enum import StrEnum

class Status(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    FAILED = "failed"
"""


# --------------------------------------------------------------------------- #
# Detector (a): silent `case _:` behind enum-member arms.                      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "fallthrough",
    ["pass", "return", "return None"],
)
def test_flags_silent_wildcard_behind_member_arms(fallthrough: str):
    src = f"""
from kinds import Kind

def handle(kind):
    match kind:
        case Kind.A:
            do_a()
        case Kind.B:
            do_b()
        case _:
            {fallthrough}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ032"
    assert "case _" in diags[0].message


def test_wildcard_diag_points_at_the_wildcard_case():
    src = """
from kinds import Kind

def handle(kind):
    match kind:
        case Kind.A:
            do_a()
        case Kind.B:
            do_b()
        case _:
            pass
"""
    diags = _check(src)
    assert diags[0].line == 10


def test_flags_member_arms_of_imported_owner():
    # Dotted members of ONE class are a closed set even when the class is imported.
    src = """
from shared.models import Model

def store(model_name, file_id):
    match model_name:
        case Model.AWS:
            set_aws(file_id)
        case Model.GEMINI:
            set_gemini(file_id)
        case _:
            pass
"""
    assert len(_check(src)) == 1


def test_flags_or_pattern_member_arms():
    src = """
from kinds import Kind

def handle(kind):
    match kind:
        case Kind.A | Kind.B:
            ab()
        case Kind.C:
            c()
        case _:
            return None
"""
    assert len(_check(src)) == 1


def test_flags_member_arms_of_aliased_from_import():
    src = """
from shared.models import Model as Kind

def handle(kind):
    match kind:
        case Kind.A:
            a()
        case Kind.B:
            b()
        case _:
            pass
"""
    assert len(_check(src)) == 1


def test_flags_member_arms_of_module_level_class_owner():
    src = """
class Kind:
    A = 1
    B = 2

def handle(kind):
    match kind:
        case Kind.A:
            a()
        case Kind.B:
            b()
        case _:
            pass
"""
    assert len(_check(src)) == 1


def test_flags_local_class_pattern_arms():
    src = """
class Created: ...
class Deleted: ...

def handle(event):
    match event:
        case Created():
            on_created(event)
        case Deleted():
            on_deleted(event)
        case _:
            return None
"""
    assert len(_check(src)) == 1


def test_flags_local_class_pattern_with_capture_and_or():
    src = """
class Created: ...
class Updated: ...
class Deleted: ...

def handle(event):
    match event:
        case Created() as c:
            on_created(c)
        case Updated() | Deleted():
            on_change(event)
        case _:
            pass
"""
    assert len(_check(src)) == 1


def test_flags_nested_match():
    src = """
from kinds import Kind

class Router:
    def route(self, kind):
        if ready:
            match kind:
                case Kind.A:
                    one()
                case Kind.B:
                    two()
                case _:
                    pass
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Detector (a) negatives: loud/value-returning fallthroughs.                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "fallthrough",
    [
        "raise ValueError(kind)",
        "assert_never(kind)",
        "typing.assert_never(kind)",
        "return False",
        'return ""',
        "return 0",
        "return default",
        "log.warning('unknown', kind=kind)",
        "handled = False",
    ],
)
def test_allows_loud_or_value_returning_wildcard(fallthrough: str):
    src = f"""
from kinds import Kind

def handle(kind):
    match kind:
        case Kind.A:
            do_a()
        case Kind.B:
            do_b()
        case _:
            {fallthrough}
"""
    assert _check(src) == []


def test_allows_wildcard_with_multi_statement_body():
    src = """
from kinds import Kind

def handle(kind):
    match kind:
        case Kind.A:
            do_a()
        case Kind.B:
            do_b()
        case _:
            log.info("skip")
            return None
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Detector (a) negatives: open-set arm shapes never qualify.                   #
# --------------------------------------------------------------------------- #


def test_allows_string_literal_arms():
    # Strings routinely come from external/open sources (metric kinds, API values).
    src = """
def handle(kind):
    match kind:
        case "stt_metrics":
            stt()
        case "vad_metrics":
            vad()
        case _:
            pass
"""
    assert _check(src) == []


def test_allows_number_literal_arms():
    src = """
def handle(code):
    match code:
        case 1:
            one()
        case 2:
            two()
        case _:
            pass
"""
    assert _check(src) == []


def test_allows_mapping_pattern_arms():
    src = """
def normalize(payload):
    match payload:
        case {"schedule_configuration": _}:
            a()
        case {"start_time": _, "end_time": _}:
            b()
        case _:
            pass
"""
    assert _check(src) == []


def test_allows_imported_class_pattern_arms():
    # Cannot prove an imported class union is closed — SARJ003's local gate.
    src = """
from events import Created, Deleted

def handle(event):
    match event:
        case Created():
            on_created(event)
        case Deleted():
            on_deleted(event)
        case _:
            pass
"""
    assert _check(src) == []


def test_allows_function_nested_class_pattern_arms():
    # Classes defined inside an unrelated function are not visible where the
    # match dispatches — they must not make it look closed-set.
    src = """
def factory():
    class Created: ...
    class Deleted: ...
    return Created, Deleted

def handle(event):
    match event:
        case Created():
            on_created(event)
        case Deleted():
            on_deleted(event)
        case _:
            pass
"""
    assert _check(src) == []


def test_allows_mixed_owner_member_arms():
    src = """
from kinds import Kind, Other

def handle(x):
    match x:
        case Kind.A:
            a()
        case Other.B:
            b()
        case _:
            pass
"""
    assert _check(src) == []


def test_allows_module_constants_owner():
    # `import constants` binds a MODULE: `constants.CREATED` is a loose
    # module-level constant, not member access on a closed set someone owns.
    src = """
import constants

def handle(state):
    match state:
        case constants.CREATED:
            a()
        case constants.UPDATED:
            b()
        case _:
            pass
"""
    assert _check(src) == []


def test_allows_aliased_module_import_owner():
    src = """
import app.constants as cfg

def handle(state):
    match state:
        case cfg.A:
            a()
        case cfg.B:
            b()
        case _:
            pass
"""
    assert _check(src) == []


def test_allows_plain_variable_owner():
    # `cfg` is a runtime object, not a class — its attributes are not a closed set.
    src = """
def handle(state):
    cfg = load_config()
    match state:
        case cfg.A:
            a()
        case cfg.B:
            b()
        case _:
            pass
"""
    assert _check(src) == []


def test_allows_unbound_owner_name():
    # A name never bound in this module cannot be proven to be a class.
    src = """
def handle(kind):
    match kind:
        case Kind.A:
            a()
        case Kind.B:
            b()
        case _:
            pass
"""
    assert _check(src) == []


def test_allows_default_then_refine_assignment_arms():
    # Defaults set before the match; arms only refine them; wildcard keeps them.
    src = """
from errors import ErrorId

def classify(error_id):
    slug = "generic"
    ui_type = "simple"
    match error_id:
        case ErrorId.AGE_BELOW_18:
            slug = "age_below_18"
            ui_type = "icon"
        case ErrorId.ID_EXPIRED:
            slug = "id_expired"
            ui_type = "icon"
        case _:
            pass
    return slug, ui_type
"""
    assert _check(src) == []


def test_mixed_assignment_and_action_arms_still_flagged():
    src = """
from kinds import Kind

def handle(kind):
    match kind:
        case Kind.A:
            x = 1
        case Kind.B:
            do_b()
        case _:
            pass
"""
    assert len(_check(src)) == 1


def test_allows_guarded_real_arm():
    # A guarded arm deliberately lets its own pattern fall through to `_`.
    src = """
from kinds import Kind

def handle(kind):
    match kind:
        case Kind.A if ready:
            a()
        case Kind.B:
            b()
        case _:
            pass
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Detector (a) negatives: wildcard shape gates.                                #
# --------------------------------------------------------------------------- #


def test_allows_single_real_arm_match():
    src = """
from kinds import Kind

def handle(kind):
    match kind:
        case Kind.A:
            a()
        case _:
            pass
"""
    assert _check(src) == []


def test_allows_capture_name_wildcard():
    src = """
from kinds import Kind

def handle(kind):
    match kind:
        case Kind.A:
            a()
        case Kind.B:
            b()
        case other:
            pass
"""
    assert _check(src) == []


def test_allows_guarded_wildcard():
    src = """
from kinds import Kind

def handle(kind):
    match kind:
        case Kind.A:
            a()
        case Kind.B:
            b()
        case _ if strict:
            pass
"""
    assert _check(src) == []


def test_allows_match_without_wildcard():
    src = """
from kinds import Kind

def handle(kind):
    match kind:
        case Kind.A:
            a()
        case Kind.B:
            b()
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Detector (b): if/elif over a LOCAL enum with a silent else.                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "fallthrough",
    ["pass", "return", "return None"],
)
def test_flags_silent_else_over_local_enum(fallthrough: str):
    src = f"""{_ENUM_PREAMBLE}
def handle(status):
    if status == Status.OPEN:
        open_it()
    elif status == Status.CLOSED:
        close_it()
    else:
        {fallthrough}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "Status" in diags[0].message


def test_flags_in_membership_arms():
    src = f"""{_ENUM_PREAMBLE}
def handle(status):
    if status in (Status.OPEN, Status.CLOSED):
        active()
    elif status == Status.FAILED:
        failed()
    else:
        return None
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "base",
    ["Enum", "IntEnum", "StrEnum", "Flag", "IntFlag", "enum.Enum"],
)
def test_flags_all_enum_family_bases(base: str):
    src = f"""
import enum
from enum import Enum, IntEnum, StrEnum, Flag, IntFlag

class Kind({base}):
    A = 1
    B = 2

def handle(kind):
    if kind == Kind.A:
        a()
    elif kind == Kind.B:
        b()
    else:
        pass
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "fallthrough",
    [
        "raise ValueError(status)",
        "assert_never(status)",
        "return False",
        "return DEFAULT",
        "log.warning('unknown status')",
    ],
)
def test_allows_loud_or_value_returning_else(fallthrough: str):
    src = f"""{_ENUM_PREAMBLE}
def handle(status):
    if status == Status.OPEN:
        open_it()
    elif status == Status.CLOSED:
        close_it()
    else:
        {fallthrough}
"""
    assert _check(src) == []


def test_allows_chain_without_else():
    # Guard-clause chains without `else` are pervasive and often deliberate.
    src = f"""{_ENUM_PREAMBLE}
def handle(status):
    if status == Status.OPEN:
        open_it()
    elif status == Status.CLOSED:
        close_it()
"""
    assert _check(src) == []


def test_allows_single_arm_chain():
    src = f"""{_ENUM_PREAMBLE}
def handle(status):
    if status == Status.OPEN:
        open_it()
    else:
        pass
"""
    assert _check(src) == []


def test_allows_imported_class_members():
    # Imported name: cannot prove it is an enum (could be a constants holder).
    src = """
from models import Status

def handle(status):
    if status == Status.OPEN:
        open_it()
    elif status == Status.CLOSED:
        close_it()
    else:
        pass
"""
    assert _check(src) == []


def test_allows_local_non_enum_class_members():
    src = """
class Codes:
    A = 1
    B = 2

def handle(code):
    if code == Codes.A:
        a()
    elif code == Codes.B:
        b()
    else:
        pass
"""
    assert _check(src) == []


def test_allows_function_nested_enum():
    # An enum defined inside an unrelated function is not visible where the
    # chain dispatches.
    src = """
from enum import StrEnum

def make():
    class Status(StrEnum):
        OPEN = "open"
        CLOSED = "closed"
    return Status

def handle(status):
    if status == Status.OPEN:
        a()
    elif status == Status.CLOSED:
        b()
    else:
        pass
"""
    assert _check(src) == []


def test_flags_enum_chain_behind_null_check_head():
    # A non-enum head (null check first) must not shield the enum sub-chain.
    src = f"""{_ENUM_PREAMBLE}
def handle(status):
    if status is None:
        return
    elif status == Status.OPEN:
        open_it()
    elif status == Status.CLOSED:
        close_it()
    else:
        pass
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "Status" in diags[0].message
    # Points at the first enum arm, not the null-check head.
    assert diags[0].line == 12


def test_allows_assignment_only_chain():
    # Default-then-refine: defaults set before the chain; arms only refine
    # them; the silent else keeps the defaults, which is defined behavior.
    src = f"""{_ENUM_PREAMBLE}
def classify(status):
    label = "generic"
    if status == Status.OPEN:
        label = "open"
    elif status == Status.CLOSED:
        label = "closed"
    else:
        pass
    return label
"""
    assert _check(src) == []


def test_mixed_assignment_and_action_chain_still_flagged():
    src = f"""{_ENUM_PREAMBLE}
def handle(status):
    if status == Status.OPEN:
        label = "open"
    elif status == Status.CLOSED:
        close_it()
    else:
        pass
"""
    assert len(_check(src)) == 1


def test_allows_mixed_variables():
    src = f"""{_ENUM_PREAMBLE}
def handle(a, b):
    if a == Status.OPEN:
        open_it()
    elif b == Status.CLOSED:
        close_it()
    else:
        pass
"""
    assert _check(src) == []


def test_allows_mixed_classes():
    src = f"""{_ENUM_PREAMBLE}
class Other(StrEnum):
    X = "x"

def handle(status):
    if status == Status.OPEN:
        open_it()
    elif status == Other.X:
        x()
    else:
        pass
"""
    assert _check(src) == []


def test_allows_non_eq_operators():
    src = f"""{_ENUM_PREAMBLE}
def handle(status):
    if status != Status.OPEN:
        a()
    elif status != Status.CLOSED:
        b()
    else:
        pass
"""
    assert _check(src) == []


def test_allows_non_member_comparators():
    src = f"""{_ENUM_PREAMBLE}
def handle(status):
    if status == "open":
        a()
    elif status == "closed":
        b()
    else:
        pass
"""
    assert _check(src) == []


def test_elif_arm_not_double_reported():
    src = f"""{_ENUM_PREAMBLE}
def handle(status):
    if status == Status.OPEN:
        a()
    elif status == Status.CLOSED:
        b()
    elif status == Status.FAILED:
        c()
    else:
        pass
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 10


def test_else_with_extra_statement_not_flagged():
    src = f"""{_ENUM_PREAMBLE}
def handle(status):
    if status == Status.OPEN:
        a()
    elif status == Status.CLOSED:
        b()
    else:
        log.info("other")
        return None
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Both detectors together; edge cases.                                         #
# --------------------------------------------------------------------------- #


def test_both_detectors_fire_independently_and_sorted():
    src = f"""{_ENUM_PREAMBLE}
from kinds import Kind

def by_chain(status):
    if status == Status.OPEN:
        a()
    elif status == Status.CLOSED:
        b()
    else:
        pass

def by_match(kind):
    match kind:
        case Kind.A:
            one()
        case Kind.B:
            two()
        case _:
            return None
"""
    diags = _check(src)
    assert len(diags) == 2
    assert [(d.line, d.col) for d in diags] == sorted((d.line, d.col) for d in diags)


@pytest.mark.parametrize("source", ["", "   ", "# comment\n"])
def test_empty_or_trivial_source(source: str):
    assert _check(source) == []


def test_syntax_error_returns_empty():
    assert _check("def f(:\n    pass") == []


# --------------------------------------------------------------------------- #
# Detector (c): handler dict that does not cover the enum.                     #
# --------------------------------------------------------------------------- #


def test_flags_handler_dict_missing_a_member():
    src = _ENUM_PREAMBLE + """
HANDLERS = {Status.OPEN: on_open, Status.CLOSED: on_closed}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ032"
    assert "2 of `Status`'s 3 members" in diags[0].message
    assert "Status.FAILED" in diags[0].message


@pytest.mark.parametrize(
    "values",
    [
        "on_open, Status.CLOSED: on_closed",
        "mod.on_open, Status.CLOSED: mod.on_closed",
        "lambda c: 1, Status.CLOSED: lambda c: 2",
    ],
)
def test_flags_each_handler_shape(values: str):
    src = _ENUM_PREAMBLE + f"\nHANDLERS = {{Status.OPEN: {values}}}\n"
    assert len(_check(src)) == 1


def test_flags_dispatch_map_inside_a_function():
    src = _ENUM_PREAMBLE + """
def build():
    handlers = {Status.OPEN: on_open, Status.CLOSED: on_closed}
    return handlers[Status.OPEN]
"""
    assert len(_check(src)) == 1


def test_flags_annotated_dispatch_map():
    src = _ENUM_PREAMBLE + """
HANDLERS: dict[Status, object] = {Status.OPEN: on_open, Status.CLOSED: on_closed}
"""
    assert len(_check(src)) == 1


def test_complete_map_is_clean():
    src = _ENUM_PREAMBLE + """
HANDLERS = {Status.OPEN: on_open, Status.CLOSED: on_closed, Status.FAILED: on_failed}
"""
    assert _check(src) == []


def test_literal_values_are_a_data_table_not_a_dispatch():
    src = _ENUM_PREAMBLE + """
COLOURS = {Status.OPEN: "green", Status.CLOSED: "grey"}
"""
    assert _check(src) == []


def test_double_star_spread_is_not_flagged():
    src = _ENUM_PREAMBLE + """
HANDLERS = {Status.OPEN: on_open, Status.CLOSED: on_closed, **extra}
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "growth",
    [
        "HANDLERS.update({Status.FAILED: on_failed})",
        "HANDLERS.setdefault(Status.FAILED, on_failed)",
        "HANDLERS[Status.FAILED] = on_failed",
    ],
)
def test_map_grown_later_is_not_flagged(growth: str):
    src = _ENUM_PREAMBLE + f"""
HANDLERS = {{Status.OPEN: on_open, Status.CLOSED: on_closed}}
{growth}
"""
    assert _check(src) == []


def test_imported_enum_is_never_flagged():
    src = """
from kinds import Kind

HANDLERS = {Kind.A: on_a, Kind.B: on_b}
"""
    assert _check(src) == []


def test_non_enum_local_class_is_not_flagged():
    src = """
class Constants:
    A = "a"
    B = "b"
    C = "c"

HANDLERS = {Constants.A: on_a, Constants.B: on_b}
"""
    assert _check(src) == []


def test_single_entry_map_is_below_the_arm_floor():
    src = _ENUM_PREAMBLE + """
HANDLERS = {Status.OPEN: on_open}
"""
    assert _check(src) == []


def test_keys_from_two_owners_are_not_a_closed_dispatch():
    src = _ENUM_PREAMBLE + """
from other import Kind

HANDLERS = {Status.OPEN: on_open, Kind.A: on_a}
"""
    assert _check(src) == []


def test_non_member_key_is_not_flagged():
    src = _ENUM_PREAMBLE + """
HANDLERS = {Status.OPEN: on_open, Status.MISSPELLED: on_other}
"""
    assert _check(src) == []


def test_string_keys_are_not_flagged():
    src = _ENUM_PREAMBLE + """
HANDLERS = {"open": on_open, "closed": on_closed}
"""
    assert _check(src) == []


def test_aliases_do_not_inflate_the_member_count():
    src = """
from enum import StrEnum

class Status(StrEnum):
    OPEN = "open"
    ACTIVE = "open"
    CLOSED = "closed"

HANDLERS = {Status.OPEN: on_open, Status.CLOSED: on_closed}
"""
    assert _check(src) == []


def test_private_and_method_names_are_not_members():
    src = """
from enum import StrEnum

class Status(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    _INTERNAL = "x"

    def label(self) -> str:
        return self.value

HANDLERS = {Status.OPEN: on_open, Status.CLOSED: on_closed}
"""
    assert _check(src) == []


def test_tuple_target_is_not_a_dispatch_map():
    src = _ENUM_PREAMBLE + """
HANDLERS, OTHER = {Status.OPEN: on_open, Status.CLOSED: on_closed}, None
"""
    assert _check(src) == []


def test_all_three_detectors_report_together_sorted():
    src = _ENUM_PREAMBLE + """
HANDLERS = {Status.OPEN: on_open, Status.CLOSED: on_closed}

def by_chain(status):
    if status == Status.OPEN:
        a()
    elif status == Status.CLOSED:
        b()
    else:
        pass
"""
    diags = _check(src)
    assert len(diags) == 2
    assert [(d.line, d.col) for d in diags] == sorted((d.line, d.col) for d in diags)
