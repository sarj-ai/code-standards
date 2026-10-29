from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import assert_type

import pytest

import sarj_python_lint
from sarj_python_lint import AnalysisSession as PublicAnalysisSession, __main__ as engine
from sarj_python_lint._analysis_session import AnalysisSession as OwnerAnalysisSession
import sarj_python_lint.rules as rules_module


_PRELUDE = """
import os as _os
import sys as _sys
from importlib.metadata import version as _version
from pathlib import Path as _Path
_os.environ['NO_COLOR'] = '1'
_os.environ['TERM'] = 'dumb'
import sarj_python_lint as _package
assert _Path(_package.__file__).resolve() == _Path(_sys.argv[1])
assert _package.__version__ == _version('sarj-python-lint')
assert not any(name == 'sarj_python_lint.rules' or name.startswith('sarj_python_lint.rules.')
               for name in _sys.modules)
assert 'sarj_python_lint._analysis_session' not in _sys.modules
assert not any(name == 'sarj_standards.libs.release' or name.startswith('sarj_standards.libs.release.')
               for name in _sys.modules)
"""

_LIGHTWEIGHT_CLI = """
_arguments = _sys.argv[3:]
if _sys.argv[2] == 'api':
    from sarj_python_lint.__main__ import main as _main
    assert _main(_arguments) == 0
else:
    import runpy as _runpy
    _sys.argv = ['sarj-python-lint', *_arguments]
    try:
        _runpy.run_module('sarj_python_lint', run_name='__main__', alter_sys=True)
    except SystemExit as _exit:
        assert _exit.code == 0
    else:
        raise AssertionError('module entry point did not exit')
assert not any(name == 'sarj_python_lint.rules' or name.startswith('sarj_python_lint.rules.')
               for name in _sys.modules)
assert 'sarj_python_lint._analysis_session' not in _sys.modules
assert 'sarj_python_lint._file_context' not in _sys.modules
assert not any(name == 'sarj_standards.libs.release' or name.startswith('sarj_standards.libs.release.')
               for name in _sys.modules)
"""

_EXPORTS = """
assert 'AnalysisSession' in dir(_package)
assert 'sarj_python_lint._analysis_session' not in _sys.modules
try:
    _package.missing_public_export
except AttributeError as _error:
    assert str(_error) == "module 'sarj_python_lint' has no attribute 'missing_public_export'"
else:
    raise AssertionError('unknown package attribute was accepted')
assert 'sarj_python_lint._analysis_session' not in _sys.modules
if _sys.argv[2] == 'from-first':
    from sarj_python_lint import AnalysisSession as _PublicSession
    from sarj_python_lint._analysis_session import AnalysisSession as _OwnerSession
    assert _PublicSession is _OwnerSession
    assert _package.AnalysisSession is _package.__dict__['AnalysisSession'] is _OwnerSession
_package.compatibility_value = object()
from sarj_python_lint import *
from sarj_python_lint._analysis_session import AnalysisSession as _OwnerSession
assert AnalysisSession is _package.AnalysisSession is _OwnerSession
assert type(AnalysisSession()) is _OwnerSession
assert compatibility_value is _package.compatibility_value
_public = {name: value for name, value in globals().copy().items() if not name.startswith('_')}
_legacy = {name: value for name, value in vars(_package).items() if not name.startswith('_')}
assert _public.keys() == _legacy.keys() == set(_package.__all__)
assert all(_public[name] is value for name, value in _legacy.items())
assert {'AnalysisSession', 'apply_fixes', 'python_source_hash', 'run_ratchet', 'python_source_encoding',
        'ApplicationLoggingUse', 'application_logging_uses'} <= _public.keys()
assert 'TYPE_CHECKING' not in _public
assert 'AnalysisSession' in dir(_package)
"""

