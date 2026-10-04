from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode
from sarj_standards.libs.linting import external
from sarj_standards.libs.linting.external import ProcessOutput, analyze_external, analyze_oxlint_project


if TYPE_CHECKING:
    from collections.abc import Sequence


@pytest.mark.parametrize(
    ("config_name", "suppression"),
    [
        ("oxlint.config.mts", "none"),
        ("oxlint.config.mts", "ledger"),
        ("oxlint.config.mts", "directive"),
        ("oxlint.config.mjs", "ledger"),
        ("oxlint.config.mjs", "directive"),
    ],
)
def test_full_native_graph_rejects_unknown_selected_rule(tmp_path: Path, config_name: str, suppression: str) -> None:
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    (tmp_path / config_name).write_text(
        "export default {categories:{correctness:'off'},rules:{'no-debugger':'error'}};\n", encoding="utf-8"
    )
    source = tmp_path / "sample.ts"
    directive = "// oxlint-disable-next-line no-debugger\n" if suppression == "directive" else ""
    source.write_text(directive + "debugger;\n", encoding="utf-8")
    if suppression == "ledger":
        (tmp_path / "oxlint-suppressions.json").write_text(
            json.dumps({"sample.ts": {"no-debugger": {"count": 1}}}), encoding="utf-8"
        )

    (report,) = analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        capabilities=frozenset({"oxlint"}),
        rule_ids=frozenset({"nextjs/unknown-revision-three-rule"}),
    )

    assert report.completion is Completion.FAILED
    assert report.issues
    assert "Selected rule is absent" in report.issues[0].message
    assert not list(tmp_path.glob(".sarj-oxlint-selected-*.mjs"))


@pytest.mark.parametrize("suppression", ["none", "ledger", "directive"])
def test_discovery_accepts_consumer_rules_and_preserves_native_severity_and_suppressions(
    tmp_path: Path, suppression: str
) -> None:
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    (tmp_path / "plugin.mjs").write_text(
        "export default {rules:{probe:{create(c){return {Identifier(n){"
        "if(n.name==='needle')c.report({node:n,message:'consumer finding'});}};}}}};\n",
        encoding="utf-8",
    )
    consumer_level = "error" if suppression == "ledger" else "warn"
    (tmp_path / "oxlint.config.mts").write_text(
        "export default {categories:{correctness:'off'},jsPlugins:[{name:'consumer',specifier:'./plugin.mjs'}],"
        f"rules:{{'consumer/probe':'{consumer_level}','no-debugger':'warn'}}}};\n",
        encoding="utf-8",
    )
    source = tmp_path / "sample.ts"
    directive = "// oxlint-disable-next-line consumer/probe\n" if suppression == "directive" else ""
    source.write_text(directive + "const needle = 1; debugger;\n", encoding="utf-8")
    if suppression == "ledger":
        (tmp_path / "oxlint-suppressions.json").write_text(
            json.dumps({"sample.ts": {"consumer/probe": {"count": 1}}}), encoding="utf-8"
        )

    (report,) = analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        capabilities=frozenset({"oxlint"}),
        rule_ids=frozenset({"consumer/probe", "no-debugger"}),
    )

    assert report.completion is Completion.COMPLETE, report.issues
    expected = {"consumer/probe", "no-debugger"} if suppression == "none" else {"no-debugger"}
    assert {item.rule_id for item in report.diagnostics} == expected
    assert all(item.severity is Severity.WARNING for item in report.diagnostics)
    assert not list(tmp_path.glob(".sarj-oxlint-selected-*.mjs"))


def test_discovery_validates_a_config_once_across_batches_and_preserves_authored_off(tmp_path: Path) -> None:
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    (tmp_path / "oxlint.config.mts").write_text(
        "export default {categories:{correctness:'off'},rules:{'no-debugger':'off'}};\n", encoding="utf-8"
    )
    sources = [tmp_path / f"sample-{index}.ts" for index in range(251)]
    for source in sources:
        source.write_text("debugger;\n", encoding="utf-8")
    validations: list[Path] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        if argv[0] == "node":
            validations.append(cwd)
        return external.run_node_process(argv, cwd=cwd)

    reports = analyze_external(
        [str(source) for source in sources],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        capabilities=frozenset({"oxlint"}),
        rule_ids=frozenset({"no-debugger"}),
        runner=runner,
    )

    assert validations == [tmp_path]
    assert len(reports) == 2
    assert all(report.completion is Completion.COMPLETE for report in reports), reports
    assert sum(report.file_count or 0 for report in reports) == len(sources)
    assert all(not report.diagnostics for report in reports)
    assert not list(tmp_path.glob(".sarj-oxlint-selected-*.mjs"))


