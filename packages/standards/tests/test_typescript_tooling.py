from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards._meta import CONFIGS_DIR
import sarj_standards.cli.main as cli
from sarj_standards.libs.adoption import doctor, transaction, typescript_migration, typescript_tooling, upgrade
from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting import autofix, oxfmt


if TYPE_CHECKING:
    from pydantic import JsonValue


_MODULES = Path(__file__).resolve().parents[2] / "typescript" / "node_modules"
_BIOME = """{
  "$schema": "https://biomejs.dev/schemas/2.6.3/schema.json",
  "files": { "includes": ["**/*.ts"] },
  "formatter": {
    "enabled": true,
    "indentStyle": "space",
    "lineWidth": 100
  },
  "javascript": { "formatter": { "quoteStyle": "single" } }
}
"""


def _repository(root: Path, files: dict[str, str]) -> Path:
    for name, text in {"package.json": '{ "name": "consumer", "private": true }\n', **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _with_tools(root: Path) -> None:
    if shutil.which("node") is None or not (_MODULES / ".bin" / "oxfmt").is_file():
        pytest.skip("requires the repository's locked oxfmt")
    (root / "node_modules").symlink_to(_MODULES, target_is_directory=True)
    (root / "oxfmt.strict.mts").write_bytes((CONFIGS_DIR / "oxfmt.strict.mts").read_bytes())


def test_seeding_without_a_formatter_to_migrate_needs_no_tools(tmp_path: Path) -> None:
    root = _repository(tmp_path, {})

    seeding = typescript_tooling.plan_oxfmt_config(root)

    [(path, contents)] = seeding.writes
    assert path == root / "oxfmt.config.mts"
    assert 'from "./oxfmt.strict.mts"' in contents
    assert not seeding.deletes
    assert not seeding.errors


def test_seeding_from_an_oxfmtrc_replaces_it(tmp_path: Path) -> None:
    root = _repository(tmp_path, {".oxfmtrc.json": '{ "$schema": "x", "printWidth": 90 }\n'})

    seeding = typescript_tooling.plan_oxfmt_config(root)

    [(_path, contents)] = seeding.writes
    assert "printWidth" not in contents
    assert seeding.deletes == (root / ".oxfmtrc.json",)


def test_seeding_from_prettier_waits_for_the_installed_oxfmt(tmp_path: Path) -> None:
    root = _repository(tmp_path, {".prettierrc.json": '{ "singleQuote": true }\n'})

    seeding = typescript_tooling.plan_oxfmt_config(root)

    assert seeding.writes
    assert seeding.deletes == (root / ".prettierrc.json",)
    assert not (root / ".oxfmtrc.json").exists()


def test_an_existing_config_is_never_seeded_again(tmp_path: Path) -> None:
    root = _repository(tmp_path, {"oxfmt.config.mts": "export default {};\n"})

    assert typescript_tooling.plan_oxfmt_config(root).errors


def test_finish_seeds_from_biome_disables_its_formatter_and_formats_once(tmp_path: Path) -> None:
    root = _repository(tmp_path, {"biome.json": _BIOME, "src/a.ts": 'export const a = "x"\n'})
    _with_tools(root)
    files = transaction.FileTransaction.capture(
        root, (root / "src/a.ts", root / "biome.json"), mode=transaction.CaptureMode.EXPLICIT
    )

    notes = typescript_tooling.finish(root, root, files, written=())

    config = (root / "oxfmt.config.mts").read_text(encoding="utf-8")
    assert "Shared Standards style" in config
    biome = (root / "biome.json").read_text(encoding="utf-8")
    assert biome == _BIOME
    assert (root / "src/a.ts").read_text(encoding="utf-8") == 'export const a = "x";\n'
    assert any(note.startswith("oxfmt formatted 1 file(s) once") for note in notes)
    assert files.rollback().ok
    assert (root / "src/a.ts").read_text(encoding="utf-8") == 'export const a = "x"\n'
    assert (root / "biome.json").read_text(encoding="utf-8") == _BIOME
    assert not (root / "oxfmt.config.mts").exists()


def test_finish_formats_a_scaffolded_entrypoint_without_reformatting_the_repository(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "oxfmt.config.mts": 'import { createConfig } from "./oxfmt.strict.mts";\n'
            "export default createConfig({});\n",
            "src/a.ts": "export const a = 1\n",
        },
    )
    _with_tools(root)
    entrypoint = root / "oxlint.config.mts"
    entrypoint.write_text(typescript_migration.render_entrypoint(), encoding="utf-8")
    files = transaction.FileTransaction.capture(root, (), mode=transaction.CaptureMode.EXPLICIT)

    assert typescript_tooling.finish(root, root, files, written=(entrypoint,)) == ()

    assert entrypoint.read_text(encoding="utf-8") != typescript_migration.render_entrypoint()
    assert "ignorePatterns: [...ignorePatterns]" in entrypoint.read_text(encoding="utf-8")
    assert (root / "src/a.ts").read_text(encoding="utf-8") == "export const a = 1\n"


