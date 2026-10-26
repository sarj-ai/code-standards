from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from sarj_rule_contracts import RuleId


_KEYWORD_RULE = "require-keyword-only-swap-prone-params"
_COMPREHENSION_RULE = "prefer-walrus-comprehension-filter"
_LOOP_RULE = "no-string-concat-in-loop"
_REGEX_RULE = "prefer-regex-fullmatch"


@pytest.mark.parametrize(
    "body",
    [
        "for item in {1, 2}:\n        pass",
        "values = [1]\n    for item in values:\n        values.append(1)",
    ],
    ids=("unordered-set-iteration", "active-list-mutation"),
)
def test_private_contract_keeps_unproven_iteration_semantics(body: str) -> None:
    rule_id = "no-unused-underscored-keyword-parameter"
    source = f"def outer():\n    def _make(*, _unused=False):\n        return 1\n    {body}\n    return _make()\n"
    path = Path("app/service.py")
    assert REGISTRY[rule_id]().check(path, source)
    assert fix_source(path, source, rule_ids=[rule_id]) == source


@pytest.mark.parametrize(
    ("rule_id", "before", "after"),
    [
        (
            _LOOP_RULE,
            "def render():\n    def _render():\n        result = ''\n        for item in ('a', 'b'):\n            result += item\n        return result\n    return _render()\n",
            "def render():\n    def _render():\n        result = []\n        for item in ('a', 'b'):\n            result.append(item)\n        return ''.join(result)\n    return _render()\n",
        ),
        (
            _REGEX_RULE,
            "import re\ndef valid():\n    return re.match(r'^[a-z]+$', 'sample') is not None\n",
            "import re\ndef valid():\n    return re.match(r'^[a-z]+\\Z', 'sample') is not None\n",
        ),
        (
            _KEYWORD_RULE,
            "def move():\n    def _move(source_id: str, target_id: str):\n        return source_id, target_id\n    return _move('inbox', 'archive')\n",
            "def move():\n    def _move(*, source_id: str, target_id: str):\n        return source_id, target_id\n    return _move(source_id='inbox', target_id='archive')\n",
        ),
        (
            _COMPREHENSION_RULE,
            "def normalized():\n    def _normalized():\n        return [value.strip() for value in (' a ', '', ' b ') if value.strip()]\n    return _normalized()\n",
            "def normalized():\n    def _normalized():\n        return [stripped_value for value in (' a ', '', ' b ') if (stripped_value := value.strip())]\n    return _normalized()\n",
        ),
        (
            _COMPREHENSION_RULE,
            "def normalized():\n    def _normalized():\n        return [value.lower() for value in ['ABC', ''] if value.lower()]\n    return _normalized()\n",
            "def normalized():\n    def _normalized():\n        return [lowered_value for value in ['ABC', ''] if (lowered_value := value.lower())]\n    return _normalized()\n",
        ),
    ],
)
def test_closing_candidates_match_exact_output_and_converge(rule_id: RuleId, before: str, after: str) -> None:
    path = Path("app/service.py")
    assert REGISTRY[rule_id]().check(path, before)
    assert fix_source(path, before, rule_ids=[rule_id]) == after
    assert not REGISTRY[rule_id]().check(path, after)
    compile(after, str(path), "exec", dont_inherit=True)
    assert fix_source(path, after, rule_ids=[rule_id]) == after
    assert fix_source(path, before, rule_ids=[]) == before