@pytest.mark.parametrize("occurrences", [0, 1, 2])
def test_repository_discovery_preserves_nearest_policy_and_native_ledger(tmp_path: Path, occurrences: int) -> None:
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    (tmp_path / "oxlint.config.mts").write_text(
        "export default {categories:{correctness:'off'},rules:{'no-debugger':'error'}};\n", encoding="utf-8"
    )
    selected: list[str] = []
    for name, level in (("enabled", "error"), ("disabled", "off")):
        project = tmp_path / name
        project.mkdir()
        (project / "oxlint.config.mts").write_text(
            f"export default {{categories:{{correctness:'off'}},rules:{{'no-debugger':'{level}'}}}};\n",
            encoding="utf-8",
        )
        source = project / "sample.ts"
        source.write_text("debugger;\n" * (occurrences if name == "enabled" else 1), encoding="utf-8")
        selected.append(str(source))
    ledger = tmp_path / "oxlint-suppressions.json"
    ledger.write_text(json.dumps({"enabled/sample.ts": {"no-debugger": {"count": 1}}}), encoding="utf-8")
    original = ledger.read_bytes()

    reports = analyze_external(
        selected,
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        capabilities=frozenset({"oxlint"}),
        rule_ids=frozenset({"no-debugger"}),
    )

    assert all(report.completion is Completion.COMPLETE for report in reports), reports
    diagnostics = tuple(item for report in reports for item in report.diagnostics)
    assert all(item.location.path != "disabled/sample.ts" for item in diagnostics)
    assert sum(report.file_count or 0 for report in reports) == 2
    match occurrences:
        case 1:
            assert not diagnostics
        case 0:
            assert any(item.rule_id == "oxlint/configuration" for item in diagnostics)
        case _:
            assert any(item.rule_id == "no-debugger" for item in diagnostics)
    assert ledger.read_bytes() == original
    assert not list(tmp_path.rglob(".sarj-oxlint-selected-*.mjs"))


def test_explicit_project_configuration_preserves_its_policy_with_root_discovery_available(tmp_path: Path) -> None:
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    (tmp_path / "oxlint.config.mts").write_text(
        "export default {categories:{correctness:'off'},rules:{'no-debugger':'off'}};\n", encoding="utf-8"
    )
    config = tmp_path / "chosen.json"
    config.write_text(json.dumps({"categories": {"correctness": "off"}, "rules": {"no-debugger": "error"}}))
    source = tmp_path / "sample.ts"
    source.write_text("debugger;\n", encoding="utf-8")

    report = analyze_oxlint_project([str(source)], root=tmp_path, config=config)

    assert report.completion is Completion.COMPLETE, report.issues
    assert [item.rule_id for item in report.diagnostics] == ["no-debugger"]


def test_repository_linter_options_fail_on_unused_unselected_directives(tmp_path: Path) -> None:
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    (tmp_path / "oxlint.config.mts").write_text(
        "export default {categories:{correctness:'off'},options:{reportUnusedDisableDirectives:'error'},"
        "rules:{'no-alert':'error','no-debugger':'error'}};\n",
        encoding="utf-8",
    )
    project = tmp_path / "package"
    project.mkdir()
    (project / "oxlint.config.mts").write_text(
        "export default {categories:{correctness:'off'},rules:{'no-alert':'error','no-debugger':'error'}};\n",
        encoding="utf-8",
    )
    source = project / "sample.ts"
    source.write_text("// oxlint-disable-next-line no-alert\nconst answer = 42;\n", encoding="utf-8")

    (report,) = analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        capabilities=frozenset({"oxlint"}),
        rule_ids=frozenset({"no-debugger"}),
    )

    assert report.completion is Completion.FAILED
    assert any("Unused oxlint-disable directive" in issue.message for issue in report.issues)


