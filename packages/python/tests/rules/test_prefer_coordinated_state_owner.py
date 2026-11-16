from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source, main
from sarj_python_lint.autofix import fix_paths
from sarj_python_lint.rule_base import Diagnostic, Severity
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules.prefer_coordinated_state_owner import PreferCoordinatedStateOwner


_SOURCE = PreferCoordinatedStateOwner.public_examples()[0].focus_file.source
_SCALAR_SOURCE = PreferCoordinatedStateOwner.public_examples()[2].focus_file.source


def _check(source: str, path: str = "app/playback.py") -> list[Diagnostic]:
    return PreferCoordinatedStateOwner().check(Path(path), source)


def _assert_valid_source(source: str) -> None:
    compile(  # sarj-noqa: SARJ557 -- Check fixture scope validity; never execute its code.
        source, "app/playback.py", "exec"
    )


def test_documented_examples() -> None:
    verify_native_rule(PreferCoordinatedStateOwner, analyze)


def test_reports_fields_writers_readers_and_conditional_invariant() -> None:
    source = (
        _SOURCE
        + "    def current(self, key: str) -> None:\n        self._observers.get(key)\n        self._playbacks.get(key)\n"
    )
    [finding] = _check(source)
    assert finding.severity is Severity.WARNING
    assert finding.line == 7
    assert "Playback._observers" in finding.message
    assert "Playback._playbacks" in finding.message
    assert "start:7, start:8, finish:10, finish:11" in finding.message
    assert "current:13, current:14" in finding.message
    assert "If entry lifetimes must agree" in finding.message
    assert finding.fixes == ()


def test_scalar_lifecycle_reports_reset_and_resource_consumer() -> None:
    [finding] = _check(_SCALAR_SOURCE)
    assert finding.severity is Severity.WARNING
    assert finding.line == 5
    assert "state.resource" in finding.message
    assert "state.started" in finding.message
    assert "finish:5" in finding.message
    assert "answer_ready:9" in finding.message
    assert finding.fixes == ()


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("        state.started = False\n", ""),
        ("state.resource is expected", "state.resource is None"),
        ("state.resource is expected", "state.resource is not None"),
        ("not session.state.started", "not session.state.unrelated"),
        ("resource.interrupt()", "log(resource)"),
        ("resource.interrupt()", "session.interrupt()"),
        ("state.started = False", "state.started = True"),
        ("state.resource = None", "other.resource = None"),
        ("def answer_ready(session: Session)", "def answer_ready(session)"),
        ("def answer_ready(session: Session)", "def answer_ready(session: object)"),
        ("def answer_ready(session: Session)", "@decorate\ndef answer_ready(session: Session)"),
        (
            "    if resource is not None",
            "    resource = replacement\n    if resource is not None",
        ),
        (
            "    if resource is not None",
            "    session.state.resource = replacement\n    if resource is not None",
        ),
    ],
)
def test_scalar_independent_ambiguous_and_unguarded_state_abstains(old: str, new: str) -> None:
    source = _SCALAR_SOURCE.replace(old, new)
    _assert_valid_source(source)
    assert _check(source) == []


def test_scalar_reset_separated_by_suspension_abstains() -> None:
    source = _SCALAR_SOURCE.replace("def finish(", "async def finish(").replace(
        "        state.started = False", "        await checkpoint()\n        state.started = False"
    )
    _assert_valid_source(source)
    assert _check(source) == []


@pytest.mark.parametrize(
    "prefix",
    ["await checkpoint()", "[None async for item in events()]", 'setattr(session.state, "resource", None)', "return"],
)
def test_scalar_operation_after_suspension_mutation_or_exit_abstains(prefix: str) -> None:
    source = _SCALAR_SOURCE.replace("def answer_ready(", "async def answer_ready(").replace(
        "        resource.interrupt()", f"        {prefix}\n        resource.interrupt()"
    )
    _assert_valid_source(source)
    assert _check(source) == []


def test_scalar_same_root_type_does_not_merge_distinct_parameters() -> None:
    source = _SCALAR_SOURCE.replace(
        "def answer_ready(session: Session)", "def answer_ready(session: Session, other: Session)"
    ).replace("not session.state.started", "not other.state.started")
    assert _check(source) == []


