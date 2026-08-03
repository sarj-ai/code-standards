import ast
from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_match_pattern_destructuring import PreferMatchPatternDestructuring


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "webserver/call_router.py") -> list[Diagnostic]:
    return PreferMatchPatternDestructuring().check(Path(path), textwrap.dedent(source))


def _messages(source: str) -> list[str]:
    return [d.message for d in _check(source)]


_REACH_BACK = """
match event:
    case AttachLiveKit():
        setup(event.config, event.room)
    case _:
        assert_never(event)
"""


# Positive: a class pattern that binds nothing and reaches back.               #


def test_flags_two_distinct_fields():
    assert len(_check(_REACH_BACK)) == 1


def test_flags_one_field_read_twice():
    source = """
    match outcome:
        case FlowFail():
            failure = make(message=outcome.reason)
            failure.text = outcome.reason
    """
    assert len(_check(source)) == 1


def test_reports_at_the_pattern_position():
    (diag,) = _check(_REACH_BACK)
    assert (diag.line, diag.col) == (3, 10)
    assert diag.code == "SARJ069"


def test_message_names_the_fields_and_writes_the_pattern():
    (message,) = _messages(_REACH_BACK)
    assert "`event.config`" in message
    assert "`event.room`" in message
    assert "`case AttachLiveKit(config=config, room=room):`" in message


def test_flags_every_reaching_arm_of_one_match():
    source = """
    match event:
        case AttachLiveKit():
            setup(event.config, event.room)
        case Detach():
            teardown(event.reason, event.code)
    """
    assert len(_check(source)) == 2


def test_flags_dotted_class_patterns():
    source = """
    match tts:
        case azure.TTS():
            log(tts.provider, tts.model)
    """
    (message,) = _messages(source)
    assert "`case azure.TTS(model=model, provider=provider):`" in message


def test_flags_nested_match_inside_an_arm():
    source = """
    match message:
        case ChatMessageTextItem(llm_metadata=llm_metadata):
            match llm_metadata:
                case LLMTextMetadata():
                    emit(llm_metadata.content, llm_metadata.role)
    """
    (diag,) = _check(source)
    assert diag.line == 5


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("emit(event.config, event.room)", 1, id="two-fields"),
        pytest.param("emit(event.config, event.config)", 1, id="one-field-twice"),
        pytest.param("emit(event.config)", 0, id="one-field-once"),
        pytest.param("emit(event.meta.a, event.meta.b)", 1, id="one-field-twice-nested"),
    ],
)
def test_read_floor(body: str, expected: int):
    source = f"""
    match event:
        case AttachLiveKit():
            {body}
    """
    assert len(_check(source)) == expected


# Guards: a capture is bound before the guard runs, so guard reads count.      #


def test_flags_reads_in_the_guard():
    source = """
    match msg:
        case ToolResultMessage() if msg.tool_name == "transfer" and not msg.is_error:
            record()
    """
    (message,) = _messages(source)
    assert "`case ToolResultMessage(is_error=is_error, tool_name=tool_name):`" in message


def test_guard_and_body_reads_combine_to_reach_the_floor():
    source = """
    match msg:
        case ToolResultMessage() if msg.is_error:
            record(msg.detail)
    """
    assert len(_check(source)) == 1


# `as` aliases.                                                                #


def test_flags_reach_back_through_an_as_alias():
    source = """
    match batch_call_scenario:
        case CustomScenario() as scenario:
            load(scenario.slug)
            log(scenario.slug)
    """
    (message,) = _messages(source)
    assert "`case CustomScenario(slug=slug) as scenario:`" in message


def test_alias_arm_still_counts_reads_through_the_subject_name():
    source = """
    match event:
        case AttachLiveKit() as evt:
            setup(evt.config, event.room)
    """
    assert len(_check(source)) == 1


def test_bare_capture_alias_is_not_a_class_pattern():
    source = """
    match event:
        case other:
            setup(other.config, other.room)
    """
    assert _check(source) == []


# Capture naming: never propose a name the arm cannot use.                     #


def test_prefixes_a_capture_that_would_shadow_a_builtin():
    source = """
    match scenario_ref:
        case CustomScenario():
            load(scenario_ref.id)
            log(scenario_ref.id)
    """
    (message,) = _messages(source)
    assert "`case CustomScenario(id=scenario_ref_id):`" in message


def test_prefixes_a_capture_that_would_shadow_a_name_the_arm_uses():
    source = """
    match outcome:
        case FlowPass():
            passes[outcome.name] += 1
            if outcome.flaky:
                flaky[outcome.name] += 1
    """
    (message,) = _messages(source)
    assert "flaky=outcome_flaky" in message
    assert "name=name" in message


