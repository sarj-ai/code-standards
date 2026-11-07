from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import doctor, manifest


if TYPE_CHECKING:
    from pathlib import Path


_ENTRYPOINT = 'import { createConfig } from "./oxlint.strict.mts";\n\nexport default { extends: [createConfig()] };\n'
_OXFMT = 'import { createConfig } from "./oxfmt.strict.mts";\n\nexport default createConfig({});\n'


def _adopt(root: Path, *, scripts: dict[str, str] | None = None) -> None:
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=("typescript",),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
    )
    (root / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    package = {"name": "fixture", "devDependencies": manifest.typescript_peers(), "scripts": scripts or {}}
    (root / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (root / "oxlint.config.mts").write_text(_ENTRYPOINT, encoding="utf-8")
    (root / "oxlint.strict.mts").write_text("export function createConfig() {}\n", encoding="utf-8")
    (root / "oxfmt.config.mts").write_text(_OXFMT, encoding="utf-8")


def _findings(root: Path, finding_id: str) -> list[tuple[doctor.Level, str]]:
    return [
        (finding.level, finding.where) for finding in doctor.diagnose_adoption_health(root) if finding.id == finding_id
    ]


def test_an_entrypoint_extending_the_managed_preset_is_wired(tmp_path: Path) -> None:
    _adopt(tmp_path)

    assert _findings(tmp_path, "doctor.typescript.wiring") == [(doctor.Level.OK, "oxlint.config.mts")]
    assert not _findings(tmp_path, "doctor.typescript.peer")
    assert _findings(tmp_path, "doctor.typescript.oxfmt-config") == [(doctor.Level.OK, "oxfmt.config.mts")]


@pytest.mark.parametrize(
    ("name", "contents", "finding_id", "where"),
    [
        pytest.param(
            "oxlint.config.mts", "export default {};\n", "doctor.typescript.wiring", "oxlint.config.mts", id="unwired"
        ),
        pytest.param(".oxlintrc.json", "{}\n", "doctor.typescript.ambiguous-config", ".", id="ambiguous"),
        pytest.param(
            "eslint.config.mts",
            "export default [];\n",
            "doctor.typescript.legacy-eslint-config",
            "eslint.config.mts",
            id="kept-eslint-config",
        ),
    ],
)
def test_root_lint_config_drift(tmp_path: Path, name: str, contents: str, finding_id: str, where: str) -> None:
    _adopt(tmp_path)
    (tmp_path / name).write_text(contents, encoding="utf-8")

    assert _findings(tmp_path, finding_id) == [(doctor.Level.DRIFT, where)]


def test_a_nested_config_outside_the_preset_shadows_the_policy(tmp_path: Path) -> None:
    _adopt(tmp_path)
    wired = tmp_path / "packages" / "wired"
    wired.mkdir(parents=True)
    (wired / "oxlint.config.mts").write_text(
        'import { createConfig } from "../../oxlint.strict.mts";\nexport default createConfig();\n', encoding="utf-8"
    )
    shadow = tmp_path / "packages" / "shadow"
    shadow.mkdir()
    (shadow / ".oxlintrc.json").write_text("{}\n", encoding="utf-8")

    findings = [
        finding
        for finding in doctor.diagnose_adoption_health(tmp_path)
        if finding.id == "doctor.typescript.shadowed-config"
    ]

    assert len(findings) == 1
    assert "packages/shadow/.oxlintrc.json" in findings[0].detail
    assert "packages/wired" not in findings[0].detail


def test_a_missing_oxfmt_config_is_install_remediable_drift(tmp_path: Path) -> None:
    _adopt(tmp_path)
    (tmp_path / "oxfmt.config.mts").unlink()

    assert _findings(tmp_path, "doctor.typescript.oxfmt-config") == [(doctor.Level.DRIFT, "oxfmt.config.mts")]


def test_an_unpinned_peer_is_drift(tmp_path: Path) -> None:
    _adopt(tmp_path)
    peers = {**manifest.typescript_peers(), "oxlint": "^1.0.0"}
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": peers}), encoding="utf-8")

    assert _findings(tmp_path, "doctor.typescript.peer") == [(doctor.Level.DRIFT, "package.json: oxlint")]


@pytest.mark.parametrize(
    ("yarnrc", "reported"),
    [
        pytest.param("enableScripts: false\n", True, id="default-pnp"),
        pytest.param("nodeLinker: pnp\n", True, id="explicit-pnp"),
        pytest.param("nodeLinker: node-modules\n", False, id="node-modules"),
    ],
)
def test_yarn_plug_n_play_is_rejected(tmp_path: Path, yarnrc: str, *, reported: bool) -> None:
    _adopt(tmp_path)
    package = {"packageManager": "yarn@4.18.1", "devDependencies": manifest.typescript_peers()}
    (tmp_path / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (tmp_path / ".yarnrc.yml").write_text(yarnrc, encoding="utf-8")

    expected = [(doctor.Level.DRIFT, ".yarnrc.yml")] if reported else []
    assert _findings(tmp_path, "doctor.typescript.node-linker") == expected


@pytest.mark.parametrize("command", ["oxlint --deny-warnings", "oxlint . --max-warnings 0", "oxlint --max-warnings=0"])
def test_failing_oxlint_on_warnings_is_drift(tmp_path: Path, command: str) -> None:
    _adopt(tmp_path, scripts={"lint": command})

    assert _findings(tmp_path, "doctor.typescript.warning-exit") == [(doctor.Level.DRIFT, "package.json: scripts.lint")]


def test_warning_budgets_of_other_tools_are_not_oxlint_policy(tmp_path: Path) -> None:
    _adopt(tmp_path, scripts={"lint": "oxlint", "other": "echo oxlint-config && eslint --max-warnings 0"})

    assert not _findings(tmp_path, "doctor.typescript.warning-exit")


@pytest.mark.parametrize(
    ("name", "command", "reported"),
    [
        pytest.param("typecheck", "tsc --noEmit", True, id="tsc-no-emit"),
        pytest.param("verify", "tsc -p tsconfig.app.json --noEmit", True, id="no-emit-flag"),
        pytest.param(
            "check:tooling", "node node_modules/@typescript/native/bin/tsc --project x.json", True, id="native"
        ),
        pytest.param("types", "tsc6 -p .", True, id="tsc6"),
        pytest.param("build", "tsc -b", False, id="build"),
        pytest.param("typecheck", "tsrs --noEmit", False, id="tsrs"),
        pytest.param("typecheck", "vue-tsc --noEmit", False, id="framework-checker"),
        pytest.param("check", "astro check", False, id="astro"),
        pytest.param("versions", "tsc --version", False, id="version"),
    ],
)
def test_remaining_tsc_type_checks_are_reported(tmp_path: Path, name: str, command: str, *, reported: bool) -> None:
    _adopt(tmp_path, scripts={name: command})

    expected = [(doctor.Level.WARN, f"package.json: scripts.{name}")] if reported else []
    assert _findings(tmp_path, "doctor.typescript.tsc") == expected


@pytest.mark.parametrize(
    ("config", "reported"),
    [
        pytest.param("export default {};\n", True, id="default"),
        pytest.param("export default { typescript: { ignoreBuildErrors: true } };\n", False, id="ignored"),
    ],
)
def test_next_builds_that_rerun_the_type_check_are_reported(tmp_path: Path, config: str, *, reported: bool) -> None:
    _adopt(tmp_path)
    app = tmp_path / "apps" / "web"
    app.mkdir(parents=True)
    (app / "next.config.mjs").write_text(config, encoding="utf-8")

    expected = [(doctor.Level.WARN, "apps/web/next.config.mjs")] if reported else []
    assert _findings(tmp_path, "doctor.typescript.tsc") == expected


def test_tsconfig_options_typescript_7_rejects_are_drift(tmp_path: Path) -> None:
    _adopt(tmp_path)
    (tmp_path / "tsconfig.json").write_text(
        "{\n  // JSONC comments and trailing commas are valid tsconfig syntax.\n"
        '  "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]},},\n'
        '  "references": [{"path": "./packages/catalog"}],\n}\n',
        encoding="utf-8",
    )
    catalog = tmp_path / "packages" / "catalog"
    catalog.mkdir(parents=True)
    (catalog / "tsconfig.json").write_text(
        '{"compilerOptions": {"allowImportingTsExtensions": true}, "include": ["src"]}\n', encoding="utf-8"
    )

    findings = [
        (finding.level, finding.where, finding.detail.split(";")[0])
        for finding in doctor.diagnose_adoption_health(tmp_path)
        if finding.id == "doctor.typescript.tsconfig"
    ]

    assert findings == [
        (
            doctor.Level.DRIFT,
            "packages/catalog/tsconfig.json",
            "`allowImportingTsExtensions` requires `noEmit` or `emitDeclarationOnly`",
        ),
        (doctor.Level.DRIFT, "tsconfig.json", "TypeScript 7 removed `baseUrl`"),
    ]


def test_inherited_no_emit_satisfies_ts_extension_imports(tmp_path: Path) -> None:
    _adopt(tmp_path)
    (tmp_path / "tsconfig.base.json").write_text(
        '{"compilerOptions": {"noEmit": true, "allowImportingTsExtensions": true}}\n', encoding="utf-8"
    )
    (tmp_path / "tsconfig.json").write_text(
        '{"extends": "./tsconfig.base.json", "include": ["src"]}\n', encoding="utf-8"
    )

    assert not _findings(tmp_path, "doctor.typescript.tsconfig")


def test_a_project_no_tsconfig_json_references_is_reported(tmp_path: Path) -> None:
    _adopt(tmp_path)
    (tmp_path / "tsconfig.json").write_text(
        '{"files": [], "references": [{"path": "./tsconfig.app.json"}]}\n', encoding="utf-8"
    )
    (tmp_path / "tsconfig.app.json").write_text('{"include": ["src"]}\n', encoding="utf-8")
    (tmp_path / "tsconfig.tooling.json").write_text('{"include": ["scripts"]}\n', encoding="utf-8")
    # A build variant covers files tsconfig.json already has; `update` leaves it unreferenced too.
    (tmp_path / "tsconfig.build.json").write_text(
        '{"extends": "./tsconfig.json", "include": ["src"]}\n', encoding="utf-8"
    )

    assert _findings(tmp_path, "doctor.typescript.tsconfig") == [(doctor.Level.WARN, "tsconfig.tooling.json")]


def test_the_reference_fix_names_what_tsc_requires_of_a_referenced_project(tmp_path: Path) -> None:
    _adopt(tmp_path)
    (tmp_path / "tsconfig.json").write_text('{"include": ["src"]}\n', encoding="utf-8")
    (tmp_path / "tsconfig.tooling.json").write_text('{"include": ["scripts"]}\n', encoding="utf-8")

    (finding,) = (item for item in doctor.diagnose_adoption_health(tmp_path) if item.id == "doctor.typescript.tsconfig")

    assert "`composite: true`" in (finding.remediation or "")


@pytest.mark.parametrize(
    ("pnpm", "workspace", "reported"),
    [
        pytest.param("11.24.0", "minimumReleaseAge: 20160\n", True, id="age-gate"),
        pytest.param("12.15.0", "trustPolicy: no-downgrade\n", True, id="trust-policy"),
        pytest.param("12.15.0", "minimumReleaseAge: 20160\ntrustLockfile: true\n", False, id="trusted-lockfile"),
        pytest.param("12.15.0", "packages:\n  - apps/*\n", False, id="no-gates"),
        pytest.param("10.33.0", "minimumReleaseAge: 20160\n", False, id="pnpm-10"),
    ],
)
def test_pnpm_gates_without_a_trusted_lockfile_warn_about_frozen_installs(
    tmp_path: Path, pnpm: str, workspace: str, *, reported: bool
) -> None:
    _adopt(tmp_path)
    package = {"packageManager": f"pnpm@{pnpm}", "devDependencies": manifest.typescript_peers()}
    (tmp_path / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (tmp_path / "pnpm-workspace.yaml").write_text(workspace, encoding="utf-8")

    expected = [(doctor.Level.WARN, "pnpm-workspace.yaml")] if reported else []
    assert _findings(tmp_path, "doctor.typescript.pnpm-trust-lockfile") == expected
