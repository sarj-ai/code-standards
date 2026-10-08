from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from sarj_standards.libs.diagnostics import Severity, TrustMode
from sarj_standards.libs.linting.external import UpstreamESLintRules, analyze_external


@pytest.mark.parametrize("upstream", [False, True])
@pytest.mark.parametrize(
    ("suppressed", "bulk_count", "pass_unpruned", "failed"),
    [
        (False, None, False, False),
        (True, None, False, False),
        (False, 1, False, False),
        (False, 2, False, True),
        (False, 2, True, False),
    ],
)
def test_selected_eslint_preserves_parser_options_and_suppressions_without_running_other_rules(
    tmp_path: Path, *, suppressed: bool, bulk_count: int | None, pass_unpruned: bool, failed: bool, upstream: bool
) -> None:
    modules = Path(__file__).resolve().parents[2] / "typescript/node_modules"
    if shutil.which("node") is None or not (modules / "eslint/package.json").is_file():
        pytest.skip("requires the repository's locked TypeScript dependencies")
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    severity = "error" if bulk_count is not None else "warn"
    namespace = "other" if upstream else "@sarj"
    selected_id = f"{namespace}/selected"
    if bulk_count is not None:
        (tmp_path / "eslint-suppressions.json").write_text(
            json.dumps({"sample.ts": {selected_id: {"count": bulk_count}, f"{namespace}/unrelated": {"count": 10}}}),
            encoding="utf-8",
        )
    (tmp_path / "eslint.config.mjs").write_text(
        "import parser from '@typescript-eslint/parser';\n"
        "const selected = {meta:{schema:[{type:'string'}],messages:{found:'selected option preserved'}},"
        "create(context){return {Identifier(node){if(node.name===context.options[0])"
        "context.report({node,messageId:'found'});}};}};\n"
        "const unrelated={create(){throw new Error('UNRELATED RULE EXECUTED');}};\n"
        "export default [{files:['**/*.ts'],languageOptions:{parser},"
        f"plugins:{{'{namespace}':{{rules:{{selected,unrelated}}}}}},"
        f"rules:{{'{selected_id}':['{severity}','needle'],'{namespace}/unrelated':'error'}}}}];\n",
        encoding="utf-8",
    )
    directive = f"// eslint-disable-next-line {selected_id}\n" if suppressed else ""
    (tmp_path / "sample.ts").write_text(directive + "const needle: number = 1;\n", encoding="utf-8")
    reports = analyze_external(
        [str(tmp_path / "sample.ts")],
        root=tmp_path,
        trust=TrustMode.TRUSTED,
        capabilities=frozenset({"eslint"}),
        rule_ids=frozenset() if upstream else frozenset({"selected"}),
        upstream_rules=UpstreamESLintRules(frozenset({selected_id}) if upstream else frozenset()),
        pass_on_unpruned_eslint_suppressions=pass_unpruned,
    )
    assert len(reports) == 1
    assert bool(reports[0].issues) is failed
    diagnostics = reports[0].diagnostics
    if suppressed or bulk_count is not None:
        assert diagnostics == ()
    else:
        assert len(diagnostics) == 1
        assert diagnostics[0].severity is Severity.WARNING
        assert diagnostics[0].message == "selected option preserved"