def test_scalar_generic_arguments_are_part_of_owner_identity() -> None:
    source = "from app.types import First, Second\n" + _SCALAR_SOURCE.replace(
        "session: Session, expected", "session: Session[First], expected"
    ).replace("session: Session)", "session: Session[Second])")
    assert _check(source) == []
    assert len(_check(source.replace("Session[Second]", "Session[First]"))) == 1


def test_scalar_quoted_generics_keep_their_original_annotation_scope() -> None:
    source = "from app.types import First, Second\n" + _SCALAR_SOURCE.replace(
        "session: Session", 'session: "Session[First]"'
    )
    assert len(_check(source)) == 1
    different = source.replace(
        'def answer_ready(session: "Session[First]")', 'def answer_ready(session: "Session[Second]")'
    )
    assert _check(different) == []


def test_scalar_fields_are_not_inferred_from_names() -> None:
    renamed = _SCALAR_SOURCE.replace("resource", "left").replace("started", "right")
    assert len(_check(renamed)) == 1
    assert _check(_SCALAR_SOURCE.split("def answer_ready", 1)[0]) == []


def test_scalar_alias_inside_loop_remains_bound_to_its_adjacent_guard() -> None:
    source = _SCALAR_SOURCE.replace(
        "    resource = session.state.resource\n    if resource is not None and not session.state.started:\n        resource.interrupt()",
        "    for item in items:\n        resource = session.state.resource\n        if resource is not None and not session.state.started:\n            resource.interrupt()",
    )
    assert len(_check(source)) == 1


def test_scalar_snapshot_outside_loop_is_not_the_current_member() -> None:
    source = _SCALAR_SOURCE.replace(
        "    if resource is not None and not session.state.started:\n        resource.interrupt()",
        '    for item in items:\n        setattr(session.state, "resource", None)\n        if resource is not None and not session.state.started:\n            resource.interrupt()',
    )
    _assert_valid_source(source)
    assert _check(source) == []


def test_scalar_snapshot_before_outer_if_is_not_adjacent_to_the_resource_guard() -> None:
    source = _SCALAR_SOURCE.replace(
        "    if resource is not None and not session.state.started:\n        resource.interrupt()",
        '    if items:\n        setattr(session.state, "resource", None)\n        if resource is not None and not session.state.started:\n            resource.interrupt()',
    )
    _assert_valid_source(source)
    assert _check(source) == []


def test_scalar_detection_does_not_depend_on_source_whitespace() -> None:
    source = _SCALAR_SOURCE.replace(" = None", "=None").replace(" = False", "=False")
    assert len(_check(source)) == 1


def test_scalar_suppression_and_existing_composed_owner() -> None:
    source = _SCALAR_SOURCE.replace(
        "state.resource = None", "state.resource = None  # sarj-noqa: SARJ565 -- External API retains separate fields."
    )
    assert _check(source) == []
    assert _check(PreferCoordinatedStateOwner.public_examples()[3].focus_file.source) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("class Playback:", "class Playback(Base):"),
        ("class Playback:", "@decorate\nclass Playback:"),
        ("dict[str,", "Mapping[str,"),
        ("dict[str, asyncio.Task[bool]]", "dict[int, asyncio.Task[bool]]"),
        ("self._playbacks[key] = playback", "self._playbacks[other] = playback"),
        ("self._playbacks.pop(key, None)", "self._playbacks.pop(other, None)"),
        ("self._playbacks.pop(key, None)", "pass"),
        ("self._playbacks[key] = playback", "pass"),
        (
            "self._playbacks: dict[str, asyncio.Task[bool]] = {}",
            "self._playbacks: dict[str, asyncio.Task[bool]] = supplied",
        ),
        ("self._observers[key] = observer", "self._observers[key] = observer\n        alias = self._observers"),
        ("self._observers[key] = observer", "self._observers[key] = observer\n        alias = self"),
        ("self._observers[key] = observer", "self._observers[key] = observer\n        publish(self._observers)"),
        ("self._observers[key] = observer", "self._observers[key] = observer\n        publish(self)"),
        ("self._playbacks.pop(key, None)", "self._playbacks.clear()"),
        ("self._playbacks.pop(key, None)", "self._playbacks.pop(key, fallback)"),
        ("self._observers[key] = observer", "key = normalize(key)\n        self._observers[key] = observer"),
        ("self._observers[key] = observer", "self._observers[key] = self._observers.pop(key)"),
    ],
)
def test_ambiguous_and_independent_bookkeeping_abstains(old: str, new: str) -> None:
    assert _check(_SOURCE.replace(old, new)) == []