@pytest.mark.parametrize(
    "source",
    [
        "def _move(source_id: str, target_id: str):\n    return source_id, target_id\n_move('a', 'b')\n",
        "def outer():\n    def _move(source_id: str, target_id: str='b'):\n        return source_id, target_id\n    return _move('a')\n",
        "def outer():\n    def _move(source_id: str, target_id: str, /):\n        return source_id, target_id\n    return _move('a', 'b')\n",
        "def outer():\n    def _move(source_id: str, target_id: str):\n        return source_id, target_id\n    return _move(*('a', 'b'))\n",
        "def outer():\n    def _move(source_id: str, target_id: str):\n        return source_id, target_id\n    return _move\n",
        "def outer():\n    def _move(source_id: str, target_id: str):\n        return source_id, target_id\n    return _move('a', 'b')  # retain caller explanation\n",
        "def outer[T]():\n    def _move(source_id: str, target_id: str):\n        return source_id, target_id\n    return _move('a', 'b')\n",
        "from inspect import stack as frames\ndef outer():\n    def _move(source_id: str, target_id: str):\n        return source_id, target_id\n    frames()\n    return _move('a', 'b')\n",
        "def outer():\n    def _move(source_id: str, target_id: str):\n        yield source_id, target_id\n    return _move('a', 'b')\n",
    ],
)
def test_keyword_migration_preserves_unproven_signature_contracts(source: str) -> None:
    assert fix_source(Path("app/service.py"), source, rule_ids=[_KEYWORD_RULE]) == source


@pytest.mark.parametrize(
    "source",
    [
        "def normalized():\n    return [value.strip() for value in (' a ', '') if value.strip()]\n",
        "def outer(values):\n    def _normalized():\n        return [value.strip() for value in values if value.strip()]\n    return _normalized()\n",
        "def outer():\n    def _normalized():\n        return [value.strip() for value in (' a ', '') if value.strip()]\n    return _normalized\n",
        "def outer():\n    def _normalized():\n        return [value.strip('a') for value in (' a ', '') if value.strip('a')]\n    return _normalized()\n",
        "def outer():\n    def _normalized():\n        return [value.strip() for value in (' a ', '') if value.strip() and value]\n    return _normalized()\n",
        "def outer():\n    def _normalized():\n        return [value.strip() for value in (' a ', '') if value.strip()]  # retain explanation\n    return _normalized()\n",
        "def outer():\n    def _normalized():\n        marker = 1\n        return [value.strip() for value in (' a ', '') if value.strip()]\n    return _normalized()\n",
        "def outer[T]():\n    def _normalized():\n        return [value.strip() for value in (' a ', '') if value.strip()]\n    return _normalized()\n",
        "from inspect import stack as frames\ndef outer():\n    def _normalized():\n        return [value.strip() for value in (' a ', '') if value.strip()]\n    frames()\n    return _normalized()\n",
    ],
)
def test_comprehension_cache_preserves_unproven_domains_and_scopes(source: str) -> None:
    assert fix_source(Path("app/service.py"), source, rule_ids=[_COMPREHENSION_RULE]) == source


def test_comprehension_cache_uses_a_fresh_normalized_identifier() -> None:
    source = "ｓｔｒｉｐｐｅｄ_value = 1\nstripped_value_2 = 2\ndef outer():\n    def _normalized():\n        return [value.strip() for value in [' a ', ''] if value.strip()]\n    return _normalized()\n"
    fixed = fix_source(Path("app/service.py"), source, rule_ids=[_COMPREHENSION_RULE])
    assert "[stripped_value_3 for" in fixed
    assert "(stripped_value_3 := value.strip())" in fixed
    assert fix_source(Path("app/service.py"), fixed, rule_ids=[_COMPREHENSION_RULE]) == fixed


@pytest.mark.parametrize(
    "capability",
    ["setprofile", "settrace", "setprofile_all_threads", "settrace_all_threads", "monitoring", "register_callback"],
)
@pytest.mark.parametrize("rule_id", [_KEYWORD_RULE, _COMPREHENSION_RULE])
def test_frame_capture_authorities_keep_private_metadata_unchanged(capability: str, rule_id: RuleId) -> None:
    source = (
        f"from sys import {capability} as capture_frames\n"
        "def outer():\n"
        "    def _move(source_id: str, target_id: str):\n"
        "        return source_id, target_id\n"
        "    def _normalized():\n"
        "        return [value.strip() for value in [' a ', ''] if value.strip()]\n"
        "    return _move('a', 'b'), _normalized()\n"
    )
    assert fix_source(Path("app/service.py"), source, rule_ids=[rule_id]) == source