def test_existing_generated_config_collects_nested_ignores_and_filters_other_roots(tmp_path: Path) -> None:
    root = _repository(
        tmp_path / "app",
        {
            "oxfmt.config.mts": 'import { createConfig } from "./oxfmt.strict.mts";\nexport default createConfig({printWidth: 120, ignorePatterns: ["dist/**",],});\n',
            "packages/web/.prettierignore": "generated/**\n",
        },
    )
    outside = tmp_path / "biome.json"
    outside.write_text("{}", encoding="utf-8")
    nested = root / "packages/web/.prettierignore"
    seeding = typescript_tooling.plan_oxfmt_config(root, (nested, outside))
    assert not seeding.errors
    assert seeding.deletes == (nested,)
    [(_, contents)] = seeding.writes
    assert "printWidth" in contents
    assert "dist/**" in contents
    assert "packages/web/generated/**" in contents


def test_real_oxfmt_roundtrip_is_idempotent(tmp_path: Path) -> None:
    root = _repository(tmp_path, {".oxfmtrc.json": '{"ignorePatterns": ["dist/**"], "printWidth": 120}'})
    _with_tools(root)
    seeding = typescript_tooling.plan_oxfmt_config(root)
    files = transaction.FileTransaction.capture(root, (), mode=transaction.CaptureMode.EXPLICIT)
    for path, text in seeding.writes:
        files.track(path)
        files.write_text(path, text)
    for path in seeding.deletes:
        files.track(path)
        files.remove_file(path)
    typescript_tooling.finish(root, root, files, written=tuple(path for path, _ in seeding.writes))
    assert not typescript_tooling.plan_oxfmt_config(root).writes


def test_update_keeps_required_astro_activation(tmp_path: Path) -> None:
    root = _repository(
        tmp_path,
        {
            "oxfmt.config.mts": 'import { createConfig } from "./oxfmt.strict.mts";\nexport default createConfig({astro: true});\n',
            "package.json": '{"devDependencies":{"@astrojs/compiler-rs":"0.5.2"}}',
        },
    )

    seeding = typescript_tooling.plan_oxfmt_config(root)

    assert not seeding.errors
    assert not seeding.writes
    assert not seeding.deletes


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("staged", [False, True])
def test_astro_adoption_update_and_explicit_staged_formatting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *, legacy: bool, staged: bool
) -> None:
    if not (_MODULES / "@astrojs/compiler-rs/package.json").is_file():
        pytest.skip("requires @astrojs/compiler-rs 0.5.2 alongside the pinned oxfmt")
    config = (
        {".oxfmtrc.json": '{"astro":true,"printWidth":120}\n'}
        if legacy
        else {
            "oxfmt.config.mts": 'import { createConfig } from "./oxfmt.strict.mts";\nexport default createConfig({astro: true});\n'
        }
    )
    root = _repository(
        tmp_path,
        {
            **config,
            "package.json": '{"name":"consumer","private":true,"devDependencies":{"@astrojs/compiler-rs":"0.5.2"}}\n',
            "tsconfig.json": '{"compilerOptions":{"strict":true},"include":["*.ts"]}\n',
            "source.ts": "export const value = 1;\n",
            "view.astro": '<div><span class="hello">world</span></div>\n',
        },
    )
    _with_tools(root)
    assert cli.main(["--root", str(root), "setup", "--no-install"]) == 0
    package = parse_json((root / "package.json").read_text())
    assert isinstance(package, dict)
    dependencies = package["devDependencies"]
    assert isinstance(dependencies, dict)
    assert dependencies["@astrojs/compiler-rs"] == "0.5.2"
    assert oxfmt.seed_config(root).options["astro"] is True
    plan = upgrade.build_plan(root)
    assert not any(path.name == "oxfmt.config.mts" for path, _ in plan.scaffold_plan.edits)
    assert not typescript_tooling.plan_oxfmt_config(root).writes
    # Exercise the unpublished candidate, rather than resolving the registry updater.
    monkeypatch.setenv("SARJ_STANDARDS_BOOTSTRAPPED", "1")
    assert capsys.readouterr().out
    before = (root / "oxfmt.config.mts").read_bytes()
    assert cli.main(["--root", str(root), "update", "--check", "--no-install"]) in {0, 1}
    assert "oxfmt.config.mts" not in capsys.readouterr().out
    assert (root / "oxfmt.config.mts").read_bytes() == before

    (root / "view.astro").write_text('<div><span class="hello">world</span></div>\n')
    selected = ["view.astro"]
    report = oxfmt.analyze(selected, project=root, root=root)
    assert report.completion is Completion.COMPLETE
    assert [finding.location.path for finding in report.diagnostics] == selected
    if staged:
        subprocess.run(("git", "init", "--quiet", "--template="), cwd=root, check=True)
        subprocess.run(("git", "add", "view.astro"), cwd=root, check=True)
        assert cli.main(["--root", str(root), "check", "--staged", "--fix", "--trust-repository-code"]) == 1
        assert "Safe fixes applied" in capsys.readouterr().err
        subprocess.run(("git", "add", "view.astro"), cwd=root, check=True)
        assert cli.main(["--root", str(root), "check", "--staged", "--trust-repository-code"]) == 0
    else:
        assert autofix.run(root, tuple(selected), trusted=True).status == 0
    assert not oxfmt.analyze(selected, project=root, root=root).diagnostics
    assert (root / "view.astro").read_text() != '<div><span class="hello">world</span></div>\n'


