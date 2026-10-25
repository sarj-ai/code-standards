from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import NamedTuple

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


class _RuntimeCase(NamedTuple):
    rule_id: str
    source: str
    oracle: str


_REVIEW_RUNTIME_CASES = (
    _RuntimeCase(
        "prefer-match-type-dispatch",
        "def label(value):\n"
        "    if isinstance(value, str):\n        return 'text'\n"
        "    elif isinstance(value, bytes):\n        return 'bytes'\n"
        "    elif isinstance(value, int):\n        return 'number'\n"
        "    return 'other'\n",
        "class Text(str): pass\n"
        "assert [label(value) for value in [Text('x'), b'x', 1, True, object()]] == ['text', 'bytes', 'number', 'number', 'other']\n",
    ),
    _RuntimeCase(
        "prefer-match-value-dispatch",
        "def label(value):\n"
        "    if value == 'one':\n        return 1\n"
        "    elif value == 'two':\n        return 2\n"
        "    elif value == 'three':\n        return 3\n"
        "    else:\n        return 0\n",
        "class Value:\n"
        "    def __init__(self): self.seen = []\n"
        "    def __eq__(self, other):\n"
        "        self.seen.append(other)\n"
        "        return other == 'two'\n"
        "value = Value()\nassert label(value) == 2\nassert value.seen == ['one', 'two']\n"
        "assert label('missing') == 0\n",
    ),
    _RuntimeCase(
        "prefer-collection-comprehension",
        "def values(rows):\n"
        "    result = {}\n"
        "    for key, row in rows:\n        result[key] = row.value\n"
        "    return result\n",
        "seen = []\n"
        "class Row:\n"
        "    def __init__(self, value): self._value = value\n"
        "    @property\n"
        "    def value(self):\n"
        "        seen.append(self._value)\n"
        "        return self._value\n"
        "result = values([('a', Row(1)), ('b', Row(2)), ('a', Row(3))])\n"
        "assert list(result.items()) == [('a', 3), ('b', 2)]\n"
        "assert seen == [1, 2, 3]\n",
    ),
)