@pytest.mark.parametrize(
    "method",
    ["strip", "lower", "upper", "lstrip", "rstrip", "casefold", "capitalize", "title", "swapcase", "expandtabs", "len"],
)
def test_exact_primitive_string_operations_can_be_cached(method: str, tmp_path: Path) -> None:
    call = "len(value)" if method == "len" else f"value.{method}()"
    source = (
        "def normalized():\n    def _normalized():\n"
        f"        return [{call} for value in (' a ', '', 'ABC', '\\u0130', '\\t', '\\u2003') if {call}]\n"
        "    return _normalized()\n"
    )
    fixed = fix_source(Path("app/service.py"), source, rule_ids=[_COMPREHENSION_RULE])
    assert fixed != source
    assert not REGISTRY[_COMPREHENSION_RULE]().check(Path("app/service.py"), fixed)
    assert fix_source(Path("app/service.py"), fixed, rule_ids=[_COMPREHENSION_RULE]) == fixed
    outcomes: list[str] = []
    for candidate in (source, fixed):
        path = tmp_path / "service.py"
        path.write_text(candidate + "\nprint(repr(normalized()))\n", encoding="utf-8")
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        outcomes.append(result.stdout)
    assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize(
    "prefix",
    [
        "len = custom\n",
        "from custom import len\n",
        "import builtins\nbuiltins.len = custom\n",
    ],
)
def test_length_cache_requires_builtin_authority(prefix: str) -> None:
    source = (
        prefix
        + "def outer():\n    def _normalized():\n        return [len(value) for value in (' a ', '') if len(value)]\n    return _normalized()\n"
    )
    assert fix_source(Path("app/service.py"), source, rule_ids=[_COMPREHENSION_RULE]) == source


@pytest.mark.parametrize(
    "pieces", [("a", "b"), ("é", "λ"), ("\0", "a"), ("\r\n", "b"), ("\ud800", "a"), ("same", "same"), ("a", "b", "c")]
)
def test_literal_loop_preserves_content_freshness_and_input_identity(pieces: tuple[str, ...], tmp_path: Path) -> None:
    source = (
        "def render():\n    def _render():\n        result = ''\n"
        f"        for item in {pieces!r}:\n            result += item\n"
        "        return result\n    return _render()\n"
    )
    fixed = fix_source(Path("app/service.py"), source, rule_ids=[_LOOP_RULE])
    assert fixed != source
    assert not REGISTRY[_LOOP_RULE]().check(Path("app/service.py"), fixed)
    assert fix_source(Path("app/service.py"), fixed, rule_ids=[_LOOP_RULE]) == fixed
    oracle = (
        f"pieces = {pieces!r}\nfirst = render()\nsecond = render()\n"
        "assert first == ''.join(pieces)\nassert first is not second\n"
        "assert all(first is not piece for piece in pieces)\n"
    )
    for candidate in (source, fixed):
        path = tmp_path / "service.py"
        path.write_text(candidate + oracle, encoding="utf-8")
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("pieces", [(), ("a",), ("", "a"), ("a", ""), ("", "")])
def test_literal_loop_preserves_identity_shortcuts_for_review(pieces: tuple[str, ...]) -> None:
    source = (
        "def render():\n    def _render():\n        result = ''\n"
        f"        for item in {pieces!r}:\n            result += item\n"
        "        return result\n    return _render()\n"
    )
    assert fix_source(Path("app/service.py"), source, rule_ids=[_LOOP_RULE]) == source


