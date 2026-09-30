from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_match_assert_never import PreferMatchAssertNever


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "python/app/app/calls/dispatch.py") -> list[Diagnostic]:
    return PreferMatchAssertNever().check(Path(path), source)


_PUBLIC_EXAMPLES = PreferMatchAssertNever.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


_ENUM_PREAMBLE = """
from enum import StrEnum

class Status(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    FAILED = "failed"
"""


@pytest.mark.parametrize("fallthrough", ["pass", "return", "return None", "...", "'ignored'", "0"])
def test_flags_noop_match_catch_all(fallthrough: str) -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status) -> None:
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            {fallthrough}
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ032"
    assert diagnostics[0].severity.value == "error"
    assert diagnostics[0].line == 15
    assert "typed `Status` match" in diagnostics[0].message


def test_flags_named_capture_catch_all() -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status) -> None:
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case unknown:
            pass
"""

    assert len(_check(source)) == 1


def test_flags_or_pattern_members() -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status) -> None:
    match status:
        case Status.OPEN | Status.CLOSED:
            active()
        case Status.FAILED:
            failed()
        case _:
            pass
"""

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "fallthrough",
    [
        "raise ValueError(status)",
        "assert_never(status)",
        "return False",
        "return default",
        "log.warning('unknown', status=status)",
        "handled = False",
    ],
)
def test_allows_loud_or_value_producing_match_catch_all(fallthrough: str) -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status):
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            {fallthrough}
"""

    assert _check(source) == []


def test_allows_guarded_member_arm() -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status) -> None:
    match status:
        case Status.OPEN if ready:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            pass
"""

    assert _check(source) == []


def test_allows_default_then_refine_match() -> None:
    source = f"""{_ENUM_PREAMBLE}
def label(status: Status) -> str:
    result = "other"
    match status:
        case Status.OPEN:
            result = "open"
        case Status.CLOSED:
            result = "closed"
        case _:
            pass
    return result
"""

    assert _check(source) == []


def test_allows_untyped_local_enum_subject() -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status) -> None:
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            pass
"""

    assert _check(source) == []


def test_allows_rebound_typed_subject() -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status, raw: str) -> None:
    status = raw
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            pass
"""

    assert _check(source) == []


def test_subject_store_in_nested_function_does_not_hide_outer_dispatch() -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status) -> None:
    def nested() -> None:
        status = Status.FAILED
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            pass
"""

    assert len(_check(source)) == 1


def test_subject_store_after_dispatch_does_not_hide_finding() -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status) -> None:
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            pass
    status = Status.FAILED
"""

    assert len(_check(source)) == 1


def test_flags_quoted_enum_annotation() -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: "Status") -> None:
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            pass
"""

    assert len(_check(source)) == 1


def test_allows_unknown_enum_member_spelling() -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status) -> None:
    match status:
        case Status.OPEN:
            open_it()
        case Status.MISSPELLED:
            close_it()
        case _:
            pass
"""

    assert _check(source) == []


def test_annotation_only_enum_attribute_is_not_a_member() -> None:
    source = """
from enum import StrEnum

class Status(StrEnum):
    label: str
    OPEN = "open"

def handle(status: Status) -> None:
    match status:
        case Status.OPEN:
            open_it()
        case Status.label:
            label_it()
        case _:
            pass
"""

    assert _check(source) == []


def test_allows_imported_member_owner() -> None:
    source = """
from plugin_api import Hook

def handle(hook: str) -> None:
    match hook:
        case Hook.BEFORE:
            before()
        case Hook.AFTER:
            after()
        case _:
            pass
"""

    assert _check(source) == []


def test_allows_ordinary_local_class_owner() -> None:
    source = """
class Kind:
    A = 1
    B = 2

def handle(kind: Kind) -> None:
    match kind:
        case Kind.A:
            a()
        case Kind.B:
            b()
        case _:
            pass
"""

    assert _check(source) == []


def test_allows_open_class_pattern_domain() -> None:
    source = """
class Created: ...
class Deleted: ...

def handle(event: object) -> None:
    match event:
        case Created():
            created()
        case Deleted():
            deleted()
        case _:
            pass
"""

    assert _check(source) == []


def test_allows_generated_source() -> None:
    source = f"""# Generated by schema compiler. Do not edit.
{_ENUM_PREAMBLE}
def handle(status: Status) -> None:
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            pass
"""

    assert _check(source) == []


@pytest.mark.parametrize("base", ["Enum", "IntEnum", "StrEnum", "ReprEnum", "enum.Enum"])
def test_flags_proven_enum_base_forms(base: str) -> None:
    source = f"""
import enum
from enum import Enum, IntEnum, StrEnum, ReprEnum

class Kind({base}):
    A = 1
    B = 2

def handle(kind: Kind) -> None:
    if kind == Kind.A:
        a()
    elif kind == Kind.B:
        b()
    else:
        pass
"""

    assert len(_check(source)) == 1


def test_flags_aliased_enum_base() -> None:
    source = """
from enum import Enum as PyEnum

class Kind(PyEnum):
    A = 1
    B = 2

def handle(kind: Kind) -> None:
    if kind == Kind.A:
        a()
    elif kind == Kind.B:
        b()
    else:
        pass
"""

    assert len(_check(source)) == 1


@pytest.mark.parametrize("base", ["Flag", "IntFlag"])
def test_allows_flag_domains_with_combinations(base: str) -> None:
    source = f"""
from enum import {base}

class Permission({base}):
    READ = 1
    WRITE = 2

def handle(permission: Permission) -> None:
    if permission == Permission.READ:
        read()
    elif permission == Permission.WRITE:
        write()
    else:
        pass
"""

    assert _check(source) == []


