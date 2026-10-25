from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


@dataclass(frozen=True, slots=True)
class _ObserverCase:
    name: str
    rule_id: str
    path: str
    helper: str
    source: str
    rejected: str
    invocation: str
    exception_name: str | None = None


_PROVIDER_IMPORT = "from observer import observe, payload, Widget\n"
_UNUSED_SOURCE = "def outer():\n    def _make(*, _unused=False):\n        return OBSERVED\n    return _make()\n"
_MOVE_SOURCE = (
    "def outer():\n"
    "    def _move(source_id: str, target_id: str):\n"
    "        return source_id + target_id\n"
    "    return _move(payload, payload)\n"
)
_DOC_SOURCE = (
    'def outer():\n    def _normalize():\n        """Normalize."""\n        return observe()\n    return _normalize()\n'
)
_FACTORY_SOURCE = (
    "def test_widgets():\n"
    "    def _make_widget(*, enabled=True):\n"
    "        return Widget(enabled=enabled)\n"
    "    _make_widget()\n"
    "    _make_widget(enabled=True)\n"
)
_RAISING_SOURCE = (
    "def outer():\n    def _make(*, _unused=False):\n        raise ValueError('rejected')\n    return _make()\n"
)
_RAISING_DOC_SOURCE = (
    "def outer():\n"
    "    def _normalize():\n"
    '        """Normalize."""\n'
    "        raise ValueError('rejected')\n"
    "    return _normalize()\n"
)
_RAISING_DOMAIN_SOURCE = (
    "from typing import Literal\n"
    "type Mode = Literal['text', 'image', 'reserved']\n"
    "def outer():\n"
    "    def _render(kind: str) -> str:\n"
    "        match kind:\n"
    "            case 'text':\n"
    "                return 'Text'\n"
    "            case 'image':\n"
    "                return 'Image'\n"
    "            case _:\n"
    "                raise ValueError('rejected')\n"
    "    return _render('reserved')\n"
)


def _unused_case(name: str, expression: str) -> _ObserverCase:
    source = _PROVIDER_IMPORT + _UNUSED_SOURCE.replace("OBSERVED", expression)
    return _ObserverCase(
        name,
        "no-unused-underscored-keyword-parameter",
        "app/service.py",
        "_make",
        source,
        source.replace("_make(*, _unused=False)", "_make()"),
        "outer()",
    )


def _parent_case(name: str, expression: str) -> _ObserverCase:
    source = _PROVIDER_IMPORT + (
        f"def outer():\n    def _make(*, _unused=False):\n        return 1\n    {expression}\n    return _make()\n"
    )
    return _ObserverCase(
        name,
        "no-unused-underscored-keyword-parameter",
        "app/service.py",
        "_make",
        source,
        source.replace("_make(*, _unused=False)", "_make()"),
        "outer()",
    )


