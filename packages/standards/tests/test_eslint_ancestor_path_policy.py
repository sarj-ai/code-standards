from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.diagnostics import Completion, TrustMode
from sarj_standards.libs.linting.external import analyze_external, run_process


_ENV_RULE = "@sarj/no-raw-env"
_EXPORT_RULE = "@sarj/sole-export-matches-filename"
_COMMENT_RULE = "@sarj/no-type-member-comment-wall"
_ALL_RULES = tuple(sorted((_ENV_RULE, _EXPORT_RULE, _COMMENT_RULE)))
_SOURCE = """import nodeProcess from 'node:process';
export const databaseUrl = nodeProcess.env.DATABASE_URL;
interface Credentials {
  // Database host.
  host?: string;
  // Database host port.
  port?: number;
  // Database username.
  username?: string;
  // Database password.
  password?: string;
}
"""


@pytest.fixture
def typescript_package() -> Path:
    package = Path(__file__).resolve().parents[2] / "typescript"
    if shutil.which("node") is None or not (package / "node_modules/eslint/package.json").is_file():
        pytest.skip("requires the repository's locked TypeScript dependencies")
    return package


def _make_project(root: Path, typescript_package: Path) -> Path:
    root.mkdir(parents=True)
    dependencies = root / "node_modules"
    dependencies.mkdir()
    modules = typescript_package / "node_modules"
    (dependencies / ".bin").symlink_to(modules / ".bin", target_is_directory=True)
    for name in ("eslint", "typescript-eslint", "@eslint-community/eslint-plugin-eslint-comments"):
        destination = dependencies / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(modules / name, target_is_directory=True)
    (dependencies / "@sarj").mkdir()
    (dependencies / "@sarj/eslint-plugin").symlink_to(typescript_package, target_is_directory=True)
    (root / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    (root / "eslint.config.mjs").write_text(
        "import ts from 'typescript-eslint';\n"
        "import sarj from '@sarj/eslint-plugin';\n"
        "export default [{files:['**/*.{ts,tsx}'],languageOptions:{parser:ts.parser},"
        "plugins:{'@sarj':sarj},rules:" + json.dumps(dict.fromkeys(_ALL_RULES, "error")) + "}];\n",
        encoding="utf-8",
    )
    return root


def _write_source(project: Path, relative: str, *, generated_header: bool = False) -> Path:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(("// @generated\n" if generated_header else "") + _SOURCE, encoding="utf-8")
    return path


def _canonical_rules(project: Path, path: Path) -> tuple[str, ...]:
    tools = analyze_external([str(path)], root=project, trust=TrustMode.TRUSTED, capabilities=frozenset({"eslint"}))
    assert len(tools) == 1
    report = tools[0]
    assert report.completion is Completion.COMPLETE, report.issues
    assert not report.issues
    return tuple(sorted(item.rule_id for item in report.diagnostics if item.rule_id is not None))


@pytest.mark.parametrize(
    "ancestor",
    ["runtime", "fixtures", "test", "tests", "__tests__", "vendor", "generated", "scripts", "stories", "external"],
    ids=(
        "ordinary",
        "fixtures",
        "singular-test",
        "tests",
        "dunder-tests",
        "vendor",
        "generated",
        "scripts",
        "stories",
        "external",
    ),
)
def test_canonical_eslint_checks_production_beneath_exempt_named_ancestors(
    tmp_path: Path, typescript_package: Path, ancestor: str
) -> None:
    project = _make_project(tmp_path / ancestor / "consumer", typescript_package)
    source = _write_source(project, "src/app.ts")

    assert _canonical_rules(project, source) == _ALL_RULES


@pytest.mark.parametrize(
    ("relative", "generated_header", "expected"),
    [
        ("fixtures/app.ts", False, ()),
        ("tests/app.ts", False, ()),
        ("src/app.test.ts", False, ()),
        ("scripts/app.ts", False, tuple(sorted((_COMMENT_RULE, _EXPORT_RULE)))),
        ("generated/app.ts", False, (_ENV_RULE,)),
        ("src/app.ts", True, (_ENV_RULE,)),
        ("stories/app.ts", False, tuple(sorted((_ENV_RULE, _EXPORT_RULE)))),
        ("src/app.stories.ts", False, tuple(sorted((_ENV_RULE, _EXPORT_RULE)))),
        ("external/app.ts", False, tuple(sorted((_ENV_RULE, _EXPORT_RULE)))),
    ],
    ids=(
        "fixtures",
        "tests",
        "test-basename",
        "scripts",
        "generated-tree",
        "generated-header",
        "stories-tree",
        "story-basename",
        "external-tree",
    ),
)
def test_canonical_eslint_preserves_in_repository_exemptions(
    tmp_path: Path, typescript_package: Path, relative: str, *, generated_header: bool, expected: tuple[str, ...]
) -> None:
    project = _make_project(tmp_path / "fixtures" / "consumer", typescript_package)
    source = _write_source(project, relative, generated_header=generated_header)

    assert _canonical_rules(project, source) == expected


@pytest.mark.parametrize("relative_cwd", [".", "src"], ids=("project-root", "source-child"))
def test_native_eslint_uses_its_project_cwd_when_the_process_runs_elsewhere(
    tmp_path: Path, typescript_package: Path, relative_cwd: str
) -> None:
    project = _make_project(tmp_path / "fixtures" / "consumer", typescript_package)
    _write_source(project, "src/app.ts")
    caller = tmp_path / "caller"
    caller.mkdir()
    script = (
        "import {createRequire} from 'node:module';"
        "import {resolve} from 'node:path';"
        "const project=process.argv[1];"
        "const cwd=process.argv[2];"
        "const require=createRequire(resolve(project,'package.json'));"
        "const {ESLint}=require('eslint');"
        "const eslint=new ESLint({cwd,overrideConfigFile:resolve(project,'eslint.config.mjs'),cache:false});"
        "const results=await eslint.lintFiles([resolve(project,'src/app.ts')]);"
        "console.log(results.flatMap(result=>result.messages.map(message=>message.ruleId)).sort().join('\\n'));"
    )
    result = run_process(
        ("node", "--input-type=module", "--eval", script, str(project), str((project / relative_cwd).resolve())),
        cwd=caller,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == list(_ALL_RULES)


def test_native_eslint_preserves_physical_project_ownership_across_consumers(
    tmp_path: Path, typescript_package: Path
) -> None:
    rule = "@sarj/prefer-shadcn-primitives"
    present = _make_project(tmp_path / "fixtures" / "present", typescript_package)
    missing = _make_project(tmp_path / "fixtures" / "missing", typescript_package)
    for project in (present, missing):
        (project / "eslint.config.mjs").write_text(
            "import ts from 'typescript-eslint';\n"
            "import sarj from '@sarj/eslint-plugin';\n"
            "export default [{files:['**/*.tsx'],languageOptions:{parser:ts.parser},"
            "plugins:{'@sarj':sarj},rules:{'@sarj/prefer-shadcn-primitives':"
            "['error',{detectProjectPrimitives:true}]}}];\n",
            encoding="utf-8",
        )
        (project / "components.json").write_text('{"aliases":{"ui":"@/components/ui"}}', encoding="utf-8")
        (project / "tsconfig.json").write_text(
            '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["./src/*"]}}}', encoding="utf-8"
        )
        source = project / "src/features/action.tsx"
        source.parent.mkdir(parents=True)
        source.write_text('export const Action = () => <button type="button">Save</button>;', encoding="utf-8")
    primitive = present / "src/components/ui/button.tsx"
    primitive.parent.mkdir(parents=True)
    primitive.write_text("const Button = () => null; export { Button };", encoding="utf-8")
    script = (
        "import {createRequire} from 'node:module';"
        "import {resolve} from 'node:path';"
        "const projects=process.argv.slice(1);"
        "const require=createRequire(resolve(projects[0],'package.json'));"
        "const {ESLint}=require('eslint');"
        "for(const project of [...projects,...projects]){"
        "const eslint=new ESLint({cwd:project,overrideConfigFile:resolve(project,'eslint.config.mjs'),cache:false});"
        "const results=await eslint.lintFiles(['src/features/action.tsx']);"
        "console.log(results.flatMap(result=>result.messages.map(message=>message.ruleId)).join(','));}"
    )
    result = run_process(("node", "--input-type=module", "--eval", script, str(present), str(missing)), cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [rule, "", rule, ""]


def test_canonical_eslint_keeps_import_binding_narrowing_under_a_test_named_ancestor(
    tmp_path: Path, typescript_package: Path
) -> None:
    project = _make_project(tmp_path / "fixtures" / "consumer", typescript_package)
    source = _write_source(project, "src/app.ts")
    source.write_text(
        "export function read(nodeProcess: {env: {DATABASE_URL: string}}) {return nodeProcess.env.DATABASE_URL;}\n",
        encoding="utf-8",
    )

    assert _canonical_rules(project, source) == (_EXPORT_RULE,)


@pytest.mark.parametrize(
    ("relative", "expected"),
    [("src/app.ts", _ALL_RULES), ("src/app.generated.ts", (_ENV_RULE,))],
    ids=("application-source", "generated-basename"),
)
def test_full_driver_uses_the_same_context_relative_path_policy(
    tmp_path: Path, typescript_package: Path, relative: str, expected: tuple[str, ...]
) -> None:
    project = _make_project(tmp_path / "fixtures" / "consumer", typescript_package)
    _write_source(project, relative)
    request = json.dumps({"full": True, "config": None, "rules": [], "consoleOutput": True, "failOnWarnings": True})
    result = run_process(
        ("node", str(manifest.PEERS_JSON.with_name("eslint-selected-rules.mts")), request, "--", relative),
        cwd=project,
    )

    assert result.returncode == 1, result.stderr
    assert all(rule in result.stdout for rule in expected)
    assert all(rule not in result.stdout for rule in _ALL_RULES if rule not in expected)