@pytest.mark.parametrize(
    "extra",
    [
        "    def done(self, key: str) -> None:\n        self._observers.pop(key, None)\n",
        "    def update(self, key: str, value: asyncio.Task[bool]) -> None:\n        self._playbacks[key] = value\n",
        "    def reset(self) -> None:\n        self._playbacks = {}\n",
        "    def update(self) -> None:\n        self._playbacks.update({})\n",
        "    def update(self, key: str) -> None:\n        self._playbacks[key] += other\n",
        "    def __getattr__(self, name: str) -> object:\n        return dynamic(name)\n",
    ],
)
def test_unpaired_mutation_and_dynamic_owners_abstain(extra: str) -> None:
    assert _check(_SOURCE + extra) == []


def test_captured_receiver_and_key_in_cleanup_callback_keep_binding_identity() -> None:
    source = _SOURCE.replace(
        "        self._observers.pop(key, None)\n        self._playbacks.pop(key, None)",
        "        def done() -> None:\n            self._observers.pop(key, None)\n            self._playbacks.pop(key, None)\n        register(done)",
    )
    [finding] = _check(source)
    assert "done:11, done:12" in finding.message
    shadowed = source.replace("def done()", "def done(self)")
    assert _check(shadowed) == []


def test_async_boundaries_are_not_treated_as_atomic_bookkeeping() -> None:
    source = _SOURCE.replace("    def start(", "    async def start(")
    assert len(_check(source)) == 1
    separated = source.replace(
        "        self._playbacks[key]", "        await checkpoint()\n        self._playbacks[key]"
    )
    assert _check(separated) == []
    awaited_value = source.replace("self._playbacks[key] = playback", "self._playbacks[key] = await build()")
    assert _check(awaited_value) == []


def test_nested_generic_annotations_do_not_prove_primitive_keys() -> None:
    source = _SOURCE.replace(
        "        self._observers.pop(key, None)\n        self._playbacks.pop(key, None)",
        "        def done[str](key: str) -> None:\n            self._observers.pop(key, None)\n"
        "            self._playbacks.pop(key, None)\n        done(key)",
    )
    assert _check(source) == []


def test_typing_final_and_renamed_fields_preserve_structural_evidence() -> None:
    source = "from typing import final as closed\n" + _SOURCE.replace("class Playback:", "@closed\nclass Playback:")
    source = source.replace("_observers", "_left").replace("_playbacks", "_right")
    assert len(_check(source)) == 1