_CONVERGENCE = Path(__file__).parent / "fixtures" / "formatter-convergence"


@pytest.mark.parametrize(
    "fixture",
    sorted(_CONVERGENCE.glob("*.mts.txt")),
    ids=[path.name.removesuffix(".mts.txt") for path in sorted(_CONVERGENCE.glob("*.mts.txt"))],
)
def test_adopted_formatter_options_survive_planning(tmp_path: Path, fixture: Path) -> None:
    original = fixture.read_text(encoding="utf-8")
    root = _repository(tmp_path, {"oxfmt.config.mts": original})

    plan = typescript_tooling.plan_oxfmt_config(root)

    if fixture.name == "computed-options.mts.txt":
        assert plan.errors
        return
    assert not plan.errors
    assert not plan.writes
    assert not plan.deletes
    assert (root / "oxfmt.config.mts").read_text(encoding="utf-8") == original


def test_literal_comments_do_not_change_string_tokens(tmp_path: Path) -> None:
    options = r"""{
      // comment before a key
      ignorePatterns: ["https://example.com/a/*b*/", "route\\[id\\]/**", /* trailing */],
      astro: /* parser */ true,
      overrides: [{files: ['src/a.ts'], options: {sortImports: false,},},],
    }"""
    root = _repository(
        tmp_path,
        {
            "oxfmt.config.mts": 'import { createConfig } from "./oxfmt.strict.mts";\n'
            f"export default createConfig({options});\n"
        },
    )

    assert not typescript_tooling.plan_oxfmt_config(root).errors
    seed = oxfmt.seed_config(root)
    assert seed.options["ignorePatterns"] == ["https://example.com/a/*b*/", r"route\[id\]/**"]
    assert seed.options["astro"] is True
    assert seed.options["overrides"] == [{"files": ["src/a.ts"], "options": {"sortImports": False}}]


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
@pytest.mark.parametrize("position", ["options", "prefix"])
def test_line_comments_cannot_hide_computation(tmp_path: Path, separator: str, position: str) -> None:
    options = f'{{ // reviewed{separator} astro: enable(),\n extensions: ["ts"] }}'
    prefix = ""
    if position == "prefix":
        options = "{}"
        prefix = f"// reviewed{separator}enable();\n"
    root = _repository(
        tmp_path,
        {
            "oxfmt.config.mts": 'import { createConfig } from "./oxfmt.strict.mts";\n'
            f"{prefix}export default createConfig({options});\n"
        },
    )

    assert typescript_tooling.plan_oxfmt_config(root).errors


