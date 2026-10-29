from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

import sarj_python_lint
from sarj_python_lint.rule_metadata import authored_descriptors


_PRELUDE = """
import sys
from importlib.metadata import version
from pathlib import Path
import sarj_python_lint
assert Path(sarj_python_lint.__file__).resolve() == Path(sys.argv[1])
assert sarj_python_lint.__version__ == version('sarj-python-lint')
"""

_KEYS = """
from types import MappingProxyType
from sarj_python_lint.rules import REGISTRY, DEFAULT_REGISTRY
from sarj_python_lint.rule_metadata import load_descriptors
entries = load_descriptors()
concrete = {entry.module for entry in entries}
assert not concrete.intersection(sys.modules)
assert isinstance(REGISTRY, MappingProxyType) and isinstance(DEFAULT_REGISTRY, MappingProxyType)
expected = tuple(entry.rule_id for entry in entries)
defaults = tuple(entry.rule_id for entry in entries if entry.enabled_by_default)
assert tuple(REGISTRY) == expected
assert len(REGISTRY) == len(expected)
assert tuple(reversed(REGISTRY)) == tuple(reversed(expected))
assert tuple(DEFAULT_REGISTRY) == defaults
assert len(DEFAULT_REGISTRY) == len(defaults)
for entry in entries:
    assert entry.rule_id in REGISTRY
    assert (entry.rule_id in DEFAULT_REGISTRY) is entry.enabled_by_default
sentinel = object()
assert 'not-registered' not in REGISTRY
assert REGISTRY.get('not-registered', sentinel) is sentinel
assert DEFAULT_REGISTRY.get('not-registered') is None
for mapping in (REGISTRY, DEFAULT_REGISTRY):
    try:
        [] in mapping
    except TypeError:
        pass
    else:
        raise AssertionError('unhashable membership did not raise')
assert not concrete.intersection(sys.modules)
"""

_SELECTED = """
from sarj_python_lint.rule_metadata import load_descriptors
entries = load_descriptors()
concrete = {entry.module for entry in entries}
from sarj_python_lint.__main__ import analyze
assert not concrete.intersection(sys.modules)
selected = sys.argv[2]
target = Path(sys.argv[3])
findings = analyze([selected, 'defect-xfail-requires-explicit-strict'], [target])
assert [finding.code for finding in findings] == ['SARJ046']
assert concrete.intersection(sys.modules) == {'sarj_python_lint.rules.defect_xfail_requires_explicit_strict'}
"""

_FULL = """
from collections import UserDict
from types import MappingProxyType
from sarj_python_lint.rules import REGISTRY, DEFAULT_REGISTRY
from sarj_python_lint.rules._registry import (
    REGISTRY as private_registry,
    DEFAULT_REGISTRY as private_defaults,
    _AUTHORING_REGISTRY,
    _AUTHORING_DEFAULT_REGISTRY,
)
assert REGISTRY is private_registry and DEFAULT_REGISTRY is private_defaults
for mapping, authored in ((REGISTRY, _AUTHORING_REGISTRY), (DEFAULT_REGISTRY, _AUTHORING_DEFAULT_REGISTRY)):
    expected = dict(authored)
    proxy = MappingProxyType(expected)
    assert dict(mapping) == expected
    assert mapping.copy() == expected and type(mapping.copy()) is dict
    assert tuple(mapping) == tuple(expected)
    assert tuple(reversed(mapping)) == tuple(reversed(expected))
    assert type(mapping.keys()) is type(expected.keys())
    assert type(mapping.values()) is type(expected.values())
    assert type(mapping.items()) is type(expected.items())
    assert list(mapping.values()) == list(expected.values())
    assert set(mapping.items()) == set(expected.items())
    assert dict(mapping.keys().mapping) == expected
    assert mapping == proxy and proxy == mapping and not (mapping != proxy)
    assert repr(mapping) == repr(proxy) and str(mapping) == str(proxy)
    for key, rule in expected.items():
        assert mapping[key] is authored[key] is rule
    marker = object()
    for other in ({'external': marker}, UserDict({'external': marker}), MappingProxyType({'external': marker})):
        actual_left, expected_left = mapping | other, proxy | other
        actual_right, expected_right = other | mapping, other | proxy
        assert type(actual_left) is type(expected_left) and actual_left == expected_left
        assert type(actual_right) is type(expected_right) and actual_right == expected_right
    class Reflected(dict):
        def __ror__(self, other):
            return 'reflected', dict(other)
    reflected = Reflected()
    assert mapping | reflected == proxy | reflected
    for operation in ('hash', 'inplace', 'bad-union'):
        def exercise(value):
            if operation == 'hash':
                return hash(value)
            if operation == 'inplace':
                value |= {}
                return value
            return value | []
        for value in (mapping, proxy):
            try:
                exercise(value)
            except TypeError:
                pass
            else:
                raise AssertionError(operation + ' should reject this operation')
defaults_before = tuple(DEFAULT_REGISTRY)
rule = REGISTRY['no-dunder-all']
old = rule.enabled_by_default
try:
    rule.enabled_by_default = not old
    assert tuple(DEFAULT_REGISTRY) == defaults_before
finally:
    rule.enabled_by_default = old
"""