def test_deletion_pairs_are_supported_without_reordering_exceptions() -> None:
    source = _SOURCE.replace("self._observers.pop(key, None)", "del self._observers[key]").replace(
        "self._playbacks.pop(key, None)", "del self._playbacks[key]"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize("prefix", ["dict = custom\n", "str = custom\n", "from unknown import *\n"])
def test_shadowed_types_and_ambiguous_namespaces_abstain(prefix: str) -> None:
    assert _check(prefix + _SOURCE) == []


def test_profile_order_suppression_and_warning_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    names = (PreferCoordinatedStateOwner.id, "prefer-discriminated-model-union", "cancel-owned-task-without-join")
    for order in (names, tuple(reversed(names))):
        rules = [REGISTRY[name]() for name in order]
        findings = check_source(rules, Path("app/playback.py"), _SOURCE)
        assert [finding.code for finding in findings] == [PreferCoordinatedStateOwner.code]
    suppressed = _SOURCE.replace(
        "self._observers[key] = observer",
        "self._observers[key] = observer  # sarj-noqa: SARJ565 -- These are intentionally mirrored protocol stores.",
    )
    assert _check(suppressed) == []
    path = tmp_path / "playback.py"
    path.write_text(_SOURCE)
    assert main(["check", "--rule", PreferCoordinatedStateOwner.id, str(path)]) == 0
    assert "warning:" in capsys.readouterr().out


def test_owner_migrations_never_offer_an_automatic_fix(tmp_path: Path) -> None:
    path = tmp_path / "playback.py"
    path.write_text(_SOURCE)
    first = fix_paths([path], rule_ids=[PreferCoordinatedStateOwner.id])
    second = fix_paths([path], rule_ids=[PreferCoordinatedStateOwner.id])
    assert first == second == 0
    assert path.read_text() == _SOURCE


@pytest.mark.parametrize("path", ["tests/test_playback.py", "generated/playback.py"])
def test_nonproduction_paths_are_excluded(path: str) -> None:
    assert _check(_SOURCE, path) == []


def test_malformed_and_generated_sources_abstain() -> None:
    assert _check("class Broken(") == []
    assert _check("# @generated\n" + _SOURCE) == []


def test_analysis_bounds_abstain_without_partial_evidence() -> None:
    large = _SOURCE.replace("    def finish(", "        pass\n" * 4100 + "    def finish(")
    assert _check(large) == []
    many = _SOURCE.replace(
        "    def start(",
        "".join(f"        self._extra{index}: dict[str, str] = {{}}\n" for index in range(17)) + "    def start(",
    )
    assert _check(many) == []


@pytest.mark.parametrize("owner", ["Playback", "_Playback", "___"])
def test_private_names_follow_the_lexical_class(owner: str) -> None:
    source = _SOURCE.replace("class Playback:", f"class {owner}:").replace("self._", "self.__")
    assert len(_check(source)) == 1
    prefix = f"_{owner.lstrip('_')}" if owner.lstrip("_") else ""
    source += f"    def independent(self, key: str) -> None:\n        self.{prefix}__observers.pop(key, None)\n"
    assert _check(source) == []


def test_two_spellings_of_one_physical_dictionary_are_not_two_fields() -> None:
    source = _SOURCE.replace("_observers", "__observers").replace("_playbacks", "_Playback__observers")
    assert _check(source) == []


def test_nested_class_mangling_does_not_hide_an_outer_field_mutation() -> None:
    source = _SOURCE.replace("_observers", "__observers").replace("_playbacks", "__playbacks")
    source += (
        "    def independent(self, key: str) -> None:\n"
        "        class Inner:\n"
        "            def remove():\n"
        "                self._Playback__observers.pop(key, None)\n"
    )
    assert _check(source) == []


def test_implementation_defined_long_private_mangling_abstains() -> None:
    assert _check(_SOURCE.replace("_observers", "__" + "x" * 256)) == []


@pytest.mark.parametrize(
    "extra",
    [
        "        state = self.__getstate__()\n        state['_observers'].pop(key, None)\n",
        "        state = self.__reduce__()\n",
        "        state = self.__reduce_ex__(4)\n",
        "        receiver = self.start.__self__\n        receiver._observers.pop(key, None)\n",
        "        def capture():\n            return self\n        receiver = capture.__closure__[0].cell_contents\n",
        "        self = self\n        self._observers.pop(key, None)\n",
        "        del self\n        self._observers.pop(key, None)\n",
        "        def remove():\n            nonlocal self\n            self._observers.pop(key, None)\n",
    ],
)
def test_reflection_and_ambiguous_receiver_bindings_abstain(extra: str) -> None:
    assert _check(_SOURCE + "    def independent(self, key: str) -> None:\n" + extra) == []


def test_a_shadowed_nested_receiver_is_an_independent_binding() -> None:
    source = _SOURCE + (
        "    def other(self, key: str) -> None:\n"
        "        def mutate(self):\n"
        "            self = self\n"
        "            self._observers.pop(key, None)\n"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "prefix",
    [
        "print.__self__.str = object\n",
        "from builtins import print as output\noutput.__self__.str = object\n",
        "import builtins as native\nnative.print.__self__.str = object\n",
        "output = print\noutput.__self__.str = object\n",
    ],
)
def test_bound_builtin_namespace_escape_invalidates_builtin_type_proof(prefix: str) -> None:
    assert _check(prefix + _SOURCE) == []


@pytest.mark.parametrize("member", ["__self__", "__closure__"])
def test_unrelated_application_reflection_preserves_owner_evidence(member: str) -> None:
    prefix = f"from app import callback\napplication = callback.{member}\n"
    assert len(_check(prefix + _SOURCE)) == 1


def test_a_later_cross_method_cleanup_is_a_lifecycle_witness() -> None:
    source = _SOURCE.replace(
        "    def finish(",
        "        if stopped():\n            self._observers.pop(key, None)\n"
        "            self._playbacks.pop(key, None)\n    def finish(",
    )
    assert len(_check(source)) == 1
    local_only = source[: source.index("    def finish(")]
    assert _check(local_only) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("= {}", "= dict()"),
        ("class Playback:", "class Playback(object):"),
        ("    def start(", "    @final\n    def start("),
    ],
)
def test_additional_proven_plain_class_forms(old: str, new: str) -> None:
    source = "from typing import final\n" + _SOURCE.replace(old, new)
    assert len(_check(source)) == 1


