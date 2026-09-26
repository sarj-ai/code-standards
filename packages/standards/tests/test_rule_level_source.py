from __future__ import annotations

from pathlib import Path

import pytest

from sarj_standards.libs.repository import rule_level_source
from sarj_standards.libs.rules import DefaultLevel, RuleEngine, RuleSelector


@pytest.mark.parametrize("engine", [RuleEngine.PYTHON, RuleEngine.SQL, RuleEngine.IAC, RuleEngine.TEXT])
@pytest.mark.parametrize("multiline", [False, True])
def test_explicit_native_levels_preserve_field_order_and_unicode(
    tmp_path: Path, engine: RuleEngine, *, multiline: bool
) -> None:
    constructor = "RuleMeta" if engine is RuleEngine.TEXT else "RuleDocumentation"
    enum = "Severity" if engine is RuleEngine.PYTHON else "DefaultLevel"
    separator = "\n    " if multiline else " "
    source = (
        f"documentation = {constructor}(summary='😀 café',"
        + separator
        + f"default_level = {enum}.WARNING,  # retained explanation\n)\n"
    )
    path = tmp_path / "rule.py"
    path.write_text(source, encoding="utf-8")
    selector = RuleSelector.parse(f"{engine.value}:sample")

    unchanged = rule_level_source.prepare(tmp_path, selector, "rule.py", DefaultLevel.WARNING)
    assert unchanged.current is DefaultLevel.WARNING
    assert unchanged.after == source
    promoted = rule_level_source.prepare(tmp_path, selector, "rule.py", DefaultLevel.ERROR)
    assert promoted.current is DefaultLevel.WARNING
    assert promoted.after == source.replace(f"{enum}.WARNING", f"{enum}.ERROR")
    compile(promoted.after, "rule.py", "exec")
    path.write_text(promoted.after, encoding="utf-8")
    assert rule_level_source.prepare(tmp_path, selector, "rule.py", DefaultLevel.WARNING).after == source


@pytest.mark.parametrize("engine", [RuleEngine.PYTHON, RuleEngine.SQL, RuleEngine.IAC])
@pytest.mark.parametrize("multiline", [False, True])
def test_missing_native_level_imports_enum_and_compiles(tmp_path: Path, engine: RuleEngine, *, multiline: bool) -> None:
    enum = "Severity" if engine is RuleEngine.PYTHON else "DefaultLevel"
    names = "(\n    RuleDocumentation,\n)" if multiline else "RuleDocumentation"
    arguments = "\n    summary='example',\n" if multiline else "summary='example'"
    source = f"from sarj_{engine.value}_lint.rule_base import {names}\ndocumentation = RuleDocumentation({arguments})\n"
    path = tmp_path / "rule.py"
    path.write_text(source, encoding="utf-8")
    selector = RuleSelector.parse(f"{engine.value}:sample")

    staged = rule_level_source.prepare(tmp_path, selector, "rule.py", DefaultLevel.WARNING)
    assert staged.current is DefaultLevel.ERROR
    assert f"default_level={enum}.WARNING" in staged.after
    assert staged.after.count(enum) == 2
    compile(staged.after, "rule.py", "exec")
    path.write_text(staged.after, encoding="utf-8")
    assert rule_level_source.prepare(tmp_path, selector, "rule.py", DefaultLevel.WARNING).after == staged.after


@pytest.mark.parametrize(
    "source",
    [
        'export const SAMPLE_DOCUMENTATION = { summary: "😀 café", defaultLevel: "warning" } as const;\n',
        (
            "export const SAMPLE_DOCUMENTATION = {\n"
            '  summary: "😀 café",\n'
            "  examples: [{ source: 'defaultLevel: \"error\"' }],\n"
            '  // defaultLevel: "error" is merely a comment.\n'
            "  defaultLevel: 'warning', // retained explanation\n"
            "} as const satisfies RuleDocumentation;\n"
        ),
    ],
)
def test_typescript_levels_edit_only_direct_property(tmp_path: Path, source: str) -> None:
    root = Path(__file__).resolve().parents[3]
    path = tmp_path / "rule.ts"
    path.write_text(source, encoding="utf-8")
    selector = RuleSelector.parse("eslint:sample")

    staged = rule_level_source.prepare(root, selector, str(path), DefaultLevel.WARNING)
    assert staged.current is DefaultLevel.WARNING
    assert staged.after == source
    promoted = rule_level_source.prepare(root, selector, str(path), DefaultLevel.ERROR)
    assert promoted.current is DefaultLevel.WARNING
    assert promoted.after == source.replace('"warning"', '"error"').replace("'warning'", "'error'")
    path.write_text(promoted.after, encoding="utf-8")
    assert rule_level_source.prepare(root, selector, str(path), DefaultLevel.WARNING).after == source


