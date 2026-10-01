from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity, is_suppressed
from sarj_python_lint.rules.no_injected_module_loader import NoInjectedModuleLoader


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_CASES = (
    EvaluationCase(
        "qualified",
        Language.PYTHON,
        "import importlib\ndef run(*, loader=importlib.import_module):\n    return loader('plugin')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        "import importlib as imports\ndef run(loader=imports.import_module):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "symbol-alias",
        Language.PYTHON,
        "from importlib import import_module as load\ndef run(loader=load):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "same-name-default",
        Language.PYTHON,
        "from importlib import import_module\ndef run(import_module=import_module):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("builtin", Language.PYTHON, "def run(loader=__import__):\n    pass\n", ExpectedOutcome.MATCH),
    EvaluationCase(
        "builtin-alias",
        Language.PYTHON,
        "from builtins import __import__ as load\ndef run(loader=load):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "qualified-builtin",
        Language.PYTHON,
        "import builtins\ndef run(loader=builtins.__import__):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "importlib-builtin",
        Language.PYTHON,
        "import importlib\ndef run(loader=importlib.__import__):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "async-posonly",
        Language.PYTHON,
        "import importlib\nasync def run(loader=importlib.import_module, /):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "method",
        Language.PYTHON,
        "import importlib\nclass Service:\n    def run(self, loader=importlib.import_module):\n        pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nested",
        Language.PYTHON,
        "import importlib\ndef outer():\n    def run(loader=importlib.import_module):\n        pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "lambda",
        Language.PYTHON,
        "import importlib\nrun = lambda loader=importlib.import_module: loader('plugin')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "assignment-alias",
        Language.PYTHON,
        "import importlib\nload = importlib.import_module\ndef run(loader=load):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "annotated-alias",
        Language.PYTHON,
        "from importlib import import_module as imported\nload: object = imported\ndef run(loader=load):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-assignment-alias",
        Language.PYTHON,
        "load = __import__\ndef run(loader=load):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "alias-method",
        Language.PYTHON,
        "import importlib\nload = importlib.import_module\nclass Service:\n    def run(self, loader=load):\n        pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "alias-rebound",
        Language.PYTHON,
        "import importlib\nload = importlib.import_module\nload = domain_loader\ndef run(loader=load):\n    pass\n",
    ),
    EvaluationCase(
        "alias-deleted",
        Language.PYTHON,
        "import importlib\nload = importlib.import_module\ndef run(loader=load):\n    pass\ndel load\n",
    ),
    EvaluationCase(
        "alias-conditional",
        Language.PYTHON,
        "import importlib\nif enabled:\n    load = importlib.import_module\ndef run(loader=load):\n    pass\n",
    ),
    EvaluationCase(
        "alias-chain",
        Language.PYTHON,
        "import importlib\nload = importlib.import_module\nother = load\ndef run(loader=other):\n    pass\n",
    ),
    EvaluationCase(
        "alias-after-default",
        Language.PYTHON,
        "import importlib\ndef run(loader=load):\n    pass\nload = importlib.import_module\n",
    ),
    EvaluationCase(
        "alias-import-too-late",
        Language.PYTHON,
        "load = importlib.import_module\nimport importlib\ndef run(loader=load):\n    pass\n",
    ),
    EvaluationCase(
        "alias-local-shadow",
        Language.PYTHON,
        "import importlib\nload = importlib.import_module\ndef outer(load):\n    def run(loader=load):\n        pass\n",
    ),
    EvaluationCase(
        "alias-class-shadow",
        Language.PYTHON,
        "import importlib\nload = importlib.import_module\nclass Service:\n    load = domain_loader\n    def run(self, loader=load):\n        pass\n",
    ),
    EvaluationCase(
        "alias-import-rebound",
        Language.PYTHON,
        "import importlib\nload = importlib.import_module\nfrom application import load\ndef run(loader=load):\n    pass\n",
    ),
    EvaluationCase(
        "alias-tuple",
        Language.PYTHON,
        "import importlib\nload, other = importlib.import_module, domain_loader\ndef run(loader=load):\n    pass\n",
    ),
    EvaluationCase(
        "alias-multiple-targets",
        Language.PYTHON,
        "import importlib\nload = other = importlib.import_module\ndef run(loader=load):\n    pass\n",
    ),
    EvaluationCase(
        "alias-pattern-rebound",
        Language.PYTHON,
        'import importlib\nload = importlib.import_module\nmatch config:\n    case {"loader": load}:\n        pass\ndef run(loader=load):\n    pass\n',
    ),
    EvaluationCase(
        "alias-wildcard",
        Language.PYTHON,
        "import importlib\nload = importlib.import_module\nfrom application import *\ndef run(loader=load):\n    pass\n",
    ),
    EvaluationCase(
        "alias-mutated-loader",
        Language.PYTHON,
        "import importlib\nload = importlib.import_module\nimportlib.import_module = domain_loader\ndef run(loader=load):\n    pass\n",
    ),
    EvaluationCase(
        "ordinary-import",
        Language.PYTHON,
        "import importlib\ndef run():\n    return importlib.import_module('plugin')\n",
    ),
    EvaluationCase("concrete-plugin", Language.PYTHON, "def run(plugin):\n    return plugin.create()\n"),
    EvaluationCase("domain-factory", Language.PYTHON, "def run(factory=DefaultFactory):\n    return factory()\n"),
    EvaluationCase(
        "loaded-module-default",
        Language.PYTHON,
        "import importlib\ndef run(plugin=importlib.import_module('plugin')):\n    pass\n",
    ),
    EvaluationCase("unproven-name", Language.PYTHON, "def run(import_module=application_loader):\n    pass\n"),
    EvaluationCase(
        "other-module",
        Language.PYTHON,
        "from application import import_module\ndef run(loader=import_module):\n    pass\n",
    ),
    EvaluationCase(
        "module-rebound",
        Language.PYTHON,
        "import importlib\nimportlib = application_loader\ndef run(loader=importlib.import_module):\n    pass\n",
    ),
    EvaluationCase(
        "symbol-rebound",
        Language.PYTHON,
        "from importlib import import_module\nimport_module = application_loader\ndef run(loader=import_module):\n    pass\n",
    ),
    EvaluationCase(
        "builtin-rebound", Language.PYTHON, "__import__ = application_loader\ndef run(loader=__import__):\n    pass\n"
    ),
    EvaluationCase(
        "outer-shadow",
        Language.PYTHON,
        "import importlib\ndef outer(importlib):\n    def run(loader=importlib.import_module):\n        pass\n",
    ),
    EvaluationCase(
        "class-shadow",
        Language.PYTHON,
        "import importlib\nclass Service:\n    importlib = application_loader\n    def run(self, loader=importlib.import_module):\n        pass\n",
    ),
    EvaluationCase(
        "builtin-outer-shadow",
        Language.PYTHON,
        "def outer(__import__):\n    def run(loader=__import__):\n        pass\n",
    ),
    EvaluationCase(
        "local-import-unresolved",
        Language.PYTHON,
        "def outer():\n    import importlib\n    def run(loader=importlib.import_module):\n        pass\n",
    ),
    EvaluationCase(
        "comprehension-shadow",
        Language.PYTHON,
        "import importlib\ncallbacks = [lambda loader=importlib.import_module: loader() for importlib in domain_plugins]\n",
    ),
    EvaluationCase(
        "wildcard-shadow",
        Language.PYTHON,
        "import importlib\nfrom application import *\ndef run(loader=importlib.import_module):\n    pass\n",
    ),
    EvaluationCase(
        "modified-module-loader",
        Language.PYTHON,
        "import importlib\nimportlib.import_module = domain_factory\ndef run(loader=importlib.import_module):\n    pass\n",
    ),
    EvaluationCase(
        "comments-and-strings",
        Language.PYTHON,
        "# loader=importlib.import_module\ntext = 'def run(loader=__import__): pass'\n",
    ),
    EvaluationCase("malformed", Language.PYTHON, "def run(loader=importlib.import_module: pass\n"),
)


def _check(source: str, path: Path = Path("app/service.py")) -> list[Diagnostic]:
    return NoInjectedModuleLoader().check(path, source)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len(findings) <= 1
    assert all(finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize("path", ["tests/test_loader.py", "app/generated/client.py"])
def test_excluded_source(path: str) -> None:
    assert _check(_CASES[0].source, Path(path)) == []


def test_exact_suppression() -> None:
    source = "import importlib\ndef run(loader=importlib.import_module):  # sarj-noqa: SARJ471 -- this public importer intentionally exposes import machinery.\n    pass\n"
    findings = _check(source)
    assert len(findings) == 1
    assert is_suppressed(source.splitlines(), findings[0].line, findings[0].code)
    assert not is_suppressed(source.replace("SARJ471", "SARJ469").splitlines(), findings[0].line, findings[0].code)


def test_combined_runner_warning_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "service.py"
    path.write_text(_CASES[0].source)
    rules = ["no-injected-module-loader", "no-nullable-dependency-fallback", "no-hidden-constructor-fallback"]
    first = analyze(rules, [path])
    second = analyze(rules, [path])
    assert first == second
    assert len(first) == 1
    assert first[0].code == "SARJ471"
    assert first[0].severity is Severity.WARNING


def test_generated_header_is_excluded() -> None:
    assert _check("# Generated by tool\n" + _CASES[0].source) == []


def test_native_cli_warning_is_nonblocking(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "service.py"
    path.write_text(_CASES[0].source)
    assert main(["check", "--rule", NoInjectedModuleLoader.id, str(path)]) == 0
    assert "SARJ471" in capsys.readouterr().out