_CASES = (
    _unused_case("helper-call", "observe()"),
    _unused_case("helper-getter", "payload.value"),
    _unused_case("helper-subscript", "payload['key']"),
    _unused_case("helper-overload", "payload + 'suffix'"),
    _unused_case("helper-truthiness", "1 if payload else 0"),
    _parent_case("parent-call", "observe()"),
    _parent_case("parent-getter", "payload.value"),
    _parent_case("parent-overload", "payload + 'suffix'"),
    _parent_case("duplicate-map-length", "if len({1: 0, 1: 0}) == 1: observe()"),
    _parent_case("duplicate-set-length", "if len({1, 1}) == 1: observe()"),
    _parent_case(
        "interleaved-map-evaluation",
        "values = []\n"
        "    mapping = {len(values): values.append(1), len(values): values.append(2)}\n"
        "    if len(mapping) == 2: observe()",
    ),
    _parent_case("pooled-literal-identity", "if 1000 is 1000: observe()"),
    _ObserverCase(
        "keyword-only-overload",
        "require-keyword-only-swap-prone-params",
        "app/service.py",
        "_move",
        _PROVIDER_IMPORT + _MOVE_SOURCE,
        _PROVIDER_IMPORT
        + _MOVE_SOURCE.replace("_move(source_id: str", "_move(*, source_id: str").replace(
            "_move(payload, payload)", "_move(source_id=payload, target_id=payload)"
        ),
        "outer()",
    ),
    *(
        _ObserverCase(
            rule,
            rule,
            "app/service.py",
            "_normalize",
            _PROVIDER_IMPORT + _DOC_SOURCE,
            _PROVIDER_IMPORT + _DOC_SOURCE.replace('        """Normalize."""\n', ""),
            "outer()",
        )
        for rule in ("redundant-docstring", "no-unnecessary-docstring")
    ),
    _ObserverCase(
        "factory-constructor",
        "unused-test-factory-option",
        "tests/test_widget.py",
        "_make_widget",
        _PROVIDER_IMPORT + _FACTORY_SOURCE,
        _PROVIDER_IMPORT
        + _FACTORY_SOURCE.replace("_make_widget(*, enabled=True)", "_make_widget()")
        .replace("Widget(enabled=enabled)", "Widget(enabled=True)")
        .replace("_make_widget(enabled=True)", "_make_widget()"),
        "test_widgets()",
    ),
    _ObserverCase(
        "signature-exception-traceback",
        "no-unused-underscored-keyword-parameter",
        "app/service.py",
        "_make",
        _RAISING_SOURCE,
        _RAISING_SOURCE.replace("_make(*, _unused=False)", "_make()"),
        "outer()",
        exception_name="ValueError",
    ),
    _ObserverCase(
        "doc-exception-traceback",
        "redundant-docstring",
        "app/service.py",
        "_normalize",
        _RAISING_DOC_SOURCE,
        _RAISING_DOC_SOURCE.replace('        """Normalize."""\n', ""),
        "outer()",
        exception_name="ValueError",
    ),
    _ObserverCase(
        "domain-exception-traceback",
        "prefer-str-enum",
        "app/service.py",
        "_render",
        _RAISING_DOMAIN_SOURCE,
        _RAISING_DOMAIN_SOURCE.replace("kind: str", "kind: Mode"),
        "outer()",
        exception_name="ValueError",
    ),
)

_PROBE_SOURCE = """import inspect
import json
import sys

observations = []

def record(function):
    parameters = inspect.signature(function).parameters
    snapshot = {
        "parameters": [[name, value.kind.name] for name, value in parameters.items()],
        "annotations": {name: repr(value.annotation) for name, value in parameters.items()},
        "doc": function.__doc__,
    }
    observations.append(snapshot)
    return json.dumps(snapshot, sort_keys=True)

def observe():
    frame = sys._getframe(1)
    while frame is not None:
        function = frame.f_locals.get(TARGET)
        if inspect.isfunction(function):
            return record(function)
        frame = frame.f_back
    raise AssertionError("observer did not reach its live private helper")

def observe_traceback(error):
    trace = error.__traceback__
    while trace is not None:
        function = trace.tb_frame.f_locals.get(TARGET)
        if inspect.isfunction(function):
            return record(function)
        trace = trace.tb_next
    raise AssertionError("exception did not retain its private helper")

class Payload(str):
    def __add__(self, other):
        return observe()

    def __getitem__(self, key):
        return observe()

    def __bool__(self):
        observe()
        return True

    @property
    def value(self):
        return observe()

payload = Payload("credential")

def Widget(*, enabled):
    return observe()
"""


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.name for case in _CASES))
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_external_observers_keep_private_metadata_contracts(case: _ObserverCase, ending: str) -> None:
    source = case.source.replace("\n", ending)
    path = Path(case.path)
    rule = REGISTRY[case.rule_id]()
    assert rule.check(path, source)
    assert fix_source(path, source, rule_ids=[case.rule_id]) == source


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.name for case in _CASES))
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_rejected_metadata_edits_have_observable_runtime_differences(
    case: _ObserverCase, ending: str, tmp_path: Path
) -> None:
    source = case.source.replace("\n", ending)
    original = _observe(case, source, tmp_path / "original")
    rejected = _observe(case, case.rejected.replace("\n", ending), tmp_path / "rejected")
    assert original != rejected