def test_typescript_inserts_missing_level_without_matching_nested_source(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    source = "const SAMPLE_DOCUMENTATION = { examples: [{source: 'defaultLevel: \"warning\"'}] };\n"
    path = tmp_path / "rule.ts"
    path.write_text(source, encoding="utf-8")
    selector = RuleSelector.parse("eslint:sample")

    staged = rule_level_source.prepare(root, selector, str(path), DefaultLevel.WARNING)
    assert staged.current is DefaultLevel.ERROR
    assert staged.after == source.replace("{ examples:", '{ defaultLevel: "warning", examples:', 1)
    path.write_text(staged.after, encoding="utf-8")
    assert rule_level_source.prepare(root, selector, str(path), DefaultLevel.WARNING).after == staged.after


def test_native_promotion_preserves_enum_alias(tmp_path: Path) -> None:
    source = (
        "from sarj_python_lint.rule_base import Severity as Level\n"
        "documentation = RuleDocumentation(summary='example', default_level=Level.WARNING)\n"
    )
    path = tmp_path / "rule.py"
    path.write_text(source, encoding="utf-8")

    promoted = rule_level_source.prepare(tmp_path, RuleSelector.parse("python:sample"), "rule.py", DefaultLevel.ERROR)

    assert promoted.after == source.replace("Level.WARNING", "Level.ERROR")
    compile(promoted.after, "rule.py", "exec")


@pytest.mark.parametrize("engine", [RuleEngine.PYTHON, RuleEngine.SQL, RuleEngine.IAC])
def test_native_staging_preserves_backslash_imports(tmp_path: Path, engine: RuleEngine) -> None:
    source = (
        f"from sarj_{engine.value}_lint.rule_base import RuleDocumentation, \\\n"
        "    Rule as BaseRule  # retain this alias\n"
        "documentation = RuleDocumentation(summary='example')\n"
    )
    path = tmp_path / "rule.py"
    path.write_text(source, encoding="utf-8")
    selector = RuleSelector.parse(f"{engine.value}:sample")

    staged = rule_level_source.prepare(tmp_path, selector, "rule.py", DefaultLevel.WARNING)

    compile(staged.after, "rule.py", "exec")
    assert "Rule as BaseRule" in staged.after
    assert "# retain this alias" in staged.after
    assert "\\\n" in staged.after
    path.write_text(staged.after, encoding="utf-8")
    assert rule_level_source.prepare(tmp_path, selector, "rule.py", DefaultLevel.WARNING).after == staged.after


@pytest.mark.parametrize(
    "arguments",
    [
        "'Summary', 'Reason', 'Fix', 'correctness'",
        "\n    'Summary', 'Reason', 'Fix', 'correctness',  # keep comment\n",
        "'Summary', 'Reason', 'Fix', category='correctness'",
        "'Summary', 'Reason', 'Fix', 'correctness', Severity.ERROR",
    ],
)
def test_native_staging_preserves_positional_arguments(tmp_path: Path, arguments: str) -> None:
    source = (
        "from sarj_python_lint.rule_base import RuleDocumentation, Severity\n"
        f"documentation = RuleDocumentation({arguments})\n"
    )
    path = tmp_path / "rule.py"
    path.write_text(source, encoding="utf-8")
    selector = RuleSelector.parse("python:sample")

    staged = rule_level_source.prepare(tmp_path, selector, "rule.py", DefaultLevel.WARNING)

    assert staged.current is DefaultLevel.ERROR
    assert "Severity.WARNING" in staged.after
    compile(staged.after, "rule.py", "exec")
    path.write_text(staged.after, encoding="utf-8")
    assert rule_level_source.prepare(tmp_path, selector, "rule.py", DefaultLevel.WARNING).after == staged.after


@pytest.mark.parametrize("arguments", ["*SHARED", "summary='example', **SHARED"])
def test_native_staging_refuses_unknown_unpacked_severity(tmp_path: Path, arguments: str) -> None:
    source = f"documentation = RuleDocumentation({arguments})\n"
    path = tmp_path / "rule.py"
    path.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match="unpacked rule documentation"):
        rule_level_source.prepare(tmp_path, RuleSelector.parse("python:sample"), "rule.py", DefaultLevel.WARNING)

    assert path.read_text(encoding="utf-8") == source


@pytest.mark.parametrize("name", ['["defaultLevel"]', "['defaultLevel']", "[`defaultLevel`]"])
def test_typescript_promotes_literal_computed_severity(tmp_path: Path, name: str) -> None:
    root = Path(__file__).resolve().parents[3]
    source = f'const SAMPLE_DOCUMENTATION = {{ summary: "😀 café", {name}: "warning" }} as const;\n'
    path = tmp_path / "rule.ts"
    path.write_text(source, encoding="utf-8")
    selector = RuleSelector.parse("eslint:sample")

    promoted = rule_level_source.prepare(root, selector, str(path), DefaultLevel.ERROR)

    assert promoted.current is DefaultLevel.WARNING
    assert promoted.after == source.replace('"warning"', '"error"')
    path.write_text(promoted.after, encoding="utf-8")
    assert rule_level_source.prepare(root, selector, str(path), DefaultLevel.WARNING).after == source


@pytest.mark.parametrize(
    "properties",
    ["...SHARED", "[KEY]: 'warning'", "defaultLevel: 'error', ...SHARED", "defaultLevel: 'error', [KEY]: 'warning'"],
)
def test_typescript_refuses_ambiguous_severity_ownership(tmp_path: Path, properties: str) -> None:
    root = Path(__file__).resolve().parents[3]
    source = f"const SAMPLE_DOCUMENTATION = {{ {properties} }};\n"
    path = tmp_path / "rule.ts"
    path.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match="ambiguous defaultLevel ownership"):
        rule_level_source.prepare(root, RuleSelector.parse("eslint:sample"), str(path), DefaultLevel.WARNING)

    assert path.read_text(encoding="utf-8") == source


@pytest.mark.parametrize("properties", ["...SHARED", "[KEY]: 'error'"])
def test_typescript_preserves_metadata_overridden_by_explicit_severity(tmp_path: Path, properties: str) -> None:
    root = Path(__file__).resolve().parents[3]
    source = f"const SAMPLE_DOCUMENTATION = {{ {properties}, defaultLevel: 'warning' }};\n"
    path = tmp_path / "rule.ts"
    path.write_text(source, encoding="utf-8")

    promoted = rule_level_source.prepare(root, RuleSelector.parse("eslint:sample"), str(path), DefaultLevel.ERROR)

    assert promoted.current is DefaultLevel.WARNING
    assert promoted.after == source.replace("'warning'", "'error'")