def test_an_x_equals_subject_x_line_is_not_a_collision():
    source = """
    match msg:
        case RegularMessage():
            content = msg.content
            role = msg.role
            emit(role, content)
    """
    (message,) = _messages(source)
    assert "`case RegularMessage(content=content, role=role):`" in message


def test_a_differently_sourced_local_of_the_same_name_is_a_collision():
    source = """
    match msg:
        case RegularMessage():
            content = normalise(msg.content)
            role = LOOKUP[msg.role]
            emit(role, content)
    """
    (message,) = _messages(source)
    assert "content=msg_content" in message
    assert "role=msg_role" in message


def test_elides_the_field_list_past_four_fields():
    source = """
    match event:
        case Big():
            use(event.a, event.b, event.c, event.d, event.e)
    """
    (message,) = _messages(source)
    assert "and 1 more" in message
    assert message.count("=") == 4
    # The remainder is stated in prose, never inside the parentheses: a trailing
    # `, ...` there is a syntax error, so the suggestion could not be pasted.
    assert "..." not in message
    assert "1 further field" in message
    pattern = message.split("write `")[1].split("` instead")[0]
    ast.parse(f"match x:\n    {pattern}\n        pass\n")


# The subject is rebound or written through.                                   #


@pytest.mark.parametrize(
    "rebinding",
    [
        pytest.param("event = normalise(event)", id="assign"),
        pytest.param("event: Foo = normalise(event)", id="annassign"),
        pytest.param("event += 1", id="augassign"),
        pytest.param("del event", id="del"),
        pytest.param("for event in batch: pass", id="for-target"),
        pytest.param("with acquire() as event: pass", id="with-as"),
        pytest.param("[x for event in batch]", id="comprehension-target"),
        pytest.param("(event := refresh())", id="walrus"),
        pytest.param("def event(): pass", id="nested-def"),
        pytest.param("async def event(): pass", id="nested-async-def"),
        pytest.param("class event: pass", id="nested-class"),
        pytest.param("def f(event): pass", id="shadowing-parameter"),
        pytest.param("g = lambda event: event", id="shadowing-lambda-parameter"),
        pytest.param("try: pass\n    except E as event: pass", id="except-as"),
        pytest.param("import event", id="import"),
        pytest.param("import os as event", id="import-as"),
        pytest.param("from a import b as event", id="from-import-as"),
        pytest.param("global event", id="global"),
        pytest.param("match other:\n        case Foo() as event: pass", id="nested-capture"),
        pytest.param("match other:\n        case [*event]: pass", id="nested-star-capture"),
        pytest.param("match other:\n        case {'k': 1, **event}: pass", id="nested-mapping-rest"),
    ],
)
def test_skips_arms_that_rebind_the_subject(rebinding: str):
    source = f"""
    def outer():
        match event:
            case AttachLiveKit():
                setup(event.config, event.room)
                {rebinding}
    """
    assert _check(source) == []