_MUTATION = """
from dataclasses import replace
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules._runtime_registry import canonical_aliases
from sarj_python_lint.__main__ import analyze
assert canonical_aliases(REGISTRY) is not None
field = sys.argv[2]
if field == 'constructor-code':
    from sarj_python_lint.rules import _runtime_registry as runtime
    real_import = runtime.import_module
    def initializer(self):
        pass
    def prepare_initializer(name):
        module = real_import(name)
        if name == 'sarj_python_lint.rules.no_dunder_all':
            module.NoDunderAll.__init__ = initializer
        return module
    runtime.import_module = prepare_initializer
rule = REGISTRY['no-dunder-all']
if field == 'constructor-code':
    runtime.import_module = real_import
    from sarj_python_lint.rules.no_dunder_all import NoDunderAll
    assert rule is NoDunderAll
    assert rule.__init__ is initializer
assert canonical_aliases(REGISTRY) is not None
if field == 'documentation':
    rule.documentation = replace(rule.documentation, aliases=(*rule.documentation.aliases, 'runtime-alias'))
elif field == 'code':
    rule.code = 'CUSTOM438'
elif field == 'description':
    rule.description = 'Runtime metadata remains live.'
elif field == 'opaque-constructor':
    class Initializer:
        def __call__(self):
            pass
    rule.__init__ = Initializer()
elif field == 'constructor-code':
    def replacement(self):
        pass
    rule.__init__.__code__ = replacement.__code__
    assert rule.__init__ is initializer
    assert initializer.__code__ is replacement.__code__
else:
    def replacement(self):
        pass
    rule.__init__ = replacement
assert canonical_aliases(REGISTRY) is None
if field == 'documentation':
    findings = analyze(['runtime-alias'], [Path(sys.argv[3])])
    assert [finding.code for finding in findings] == ['SARJ438']
"""

_EXTERNAL = """
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules._runtime_registry import canonical_aliases
assert canonical_aliases(REGISTRY) is not None
from sarj_python_lint.rules.no_dunder_all import NoDunderAll
assert canonical_aliases(REGISTRY) is None
assert REGISTRY['no-dunder-all'] is NoDunderAll
"""

_CLI = """
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from sarj_python_lint.__main__ import main
from sarj_python_lint.rules._registry import _AUTHORING_REGISTRY
def invoke(arguments):
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = main(arguments)
    return status, out.getvalue(), err.getvalue()
instances = {key: value() for key, value in sorted(_AUTHORING_REGISTRY.items())}
expected = ''.join(f'{rule.code:8}  {key:40}  {rule.description}\\n' for key, rule in instances.items())
assert invoke(['list-rules']) == (0, expected, '')
rule = _AUTHORING_REGISTRY['no-dunder-all']
expected = f'{rule.code}  {rule.id}\\n{rule.description}\\nexamples: {rule.examples_url()}\\n'
assert invoke(['explain', rule.id]) == (0, expected, '')
assert invoke(['explain', rule.code]) == (0, expected, '')
target = Path(sys.argv[2])
assert invoke(['check', '--rule', 'no-comment-cruft', '--fix', str(target)])[0] == 0
assert target.read_text(encoding='utf-8') == '\\nvalue = 1\\n'
"""