@pytest.mark.parametrize(
    "source",
    [
        "def _render():\n    result = ''\n    for item in ('a', 'b'):\n        result += item\n    return result\n_render()\n",
        "def outer():\n    def _render():\n        result = ''\n        for item in ('a', 'b'):\n            result += item\n        return result\n    return _render\n",
        "def outer(items):\n    def _render():\n        result = ''\n        for item in items:\n            result += item\n        return result\n    return _render()\n",
        "def outer():\n    def _render():\n        result = ''\n        for item in ('a', 'b'):\n            result += item\n            consume(result)\n        return result\n    return _render()\n",
        "def outer():\n    def _render():\n        result = ''\n        for item in ('a', 'b'):\n            result += item  # retain accumulator rationale\n        return result\n    return _render()\n",
        "def outer[T]():\n    def _render():\n        result = ''\n        for item in ('a', 'b'):\n            result += item\n        return result\n    return _render()\n",
        "from sys import setprofile as capture_frames\ndef outer():\n    def _render():\n        result = ''\n        for item in ('a', 'b'):\n            result += item\n        return result\n    return _render()\n",
    ],
)
def test_literal_loop_requires_an_unobserved_exact_owned_accumulator(source: str) -> None:
    assert fix_source(Path("app/service.py"), source, rule_ids=[_LOOP_RULE]) == source


@pytest.mark.parametrize(
    ("pattern", "subject"),
    [
        ("^[a-z]+$", "sample"),
        ("^[a-z]+$", "UPPER"),
        ("^[a-z]*$", ""),
        ("^[A-Z0-9]{1,3}$", "B2"),
        ("^[a-z]?$", "é"),
        ("^[a-z]+$", "\ud800"),
    ],
)
def test_strict_end_anchor_preserves_literal_validation_predicates(pattern: str, subject: str, tmp_path: Path) -> None:
    source = f"import re\ndef valid():\n    return re.match({pattern!r}, {subject!r}) is not None\n"
    fixed = fix_source(Path("app/service.py"), source, rule_ids=[_REGEX_RULE])
    assert fixed != source
    assert "re.match(" in fixed
    assert "fullmatch" not in fixed
    assert not REGISTRY[_REGEX_RULE]().check(Path("app/service.py"), fixed)
    assert fix_source(Path("app/service.py"), fixed, rule_ids=[_REGEX_RULE]) == fixed
    outputs: list[str] = []
    for candidate in (source, fixed):
        path = tmp_path / "service.py"
        path.write_text(candidate + "\nprint(valid())\n", encoding="utf-8")
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize(
    "source",
    [
        "import re\ndef valid(value):\n    return re.match(r'^[a-z]+$', value) is not None\n",
        "import re\ndef valid():\n    return re.match(r'^[a-z]+$', 'a\\n') is not None\n",
        "import re\ndef valid():\n    return re.match(r'^(a|b)$', 'a') is not None\n",
        "import re\ndef valid():\n    return re.match(r'^[a-z]+$', 'a', re.I) is not None\n",
        "import re\ndef valid():\n    return re.match(r'^[a-z]+$', 'a')\n",
        "import re\nfrom unittest.mock import patch\ndef valid():\n    with patch('re.fullmatch', return_value=None):\n        return re.match(r'^[a-z]+$', 'a') is not None\n",
        "import re\ngetattr(re, 'match')\ndef valid():\n    return re.match(r'^[a-z]+$', 'a') is not None\n",
        "import re\nalias = re\ndef valid():\n    return re.match(r'^[a-z]+$', 'a') is not None\n",
        "import re\ndef valid[re]():\n    return re.match(r'^[a-z]+$', 'a') is not None\n",
    ],
)
def test_strict_end_anchor_preserves_dynamic_contracts_and_regex_authority(source: str) -> None:
    assert fix_source(Path("app/service.py"), source, rule_ids=[_REGEX_RULE]) == source