def test_the_same_arm_without_the_rebinding_fires():
    source = """
    def outer():
        match event:
            case AttachLiveKit():
                setup(event.config, event.room)
                other = normalise(other)
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param("event.config = None", id="attribute-store"),
        pytest.param("event.retries += 1", id="attribute-augassign"),
        pytest.param("del event.tmp", id="attribute-del"),
        pytest.param("event['k'] = 1", id="subscript-store"),
        pytest.param("del event['k']", id="subscript-del"),
    ],
)
def test_skips_arms_that_write_through_the_subject(mutation: str):
    source = f"""
    match event:
        case AttachLiveKit():
            setup(event.config, event.room)
            {mutation}
    """
    assert _check(source) == []


def test_a_write_two_levels_deep_is_still_a_read_of_the_field():
    # `analysis.transcript.messages = [...]` mutates the object the field points
    # at, which destructuring preserves exactly.
    source = """
    match result:
        case PostCallAnalysis():
            result.transcript.messages = []
            emit(result.outcome)
    """
    assert len(_check(source)) == 1


def test_an_alias_rebinding_also_disqualifies():
    source = """
    match event:
        case AttachLiveKit() as evt:
            setup(evt.config, evt.room)
            evt = normalise(evt)
    """
    assert _check(source) == []


# Private attributes, methods, and non-field access.                           #


@pytest.mark.parametrize(
    "attrs",
    [
        pytest.param("stt._opts.language, stt._opts.model", id="private"),
        pytest.param("stt.__class__, stt.__dict__", id="dunder"),
    ],
)
def test_skips_private_and_dunder_attributes(attrs: str):
    source = f"""
    match stt:
        case HamsaSTT():
            configure({attrs})
    """
    assert _check(source) == []


def test_the_same_arm_with_public_attributes_fires():
    source = """
    match stt:
        case HamsaSTT():
            configure(stt.opts.language, stt.opts.model)
    """
    assert len(_check(source)) == 1


def test_skips_method_calls():
    source = """
    match error:
        case PaymentAPIError():
            code = error.get_primary_error_code()
            message = error.get_primary_error_message()
    """
    assert _check(source) == []


def test_a_method_name_is_dropped_but_real_fields_still_count():
    source = """
    match error:
        case PaymentAPIError():
            code = error.get_primary_error_code()
            emit(error.service_code, error.response)
    """
    (message,) = _messages(source)
    assert "get_primary_error_code" not in message
    assert "`case PaymentAPIError(response=response, service_code=service_code):`" in message


def test_an_attribute_that_is_both_read_and_called_is_dropped():
    source = """
    match event:
        case Foo():
            emit(event.handler)
            event.handler()
    """
    assert _check(source) == []


def test_only_one_level_of_attribute_access_is_proposed():
    source = """
    match event:
        case Foo():
            emit(event.meta.trace_id, event.meta.span_id)
    """
    (message,) = _messages(source)
    assert "`case Foo(meta=meta):`" in message
    assert "trace_id" not in message


def test_subscripting_a_field_still_counts_the_field():
    source = """
    match event:
        case Foo():
            emit(handlers[event.kind], event.kind)
    """
    (message,) = _messages(source)
    assert "`case Foo(kind=kind):`" in message


# Patterns that are not a plain class pattern.                                 #


@pytest.mark.parametrize(
    "pattern",
    [
        pytest.param("[a, b]", id="sequence"),
        pytest.param("1 | 2", id="or-of-literals"),
        pytest.param("Attach() | Detach()", id="or-of-classes"),
        pytest.param("None", id="none"),
        pytest.param('{"type": "attach"}', id="mapping"),
        pytest.param("Kind.ATTACH", id="enum-value"),
        pytest.param("_", id="wildcard"),
    ],
)
def test_skips_non_class_patterns(pattern: str):
    source = f"""
    match event:
        case {pattern}:
            setup(event.config, event.room)
    """
    assert _check(source) == []


def test_the_same_arm_as_a_class_pattern_fires():
    source = """
    match event:
        case Attach():
            setup(event.config, event.room)
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "cls",
    ["str", "bytes", "int", "float", "bool", "dict", "list", "tuple", "set", "type", "Mapping", "Sequence"],
)
def test_skips_builtin_and_abc_class_patterns(cls: str):
    source = f"""
    match value:
        case {cls}():
            emit(value.first, value.second)
    """
    assert _check(source) == []


def test_a_domain_class_with_the_same_shape_fires():
    source = """
    match value:
        case Payload():
            emit(value.first, value.second)
    """
    assert len(_check(source)) == 1


# Subjects the arm cannot reach back through, and already-bound fields.        #


@pytest.mark.parametrize(
    "subject",
    [
        pytest.param("resolve(event)", id="call"),
        pytest.param("self.state", id="attribute"),
        pytest.param("(a, b)", id="tuple"),
        pytest.param("events[0]", id="subscript"),
    ],
)
def test_skips_subjects_that_are_not_a_plain_name(subject: str):
    source = f"""
    match {subject}:
        case AttachLiveKit():
            setup(event.config, event.room)
    """
    assert _check(source) == []


def test_a_plain_name_subject_with_the_same_body_fires():
    source = """
    match event:
        case AttachLiveKit():
            setup(event.config, event.room)
    """
    assert len(_check(source)) == 1


def test_skips_a_fully_destructured_arm():
    source = """
    match event:
        case AttachLiveKit(config=config, room=room):
            setup(config, room)
    """
    assert _check(source) == []


def test_skips_when_the_body_reads_only_already_bound_fields():
    source = """
    match event:
        case AttachLiveKit(config=config, room=room):
            setup(event.config, event.room)
    """
    assert _check(source) == []


def test_a_partly_destructured_arm_keeps_the_binding_it_already_had():
    # The suggestion has to reproduce `llm_metadata=llm_metadata`.
    source = """
    match message:
        case ChatMessageActionItem(llm_metadata=llm_metadata):
            emit(message.action, message.llm_metadata, message.status)
    """
    (message,) = _messages(source)
    assert "`case ChatMessageActionItem(llm_metadata=llm_metadata, action=action, status=status):`" in message


