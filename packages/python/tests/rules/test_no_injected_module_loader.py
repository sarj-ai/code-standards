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
        "conditional-domain-import-replaces-module",
        Language.PYTHON,
        "import importlib\nif enabled:\n    from application import importer as importlib\ndef run(loader=importlib.import_module):\n    return loader\n",
    ),
    EvaluationCase(
        "type-checking-import-runtime-domain-loader",
        Language.PYTHON,
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import importlib\nelse:\n    from application import importer as importlib\ndef run(loader=importlib.import_module):\n    return loader\n",
    ),
    EvaluationCase(
        "relative-import-replaces-module",
        Language.PYTHON,
        "import importlib\nfrom . import importer as importlib\ndef run(loader=importlib.import_module):\n    return loader\n",
    ),
    EvaluationCase(
        "conditional-import-replaces-builtin",
        Language.PYTHON,
        "if enabled:\n    from application import loader as __import__\ndef run(loader=__import__):\n    return loader\n",
    ),
    EvaluationCase(
        "relative-import-replaces-builtin",
        Language.PYTHON,
        "from . import loader as __import__\ndef run(loader=__import__):\n    return loader\n",
    ),
    EvaluationCase(
        "identical-conditional-module-import",
        Language.PYTHON,
        "import importlib\nif enabled:\n    import importlib\ndef run(loader=importlib.import_module):\n    return loader\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "identical-conditional-symbol-import",
        Language.PYTHON,
        "from importlib import import_module as load\nif enabled:\n    from importlib import import_module as load\ndef run(loader=load):\n    return loader\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "conditional-builtin-import-stays-loader",
        Language.PYTHON,
        "if enabled:\n    from builtins import __import__\ndef run(loader=__import__):\n    return loader\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "enclosing-global-rebinding",
        Language.PYTHON,
        "from importlib import import_module as load\ndef outer():\n    global load\n    load = domain_loader\n    def run(loader=load):\n        pass\n",
    ),
    EvaluationCase(
        "global-module-root-rebinding",
        Language.PYTHON,
        "import importlib\ndef change():\n    global importlib\n    importlib = domain_imports\ndef run(loader=importlib.import_module):\n    pass\n",
    ),
    EvaluationCase(
        "global-builtin-rebinding",
        Language.PYTHON,
        "def change():\n    global __import__\n    __import__ = domain_loader\ndef run(loader=__import__):\n    pass\n",
    ),
    EvaluationCase(
        "unrelated-global-retains-loader",
        Language.PYTHON,
        "import importlib\ndef change():\n    global status\n    status = 'ready'\ndef run(loader=importlib.import_module):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "later-class-binding-does-not-shadow-default",
        Language.PYTHON,
        "from importlib import import_module as load\nclass Service:\n    def run(self, loader=load):\n        pass\n    load = domain_loader\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "method-name-binds-after-default",
        Language.PYTHON,
        "from importlib import import_module as load\nclass Service:\n    def load(self, loader=load):\n        pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "method-body-does-not-close-over-class",
        Language.PYTHON,
        "import importlib\nclass Service:\n    importlib = domain_imports\n    def outer(self):\n        def run(loader=importlib.import_module):\n            pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nested-class-does-not-close-over-outer-class",
        Language.PYTHON,
        "from importlib import import_module as load\nclass Outer:\n    load = domain_loader\n    class Inner:\n        def run(self, loader=load):\n            pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "enclosing-function-capture-through-class",
        Language.PYTHON,
        "from importlib import import_module as load\ndef outer(load):\n    class Service:\n        def method(self):\n            def run(loader=load):\n                pass\n",
    ),
    EvaluationCase(
        "earlier-class-binding-shadows-default",
        Language.PYTHON,
        "from importlib import import_module as load\nclass Service:\n    load = domain_loader\n    def run(self, loader=load):\n        pass\n",
    ),
    EvaluationCase(
        "same-line-earlier-class-binding",
        Language.PYTHON,
        "from importlib import import_module as load\nclass Service: load = domain_loader; run = lambda loader=load: None\n",
    ),
    EvaluationCase(
        "same-line-later-class-binding",
        Language.PYTHON,
        "from importlib import import_module as load\nclass Service: run = lambda loader=load: None; load = domain_loader\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "same-line-assignment-alias-default",
        Language.PYTHON,
        "load = __import__; run = lambda loader=load: None\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "same-line-import-before-assignment-alias",
        Language.PYTHON,
        "import importlib; load = importlib.import_module\nrun = lambda loader=load: None\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nested-default-executes-enclosing-scope",
        Language.PYTHON,
        "from importlib import import_module as load\ndef outer(load=(lambda loader=load: None)):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-loop-target-shadows-default",
        Language.PYTHON,
        "from importlib import import_module as load\nclass Service:\n    for load in domain_loaders:\n        def run(self, loader=load):\n            pass\n",
    ),
    EvaluationCase(
        "class-header-default-uses-enclosing-class",
        Language.PYTHON,
        "from importlib import import_module as load\nclass Outer:\n    load = domain_loader\n    class Inner((lambda loader=load: object)()):\n        pass\n",
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
        "same-name-builtin-assignment-default",
        Language.PYTHON,
        "load = __import__\ndef run(load=load):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "same-name-qualified-assignment-default",
        Language.PYTHON,
        "import importlib\nload = importlib.import_module\ndef run(*, load=load):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "same-name-async-assignment-default",
        Language.PYTHON,
        "import importlib\nload = importlib.import_module\nasync def run(load=load, /):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-parameter-keeps-global-alias",
        Language.PYTHON,
        "load = __import__\ndef domain(load):\n    pass\ndef run(load=load):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-local-keeps-global-alias",
        Language.PYTHON,
        "load = __import__\ndef domain():\n    load = domain_loader\ndef run(load=load):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "same-name-outer-parameter-shadow",
        Language.PYTHON,
        "load = __import__\ndef outer(load):\n    def run(load=load):\n        pass\n",
    ),
    EvaluationCase(
        "same-name-class-shadow",
        Language.PYTHON,
        "load = __import__\nclass Service:\n    load = domain_loader\n    def run(self, load=load):\n        pass\n",
    ),
    EvaluationCase(
        "alias-global-write",
        Language.PYTHON,
        "load = __import__\ndef change():\n    global load\n    load = domain_loader\ndef run(load=load):\n    pass\n",
    ),
    EvaluationCase(
        "alias-walrus-write",
        Language.PYTHON,
        "load = __import__\nvalues = [(load := domain_loader) for item in source]\ndef run(load=load):\n    pass\n",
    ),
    EvaluationCase(
        "captured-importlib-root",
        Language.PYTHON,
        "import importlib\nmatch source:\n    case importlib:\n        pass\ndef run(loader=importlib.import_module):\n    pass\n",
    ),
    EvaluationCase(
        "captured-module-alias",
        Language.PYTHON,
        "import importlib as modules\nmatch source:\n    case modules:\n        pass\ndef run(loader=modules.import_module):\n    pass\n",
    ),
    EvaluationCase(
        "captured-imported-loader",
        Language.PYTHON,
        "from importlib import import_module as load\nmatch source:\n    case load:\n        pass\ndef run(loader=load):\n    pass\n",
    ),
    EvaluationCase(
        "exception-bound-importlib-root",
        Language.PYTHON,
        "import importlib\ntry:\n    pass\nexcept Exception as importlib:\n    pass\ndef run(loader=importlib.import_module):\n    pass\n",
    ),
    EvaluationCase(
        "exception-bound-imported-loader",
        Language.PYTHON,
        "from importlib import import_module as load\ntry:\n    pass\nexcept Exception as load:\n    pass\ndef run(loader=load):\n    pass\n",
    ),
    EvaluationCase(
        "assignment-from-captured-root",
        Language.PYTHON,
        "import importlib\nmatch source:\n    case importlib:\n        pass\nload = importlib.import_module\ndef run(loader=load):\n    pass\n",
    ),
    EvaluationCase(
        "assignment-from-exception-bound-root",
        Language.PYTHON,
        "import importlib\ntry:\n    pass\nexcept Exception as importlib:\n    pass\nload = importlib.import_module\ndef run(loader=load):\n    pass\n",
    ),
    EvaluationCase(
        "captured-builtin-import",
        Language.PYTHON,
        "match source:\n    case __import__:\n        pass\ndef run(loader=__import__):\n    pass\n",
    ),
    EvaluationCase(
        "mapping-rest-importer-root",
        Language.PYTHON,
        "import importlib\nmatch source:\n    case {**importlib}:\n        pass\ndef run(loader=importlib.import_module):\n    pass\n",
    ),
    EvaluationCase(
        "sequence-star-importer-root",
        Language.PYTHON,
        "import importlib\nmatch source:\n    case [*importlib]:\n        pass\ndef run(loader=importlib.import_module):\n    pass\n",
    ),
    EvaluationCase(
        "outer-pattern-alias-shadow",
        Language.PYTHON,
        "load = __import__\ndef outer():\n    match source:\n        case load:\n            def run(loader=load):\n                pass\n",
    ),
    EvaluationCase(
        "outer-exception-alias-shadow",
        Language.PYTHON,
        "load = __import__\ndef outer():\n    try:\n        pass\n    except Exception as load:\n        def run(loader=load):\n            pass\n",
    ),
    EvaluationCase(
        "unrelated-capture-retains-loader",
        Language.PYTHON,
        "import importlib\nmatch source:\n    case record:\n        pass\ndef run(loader=importlib.import_module):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-exception-retains-loader",
        Language.PYTHON,
        "import importlib\ntry:\n    pass\nexcept Exception as error:\n    pass\ndef run(loader=importlib.import_module):\n    pass\n",
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
    EvaluationCase(
        "importer-root-rebound-in-function-default",
        Language.PYTHON,
        "import importlib\nclass Domain:\n    @staticmethod\n    def import_module(name):\n        return name\ndef configure(unused=(importlib := Domain)):\n    pass\ndef run(loader=importlib.import_module):\n    pass\n",
    ),
    EvaluationCase(
        "imported-loader-rebound-in-function-default",
        Language.PYTHON,
        "from importlib import import_module\ndef domain_loader(name):\n    return name\ndef configure(unused=(import_module := domain_loader)):\n    pass\ndef run(loader=import_module):\n    pass\n",
    ),
    EvaluationCase(
        "builtin-loader-rebound-in-function-default",
        Language.PYTHON,
        "def domain_loader(name):\n    return name\ndef configure(unused=(__import__ := domain_loader)):\n    pass\ndef run(loader=__import__):\n    pass\n",
    ),
    EvaluationCase(
        "unrelated-default-walrus-retains-loader",
        Language.PYTHON,
        "import importlib\ndef configure(unused=(setting := 1)):\n    pass\ndef run(loader=importlib.import_module):\n    pass\n",
        ExpectedOutcome.MATCH,
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