_CONCURRENT_FIRST_USE = """
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from importlib import import_module
from threading import Event, Lock
from sarj_rule_contracts import RuleId
from sarj_python_lint.rules import REGISTRY, DEFAULT_REGISTRY
from sarj_python_lint.rules import _runtime_registry as runtime

real_loader = runtime.load_descriptors
rows = real_loader()
target = next(entry for entry in rows if entry.enabled_by_default)
constructing = Event()
release = Event()
call_lock = Lock()
load_calls = []

class PausingRuleId(str):
    def __hash__(self):
        if not constructing.is_set():
            constructing.set()
            assert release.wait(15), 'catalog construction was not released'
        return str.__hash__(self)

def forwarded_loader():
    actual = real_loader()
    with call_lock:
        first = not load_calls
        load_calls.append(actual)
    if first:
        # A nominal ID with identical str equality/hash is valid source metadata.
        # Its first map insertion exposes the exact publication interval deterministically.
        return tuple(replace(entry, rule_id=RuleId(PausingRuleId(entry.rule_id)))
                     if entry.rule_id == target.rule_id else entry for entry in actual)
    return actual

def second_reader():
    return target.rule_id in DEFAULT_REGISTRY, REGISTRY[target.rule_id]

runtime.load_descriptors = forwarded_loader
try:
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(lambda: REGISTRY[target.rule_id])
        try:
            assert constructing.wait(15), 'first reader did not reach map construction'
            enabled, resolved = pool.submit(second_reader).result(timeout=15)
            assert enabled, 'an enabled default was observed absent during construction'
            actual_class = getattr(import_module(target.module), target.class_name)
            assert resolved is actual_class
        finally:
            release.set()
        assert first.result(timeout=15) is actual_class
    assert tuple(REGISTRY) == tuple(entry.rule_id for entry in rows)
    assert tuple(DEFAULT_REGISTRY) == tuple(entry.rule_id for entry in rows if entry.enabled_by_default)
    assert DEFAULT_REGISTRY[target.rule_id] is REGISTRY[target.rule_id] is actual_class
finally:
    release.set()
    runtime.load_descriptors = real_loader
"""

_ORACLE = """
from importlib.abc import MetaPathFinder
from sarj_python_lint.rule_metadata import authored_descriptors, render_authored_descriptors
class BlockGenerated(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == 'sarj_python_lint._rule_descriptors':
            raise AssertionError('independent oracle tried to read generated descriptors')
        return None
sys.meta_path.insert(0, BlockGenerated())
entries = authored_descriptors()
assert entries
rendered = render_authored_descriptors()
compile(rendered, 'generated_rule_descriptors.py', 'exec')
assert 'DESCRIPTORS: tuple[RuleDescriptor, ...]' in rendered
assert 'sarj_python_lint._rule_descriptors' not in sys.modules
"""


def _fresh(tmp_path: Path, body: str, *arguments: str) -> str:
    probe = tmp_path / "descriptor_probe.py"
    probe.write_text(_PRELUDE + body, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-I", str(probe), str(Path(sarj_python_lint.__file__).resolve()), *arguments],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr
    return completed.stdout


def test_installed_registry_key_operations_do_not_import_rule_implementations(tmp_path: Path) -> None:
    assert not _fresh(tmp_path, _KEYS)


@pytest.mark.parametrize("selection", ["xfail-requires-strict", "defect-xfail-requires-explicit-strict"])
def test_installed_canonical_and_alias_selection_import_only_the_selected_rule(tmp_path: Path, selection: str) -> None:
    source = tmp_path / "test_example.py"
    source.write_text(
        'import pytest\n@pytest.mark.xfail(reason="BUG: wrong status code")\ndef test_status():\n    assert True\n',
        encoding="utf-8",
    )
    assert not _fresh(tmp_path, _SELECTED, selection, str(source))


def test_installed_public_and_private_proxies_preserve_full_dict_behavior(tmp_path: Path) -> None:
    assert not _fresh(tmp_path, _FULL)


@pytest.mark.parametrize(
    "field", ["code", "description", "documentation", "constructor", "opaque-constructor", "constructor-code"]
)
def test_owned_registry_identity_does_not_hide_live_class_metadata_edits(tmp_path: Path, field: str) -> None:
    source = tmp_path / "app.py"
    source.write_text("__all__ = ['value']\nvalue = 1\n", encoding="utf-8")
    assert not _fresh(tmp_path, _MUTATION, field, str(source))


def test_unobserved_external_rule_import_uses_live_alias_resolution(tmp_path: Path) -> None:
    assert not _fresh(tmp_path, _EXTERNAL)


def test_installed_full_cli_metadata_and_selected_fix_match_live_authoring(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("# --------\nvalue = 1\n", encoding="utf-8")
    assert not _fresh(tmp_path, _CLI, str(source))


def test_installed_concurrent_first_use_keeps_keys_and_defaults_ready(tmp_path: Path) -> None:
    assert not _fresh(tmp_path, _CONCURRENT_FIRST_USE)


def test_independent_eager_oracle_does_not_read_generated_data(tmp_path: Path) -> None:
    assert not _fresh(tmp_path, _ORACLE)


def test_descriptor_records_reject_mutable_aliases_and_non_boolean_flags() -> None:
    descriptor = authored_descriptors()[0]
    with pytest.raises(TypeError, match="immutable string tuple"):
        replace(descriptor, aliases=["mutable"])
    with pytest.raises(TypeError, match="must be a bool"):
        replace(descriptor, enabled_by_default=1)