@pytest.mark.parametrize("options", ["{...process.env}", "{astro: enable()}", "{overrides: exceptions}"])
def test_planning_rejects_computed_managed_options(tmp_path: Path, options: str) -> None:
    root = _repository(
        tmp_path,
        {
            "oxfmt.config.mts": 'import { createConfig } from "./oxfmt.strict.mts";\n'
            f"export default createConfig({options});\n"
        },
    )

    assert typescript_tooling.plan_oxfmt_config(root).errors


def test_first_adoption_still_refuses_legacy_overrides(tmp_path: Path) -> None:
    root = _repository(
        tmp_path, {".oxfmtrc.json": '{"overrides":[{"files":["src/a.ts"],"options":{"singleQuote":true}}]}'}
    )

    assert typescript_tooling.plan_oxfmt_config(root).errors


@pytest.mark.parametrize(
    "name",
    [
        "mobile-coverage",
        "dashboard-exceptions",
        "parser-exceptions",
        "tailwind-exceptions",
        "web-exceptions",
        "raw-exceptions",
    ],
)
def test_existing_formatter_setup_and_update_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    original = (_CONVERGENCE / f"{name}.mts.txt").read_bytes()
    root = _repository(
        tmp_path,
        {
            "oxfmt.config.mts": original.decode(),
            "tsconfig.json": '{"compilerOptions":{"strict":true},"include":["*.ts"]}\n',
            "source.ts": "export const value = 1;\n",
        },
    )
    _with_tools(root)
    monkeypatch.setenv("SARJ_STANDARDS_BOOTSTRAPPED", "1")

    for _ in range(2):
        assert cli.main(["--root", str(root), "setup", "--no-install"]) == 0
        setup_output = capsys.readouterr()
        assert "eslint <=9.7" not in setup_output.out + setup_output.err
        assert '"overrides": {}' not in setup_output.out + setup_output.err
        assert (root / "oxfmt.config.mts").read_bytes() == original
        plan = upgrade.build_plan(root)
        assert not plan.scaffold_plan.errors
        assert not any(path.name == "oxfmt.config.mts" for path, _ in plan.scaffold_plan.edits)
        capsys.readouterr()
        assert cli.main(["--root", str(root), "update", "--check", "--no-install"]) in {0, 1}
        assert "oxfmt.config.mts" not in capsys.readouterr().out
        assert cli.main(["--root", str(root), "update", "--offline", "--no-install"]) == 0
        assert (root / "oxfmt.config.mts").read_bytes() == original
    findings = [
        finding for finding in doctor.diagnose_adoption_health(root) if finding.id == "doctor.typescript.oxfmt-config"
    ]
    assert findings
    assert all(finding.level is doctor.Level.OK for finding in findings)
    cli.main(["--root", str(root), "doctor"])
    output = capsys.readouterr()
    assert "handcrafted" not in output.out + output.err
    assert "eslint <=9.7" not in output.out + output.err


def test_existing_exceptions_keep_import_order_raw_text_and_shared_style(tmp_path: Path) -> None:
    options: dict[str, JsonValue] = {
        "overrides": [
            {
                "files": ["preserved.ts"],
                "options": {
                    "sortImports": False,
                    "embeddedLanguageFormatting": "off",
                },
            }
        ],
    }
    source = (
        'import z from "z";\nimport a from "a";\nexport const raw = css`a{color: red}`;\nexport const values=[z,a];\n'
    )
    root = _repository(
        tmp_path,
        {
            "oxfmt.config.mts": oxfmt.render_config(oxfmt.OxfmtSeed(None, options)),
            "preserved.ts": source,
            "ordinary.ts": source,
        },
    )
    _with_tools(root)
    assert not typescript_tooling.plan_oxfmt_config(root).writes
    command = oxfmt.write_command(["preserved.ts", "ordinary.ts"], project=root, root=root)
    subprocess.run(command.argv, cwd=command.cwd, check=True, capture_output=True)
    preserved = (root / "preserved.ts").read_text()
    ordinary = (root / "ordinary.ts").read_text()
    assert preserved.index('from "z"') < preserved.index('from "a"')
    assert ordinary.index('from "a"') < ordinary.index('from "z"')
    assert "css`a{color: red}`" in preserved
    assert "css`a{color: red}`" not in ordinary
    assert "values = [z, a];" in preserved