_CASES = (
    _RuntimeCase(
        "no-broad-keyword-capture",
        "def adapt(value):\n    def _adapt(value, *, strict=True, **kwargs: object):\n        return value, strict\n    return _adapt(value, strict=False)\n",
        "assert adapt(3) == (3, False)\n",
    ),
    _RuntimeCase(
        "no-unused-underscored-keyword-parameter",
        "def emit():\n    def _emit(value=None, *, _unused=True):\n        return value\n    return _emit(3, _unused=False)\n",
        "assert emit() == 3\n",
    ),
    _RuntimeCase(
        "unused-test-factory-option",
        "def test_widgets():\n    def _make_widget(*, enabled=True):\n        return dict(enabled=enabled)\n    return [_make_widget(), _make_widget(enabled=True)]\n",
        "assert test_widgets() == [{'enabled': True}, {'enabled': True}]\n",
    ),
    _RuntimeCase(
        "prefer-walrus-stream-loop",
        "def consume(read):\n"
        "    result = []\n"
        "    while True:\n"
        "        chunk = read()\n"
        "        if chunk is None:\n"
        "            break\n"
        "        result.append(chunk)\n"
        "    return result\n",
        "items = iter([0, '', False, 'ready', None, 'unread'])\n"
        "assert consume(lambda: next(items)) == [0, '', False, 'ready']\n"
        "assert next(items) == 'unread'\n",
    ),
    _RuntimeCase(
        "prefer-walrus-awaited-none-guard",
        "async def load(store):\n"
        "    item = await store.get()\n"
        "    if item is None:\n"
        "        return\n"
        "    return item.name\n",
        "import asyncio\n"
        "from types import SimpleNamespace\n"
        "class Store:\n"
        "    def __init__(self, item):\n"
        "        self.item = item\n"
        "        self.calls = 0\n"
        "    async def get(self):\n"
        "        self.calls += 1\n"
        "        return self.item\n"
        "for item, expected in [(None, None), (SimpleNamespace(name='ready'), 'ready')]:\n"
        "    store = Store(item)\n"
        "    assert asyncio.run(load(store)) == expected\n"
        "    assert store.calls == 1\n",
    ),
    _RuntimeCase(
        "prefer-walrus-regex-match",
        "import re\n"
        "def parse(text):\n"
        "    found = re.search(r'\\d+', text)\n"
        "    if found is not None:\n"
        "        return found.group(0)\n"
        "    return None\n",
        "assert parse('a12b') == '12'\nassert parse('none') is None\n",
    ),
    _RuntimeCase(
        "prefer-fstring-over-concat",
        "def label(value):\n    return 'The value is ' + str(len(value)) + '!'\n",
        "class Sized:\n"
        "    def __init__(self):\n"
        "        self.calls = 0\n"
        "    def __len__(self):\n"
        "        self.calls += 1\n"
        "        return 3\n"
        "value = Sized()\nassert label(value) == 'The value is 3!'\nassert value.calls == 1\n",
    ),
    _RuntimeCase(
        "prefer-match-type-dispatch",
        "def label():\n    def _label(value):\n        if isinstance(value, str):\n            return 'text'\n        elif isinstance(value, bytes):\n            return 'bytes'\n        elif isinstance(value, int):\n            return 'number'\n        return 'other'\n    return _label('x'), _label(b'x'), _label(1), _label(True), _label(None)\n",
        "assert label() == ('text', 'bytes', 'number', 'number', 'other')\n",
    ),
    _RuntimeCase(
        "prefer-match-value-dispatch",
        "def label():\n    def _label(value):\n        if value == 'one':\n            return 1\n        elif value == 'two':\n            return 2\n        elif value == 'three':\n            return 3\n        else:\n            return 0\n    return _label('one'), _label('two'), _label('three'), _label('missing')\n",
        "assert label() == (1, 2, 3, 0)\n",
    ),
    _RuntimeCase(
        "duplicate-adjacent-exception-handler",
        "def translate(call):\n"
        "    try:\n        call()\n"
        "    except ValueError as error:\n        raise RuntimeError('invalid') from error\n"
        "    except TypeError as error:\n        raise RuntimeError('invalid') from error\n",
        "def fail(error): raise error\n"
        "for error in [ValueError('v'), TypeError('t')]:\n"
        "    try: translate(lambda: fail(error))\n"
        "    except RuntimeError as translated:\n"
        "        assert str(translated) == 'invalid'\n"
        "        assert translated.__cause__ is error\n"
        "    else: raise AssertionError('translation did not raise')\n"
        "other = KeyError('k')\n"
        "try: translate(lambda: fail(other))\n"
        "except KeyError as unchanged: assert unchanged is other\n"
        "else: raise AssertionError('unhandled error was swallowed')\n",
    ),
    _RuntimeCase(
        "prefer-collection-comprehension",
        "def values():\n    result = {}\n    for key, row in [('a', 1), ('b', 2), ('a', 3)]:\n        result[key] = (row,)\n    return result\n",
        "assert list(values().items()) == [('a', (3,)), ('b', (2,))]\n",
    ),
    _RuntimeCase(
        "prefer-or-pattern",
        "def label(value):\n"
        "    match value:\n"
        "        case 'one':\n            return 1\n"
        "        case 'two':\n            return 1\n"
        "    return 0\n",
        "assert [label(value) for value in ['one', 'two', 'other']] == [1, 1, 0]\n",
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.rule_id for case in _CASES))
def test_runtime_fixes_preserve_values_order_and_exception_contracts(case: _RuntimeCase, tmp_path: Path) -> None:
    path = tmp_path / ("test_runtime.py" if case.rule_id == "unused-test-factory-option" else "runtime.py")
    fixed = fix_source(path, case.source, rule_ids=[case.rule_id])
    assert fixed != case.source
    for source in (case.source, fixed):
        path.write_text(source + "\n" + case.oracle, encoding="utf-8")
        runtime = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert runtime.returncode == 0, runtime.stderr


