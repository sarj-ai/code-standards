from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- repository-owned TypeScript verifier.
import sys
from typing import TYPE_CHECKING

from sarj_rule_contracts.examples import ExampleAnalyzer, ExampleFinding, verify_examples

from sarj_standards.libs.repository import rule_catalog_artifact
from sarj_standards.libs.rules import Language, RuleEngine, RuleSelector, RuleSpec


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_rule_contracts.examples import NativeAnalyzer, NativeRule


@dataclass(frozen=True, slots=True)
class SelectedRule:
    spec: RuleSpec
    analyze: ExampleAnalyzer


_NODE_VERIFY = """import {rules} from './dist/index.js';
import {verifyRuleExamples} from './dist/rule-examples.js';
const rule = rules[process.argv[1]];
if (!rule) throw new Error('unknown live rule selector: eslint:' + process.argv[1]);
console.log(await verifyRuleExamples(rule));
"""


def verify(root: Path, selector: RuleSelector) -> int:
    if selector.engine is RuleEngine.ESLINT:
        return _typescript(root, selector)
    rule = selected(selector)
    return verify_examples(rule.spec.examples, rule.analyze)


def selected(selector: RuleSelector) -> SelectedRule:
    match selector.engine:
        case RuleEngine.PYTHON:
            return _python(str(selector.rule_id))
        case RuleEngine.SQL:
            return _sql(str(selector.rule_id))
        case RuleEngine.IAC:
            return _iac(str(selector.rule_id))
        case RuleEngine.TEXT:
            return _text(str(selector.rule_id))
        case _:
            msg = f"native example runner does not support {selector.engine}"
            raise ValueError(msg)


def _python(rule_id: str) -> SelectedRule:
    from sarj_python_lint.__main__ import analyze  # ruff: ignore[import-outside-top-level] -- load only the selected engine.
    from sarj_python_lint.rules import REGISTRY  # ruff: ignore[import-outside-top-level]

    return _native(rule_id, RuleEngine.PYTHON, REGISTRY.get(rule_id), analyze)


def _sql(rule_id: str) -> SelectedRule:
    from sarj_sql_lint.__main__ import analyze  # ruff: ignore[import-outside-top-level] -- load only the selected engine.
    from sarj_sql_lint.rules import REGISTRY  # ruff: ignore[import-outside-top-level]

    return _native(rule_id, RuleEngine.SQL, REGISTRY.get(rule_id), analyze)


def _iac(rule_id: str) -> SelectedRule:
    from sarj_iac_lint.__main__ import analyze  # ruff: ignore[import-outside-top-level] -- load only the selected engine.
    from sarj_iac_lint.rules import REGISTRY  # ruff: ignore[import-outside-top-level]

    return _native(rule_id, RuleEngine.IAC, REGISTRY.get(rule_id), analyze)


def _native(rule_id: str, engine: RuleEngine, rule: type[NativeRule] | None, analyze: NativeAnalyzer) -> SelectedRule:
    if rule is None or (native := rule.native_spec()) is None:
        msg = f"unknown or undocumented live rule selector: {engine}:{rule_id}"
        raise ValueError(msg)
    spec = rule_catalog_artifact.native_spec(native, engine=engine, languages=frozenset({Language(engine.value)}))

    def run(_root: Path, focus: Path) -> list[ExampleFinding]:
        return [ExampleFinding(d.path, d.line, d.col, d.code, d.message) for d in analyze([rule_id], [focus])]

    return SelectedRule(spec, run)


def _text(rule_id: str) -> SelectedRule:
    from sarj_standards.libs.linting import textlint  # ruff: ignore[import-outside-top-level] -- selected engine only.

    meta = textlint.REGISTRY.get(rule_id)
    if meta is None:
        msg = f"unknown live rule selector: text:{rule_id}"
        raise ValueError(msg)

    def run(root: Path, focus: Path) -> list[ExampleFinding]:
        return [
            ExampleFinding(d.path, d.line, 1, d.code, d.message)
            for d in textlint.check_paths([str(focus)], root=root, rule_ids=frozenset({rule_id}))
        ]

    return SelectedRule(meta.native_spec(rule_id), run)


def _typescript(root: Path, selector: RuleSelector) -> int:
    rule_catalog_artifact.build_typescript(root)
    node = shutil.which("node")
    if node is None:
        msg = "cannot verify TypeScript examples: node is not installed"
        raise RuntimeError(msg)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed verifier, selector is argv.
        (node, "--input-type=module", "--eval", _NODE_VERIFY, str(selector.rule_id)),
        cwd=root / "packages/typescript",
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode:
        raise ValueError(completed.stderr.strip() or "TypeScript example verification failed")
    return int(completed.stdout.strip())


def run_focused_tests(root: Path, selector: RuleSelector) -> None:
    package = (
        root
        / "packages"
        / (
            "typescript"
            if selector.engine is RuleEngine.ESLINT
            else "standards"
            if selector.engine is RuleEngine.TEXT
            else selector.engine.value
        )
    )
    slug = str(selector.rule_id)
    if selector.engine is RuleEngine.ESLINT:
        test = package / "tests/rules" / f"{slug}.test.ts"
        npm = shutil.which("npm")
        if npm is None:
            msg = "cannot execute selected tests: npm is not installed"
            raise RuntimeError(msg)
        command = (npm, "run", "test", "--", str(test))
    else:
        test = (
            package
            / ("tests/text_rules" if selector.engine is RuleEngine.TEXT else "tests/rules")
            / f"test_{slug.replace('-', '_')}.py"
        )
        if selector.engine is RuleEngine.TEXT and not test.is_file():
            test = package / "tests/test_textlint.py"
        command = (sys.executable, "-m", "pytest", str(test), "-q", "-o", "addopts=")
    if not test.is_file():
        msg = f"missing selected-rule test: {test.relative_to(root)}"
        raise ValueError(msg)
    environment = dict(os.environ)  # ruff: ignore[banned-api] -- forward the process environment to the selected test runner.
    environment["PYTHONPATH"] = os.pathsep.join(
        str(root / f"packages/{name}/src") for name in ("contracts", "python", "sql", "iac", "standards")
    )
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed owning-package command.
        command,
        cwd=package,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode:
        raise ValueError(completed.stdout.strip() + "\n" + completed.stderr.strip())
