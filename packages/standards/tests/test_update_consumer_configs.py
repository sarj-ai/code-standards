from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.cli.main import main
from sarj_standards.libs.adoption import doctor, manifest, upgrade


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("version", ["0.0.1", manifest.adopted_version()], ids=("upgrade", "repair-current"))
def test_one_update_refreshes_both_linter_configs_without_overwriting_consumer_settings(
    tmp_path: Path, version: str
) -> None:
    python = tmp_path / "python"
    web = tmp_path / "web"
    python.mkdir()
    web.mkdir()
    pyproject = python / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "example"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n'
        '[dependency-groups]\ndev = ["ruff>=0.16.0,<0.16.1"]\n'
        '[tool.ruff]\nextend = ".ruff-strict.toml"\n'
        '[tool.ruff.lint]\nextend-ignore = ["D"]\n'
    )
    (python / ".ruff-strict.toml").write_text('[lint]\nselect = ["F"]\n')
    (web / "package.json").write_text(
        json.dumps(
            {
                "name": "example-web",
                "private": True,
                "devDependencies": {"eslint": "1.0.0", "@sarj/eslint-plugin": "0.0.1"},
            }
        )
    )
    (web / "eslint.strict.mjs").write_text("export default [];\n")
    wrapper = web / "eslint.config.mjs"
    consumer_config = (
        'import strict from "./eslint.strict.mjs";\n'
        'export default [...strict, { name: "consumer-local", rules: { "no-console": "off" } }];\n'
    )
    wrapper.write_text(consumer_config)
    adopted = manifest.Manifest(version, ("ruff", "eslint"), "python", "web", hook_manager="none")
    adoption = tmp_path / manifest.MANIFEST_NAME
    adoption.write_text(adopted.render() + '\n[consumer]\nsetting = "preserved"\n')
    argv = ["--root", str(tmp_path), "update", "--offline", "--no-install"]

    assert main(argv) == 0
    assert (  # sarj-noqa: SARJ402 -- managed config copies must byte-match the shipped bundle.
        (python / ".ruff-strict.toml").read_bytes() == (CONFIGS_DIR / "ruff.strict.toml").read_bytes()
    )
    assert (  # sarj-noqa: SARJ402 -- managed config copies must byte-match the shipped bundle.
        (web / "eslint.strict.mjs").read_bytes() == (CONFIGS_DIR / "eslint.strict.mjs").read_bytes()
    )
    assert wrapper.read_text() == consumer_config
    assert 'extend-ignore = ["D"]' in pyproject.read_text()
    assert 'setting = "preserved"' in adoption.read_text()
    assert f'bundle = "{manifest.adopted_version()}"' in adoption.read_text()
    assert f"ruff=={manifest.installed_versions()['ruff']}" in pyproject.read_text()
    assert "<0.16.1" not in pyproject.read_text()
    assert '"0.0.1"' not in (web / "package.json").read_text()
    assert f'"eslint": "{manifest.eslint_peers()["eslint"]}"' in (web / "package.json").read_text()
    snapshot = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    assert main(argv) == 0
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == snapshot


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ('"ruff>=0.16.0,<0.16.1"', '"ruff==0.16.5"'),
        ('"ruff==0.15.*"', '"ruff==0.16.5"'),
        ("ruff == 0.16.0 ; python_version >= '3.14'", "ruff==0.16.5 ; python_version >= '3.14'"),
        ("ruff==0.16.5,<0.17", "ruff==0.16.5,<0.17"),
        ("ruff==0.16.5", "ruff==0.16.5"),
        ("ruff>=0.16.5", "ruff>=0.16.5"),
        ("ruff>=0.16.0, !=0.16.2, <0.16.3 # retained", "ruff==0.16.5 # retained"),
        ("ruff-helper==0.16.0", "ruff-helper==0.16.0"),
        ("custom-ruff==0.16.0", "custom-ruff==0.16.0"),
    ],
    ids=(
        "range",
        "wildcard",
        "marker",
        "compound-exact",
        "current",
        "compatible-minimum",
        "exclusion",
        "suffix-package",
        "prefix-package",
    ),
)
def test_ruff_pin_rewrite_preserves_markers_and_unrelated_packages(original: str, expected: str) -> None:
    versions = {"ruff": "0.16.5"}

    assert doctor.rewrite_version_pins(original, versions).contents == expected
    assert doctor.rewrite_version_pins(expected, versions).contents == expected


def test_updating_a_native_ruff_pin_schedules_the_consumer_lock_refresh(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n'
        '[dependency-groups]\ndev = ["ruff>=0.16.0,<0.16.1"]\n'
        '[tool.ruff]\nextend = ".ruff-strict.toml"\n'
    )
    lockfile = tmp_path / "uv.lock"
    lockfile.write_text("version = 1\n")
    (tmp_path / manifest.MANIFEST_NAME).write_text(
        manifest.Manifest("0.0.1", ("ruff",), ".", ".", hook_manager="none").render()
    )

    plan = upgrade.build_plan(tmp_path)

    assert plan.lockfiles == (lockfile,)
    assert any(change.reason == "refresh Python lockfile" for change in plan.changes)