@pytest.mark.parametrize(
    ("source", "oracle"),
    [
        (
            "def outer():\n    def _emit(*, _unused=True):\n        return 'ready'\n    yield _emit(_unused=False)\n",
            "generator = outer()\nassert next(generator) == 'ready'\nassert generator.gi_frame.f_locals['_emit'](_unused=False) == 'ready'\ngenerator.close()\n",
        ),
        (
            "def outer():\n    def _emit(*, _unused=True):\n        return 'ready'\n    return (_emit(_unused=False) for item in ('a',))\n",
            "generator = outer()\nassert generator.gi_frame.f_locals['_emit'](_unused=False) == 'ready'\ngenerator.close()\n",
        ),
        (
            "def outer():\n    def _emit(*, _unused=True):\n        return 'ready'\n    def wrapper():\n        return _emit(_unused=False)\n    return wrapper\n",
            "wrapper = outer()\nassert wrapper.__closure__[0].cell_contents(_unused=False) == 'ready'\n",
        ),
        (
            "def outer():\n    def _emit(*, _unused=True):\n        return 'ready'\n    async def wrapper():\n        return _emit(_unused=False)\n    return wrapper()\n",
            "coroutine = outer()\nassert coroutine.cr_frame.f_locals['_emit'](_unused=False) == 'ready'\ncoroutine.close()\n",
        ),
        (
            "async def outer(pause):\n    def _emit(*, _unused=True):\n        return 'ready'\n    await pause()\n    return _emit(_unused=False)\n",
            "class Pause:\n    def __await__(self):\n        yield 'pause'\ncoroutine = outer(Pause)\nassert coroutine.send(None) == 'pause'\nassert coroutine.cr_frame.f_locals['_emit'](_unused=False) == 'ready'\ncoroutine.close()\n",
        ),
    ],
)
def test_private_helper_contracts_cannot_escape_through_outer_frames_or_closures(
    source: str, oracle: str, tmp_path: Path
) -> None:
    fixed = fix_source(Path("app/service.py"), source, rule_ids=["no-unused-underscored-keyword-parameter"])
    assert fixed == source
    path = tmp_path / "service.py"
    path.write_text(fixed + "\n" + oracle, encoding="utf-8")
    result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("rule_id", ["no-unnecessary-docstring", "redundant-docstring"])
def test_private_docstring_metadata_cannot_escape_in_an_outer_generator(rule_id: RuleId) -> None:
    source = 'def outer():\n    def _normalize(item):\n        """Normalize."""\n        return item\n    yield _normalize(3)\n'
    assert fix_source(Path("app/service.py"), source, rule_ids=[rule_id]) == source


@pytest.mark.parametrize(
    ("rule_id", "source", "oracle"),
    [
        (
            _KEYWORD_RULE,
            "def move():\n    def _move(source_id: str, target_id: str):\n        return source_id, target_id\n    return _move('inbox', 'archive')\n",
            "assert move() == ('inbox', 'archive')\n",
        ),
        (
            _COMPREHENSION_RULE,
            "def normalized():\n    def _normalized():\n        return [value.strip() for value in (' a ', '', ' b ', '\\u2003') if value.strip()]\n    return _normalized()\n",
            "assert normalized() == ['a', 'b']\n",
        ),
        (
            _COMPREHENSION_RULE,
            "def normalized():\n    def _normalized():\n        return [value.lower() for value in ['ABC', '', '\\u0130', '\\u1e9e'] if value.lower()]\n    return _normalized()\n",
            "assert normalized() == ['abc', 'i\\u0307', '\\u00df']\n",
        ),
    ],
)
def test_closing_candidates_preserve_runtime_values_and_evaluation_order(
    rule_id: RuleId, source: str, oracle: str, tmp_path: Path
) -> None:
    path = tmp_path / "service.py"
    fixed = fix_source(Path("app/service.py"), source, rule_ids=[rule_id])
    assert fixed != source
    for candidate in (source, fixed):
        path.write_text(candidate + "\n" + oracle, encoding="utf-8")
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