def _observe(case: _ObserverCase, source: str, directory: Path) -> str:
    directory.mkdir()
    (directory / "observer.py").write_text(f"TARGET = {case.helper!r}\n" + _PROBE_SOURCE, encoding="utf-8")
    script = directory / "runtime.py"
    invocation = case.invocation
    if case.exception_name is not None:
        invocation = (
            f"try:\n    {invocation}\nexcept {case.exception_name} as error:\n"
            "    from observer import observe_traceback\n    observe_traceback(error)\n"
            "else:\n    raise AssertionError('expected a retained private frame')\n"
        )
    script.write_text(
        source
        + f"\n{invocation}\n"
        + "import json\nfrom observer import observations\nprint(json.dumps(observations, sort_keys=True))\n",
        encoding="utf-8",
    )
    completed = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip()
    assert completed.stdout.strip() != "[]"
    return completed.stdout


@dataclass(frozen=True, slots=True)
class _DispatchCase:
    rule_id: str
    source: str
    rejected: str
    original_result: str
    rejected_result: str


_DISPATCH_CASES = (
    _DispatchCase(
        "prefer-match-value-dispatch",
        "def dispatch(value):\n"
        "    if value == 'one':\n        return 1\n"
        "    elif value == 'two':\n        return 2\n"
        "    elif value == 'three':\n        return 3\n"
        "    else:\n        return 0\n",
        "def dispatch(value):\n"
        "    match value:\n"
        "        case 'one':\n            return 1\n"
        "        case 'two':\n            return 2\n"
        "        case 'three':\n            return 3\n"
        "        case _:\n            return 0\n",
        "2",
        "0",
    ),
    _DispatchCase(
        "prefer-match-type-dispatch",
        "def dispatch(value):\n"
        "    if isinstance(value, str):\n        return 'text'\n"
        "    elif isinstance(value, bytes):\n        return 'bytes'\n"
        "    elif isinstance(value, int):\n        return 'number'\n"
        "    return 'other'\n",
        "def dispatch(value):\n"
        "    match value:\n"
        "        case str():\n            return 'text'\n"
        "        case bytes():\n            return 'bytes'\n"
        "        case int():\n            return 'number'\n"
        "    return 'other'\n",
        "bytes",
        "other",
    ),
)

_DISPATCH_PROBE_SOURCE = """import sys

class Subject:
    def __eq__(self, other):
        sys._getframe(1).f_locals['value'] = 'two'
        return False

    @property
    def __class__(self):
        sys._getframe(1).f_locals['value'] = b'credential'
        return object
"""


@pytest.mark.parametrize("case", _DISPATCH_CASES, ids=tuple(case.rule_id for case in _DISPATCH_CASES))
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_external_dispatch_subjects_require_review(case: _DispatchCase, ending: str) -> None:
    source = case.source.replace("\n", ending)
    path = Path("app/dispatch.py")
    assert REGISTRY[case.rule_id]().check(path, source)
    assert fix_source(path, source, rule_ids=[case.rule_id]) == source


@pytest.mark.parametrize("case", _DISPATCH_CASES, ids=tuple(case.rule_id for case in _DISPATCH_CASES))
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_rejected_dispatch_edits_change_runtime_results(case: _DispatchCase, ending: str, tmp_path: Path) -> None:
    for name, source, expected in (
        ("original", case.source, case.original_result),
        ("rejected", case.rejected, case.rejected_result),
    ):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "observer.py").write_text(_DISPATCH_PROBE_SOURCE, encoding="utf-8")
        script = directory / "runtime.py"
        script.write_text(
            source.replace("\n", ending) + "\nfrom observer import Subject\nprint(dispatch(Subject()))\n",
            encoding="utf-8",
        )
        completed = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=False)
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == expected