def test_class_annotations_do_not_create_shared_dictionary_values() -> None:
    source = (
        _SOURCE.replace(
            "    def __init__(self) -> None:",
            "    _observers: dict[str, asyncio.Task[None]]\n"
            "    _playbacks: dict[str, asyncio.Task[bool]]\n"
            "    def __init__(self) -> None:",
        )
        .replace("self._observers: dict[str, asyncio.Task[None]]", "self._observers")
        .replace("self._playbacks: dict[str, asyncio.Task[bool]]", "self._playbacks")
    )
    assert len(_check(source)) == 1
    assert (
        _check(
            source.replace(
                "_observers: dict[str, asyncio.Task[None]]", "_observers: dict[str, asyncio.Task[None]] = {}"
            )
        )
        == []
    )
    assert _check(source.replace("    _observers:", "    _observers: bytes\n    _observers:")) == []


@pytest.mark.parametrize("prefix", ["object = supplied\n", "dict = supplied\n", "final = supplied\n"])
def test_expanded_class_forms_still_require_builtin_and_decorator_identity(prefix: str) -> None:
    source = "from typing import final\n" + prefix + _SOURCE.replace("class Playback:", "class Playback(object):")
    source = source.replace("= {}", "= dict()").replace("    def start(", "    @final\n    def start(")
    assert _check(source) == []


def _third_field(source: str = _SOURCE) -> str:
    return (
        source.replace("    def start(", "        self._receipts: dict[str, str] = {}\n    def start(")
        .replace(
            "        self._playbacks[key] = playback",
            "        self._playbacks[key] = playback\n        self._receipts[key] = 'saved'",
        )
        .replace(
            "        self._playbacks.pop(key, None)",
            "        self._playbacks.pop(key, None)\n        self._receipts.pop(key, None)",
        )
    )


def test_three_coordinated_fields_have_one_maximal_finding() -> None:
    [finding] = _check(_third_field())
    assert all(f"Playback.{field}" in finding.message for field in ("_observers", "_playbacks", "_receipts"))
    assert finding.fixes == ()


def test_grouped_removal_order_does_not_have_to_match_assignment_order() -> None:
    source = _third_field().replace(
        "        self._observers.pop(key, None)\n        self._playbacks.pop(key, None)\n        self._receipts.pop(key, None)",
        "        self._receipts.pop(key, None)\n        self._observers.pop(key, None)\n        self._playbacks.pop(key, None)",
    )
    assert len(_check(source)) == 1


def test_independently_completing_third_field_keeps_only_the_coordinated_pair() -> None:
    source = _third_field() + "    def receipt_done(self, key: str) -> None:\n        self._receipts.pop(key, None)\n"
    [finding] = _check(source)
    assert "Playback._receipts" not in finding.message