@pytest.mark.parametrize(
    ("jsx", "expected_rules"),
    [
        ('<a href="/about">About</a>', ("nextjs/no-html-link-for-pages",)),
        ('<a href="https://example.com">External</a>', ()),
    ],
)
def test_selected_native_next_rule_preserves_reported_namespace(
    tmp_path: Path, jsx: str, expected_rules: tuple[str, ...]
) -> None:
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    (tmp_path / "oxlint.config.mts").write_text(
        "export default {plugins:['nextjs'],categories:{correctness:'off'},"
        "rules:{'nextjs/no-html-link-for-pages':'error','no-debugger':'error'}};\n",
        encoding="utf-8",
    )
    path = tmp_path / "sample.tsx"
    path.write_text(f"export default function Sample(){{debugger;return {jsx}}}\n", encoding="utf-8")

    (report,) = analyze_external(
        [str(path)],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        capabilities=frozenset({"oxlint"}),
        rule_ids=frozenset({"nextjs/no-html-link-for-pages"}),
    )

    assert report.completion is Completion.COMPLETE, report.issues
    assert report.file_count == 1
    assert tuple(item.rule_id for item in report.diagnostics) == expected_rules


@pytest.mark.parametrize(("suppressed", "bulk_count"), [(False, None), (True, None), (False, 1), (False, 2)])
def test_selected_native_rules_preserve_options_warnings_and_suppression_validation(
    tmp_path: Path, suppressed: bool, bulk_count: int | None
) -> None:
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    if shutil.which("node") is None or not (modules / "oxlint/package.json").is_file():
        pytest.skip("requires the repository's locked TypeScript dependencies")
    dependencies = tmp_path / "node_modules"
    dependencies.mkdir()
    (dependencies / ".bin").symlink_to(modules / ".bin", target_is_directory=True)
    for package in ("oxlint", "oxlint-tsgolint"):
        (dependencies / package).symlink_to(modules / package, target_is_directory=True)
    (dependencies / "@sarj").mkdir()
    (dependencies / "@sarj/oxlint-plugin").symlink_to(modules.parent / "packages/typescript", target_is_directory=True)
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    ledger = tmp_path / "oxlint-suppressions.json"
    if bulk_count is not None:
        ledger.write_text(
            json.dumps({"sample.ts": {"@sarj/selected": {"count": bulk_count}, "@sarj/unrelated": {"count": 1}}}),
            encoding="utf-8",
        )
    unrelated = (
        "{create(c){return {Program(n){c.report({node:n,message:'unrelated'});}};}}"
        if bulk_count is not None or suppressed
        else "{create(){throw new Error('UNRELATED RULE EXECUTED');}}"
    )
    (tmp_path / "plugin.mjs").write_text(
        "const selected = {meta:{schema:[{type:'string'}],messages:{found:'selected option preserved'}},"
        "create(context){return {Identifier(node){if(node.name===context.options[0])"
        "context.report({node,messageId:'found'});}};}};\n"
        f"export default {{rules:{{selected,unrelated:{unrelated}}}}};\n",
        encoding="utf-8",
    )
    severity = "error" if bulk_count is not None else "warn"
    config = tmp_path / "oxlint.config.mjs"
    config.write_text(
        "export default {categories:{correctness:'off'},options:{reportUnusedDisableDirectives:'error'},"
        "jsPlugins:[{name:'@sarj',specifier:'./plugin.mjs'}],"
        f"rules:{{'@sarj/selected':['{severity}','needle'],'@sarj/unrelated':'error'}}}};\n",
        encoding="utf-8",
    )
    directive = "// oxlint-disable-next-line @sarj/selected\n" if suppressed else ""
    source = tmp_path / "sample.ts"
    source.write_text(directive + "const needle: number = 1;\n", encoding="utf-8")
    originals = {path: path.read_bytes() for path in (source, config, ledger) if path.exists()}
    (report,) = analyze_external(
        [str(source)],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        capabilities=frozenset({"oxlint"}),
        rule_ids=frozenset({"selected"}),
    )
    assert report.completion is Completion.COMPLETE, report.issues
    assert not report.issues
    assert {path: path.read_bytes() for path in originals} == originals
    assert not list(tmp_path.glob(".sarj-oxlint-selected-*.mjs"))
    if bulk_count == 2:
        assert [(d.rule_id, d.severity) for d in report.diagnostics] == [("oxlint/configuration", Severity.ERROR)]
    elif suppressed or bulk_count is not None:
        assert not report.diagnostics
    else:
        assert [(d.rule_id, d.severity, d.message) for d in report.diagnostics] == [
            ("@sarj/selected", Severity.WARNING, "selected option preserved")
        ]