def test_an_existing_keyword_constraint_is_not_silently_widened():
    source = """
    match event:
        case Message(kind="primary"):
            emit(event.payload, event.sender)
    """
    (message,) = _messages(source)
    assert "`case Message(kind='primary', payload=payload, sender=sender):`" in message


def test_positional_patterns_are_carried_into_the_suggestion():
    # `case Point(x, y)` binds x and y through `__match_args__`.
    source = """
    match point:
        case Point(x, y):
            emit(point.z, point.w)
    """
    (message,) = _messages(source)
    assert "`case Point(x, y, w=w, z=z):`" in message


def test_a_positional_constraint_is_not_silently_widened():
    # `case Point(0, 0)` matches only the origin.
    source = """
    match point:
        case Point(0, 0):
            emit(point.label, point.color)
    """
    (message,) = _messages(source)
    assert "`case Point(0, 0, color=color, label=label):`" in message


@pytest.mark.parametrize(
    ("existing", "capture"),
    [
        pytest.param("existing=collision", "item_collision", id="keyword"),
        pytest.param("collision", "item_collision", id="positional"),
        pytest.param("existing=Pair(collision, item_collision)", "item_item_collision", id="nested"),
    ],
)
def test_existing_capture_names_do_not_collide_with_suggested_bindings(existing: str, capture: str):
    source = f"""
    match item:
        case Widget({existing}):
            emit(item.collision, item.other)
    """
    (message,) = _messages(source)
    pattern = message.split("write `")[1].split("` instead")[0]
    parsed = ast.parse(f"match x:\n    {pattern}\n        pass\n")

    compile(parsed, "<suggested pattern>", "exec")
    assert f"collision={capture}" in pattern


@pytest.mark.parametrize(
    "existing",
    [
        pytest.param("existing=item", id="keyword"),
        pytest.param("item", id="positional"),
        pytest.param("existing=Pair(item)", id="nested"),
    ],
)
def test_skips_when_an_existing_capture_shadows_the_subject(existing: str):
    source = f"""
    match item:
        case Widget({existing}):
            emit(item.collision, item.other)
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "existing",
    [
        pytest.param("existing=item", id="keyword"),
        pytest.param("item", id="positional"),
        pytest.param("existing=Pair(item)", id="nested"),
    ],
)
def test_uses_an_outer_alias_when_the_subject_is_shadowed(existing: str):
    source = f"""
    match item:
        case Widget({existing}) as whole:
            emit(whole.collision, whole.other)
    """
    (message,) = _messages(source)
    assert "collision=collision, other=other" in message
    assert "as whole" in message


def test_every_suggested_pattern_is_valid_python():
    source = """
    match item:
        case Wide():
            emit(item.a, item.b, item.c, item.d, item.e, item.f, item.g, item.h)
    """
    (message,) = _messages(source)
    pattern = message.split("write `")[1].split("` instead")[0]
    parsed = ast.parse(f"match x:\n    {pattern}\n        pass\n")
    compile(parsed, "<suggested pattern>", "exec")

    assert isinstance(parsed.body[0], ast.Match)
    assert isinstance(parsed.body[0].cases[0].pattern, ast.MatchClass)


# Whole-object use: the subject stays bound, so the arm still fires.           #


def test_an_arm_that_also_passes_the_whole_object_still_fires():
    source = """
    match event:
        case AttachLiveKit():
            record(event)
            setup(event.config, event.room)
    """
    (message,) = _messages(source)
    assert "`case AttachLiveKit(config=config, room=room):`" in message


# Robustness: paths, syntax errors, empty input, ordering.                     #


@pytest.mark.parametrize(
    "path",
    ["webserver/call_router.py", "tests/test_router.py", "conftest.py", "scripts/probe.py"],
)
def test_fires_on_every_path(path: str):
    # Reaching back into the subject is just as wrong in a test as in a router,
    # so this rule is deliberately not path-gated.
    assert len(_check(_REACH_BACK, path)) == 1


def test_syntax_error_source_is_silent():
    assert _check("match event\n    case Foo(:\n") == []


def test_empty_source_is_silent():
    assert _check("") == []


def test_module_without_a_match_statement_is_silent():
    assert _check("def f(event):\n    return event.config, event.room\n") == []


def test_diagnostics_are_sorted_by_position():
    source = """
    def a():
        match event:
            case Later():
                setup(event.x, event.y)

    def b():
        match event:
            case Earlier():
                setup(event.p, event.q)
    """
    diags = _check(source)
    assert [d.line for d in diags] == sorted(d.line for d in diags)
