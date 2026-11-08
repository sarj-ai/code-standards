from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.adoption import transaction, typescript_migration, typescript_tooling


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
    files = transaction.FileTransaction.capture(root, (root / "src/a.ts", root / "biome.json"), explicit_only=True)

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
    files = transaction.FileTransaction.capture(root, (), explicit_only=True)

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
    assert "printWidth" not in contents
    assert "dist/**" in contents
    assert "packages/web/generated/**" in contents


def test_real_oxfmt_roundtrip_is_idempotent(tmp_path: Path) -> None:
    root = _repository(tmp_path, {".oxfmtrc.json": '{"ignorePatterns": ["dist/**"], "printWidth": 120}'})
    _with_tools(root)
    seeding = typescript_tooling.plan_oxfmt_config(root)
    files = transaction.FileTransaction.capture(root, (), explicit_only=True)
    for path, text in seeding.writes:
        files.track(path)
        files.write_text(path, text)
    for path in seeding.deletes:
        files.track(path)
        files.remove_file(path)
    typescript_tooling.finish(root, root, files, written=tuple(path for path, _ in seeding.writes))
    assert not typescript_tooling.plan_oxfmt_config(root).writes
