from __future__ import annotations

from dataclasses import dataclass
import keyword
from pathlib import Path
from typing import Final

from sarj_standards.libs.rules import RuleEngine, RuleId


AUTHORED_ENGINES: Final = (
    RuleEngine.PYTHON,
    RuleEngine.SQL,
    RuleEngine.IAC,
    RuleEngine.TEXT,
    RuleEngine.ESLINT,
)


@dataclass(frozen=True, slots=True)
class RuleLayout:
    package: Path
    source: Path
    tests: Path
    registry: Path
    module: str | None

    @property
    def native_module(self) -> str:
        if self.module is None:
            msg = "ESLint rules do not have a native Python module"
            raise ValueError(msg)
        return self.module

    def implementation(self, rule_id: RuleId) -> Path:
        name = str(rule_id) if self.module is None else module_name(rule_id)
        return self.source / f"{name}.{'ts' if self.module is None else 'py'}"

    def test(self, rule_id: RuleId) -> Path:
        name = f"{rule_id}.test.ts" if self.module is None else f"test_{module_name(rule_id)}.py"
        return self.tests / name


def layout(root: Path, engine: RuleEngine) -> RuleLayout:
    if engine not in AUTHORED_ENGINES:
        choices = ", ".join(item.value for item in AUTHORED_ENGINES)
        msg = f"cannot scaffold upstream {engine.value} rules; supported authoring engines: {choices}"
        raise ValueError(msg)
    if engine is RuleEngine.ESLINT:
        package = root / "packages/typescript"
        return RuleLayout(package, package / "src/rules", package / "tests/rules", package / "src/index.ts", None)
    package = root / "packages" / ("standards" if engine is RuleEngine.TEXT else engine.value)
    module = (
        "sarj_standards.libs.linting.text_rules" if engine is RuleEngine.TEXT else f"sarj_{engine.value}_lint.rules"
    )
    source = package / "src" / module.replace(".", "/")
    tests = package / "tests" / ("text_rules" if engine is RuleEngine.TEXT else "rules")
    return RuleLayout(package, source, tests, source / "_registry.py", module)


def class_name(rule_id: RuleId) -> str:
    name = "".join(part.capitalize() for part in str(rule_id).split("-"))
    return name if name.isidentifier() and not keyword.iskeyword(name) else f"Rule{name}"


def module_name(rule_id: RuleId) -> str:
    name = str(rule_id).replace("-", "_")
    return name if name.isidentifier() and not keyword.iskeyword(name) else f"rule_{name}"


def eslint_binding(rule_id: RuleId) -> str:
    return f"rule{class_name(rule_id)}"