_SELECTED_ANALYSIS = """
from contextlib import redirect_stdout as _redirect_stdout, redirect_stderr as _redirect_stderr
from io import StringIO as _StringIO
from types import MappingProxyType as _MappingProxyType
from sarj_python_lint.__main__ import analyze as _analyze, main as _main
assert 'sarj_python_lint.rules._registry' not in _sys.modules
_target = _Path(_sys.argv[2])
_findings = _analyze(['xfail-requires-strict', 'defect-xfail-requires-explicit-strict',
                      'defect-xfail-requires-strict'], [_target])
assert [finding.code for finding in _findings] == ['SARJ046']
from sarj_python_lint.rules import REGISTRY as _registry, DEFAULT_REGISTRY as _defaults
from sarj_python_lint.rules._registry import REGISTRY as _owner_registry, DEFAULT_REGISTRY as _owner_defaults
assert _registry is _owner_registry and _defaults is _owner_defaults
assert isinstance(_registry, _MappingProxyType) and isinstance(_defaults, _MappingProxyType)
assert tuple(_defaults) == tuple(name for name, rule in _registry.items() if rule.enabled_by_default)
assert 'xfail-requires-strict' not in _registry
_expected = ''.join(f'{rule().code:8}  {name:40}  {rule().description}\\n'
                    for name, rule in sorted(_registry.items()))
_out = _StringIO()
with _redirect_stdout(_out):
    assert _main(['list-rules']) == 0
assert _out.getvalue() == _expected
_rule = _registry['defect-xfail-requires-explicit-strict']
for _wanted in (_rule.id, _rule.code.lower()):
    _out = _StringIO()
    with _redirect_stdout(_out):
        assert _main(['explain', _wanted]) == 0
    assert _out.getvalue() == f'{_rule.code}  {_rule.id}\\n{_rule.description}\\nexamples: {_rule.examples_url()}\\n'
_before = _target.read_bytes()
_error = _StringIO()
with _redirect_stderr(_error):
    try:
        _main(['check', '--rule', 'missing-rule', '--fix', str(_target)])
    except SystemExit as _exit:
        assert _exit.code == 2
    else:
        raise AssertionError('unknown fix selection did not exit')
assert _error.getvalue() == ('unknown rule(s): missing-rule\\navailable: ' + ', '.join(sorted(_registry)) + '\\n')
assert _target.read_bytes() == _before
"""


_MAIN_REGISTRY = """
from sarj_python_lint import __main__ as _engine
assert 'sarj_python_lint.rules._registry' not in _sys.modules
from sarj_python_lint.__main__ import REGISTRY as _main_registry
from sarj_python_lint.rules import REGISTRY as _registry
assert _main_registry is _registry is _engine.REGISTRY
"""


def _fresh(tmp_path: Path, body: str, *arguments: str) -> str:
    probe = tmp_path / "startup_probe.py"
    probe.write_text(_PRELUDE + body, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-I", str(probe), str(Path(sarj_python_lint.__file__).resolve()), *arguments],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr
    return completed.stdout


@pytest.mark.parametrize(
    "arguments",
    [["--version"], ["--help"], ["-h"], ["check", "--help"]],
    ids=("version", "help", "short-help", "check-help"),
)
def test_fresh_cli_metadata_operations_leave_semantic_rules_unloaded(tmp_path: Path, arguments: list[str]) -> None:
    api = _fresh(tmp_path, _LIGHTWEIGHT_CLI, "api", *arguments)
    module = _fresh(tmp_path, _LIGHTWEIGHT_CLI, "module", *arguments)
    assert api == module
    if arguments == ["--version"]:
        assert api == f"sarj-python-lint {sarj_python_lint.__version__}\n"
    else:
        assert "Usage:" in api
        assert "sarj-python-lint" in api
        expected_help = "Run rules over files." if arguments[0] == "check" else "Custom Python lint rules."
        assert expected_help in api


@pytest.mark.parametrize("order", ["from-first", "star-first"])
def test_fresh_public_session_and_implicit_star_exports_remain_compatible(tmp_path: Path, order: str) -> None:
    assert not _fresh(tmp_path, _EXPORTS, order)


def test_public_session_export_retains_the_actual_typed_class() -> None:
    assert PublicAnalysisSession is OwnerAnalysisSession
    session = PublicAnalysisSession()
    assert_type(session, OwnerAnalysisSession)
    assert type(session) is OwnerAnalysisSession


def test_fresh_main_registry_export_loads_only_when_requested(tmp_path: Path) -> None:
    assert not _fresh(tmp_path, _MAIN_REGISTRY)


@pytest.mark.parametrize("override", ["main-only", "dual-module"])
def test_legacy_registry_injection_controls_actual_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override: str
) -> None:
    monkeypatch.delitem(vars(engine), "REGISTRY", raising=False)
    registry = {"embedded-rule": rules_module.REGISTRY["no-dunder-all"]}
    published = engine.REGISTRY
    target = tmp_path / "app.py"
    target.write_text("__all__ = ['value']\nvalue = 1\n", encoding="utf-8")
    with monkeypatch.context() as patch:
        if override == "dual-module":
            patch.setattr(  # sarj-noqa: SARJ445 -- preserve authoring's facade-first override order.
                rules_module, "REGISTRY", registry
            )
        patch.setattr(  # sarj-noqa: SARJ445 -- preserve the existing module-level registry injection boundary.
            engine, "REGISTRY", registry
        )
        findings = engine.analyze(["embedded-rule"], [target])
    assert [finding.code for finding in findings] == ["SARJ438"]
    assert engine.REGISTRY is published


def test_fresh_selected_analysis_preserves_aliases_mappings_and_cli_outputs(tmp_path: Path) -> None:
    target = tmp_path / "test_example.py"
    target.write_text(
        'import pytest\n@pytest.mark.xfail(reason="BUG: wrong status code")\ndef test_status():\n    assert True\n',
        encoding="utf-8",
    )
    assert not _fresh(tmp_path, _SELECTED_ANALYSIS, str(target))
