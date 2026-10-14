from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import pytest

from sarj_standards.libs.repository import rule_authoring
from sarj_standards.libs.rules import RuleSelector


if TYPE_CHECKING:
    from sarj_rule_contracts import RuleDocumentation

    from sarj_standards.libs.linting.text_rule_base import RuleMeta


_PARSE_TYPESCRIPT = """const ts = require(process.argv[1]);
const fs = require('node:fs');
for (const path of process.argv.slice(2)) {
  const file = ts.createSourceFile(path, fs.readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  for (const diagnostic of file.parseDiagnostics) {
    console.error(ts.flattenDiagnosticMessageText(diagnostic.messageText, '\\n'));
    process.exitCode = 1;
  }
}
"""


@runtime_checkable
class _AuthoredRule(Protocol):
    id: str
    documentation: RuleDocumentation | RuleMeta


@pytest.mark.parametrize("engine", ["python", "sql", "iac", "text"])
@pytest.mark.parametrize("rule_id", ["2fa-required", "class", "false"])
@pytest.mark.parametrize(
    "summary",
    [
        pytest.param('Reject triple quotes like """ and apostrophes.', id="triple-quotes"),
        pytest.param(r"Keep literal paths such as C:\new\tools.", id="backslashes"),
        pytest.param("Preserve café and Unicode separators: \u2028.", id="unicode"),
    ],
)
def test_native_scaffolds_compile_and_preserve_authored_metadata(
    tmp_path: Path, engine: str, rule_id: str, summary: str
) -> None:
    selector = RuleSelector.parse(f"{engine}:{rule_id}")
    plan = rule_authoring.plan_new(tmp_path, selector, category="correctness", summary=summary)
    rule_authoring.apply(plan, tmp_path)
    namespace: dict[str, object] = {"__name__": "generated_rule"}
    source = plan.files[0][0]
    exec(compile(source.read_text(), str(source), "exec"), namespace)  # ruff: ignore[exec-builtin] -- execute the generated authoring output.
    classes: list[object] = [
        value for value in namespace.values() if isinstance(value, type) and value.__module__ == "generated_rule"
    ]
    assert len(classes) == 1
    generated = classes[0]
    assert isinstance(generated, _AuthoredRule)
    assert generated.documentation.summary == summary
    assert generated.documentation.default_level.value == "warning"
    assert generated.id == rule_id
    for path in (plan.files[1][0], plan.edits[0].path):
        compile(path.read_text(), str(path), "exec")


@pytest.mark.parametrize("rule_id", ["2fa-required", "class", "import"])
def test_eslint_scaffolds_and_registration_parse_with_the_locked_compiler(tmp_path: Path, rule_id: str) -> None:
    compiler = Path(__file__).resolve().parents[3] / "typescript/node_modules/typescript/lib/typescript.js"
    node = shutil.which("node")
    if node is None or not compiler.is_file():
        pytest.skip("requires the locked TypeScript compiler from make setup")
    plan = rule_authoring.plan_new(
        tmp_path,
        RuleSelector.parse(f"eslint:{rule_id}"),
        category="correctness",
        summary='Preserve "quoted" paths such as C:\\new\\tools.',
    )
    rule_authoring.apply(plan, tmp_path)
    paths = [*(str(path) for path, _source in plan.files), str(plan.edits[0].path)]
    completed = subprocess.run(
        [node, "-e", _PARSE_TYPESCRIPT, str(compiler), *paths],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("engine", ["python", "sql", "iac", "text", "eslint"])
@pytest.mark.parametrize(
    "summary",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
        pytest.param("First line\nSecond line", id="multiline"),
        pytest.param("a" * 161, id="too-long"),
    ],
)
def test_invalid_documentation_is_rejected_before_reserving_an_identity(
    tmp_path: Path, engine: str, summary: str
) -> None:
    with pytest.raises(ValueError, match="summary"):
        rule_authoring.plan_new(
            tmp_path, RuleSelector.parse(f"{engine}:new-rule"), category="correctness", summary=summary
        )
    assert not any(tmp_path.iterdir())