def test_supported_alias_source_survives_setup_and_offline_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        "// eslint-disable-next-line @typescript-eslint/no-deprecated -- legacy API boundary\n"
        "export const value = legacy();\n"
        "// eslint-disable-next-line @typescript-eslint/no-unnecessary-type-parameters -- public signature\n"
        "export function identity<T extends string>(value: T): T { return value; }\n"
        "// eslint-disable-next-line @typescript-eslint/no-unnecessary-condition -- known runtime boundary\n"
        "export const optional = value?.length;\n"
        "declare function consume(callback: () => void): void;\n"
        "// eslint-disable-next-line @typescript-eslint/strict-void-return -- ignored callback result\n"
        "consume(() => null);\n"
        "// eslint-disable-next-line @typescript-eslint/consistent-type-assertions -- assertion boundary\n"
        'export const asserted = "control" as string;\n'
        "// eslint-disable-next-line @typescript-eslint/no-unsafe-type-assertion -- validated boundary\n"
        "export function unsafe(value: unknown) { return value as string; }\n"
        "// eslint-disable-next-line @typescript-eslint/no-misused-spread -- intentional characters\n"
        'export const characters = [..."control"];\n'
    )
    root = _repository(
        tmp_path,
        {"source.ts": source, "tsconfig.json": '{"compilerOptions":{"strict":true},"include":["*.ts"]}\n'},
    )
    _with_tools(root)
    monkeypatch.setenv("SARJ_STANDARDS_BOOTSTRAPPED", "1")
    for _ in range(2):
        assert cli.main(["--root", str(root), "setup", "--no-install"]) == 0
        assert (root / "source.ts").read_text() == source
        assert cli.main(["--root", str(root), "update", "--offline", "--no-install"]) == 0
        assert (root / "source.ts").read_text() == source


def test_generated_source_file_exclusion_survives_setup_and_offline_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = b"/* eslint-disable react-hooks/exhaustive-deps */\r\nexport const Stepper = () => null;\r\n"
    root = _repository(
        tmp_path,
        {
            "src/components/ui/stepper.tsx": source.decode(),
            "src/hooks/generated.ts": source.decode(),
            "oxlint.config.mts": typescript_migration.render_entrypoint().replace(
                "...ignorePatterns,", '...ignorePatterns, "src/components/ui/**", "src/hooks/**",'
            ),
            "oxfmt.config.mts": oxfmt.render_config(
                oxfmt.OxfmtSeed(None, {"ignorePatterns": ["src/components/ui/**", "src/hooks/**"]})
            ),
            "src/authored.tsx": source.decode(),
            "tsconfig.json": '{"compilerOptions":{"jsx":"react-jsx"},"include":["src"]}\n',
        },
    )
    _with_tools(root)
    monkeypatch.setenv("SARJ_STANDARDS_BOOTSTRAPPED", "1")
    # Use the supported file-level adoption exclusion; directory exclusions also
    # exclude security discovery and are deliberately not used here.
    assert cli.main(["--root", str(root), "setup", "--no-install"]) == 0
    config = root / ".sarj-standards.toml"
    config.write_text(
        config.read_text() + '\n[doctor]\nexclude = ["src/components/ui/stepper.tsx", "src/hooks/generated.ts"]\n'
    )
    generated = root / "src/components/ui/stepper.tsx"
    generated.write_bytes(source)
    hook = root / "src/hooks/generated.ts"
    hook.write_bytes(source)
    for _ in range(2):
        (root / "src/authored.tsx").write_bytes(source)
        migration = typescript_migration.plan(root, root, doctor.authored_files(root))
        assert generated not in dict(migration.writes)
        assert "react-hooks/exhaustive-deps" not in dict(migration.writes)[root / "src/authored.tsx"]
        assert cli.main(["--root", str(root), "setup", "--no-install"]) == 0
        assert generated.read_bytes() == source
        assert hook.read_bytes() == source
        assert "react-hooks/exhaustive-deps" not in (root / "src/authored.tsx").read_text()
        assert cli.main(["--root", str(root), "update", "--offline", "--no-install"]) == 0
        assert generated.read_bytes() == source
        assert hook.read_bytes() == source
        assert cli.main(["--root", str(root), "update", "--offline", "--check", "--no-install"]) == 0