def test_disjoint_owners_report_separately_without_overlapping_diagnostics() -> None:
    source = _SOURCE.replace(
        "    def start(",
        "        self._pending: dict[str, str] = {}\n        self._results: dict[str, str] = {}\n    def start(",
    ) + (
        "    def queue(self, key: str) -> None:\n"
        "        self._pending[key] = 'pending'\n        self._results[key] = 'result'\n"
        "    def complete(self, key: str) -> None:\n"
        "        self._results.pop(key, None)\n        self._pending.pop(key, None)\n"
    )
    findings = _check(source)
    assert len(findings) == 2
    assert sum("Playback._observers" in finding.message for finding in findings) == 1
    assert sum("Playback._pending" in finding.message for finding in findings) == 1


def test_many_distinct_group_candidates_abstain_as_one_bounded_analysis() -> None:
    fields = [f"_entry{index}" for index in range(16)]
    source = "class Entries:\n    def __init__(self):\n" + "".join(
        f"        self.{field}: dict[str, str] = {{}}\n" for field in fields
    )
    cleanup = "    def finish(self, key: str):\n" + "".join(
        f"        self.{field}.pop(key, None)\n" for field in fields
    )
    for ordinal, multiplier in enumerate((1, 3, 5, 7)):
        for offset in range(3):
            source += f"    def start{ordinal}_{offset}(self, key: str):\n" + "".join(
                f"        self.{fields[(index * multiplier + offset) % 16]}[key] = 'value'\n" for index in range(16)
            )
            if ordinal == offset == 0:
                assert len(_check(source + cleanup)) == 1
    source += cleanup
    assert sum(1 for _ in ast.walk(ast.parse(source))) < 4096
    assert _check(source) == []


def test_nested_class_namespace_is_not_a_method_closure() -> None:
    source = _SOURCE + (
        "    def independent(self, key: str) -> None:\n"
        "        class Shadow:\n"
        "            self = None\n"
        "            def remove():\n"
        "                self._observers.pop(key, None)\n"
        "        Shadow.remove()\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "extra",
    [
        "        receiver = getattr(self.start, '__self__')\n        receiver._observers.pop(key, None)\n",
        "        register(self.finish)\n",
        "        method = self.start\n        inspect(method)\n",
        "        owner = self.__class__\n        owner.start = replacement\n",
        "        state = getattr(super(), '__getstate__')()\n        state['_observers'].pop(key, None)\n",
        "        parent = super\n        state = getattr(parent(), '__getstate__')()\n        state['_observers'].pop(key, None)\n",
        "        owner = __class__\n        owner.start = replacement\n",
    ],
)
def test_bound_method_and_class_escapes_abstain(extra: str) -> None:
    assert _check(_SOURCE + "    def inspect(self, key: str) -> None:\n" + extra) == []


def test_private_bound_method_names_have_the_same_escape_contract() -> None:
    source = _SOURCE + "    def inspect(self) -> None:\n        register(self.start)\n"
    assert _check(source.replace("def start(", "def __start(").replace("self.start", "self.__start")) == []


def test_direct_local_method_calls_do_not_escape_the_receiver() -> None:
    source = _SOURCE + "    def complete(self, key: str) -> None:\n        self.finish(key)\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "expression",
    [
        "[value async for value in values]",
        "{value async for value in values}",
        "{value: value async for value in values}",
    ],
)
def test_implicit_async_comprehension_await_between_dictionary_writes_abstains(expression: str) -> None:
    source = (
        "from collections.abc import AsyncIterator\n"
        "class Entries:\n"
        "    def __init__(self) -> None:\n"
        "        self._values: dict[str, object] = {}\n"
        "        self._labels: dict[str, str] = {}\n"
        "    async def start(self, key: str, values: AsyncIterator[int], label: str) -> None:\n"
        "        self._labels[key] = label\n"
        f"        self._values[key] = {expression}\n"
        "    def finish(self, key: str) -> None:\n"
        "        self._values.pop(key, None)\n"
        "        self._labels.pop(key, None)\n"
    )
    assert _check(source) == []