def test_allows_shadowed_enum_base_name() -> None:
    source = """
class Enum: ...

class Status(Enum):
    OPEN = "open"
    CLOSED = "closed"

def handle(status: Status) -> None:
    if status == Status.OPEN:
        open_it()
    elif status == Status.CLOSED:
        close_it()
    else:
        pass
"""

    assert _check(source) == []


def test_allows_rebound_enum_owner_at_module_scope() -> None:
    source = f"""{_ENUM_PREAMBLE}
Status = load_constants()

def handle(status: Status) -> None:
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            pass
"""

    assert _check(source) == []


def test_allows_enum_owner_shadowed_by_function_parameter() -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status, Status: object) -> None:
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            pass
"""

    assert _check(source) == []


@pytest.mark.parametrize("fallthrough", ["pass", "return", "return None", "...", "'ignored'", "0"])
def test_flags_noop_if_else(fallthrough: str) -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status) -> None:
    if status == Status.OPEN:
        open_it()
    elif status == Status.CLOSED:
        close_it()
    else:
        {fallthrough}
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "typed `Status` if/elif" in diagnostics[0].message


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("status == Status.OPEN", "status == Status.CLOSED"),
        ("Status.OPEN == status", "Status.CLOSED == status"),
        ("status is Status.OPEN", "Status.CLOSED is status"),
        ("status in (Status.OPEN, Status.CLOSED)", "status == Status.FAILED"),
    ],
)
def test_flags_supported_enum_comparisons(first: str, second: str) -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status) -> None:
    if {first}:
        first_case()
    elif {second}:
        second_case()
    else:
        pass
"""

    assert len(_check(source)) == 1


def test_allows_if_chain_without_else() -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(status: Status) -> None:
    if status == Status.OPEN:
        open_it()
    elif status == Status.CLOSED:
        close_it()
"""

    assert _check(source) == []


def test_allows_if_chain_over_mixed_subjects() -> None:
    source = f"""{_ENUM_PREAMBLE}
def handle(first: Status, second: Status) -> None:
    if first == Status.OPEN:
        open_it()
    elif second == Status.CLOSED:
        close_it()
    else:
        pass
"""

    assert _check(source) == []


def test_allows_incomplete_handler_map_because_lookup_fails_loudly() -> None:
    source = f"""{_ENUM_PREAMBLE}
HANDLERS = {{Status.OPEN: on_open, Status.CLOSED: on_closed}}

def dispatch(status: Status) -> None:
    HANDLERS[status]()
"""

    assert _check(source) == []


def test_reports_match_and_if_diagnostics_in_source_order() -> None:
    source = f"""{_ENUM_PREAMBLE}
def by_match(status: Status) -> None:
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            pass

def by_if(status: Status) -> None:
    if status == Status.OPEN:
        open_it()
    elif status == Status.CLOSED:
        close_it()
    else:
        pass
"""

    diagnostics = _check(source)

    assert len(diagnostics) == 2
    assert [(item.line, item.col) for item in diagnostics] == sorted((item.line, item.col) for item in diagnostics)


@pytest.mark.parametrize("source", ["", "   ", "# comment\n", "def f(:\n    pass"])
def test_trivial_or_invalid_source_is_ignored(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "comment",
    [
        "type: ignore",
        "type: ignore[reportArgumentType]",
        "type: ignore[arg-type]",
        "pyright: ignore",
        "pyright: ignore[reportArgumentType, reportUnknownArgumentType]",
    ],
)
def test_warns_when_exhaustiveness_argument_check_is_suppressed(comment: str) -> None:
    source = f"from typing import assert_never\nassert_never(value)  # {comment}\n"

    findings = _check(source)

    assert len(findings) == 1
    assert findings[0].severity.value == "warning"
    assert findings[0].line == 2


@pytest.mark.parametrize(
    ("imports", "call"),
    [
        ("import typing as t", "t.assert_never"),
        ("from typing_extensions import assert_never as unreachable", "unreachable"),
        ("import typing_extensions", "typing_extensions.assert_never"),
    ],
)
def test_resolves_exhaustiveness_aliases_and_multiline_arguments(imports: str, call: str) -> None:
    source = f"{imports}\n{call}(\n    value,  # pyright: ignore[reportArgumentType]\n)\n"

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "from typing import assert_never\nassert_never(value)\n",
        "from typing import assert_never\nassert_never(value)  # pyright: ignore[reportUnknownArgumentType]\n",
        "from typing import assert_never\nassert_never(value)  # type: ignore[assignment]\n",
        "from typing import assert_never\n# type: ignore[reportArgumentType]\nassert_never(value)\n",
        "from typing import assert_never\nassert_never('type: ignore[reportArgumentType]')\n",
        "from custom import assert_never\nassert_never(value)  # type: ignore\n",
        "def assert_never(value): ...\nassert_never(value)  # type: ignore\n",
        "from typing import assert_never\ndef f(assert_never):\n    assert_never(value)  # type: ignore\n",
        "from typing import assert_never\nassert_never(value)  # type: ignore[reportArgumentType] # sarj-noqa: SARJ032 — explicit runtime rejection\n",
    ],
)
def test_preserves_unrelated_ignores_and_unproven_exhaustiveness_calls(source: str) -> None:
    assert _check(source) == []


def test_warning_extension_does_not_weaken_existing_errors() -> None:
    source = f"""{_ENUM_PREAMBLE}
from typing import assert_never

def handle(status: Status) -> None:
    match status:
        case Status.OPEN:
            open_it()
        case Status.CLOSED:
            close_it()
        case _:
            pass
assert_never(value)  # type: ignore[reportArgumentType]
"""
    findings = _check(source)

    assert [finding.severity.value for finding in findings] == ["error", "warning"]