@pytest.mark.parametrize(
    "case",
    [
        *_REVIEW_RUNTIME_CASES,
        _RuntimeCase(
            "no-broad-keyword-capture",
            "events = []\ndef default():\n    events.append('default')\n    return 3\ndef adapt():\n    def _adapt(value=default(), **kwargs):\n        return value\n    return _adapt()\n",
            "assert adapt() == 3\nassert adapt() == 3\nassert events == ['default', 'default']\n",
        ),
        _RuntimeCase(
            "no-unused-underscored-keyword-parameter",
            "events = []\ndef mark():\n    events.append('argument')\n    return 3\ndef emit():\n    def _emit(value=None, *, _unused=True):\n        events.append(value)\n        return value\n    return _emit(mark(), _unused=False)\n",
            "assert emit() == 3\nassert events == ['argument', 3]\n",
        ),
        _RuntimeCase(
            "require-keyword-only-swap-prone-params",
            "events = []\ndef mark(value):\n    events.append(value)\n    return value\ndef move():\n    def _move(source_id: str, target_id: str):\n        return source_id, target_id\n    return _move(mark('inbox'), mark('archive'))\n",
            "assert move() == ('inbox', 'archive')\nassert events == ['inbox', 'archive']\n",
        ),
    ],
    ids=(
        "public-type-dispatch",
        "public-value-dispatch",
        "dynamic-collection",
        "default-callout",
        "helper-and-argument-callouts",
        "keyword-migration-argument-callouts",
    ),
)
def test_effectful_callouts_keep_the_original_private_contract(case: _RuntimeCase, tmp_path: Path) -> None:
    assert fix_source(Path("app/service.py"), case.source, rule_ids=[case.rule_id]) == case.source
    path = tmp_path / "service.py"
    path.write_text(case.source + "\n" + case.oracle, encoding="utf-8")
    runtime = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
    assert runtime.returncode == 0, runtime.stderr


@pytest.mark.parametrize(
    "case",
    [
        _RuntimeCase(
            "no-unused-underscored-keyword-parameter",
            "from inspect import stack\nfrom operator import attrgetter\ndef emit():\n    def _emit(*, _unused=True):\n        return 'ready'\n    _emit()\n    functions = attrgetter('f_locals')(stack()[0][0])\n    return functions['_emit'](_unused=False)\n",
            "assert emit() == 'ready'\n",
        ),
        _RuntimeCase(
            "no-broad-keyword-capture",
            "from inspect import stack as frames\nfrom operator import attrgetter\ndef adapt(value):\n    def _adapt(value, **kwargs):\n        return value\n    _adapt(value)\n    functions = attrgetter('f_locals')(frames()[0][0])\n    return functions['_adapt'](value, extra=False)\n",
            "assert adapt(3) == 3\n",
        ),
        _RuntimeCase(
            "unused-test-factory-option",
            "from inspect import stack as frames\nfrom operator import attrgetter\nclass Widget:\n    def __init__(self, *, enabled):\n        self.enabled = enabled\ndef test_widgets():\n    def _make_widget(*, enabled=True):\n        return Widget(enabled=enabled)\n    _make_widget()\n    _make_widget()\n    functions = attrgetter('f_locals')(frames()[0][0])\n    return functions['_make_widget'](enabled=False)\n",
            "assert test_widgets().enabled is False\n",
        ),
        _RuntimeCase(
            "redundant-docstring",
            'def outer():\n    def _normalize(item):\n        """Normalize."""\n        yield item\n    return _normalize(3)\n',
            "value = outer()\nassert 'Normalize.' in value.gi_code.co_consts\nassert next(value) == 3\n",
        ),
        _RuntimeCase(
            "redundant-docstring",
            'def outer():\n    async def _normalize(item):\n        """Normalize."""\n        return item\n    return _normalize(3)\n',
            "value = outer()\nassert 'Normalize.' in value.cr_code.co_consts\nvalue.close()\n",
        ),
    ],
    ids=("unused-keyword-frame", "capture-frame", "factory-frame", "generator-docstring", "coroutine-docstring"),
)
def test_frame_and_generator_metadata_require_unchanged_private_contracts(case: _RuntimeCase, tmp_path: Path) -> None:
    path = tmp_path / ("test_runtime.py" if case.rule_id == "unused-test-factory-option" else "runtime.py")
    fixed = fix_source(path, case.source, rule_ids=[case.rule_id])
    assert fixed == case.source
    path.write_text(fixed + "\n" + case.oracle, encoding="utf-8")
    runtime = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
    assert runtime.returncode == 0, runtime.stderr


