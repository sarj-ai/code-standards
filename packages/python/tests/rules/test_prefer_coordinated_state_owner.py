from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source, main
from sarj_python_lint.autofix import fix_paths
from sarj_python_lint.rule_base import Diagnostic, Severity
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules.prefer_coordinated_state_owner import PreferCoordinatedStateOwner


_SOURCE = PreferCoordinatedStateOwner.public_examples()[0].focus_file.source


def _check(source: str, path: str = "app/playback.py") -> list[Diagnostic]:
    return PreferCoordinatedStateOwner().check(Path(path), source)


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