@pytest.mark.parametrize(
    ("source", "completion", "expected_rules"),
    [
        pytest.param(
            "// oxlint-disable-next-line no-debugger\ndebugger;\n",
            Completion.COMPLETE,
            (),
            id="valid-unselected-suppression",
        ),
        pytest.param(
            "// oxlint-disable-next-line no-debugger\ndebugger;\nalert('unsafe');\n",
            Completion.COMPLETE,
            ("no-alert",),
            id="selected-rule-still-reports",
        ),
        pytest.param(
            "// oxlint-disable no-debugger\ndebugger;\n// oxlint-enable no-debugger\nalert('unsafe');\n",
            Completion.COMPLETE,
            ("no-alert",),
            id="native-block-directives",
        ),
        pytest.param(
            "// oxlint-disable-next-line no-debugger\nconst answer = 42;\n",
            Completion.FAILED,
            ("oxlint/configuration",),
            id="genuinely-unused-suppression",
        ),
    ],
)
def test_selected_native_rules_validate_unselected_inline_suppressions(
    tmp_path: Path, source: str, completion: Completion, expected_rules: tuple[str, ...]
) -> None:
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    config = tmp_path / "oxlint.config.mts"
    config.write_text(
        "export default {categories:{correctness:'off'},options:{reportUnusedDisableDirectives:'error'},"
        "rules:{'no-debugger':'error','no-alert':'error'}};\n",
        encoding="utf-8",
    )
    path = tmp_path / "sample.ts"
    path.write_text(source, encoding="utf-8")

    (report,) = analyze_external(
        [str(path)],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        capabilities=frozenset({"oxlint"}),
        rule_ids=frozenset({"no-alert"}),
    )

    assert report.completion is completion
    assert tuple(item.rule_id for item in report.diagnostics) == expected_rules
    assert all(item.severity is Severity.ERROR for item in report.diagnostics)
    assert report.file_count == 1
    assert path.read_text(encoding="utf-8") == source
    assert not list(tmp_path.glob(".sarj-oxlint-selected-*.mjs"))
    if completion is Completion.FAILED:
        assert report.issues[0].kind == "tool-failure"
        assert "Unused oxlint-disable directive" in report.issues[0].message
    else:
        assert not report.issues


@pytest.fixture
def ignored_native_project(tmp_path: Path) -> Path:
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    if shutil.which("node") is None or not (modules / "oxlint/package.json").is_file():
        pytest.skip("requires the repository's locked TypeScript dependencies")
    dependencies = tmp_path / "node_modules"
    dependencies.mkdir()
    (dependencies / ".bin").symlink_to(modules / ".bin", target_is_directory=True)
    for package in ("oxlint", "oxlint-tsgolint"):
        (dependencies / package).symlink_to(modules / package, target_is_directory=True)
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    (tmp_path / "oxlint.config.mjs").write_text(
        'export default {ignorePatterns:["ignored.ts"],rules:{"no-debugger":"error"}};\n', encoding="utf-8"
    )
    for filename in ("ignored.ts", "visible.ts"):
        (tmp_path / filename).write_text("debugger;\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("include_visible", [True, False])
def test_native_ignores_preserve_scope_without_hiding_findings(
    ignored_native_project: Path, include_visible: bool
) -> None:
    root = ignored_native_project
    original = (root / "ignored.ts").read_bytes()
    selected = ["ignored.ts", "visible.ts"] if include_visible else ["ignored.ts"]
    report = analyze_oxlint_project(selected, root=root, config=Path("oxlint.config.mjs"))
    assert report.completion is Completion.COMPLETE, report.issues
    assert report.file_count == int(include_visible)
    assert tuple(item.location.path for item in report.diagnostics) == (("visible.ts",) if include_visible else ())
    assert all(item.rule_id == "no-debugger" for item in report.diagnostics)
    assert (root / "ignored.ts").read_bytes() == original  # sarj-noqa: SARJ402 -- native checks preserve source bytes


@pytest.mark.parametrize("filename", ["missing.ts", "unsupported.py"])
def test_native_ignored_scope_does_not_hide_unsupported_or_missing_inputs(
    ignored_native_project: Path, filename: str
) -> None:
    root = ignored_native_project
    if filename == "unsupported.py":
        (root / filename).write_text("VALUE = 1\n", encoding="utf-8")
    report = analyze_oxlint_project(["ignored.ts", filename], root=root, config=Path("oxlint.config.mjs"))
    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "coverage-missing"
