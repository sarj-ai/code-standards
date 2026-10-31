from __future__ import annotations

import builtins
import importlib
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import ModuleType

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


_RULE_ID = "prefer-direct-import-module"
_PATH = Path("app/loader.py")
_SOURCE = "import importlib\nimport sys\nplugin = importlib.import_module('sys')\n"


def _load_source(path: Path, source: str) -> ModuleType:
    path.write_text(source, encoding="utf-8")
    spec = spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plugin(module: ModuleType) -> ModuleType:
    namespace: dict[str, object] = vars(module)
    value = namespace["plugin"]
    assert isinstance(value, ModuleType)
    return value


@pytest.mark.parametrize(
    "replacement",
    ["import sys as plugin", "plugin = sys"],
    ids=["static-import-in-place", "reuse-adjacent-sys-binding"],
)
def test_static_import_rewrite_loses_an_observable_loader_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    rule = REGISTRY[_RULE_ID]()
    findings = rule.check(_PATH, _SOURCE)
    assert len(findings) == 1
    assert findings[0].code == "SARJ529"
    assert fix_source(_PATH, _SOURCE, rule_ids=[_RULE_ID]) == _SOURCE
    rewritten = _SOURCE.replace("plugin = importlib.import_module('sys')", replacement)
    assert not rule.check(_PATH, rewritten)
    load = importlib.import_module
    canonical_import = builtins.__import__  # ruff: ignore[banned-api] -- Observe the real import hook to prove the rewrite preserves interpreter state.
    cached_sys = sys.modules["sys"]
    calls: list[str] = []

    def observed_load(name: str, package: str | None = None) -> ModuleType:
        if name == "sys":
            calls.append(name)
        return load(name, package)

    with monkeypatch.context() as patch:
        # Injection would bypass the global lookup whose loader call is measured here.
        patch.setattr(  # sarj-noqa: SARJ445 -- tests the global loader lookup.
            importlib, "import_module", observed_load
        )
        original = _load_source(tmp_path / "original_loader.py", _SOURCE)
        assert calls == ["sys"]
        calls.clear()
        changed = _load_source(tmp_path / "rewritten_loader.py", rewritten)
        assert not calls
        assert _plugin(original) is _plugin(changed) is sys
        assert builtins.__import__ is canonical_import  # ruff: ignore[banned-api] -- Assert the authored loader fixture leaves the real import hook unchanged.
        assert sys.modules["sys"] is cached_sys is sys
