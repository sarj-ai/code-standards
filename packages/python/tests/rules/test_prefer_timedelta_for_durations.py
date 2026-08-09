from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_timedelta_for_durations import (
    PreferTimedeltaForDurations,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = PreferTimedeltaForDurations.public_examples()


def _check(source: str) -> list[Diagnostic]:
    return PreferTimedeltaForDurations().check(Path("<t>.py"), source)


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = PreferTimedeltaForDurations().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


def test_flags_int_param_named_seconds():
    src = "def schedule(timeout_seconds: int) -> None: ...\n"
    diags = _check(src)
    assert len(diags) == 1
    assert "timedelta" in diags[0].message


def test_flags_float_field_named_interval_ms():
    src = """
class Settings:
    retry_interval_ms: float = 250.0
"""
    assert len(_check(src)) == 1


def test_flags_optional_int_duration():
    src = "def f(ttl: int | None = None) -> None: ...\n"
    assert len(_check(src)) == 1


def test_flags_optional_subscript_duration():
    src = "def f(backoff_seconds: Optional[float]) -> None: ...\n"
    assert len(_check(src)) == 1


def test_allows_timedelta_annotation():
    src = "def schedule(timeout: timedelta) -> None: ...\n"
    assert _check(src) == []


def test_flags_pydantic_constrained_duration():
    src = """
class Settings:
    api_timeout_s: NonNegativeFloat = 30.0
    retry_interval_seconds: PositiveInt = 5
"""
    assert len(_check(src)) == 2


def test_flags_annotated_duration():
    src = "def f(delay_seconds: Annotated[int, Field(ge=0)]) -> None: ...\n"
    assert len(_check(src)) == 1


def test_flags_pydantic_constrained_optional_duration():
    src = "def f(ttl: PositiveInt | None = None) -> None: ...\n"
    assert len(_check(src)) == 1


def test_allows_typed_dict_duration_wire_field() -> None:
    source = """
from typing import TypedDict

class LoginResult(TypedDict):
    expires_in_seconds: int
"""
    assert _check(source) == []


def test_allows_observability_duration_boundary() -> None:
    source = """
def log_response(duration_ms: float) -> None:
    emit("response", duration_ms=round(duration_ms, 2))
"""
    assert _check(source) == []


def test_allows_private_observability_compatibility_hook() -> None:
    assert _check("def _log_completed(duration_ms: float) -> None: ...\n") == []


@pytest.mark.parametrize("name", ["update_performance_metric", "_update_performance_metrics"])
def test_allows_metrics_accumulator_boundary(name: str) -> None:
    source = f"""
def {name}(processing_time_ms: float) -> None:
    total_processing_time_ms += processing_time_ms
    emit(processing_time_ms=round(processing_time_ms, 2))
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    "assignment",
    [
        "REQUEST_TIMEOUT_SECONDS = 30",
        "_POLL_INTERVAL_MS = 250.0",
        "TOKEN_TTL_SECONDS = 5 * 60",
    ],
)
def test_flags_unannotated_numeric_duration_constant(assignment: str) -> None:
    assert len(_check(f"{assignment}\n")) == 1


def test_allows_duration_constant_used_only_in_typed_wire_result() -> None:
    source = """
from typing import TypedDict

SESSION_LIFETIME_SECONDS = 180

class SessionResult(TypedDict):
    expires_after: int

def create_session() -> SessionResult:
    return {"expires_after": SESSION_LIFETIME_SECONDS}
"""
    assert _check(source) == []


def test_allows_duration_constant_used_only_to_construct_pydantic_wire_model() -> None:
    source = """
from pydantic import BaseModel

SESSION_LIFETIME_SECONDS = 180

class SessionResult(BaseModel):
    expires_after: int

def create_session() -> SessionResult:
    return SessionResult(expires_after=SESSION_LIFETIME_SECONDS)
"""
    assert _check(source) == []


def test_flags_wire_duration_constant_that_also_drives_datetime_arithmetic() -> None:
    source = """
from datetime import datetime, timedelta
from typing import TypedDict

SESSION_LIFETIME_SECONDS = 180

class SessionResult(TypedDict):
    expires_after: int

def create_session() -> SessionResult:
    expires_at = datetime.now() + timedelta(seconds=SESSION_LIFETIME_SECONDS)
    persist_expiry(expires_at)
    return {"expires_after": SESSION_LIFETIME_SECONDS}
"""
    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert "SESSION_LIFETIME_SECONDS" in diagnostics[0].message


def test_plain_dict_return_does_not_prove_wire_serialization() -> None:
    source = """
SESSION_LIFETIME_SECONDS = 180

def create_session() -> dict[str, int]:
    return {"expires_after": SESSION_LIFETIME_SECONDS}
"""
    assert len(_check(source)) == 1


def test_shadowed_wire_value_does_not_exempt_module_constant() -> None:
    source = """
from typing import TypedDict

SESSION_LIFETIME_SECONDS = 180

class SessionResult(TypedDict):
    expires_after: int

def create_session(SESSION_LIFETIME_SECONDS: int) -> SessionResult:
    return {"expires_after": SESSION_LIFETIME_SECONDS}
"""
    diagnostics = _check(source)

    assert any(diagnostic.line == 4 for diagnostic in diagnostics)


def test_allows_wall_clock_singular_components():
    src = """
class TimeEdge:
    hour: int
    minute: int
    second: int
"""
    assert _check(src) == []


def test_allows_bare_plural_units_and_formula_names():
    src = """
def payroll(hours_worked: float, hours: float, days: int) -> float: ...
"""
    assert _check(src) == []


def test_allows_percentage_and_rate_named_floats():
    src = """
class Report:
    average_duration_trend_percentage: float
    interval_hit_rate: float
"""
    assert _check(src) == []


def test_allows_count_like_names():
    src = """
def f(retry_count: int, num_days: int, page_size: int) -> None: ...
"""
    assert _check(src) == []


def test_allows_calendar_units_and_instants():
    src = """
def f(retention_months: int, created_at: int, expires_timestamp: float) -> None: ...
"""
    assert _check(src) == []


def test_allows_unannotated_param():
    src = "def f(timeout_seconds=30): ...\n"
    assert _check(src) == []


def test_ignores_non_numeric_annotation():
    src = "def f(timeout_seconds: str) -> None: ...\n"
    assert _check(src) == []


# Positive family: every time-unit token in the rule's `_UNIT_RE`, as a
# function parameter annotated `int`, must be flagged exactly once.

_UNIT_NAMES = [
    "timeout_seconds",
    "poll_secs",
    "poll_milliseconds",
    "poll_millis",
    "poll_ms",
    "wait_minutes",
    "wait_mins",
    "wait_hours",
    "sleep_hrs",
    "retry_days",
    "timeout",
    "request_timeout",
    "poll_interval",
    "interval",
    "ttl",
    "delay",
    "retry_delay",
    "backoff",
    "backoff_ms",
    "duration",
    "call_duration",
    "cooldown",
    "cooldown_seconds",
    "expires_in",
]


@pytest.mark.parametrize("name", _UNIT_NAMES)
@pytest.mark.parametrize("numeric", ["int", "float"])
def test_flags_every_unit_token_as_param(name: str, numeric: str):
    src = f"def f({name}: {numeric}) -> None: ...\n"
    diags = _check(src)
    assert len(diags) == 1
    assert name in diags[0].message
    assert numeric in diags[0].message
    assert "timedelta" in diags[0].message


@pytest.mark.parametrize("name", _UNIT_NAMES)
def test_flags_every_unit_token_as_field(name: str):
    src = f"class C:\n    {name}: int = 1\n"
    assert len(_check(src)) == 1


@pytest.mark.parametrize("name", _UNIT_NAMES)
def test_flags_every_unit_token_module_level_field(name: str):
    src = f"{name}: float\n"
    assert len(_check(src)) == 1


# Positive family: numeric-annotation shapes that must resolve to a duration.

_NUMERIC_SHAPES = [
    "int",
    "float",
    "int | None",
    "None | int",
    "float | None",
    "Optional[int]",
    "Optional[float]",
    "typing.Optional[int]",
    "Annotated[int, Field(ge=0)]",
    "Annotated[float, 'meta']",
    "Optional[Annotated[int, Field(ge=0)]]",
    "Annotated[int | None, Field()]",
    "PositiveInt",
    "NonNegativeInt",
    "NegativeInt",
    "NonPositiveInt",
    "StrictInt",
    "PositiveFloat",
    "NonNegativeFloat",
    "NegativeFloat",
    "NonPositiveFloat",
    "StrictFloat",
    "PositiveInt | None",
    "Optional[NonNegativeFloat]",
    "pydantic.PositiveInt",
]


@pytest.mark.parametrize("annotation", _NUMERIC_SHAPES)
def test_flags_all_numeric_annotation_shapes(annotation: str):
    src = f"def f(timeout_seconds: {annotation}) -> None: ...\n"
    assert len(_check(src)) == 1


# Negative family: a real duration name but excluded by `_EXCLUDE_RE`.

_EXCLUDED_NAMES = [
    "timeout_count",
    "interval_index",
    "duration_id",
    "num_seconds",
    "n_ms",
    "delay_size",
    "backoff_limit",
    "ttl_version",
    "timeout_idx",
    "interval_len",
    "duration_length",
    "delay_offset",
    "timeout_at",
    "interval_ts",
    "duration_months",
    "backoff_years",
    "timeout_percentage",
    "interval_percent",
    "delay_pct",
    "duration_ratio",
    "timeout_rate",
    "interval_trend",
    "backoff_factor",
    "retry_delay_multiplier",
    "timeout_confidence",
    "interval_probability",
    "duration_epoch",
    "cooldown_timestamp",
]


@pytest.mark.parametrize("name", _EXCLUDED_NAMES)
def test_excluded_names_not_flagged(name: str):
    src = f"def f({name}: int) -> None: ...\n"
    assert _check(src) == []


# Negative family: non-duration numeric fields (no unit token at all).

_NON_DURATION_NAMES = [
    "retry_count",
    "page_size",
    "port",
    "max_retries",
    "buffer_length",
    "offset",
    "n_items",
    "version",
    "user_id",
    "row_index",
    "http_status",
    "capacity",
]


@pytest.mark.parametrize("name", _NON_DURATION_NAMES)
def test_non_duration_numeric_not_flagged(name: str):
    src = f"def f({name}: int) -> None: ...\n"
    assert _check(src) == []


# Negative family: wall-clock singular components are positions, not durations.


@pytest.mark.parametrize(
    "name", ["hour", "hours", "minute", "minutes", "second", "seconds", "day", "days", "week", "month"]
)
def test_singular_wall_clock_not_flagged(name: str):
    src = f"def f({name}: int) -> None: ...\n"
    assert _check(src) == []


# Negative family: already-`timedelta`-typed durations are the goal state.


@pytest.mark.parametrize(
    "annotation",
    [
        "timedelta",
        "datetime.timedelta",
        "timedelta | None",
        "Optional[timedelta]",
    ],
)
@pytest.mark.parametrize("name", ["timeout_seconds", "ttl", "retry_delay"])
def test_timedelta_typed_not_flagged(name: str, annotation: str):
    src = f"def f({name}: {annotation}) -> None: ...\n"
    assert _check(src) == []


# Negative family: duration name but a non-numeric annotation.

_NON_NUMERIC_ANNOTATIONS = [
    "str",
    "bytes",
    "bool",
    "list[int]",
    "dict[str, int]",
    "MyDuration",
    "Optional[str]",
    "str | None",
    "Annotated[str, Field()]",
    "'int'",
]


@pytest.mark.parametrize("annotation", _NON_NUMERIC_ANNOTATIONS)
def test_duration_name_non_numeric_annotation_not_flagged(annotation: str):
    src = f"def f(timeout_seconds: {annotation}) -> None: ...\n"
    assert _check(src) == []


def test_string_forward_ref_annotation_is_not_resolved():
    """String (forward-ref) annotations are opaque to the AST rule — a known limit."""
    src = 'def f(delay_seconds: "int") -> None: ...\n'
    assert _check(src) == []


# Explicit false-positive guards named in the task.


def test_num_seconds_display_str_not_flagged():
    src = "class C:\n    num_seconds_display: str\n"
    assert _check(src) == []


def test_max_retries_int_not_flagged():
    src = "class C:\n    max_retries: int = 3\n"
    assert _check(src) == []


def test_timestamp_field_is_an_instant_not_a_duration():
    src = "class C:\n    timestamp: float\n    created_timestamp: int\n"
    assert _check(src) == []


def test_seconds_name_typed_str_not_flagged():
    src = "class C:\n    duration_seconds: str\n"
    assert _check(src) == []


# Edge cases: parsing, scope, argument kinds.


@pytest.mark.parametrize("src", ["", "   \n\n", "# just a comment\n", "\n\n\n"])
def test_empty_or_trivial_source_returns_empty(src: str):
    assert _check(src) == []


def test_syntax_error_returns_empty():
    src = "def f(timeout_seconds: int  ->\n"
    assert _check(src) == []


def test_async_function_param_flagged():
    src = "async def f(timeout_seconds: int) -> None: ...\n"
    assert len(_check(src)) == 1


def test_posonly_and_kwonly_params_flagged():
    src = "def f(timeout_seconds: int, /, *, retry_delay: float) -> None: ...\n"
    assert len(_check(src)) == 2


def test_plain_assignment_not_flagged():
    src = "timeout_seconds = 30\n"
    assert _check(src) == []


def test_module_level_annassign_flagged():
    src = "poll_interval_seconds: int = 5\n"
    assert len(_check(src)) == 1


def test_attribute_target_annassign_flagged():
    src = "self.timeout_seconds: int = 5\n"
    assert len(_check(src)) == 1


def test_nested_function_param_flagged():
    src = """
def outer() -> None:
    def inner(retry_delay: float) -> None: ...
"""
    assert len(_check(src)) == 1


def test_method_self_not_flagged():
    src = """
class C:
    def m(self, timeout_seconds: int) -> None: ...
"""
    assert len(_check(src)) == 1


# Multiple diagnostics: count and ascending-line ordering.


def test_multiple_diagnostics_counted_and_sorted():
    src = """
timeout_seconds: int = 1
retry_delay: float = 2.0
poll_interval: int = 3
"""
    diags = _check(src)
    assert len(diags) == 3
    lines = [d.line for d in diags]
    assert lines == sorted(lines)


def test_mixed_flag_and_allow_in_one_class():
    src = """
class Settings:
    timeout_seconds: int
    retry_count: int
    poll_interval_ms: float
    created_at: int
"""
    diags = _check(src)
    assert len(diags) == 2
    assert {d.line for d in diags} == {3, 5}


# Line / column precision.


def test_param_line_and_col():
    src = "def schedule(timeout_seconds: int) -> None: ...\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 1
    assert diags[0].col == 14


def test_field_line_and_col():
    src = "x_ms: int = 5\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 1
    assert diags[0].col == 1


def test_diagnostic_code_is_sarj014():
    src = "def f(timeout_seconds: int) -> None: ...\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ014"


# BaseSettings exemption: env-wire fields cannot be timedelta (bare-numeric env strings), so duration fields on a pydantic-settings class are not flagged.


def test_basesettings_field_not_flagged():
    src = """
class AppSettings(BaseSettings):
    timeout_seconds: float
"""
    assert _check(src) == []


def test_pydantic_settings_import_path_not_flagged():
    src = """
class AppSettings(pydantic_settings.BaseSettings):
    poll_interval_ms: int = 250
"""
    assert _check(src) == []


def test_settings_subclass_of_settings_not_flagged():
    src = """
class DerivedSettings(BaseSettings):
    ttl: int = 60

class Concrete(DerivedSettings):
    retry_delay: float = 1.5
"""
    assert _check(src) == []


def test_basesettings_multiple_duration_fields_all_exempt():
    src = """
class AppSettings(BaseSettings):
    timeout_seconds: float
    retry_delay_ms: int = 100
    poll_interval: NonNegativeFloat = 0.5
"""
    assert _check(src) == []


def test_ordinary_basemodel_domain_field_still_flagged():
    src = """
class Config(BaseModel):
    timeout_seconds: float
"""
    assert len(_check(src)) == 1


def test_import_proven_pydantic_wire_duration_field_not_flagged():
    src = """
from pydantic import BaseModel, NonNegativeFloat

class TimingEvent(BaseModel):
    duration_ms: int | None = None
    ttft_ms: NonNegativeFloat
"""
    assert _check(src) == []


def test_pydantic_model_subclass_wire_duration_field_not_flagged():
    src = """
import pydantic as pd

class WireModel(pd.BaseModel):
    pass

class TimingEvent(WireModel):
    duration_ms: float
"""
    assert _check(src) == []


def test_pydantic_v1_wire_duration_field_not_flagged():
    src = """
from pydantic.v1 import BaseModel

class TimingEvent(BaseModel):
    duration_ms: float
"""
    assert _check(src) == []


def test_pydantic_model_method_duration_values_are_still_checked():
    src = """
from pydantic import BaseModel

class TimingEvent(BaseModel):
    duration_ms: float

    def normalized(self, timeout_seconds: int) -> None:
        retry_delay_ms: float = 1.0
"""
    diagnostics = _check(src)
    assert {diagnostic.line for diagnostic in diagnostics} == {7, 8}


def test_shadowed_pydantic_basemodel_name_does_not_create_exemption():
    src = """
from pydantic import BaseModel

class BaseModel:
    pass

class DomainConfig(BaseModel):
    timeout_seconds: float
"""
    assert len(_check(src)) == 1


def test_plain_function_param_still_flagged_alongside_settings():
    src = """
class AppSettings(BaseSettings):
    timeout_seconds: float

def schedule(timeout_seconds: int) -> None: ...
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 5


def test_settings_via_intermediate_non_settings_named_base_not_flagged():
    src = """
class _InstrumentationBase(BaseSettings):
    x: int = 1

class OtlpConfig(_InstrumentationBase):
    export_timeout_seconds: float = 30.0
"""
    assert _check(src) == []


def test_basemodel_intermediate_base_still_flagged():
    src = """
class _DomainBase(BaseModel):
    x: int = 1

class Config(_DomainBase):
    timeout_seconds: float = 30.0
"""
    assert len(_check(src)) == 1


def test_basesettings_non_field_method_param_still_flagged():
    src = """
class AppSettings(BaseSettings):
    poll_interval_seconds: int

    def recompute(self, retry_delay: float) -> None: ...
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "retry_delay" in diags[0].message


# Adversarial: Settings-exemption edges (base-name heuristic + transitive intra-module resolution).


def test_settings_named_class_without_base_still_flagged():
    """Flag a class *named* `...Settings` that has no base."""
    src = """
class RedisSettings:
    connect_timeout_seconds: int
"""
    assert len(_check(src)) == 1


def test_non_pydantic_settings_named_base_exempts_by_name_heuristic():
    """Exempt a class deriving from any base whose name ends in `Settings`."""
    src = """
class LegacySettings:
    pass

class Foo(LegacySettings):
    timeout_seconds: int
"""
    assert _check(src) == []


def test_multiple_inheritance_one_settings_base_exempt():
    src = """
class Config(Mixin, BaseSettings):
    timeout_seconds: int
"""
    assert _check(src) == []


def test_generic_plus_settings_base_exempt():
    src = """
class Config(Generic[T], BaseSettings):
    timeout_seconds: int
"""
    assert _check(src) == []


def test_nested_settings_class_fields_exempt():
    src = """
def build() -> None:
    class LocalSettings(BaseSettings):
        timeout_seconds: int
"""
    assert _check(src) == []


def test_external_intermediate_base_not_resolved_still_flagged():
    """Flag a field whose intermediate base is from another module."""
    src = """
class Config(ExternalBase):
    request_timeout_seconds: float
"""
    assert len(_check(src)) == 1


def test_external_settings_named_base_exempt_by_name():
    src = """
class Config(RedisCacheSettings):
    request_timeout_seconds: float
"""
    assert _check(src) == []


def test_deep_transitive_settings_chain_all_exempt():
    src = """
class A(BaseSettings):
    a_timeout_seconds: int

class B(A):
    b_ttl: int

class C(B):
    c_delay: float
"""
    assert _check(src) == []


def test_settings_optional_and_annotated_fields_exempt():
    src = """
class AppSettings(BaseSettings):
    ttl: Optional[int] = None
    retry_delay: Annotated[float, Field(ge=0)] = 1.0
"""
    assert _check(src) == []


def test_settings_class_local_var_in_method_still_flagged():
    """Flag an annotated local inside a settings-class method body."""
    src = """
class AppSettings(BaseSettings):
    def m(self) -> None:
        cache_ttl: int = 5
"""
    assert len(_check(src)) == 1


def test_settings_base_cycle_terminates_and_flags():
    """Terminate on a base cycle with no `Settings` root and flag both classes."""
    src = """
class A(B):
    timeout_seconds: int

class B(A):
    poll_interval: int
"""
    assert len(_check(src)) == 2


# Adversarial: unit-token vs exclusion-token boundary collisions.


def test_timestamp_ms_exclusion_wins_over_unit_token():
    src = "def f(timestamp_ms: int) -> None: ...\n"
    assert _check(src) == []


def test_countdown_seconds_flagged_count_substring_not_a_boundary():
    """Flag `countdown_seconds` because `count` is not on a token boundary."""
    src = "def f(countdown_seconds: int) -> None: ...\n"
    assert len(_check(src)) == 1


def test_conint_call_annotation_not_resolved():
    """Skip a `conint(...)` factory-call annotation the AST rule can't resolve."""
    src = "def f(timeout_seconds: conint(ge=0)) -> None: ...\n"
    assert _check(src) == []


# Regressions — false positives from the class-name index, now fixed.


def test_name_collision_nested_class_shadows_settings():
    src = """
class Config(BaseSettings):
    timeout_seconds: int

def factory() -> None:
    class Config(BaseModel):
        payload_size: int
"""
    assert _check(src) == []


def test_subscripted_generic_settings_base_wrongly_flagged():
    src = """
class Base(BaseSettings, Generic[T]):
    x: int

class Config(Base[int]):
    timeout_seconds: int
"""
    assert _check(src) == []


def _check_at(source: str, path: str) -> list[Diagnostic]:
    return PreferTimedeltaForDurations().check(Path(path), source)


def test_test_file_is_exempt():
    src = "class JankyLock:\n    def acquire(self, timeout: int = -1) -> bool: ...\n"
    assert _check_at(src, "src/trio/_core/_tests/test_thread_cache.py") == []


def test_conftest_is_exempt():
    src = "def assert_gc(test, timeout: float = 10) -> None: ...\n"
    assert _check_at(src, "tests/conftest.py") == []


def test_production_file_still_fires():
    src = "def schedule(timeout_seconds: int) -> None: ...\n"
    assert len(_check_at(src, "app/calls/service.py")) == 1


def test_overload_stub_is_exempt():
    src = """
@overload
async def connect_tcp(host: str, *, happy_eyeballs_delay: float = ...) -> TLSStream: ...

async def connect_tcp(host: str, *, happy_eyeballs_delay: float = 0.25) -> SocketStream:
    return await _connect(host, happy_eyeballs_delay)
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 5


def test_typing_qualified_overload_is_exempt():
    src = "@typing.overload\ndef wait(timeout_seconds: int) -> None: ...\n"
    assert _check(src) == []


@pytest.mark.parametrize(
    "decorator",
    [
        '@click.option("--timeout", type=float, default=5.0)',
        '@click.argument("timeout")',
        '@option("--timeout", type=float)',
        "@typer.run",
    ],
)
def test_cli_decorated_parameters_are_exempt(decorator: str):
    src = f"{decorator}\ndef main(url: str, timeout: float) -> None: ...\n"
    assert _check(src) == []


def test_non_cli_decorator_still_fires():
    src = "@functools.cache\ndef main(url: str, timeout: float) -> None: ...\n"
    assert len(_check(src)) == 1


def test_same_name_delegation_is_exempt():
    src = """
class Backend:
    @classmethod
    async def sleep(cls, delay: float) -> None:
        await trio.sleep(delay)
"""
    assert _check(src) == []


def test_same_name_delegation_with_docstring_is_exempt():
    src = """
async def sleep(delay: float) -> None:
    \"\"\"Pause the current task for the specified duration.\"\"\"
    return await get_async_backend().sleep(delay)
"""
    assert _check(src) == []


def test_delegation_to_a_different_name_still_fires():
    src = "async def wait(delay: float) -> None:\n    await anyio.sleep(delay)\n"
    assert len(_check(src)) == 1


def test_computing_with_the_parameter_still_fires():
    src = """
def fail_after(delay: float) -> CancelScope:
    return fail_after(current_time() + delay)
"""
    assert len(_check(src)) == 1


def test_multi_statement_body_still_fires():
    src = """
async def sleep(delay: float) -> None:
    log.debug("sleeping")
    await anyio.sleep(delay)
"""
    assert len(_check(src)) == 1


def test_delegation_only_exempts_the_forwarded_parameter():
    src = """
async def sleep(delay: float, ttl: int) -> None:
    await anyio.sleep(delay)
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "`ttl" in diags[0].message


def test_keyword_forwarded_parameter_is_exempt():
    src = """
def list_accounts(self, retry: Retry = DEFAULT, timeout: float | None = None) -> Pager:
    return self.get_conn().list_accounts(request={}, retry=retry, timeout=timeout)
"""
    assert _check(src) == []


def test_forward_through_a_nested_helper_is_exempt():
    src = """
def consume(self, poll_timeout: float = 1.0) -> list[Message]:
    consumer = self.get_consumer()
    return consumer.consume(num_messages=10, timeout=1) or consumer.poll(poll_timeout=poll_timeout)
"""
    assert _check(src) == []


def test_constructor_storing_the_parameter_verbatim_is_exempt():
    src = """
class Waiter:
    def __init__(self, waiter_delay: int = 30) -> None:
        self.waiter_delay = waiter_delay
"""
    assert _check(src) == []


def test_declared_field_of_a_forwarding_constructor_still_fires():
    src = """
class Waiter:
    waiter_delay: int = 30

    def __init__(self, waiter_delay: int = 30) -> None:
        self.waiter_delay = waiter_delay
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3


def test_arithmetic_on_a_forwarded_parameter_still_fires():
    src = """
def set_retry(self, delay_seconds: float) -> None:
    self.state.scheduled_time = now("UTC") + timedelta(seconds=delay_seconds)
"""
    assert len(_check(src)) == 1


def test_forward_wrapped_in_arithmetic_still_fires():
    src = """
def call(self, timeout: float) -> None:
    self.client.call(timeout=timeout * 2)
"""
    assert len(_check(src)) == 1


def test_comparison_on_the_parameter_still_fires():
    src = """
def call(self, timeout: float) -> None:
    if timeout > 0:
        self.client.call(timeout=timeout)
"""
    assert len(_check(src)) == 1


def test_subscript_use_of_the_parameter_still_fires():
    src = """
def call(self, timeout: float) -> None:
    self.client.call(timeout=timeout[0])
"""
    assert len(_check(src)) == 1


def test_forwarding_under_a_different_keyword_still_fires():
    src = """
def call(self, poll_interval: float) -> None:
    self.client.wait(delay=poll_interval)
"""
    assert len(_check(src)) == 1


def test_positional_forward_still_fires():
    src = """
def call(self, retry_delay: float) -> None:
    self.client.wait(retry_delay)
"""
    assert len(_check(src)) == 1


def test_store_to_a_differently_named_attribute_still_fires():
    src = """
class C:
    def __init__(self, timeout_seconds: float) -> None:
        self._deadline = timeout_seconds
"""
    assert len(_check(src)) == 1


def test_unused_parameter_is_not_a_forward():
    src = "def schedule(self, timeout_seconds: int) -> None: ...\n"
    assert len(_check(src)) == 1


def test_forwarding_only_exempts_the_forwarded_parameter():
    src = """
def submit(self, timeout: float, retry_delay: float) -> None:
    self.client.call(timeout=timeout, delay=retry_delay)
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "`retry_delay" in diags[0].message


def test_wire_format_duration_field_still_fires():
    src = "class TokenResponse:\n    expires_in: int\n"
    assert len(_check(src)) == 1


def test_numeric_helper_duration_parameter_still_fires():
    src = "def poisson_interval(average_interval: float) -> float:\n    return average_interval * 2\n"
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "annotation",
    [
        "float | timedelta",
        "timedelta | float",
        "float | timedelta | None",
        "int | datetime.timedelta",
        "Optional[float | timedelta]",
        "Annotated[float | timedelta, Field()]",
    ],
)
def test_union_admitting_timedelta_is_exempt(annotation: str):
    src = f"def _coerce_poke_interval(poke_interval: {annotation}) -> timedelta: ...\n"
    assert _check(src) == []


def test_union_admitting_timedelta_as_a_field_is_exempt():
    src = "class C:\n    timeout: float | timedelta = 60.0\n"
    assert _check(src) == []


def test_union_of_numeric_without_timedelta_still_fires():
    src = "def f(poke_interval: int | float | None = None) -> None: ...\n"
    assert len(_check(src)) == 1


def test_a_timedelta_named_container_does_not_exempt():
    """Flag a numeric duration alongside an unrelated `timedelta` mention."""
    src = "def f(timeout_seconds: int, schedule: list[timedelta]) -> None: ...\n"
    assert len(_check(src)) == 1


_GENERATED_PROBE = """
def f(timeout_seconds: int = 30) -> None:
    pass
"""


@pytest.mark.parametrize(
    "header",
    [
        '"""Code generated by Speakeasy (https://speakeasy.com). DO NOT EDIT."""',
        "# Auto-generated file, do not edit.",
        "# This file was automatically generated.",
    ],
)
def test_generated_source_is_exempt(header: str):
    assert _check(f"{header}\n{_GENERATED_PROBE}") == []


def test_the_same_body_without_a_generated_header_still_fires():
    assert len(_check(_GENERATED_PROBE)) >= 1