@pytest.mark.parametrize(
    "body",
    [
        "value = None",
        "for value in ('done',):\n        pass",
        "values = [value]\n    value = None\n    values = []",
        "def retain(captured=value):\n        return captured\n    value = None\n    retain = None",
        "held = value\n    def retain():\n        return held\n    value = None\n    retain = None\n    held = None",
    ],
    ids=("assignment", "loop-target", "container-release", "default-release", "closure-release"),
)
def test_unknown_value_finalizers_keep_the_live_private_contract(body: str, tmp_path: Path) -> None:
    rule_id = "no-unused-underscored-keyword-parameter"
    source = f"def outer(value):\n    def _make(*, _unused=False):\n        return 1\n    {body}\n    return _make()\n"
    path = Path("app/service.py")
    assert REGISTRY[rule_id]().check(path, source)
    assert fix_source(path, source, rule_ids=[rule_id]) == source
    (tmp_path / "observer.py").write_text(
        "import sys\n"
        "observations = []\n"
        "class Finalizer:\n"
        "    def __del__(self):\n"
        "        frame = sys._getframe(1)\n"
        "        while frame is not None:\n"
        "            if '_make' in frame.f_locals:\n"
        "                observations.append(tuple(frame.f_locals['_make'].__kwdefaults__ or {}))\n"
        "                return\n"
        "            frame = frame.f_back\n",
        encoding="utf-8",
    )
    rejected = source.replace("_make(*, _unused=False)", "_make()")
    for index, (candidate, expected) in enumerate(((source, [("_unused",)]), (rejected, [()]))):
        program = tmp_path / f"runtime_{index}.py"
        program.write_text(
            "from observer import Finalizer, observations\n"
            + candidate
            + f"\nouter(Finalizer())\nassert observations == {expected!r}\n",
            encoding="utf-8",
        )
        runtime = subprocess.run([sys.executable, str(program)], capture_output=True, text=True, check=False)
        assert runtime.returncode == 0, runtime.stderr


def test_uninitialized_global_error_keeps_private_traceback_metadata(tmp_path: Path) -> None:
    rule_id = "no-unused-underscored-keyword-parameter"
    source = (
        "unbound: object\n"
        "def outer():\n"
        "    def _make(*, _unused=False):\n"
        "        return 1\n"
        "    _make()\n"
        "    return unbound\n"
    )
    path = Path("app/service.py")
    assert REGISTRY[rule_id]().check(path, source)
    assert fix_source(path, source, rule_ids=[rule_id]) == source
    rejected = source.replace("_make(*, _unused=False)", "_make()")
    for index, (candidate, expected) in enumerate(((source, ("_unused",)), (rejected, ()))):
        program = tmp_path / f"runtime_{index}.py"
        program.write_text(
            candidate + "\ntry:\n    outer()\nexcept NameError as error:\n"
            "    trace = error.__traceback__\n"
            "    while trace is not None:\n"
            "        if '_make' in trace.tb_frame.f_locals:\n"
            f"            assert tuple(trace.tb_frame.f_locals['_make'].__kwdefaults__ or {{}}) == {expected!r}\n"
            "            break\n"
            "        trace = trace.tb_next\n"
            "    else:\n        raise AssertionError('private frame missing')\n"
            "else:\n    raise AssertionError('uninitialized name did not raise')\n",
            encoding="utf-8",
        )
        runtime = subprocess.run([sys.executable, str(program)], capture_output=True, text=True, check=False)
        assert runtime.returncode == 0, runtime.stderr
