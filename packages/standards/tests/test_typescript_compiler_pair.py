from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import doctor, manifest, service, upgrade
from sarj_standards.libs.json_boundary import parse_json


if TYPE_CHECKING:
    from pathlib import Path


# tsrs does all type checking (DECISIONS #16); `typescript` stays only for the JS API a plugin imports.
TYPE_CHECKER = {
    "tsrs": "0.22.0-ts7.1.0-beta",
    "typescript": "npm:@typescript/typescript6@6.0.2",
}


@pytest.fixture
def compiler_repository(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "compiler-consumer",
                "private": True,
                "scripts": {"typecheck": "tsc --noEmit", "build": "tsc -p tsconfig.build.json"},
                "devDependencies": {"typescript": "6.0.3", "unrelated": "1.0.0"},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_the_peer_set_pins_tsrs_and_no_native_compiler() -> None:
    peers = manifest.typescript_peers()

    assert {name: peers.get(name) for name in TYPE_CHECKER} == TYPE_CHECKER
    assert "@typescript/native" not in peers


@pytest.mark.parametrize("package_manager", ["npm@12.1.0", "yarn@4.18.0"])
def test_setup_type_checks_with_tsrs(compiler_repository: Path, package_manager: str) -> None:
    package = manifest.as_table(parse_json((compiler_repository / "package.json").read_text(encoding="utf-8")))
    package["packageManager"] = package_manager
    (compiler_repository / "package.json").write_text(json.dumps(package), encoding="utf-8")

    plan = service.plan_init(compiler_repository, configs=("typescript",), hook_manager="none")
    assert service.apply_init(plan, install=False).status == 0

    package = manifest.as_table(parse_json((compiler_repository / "package.json").read_text(encoding="utf-8")))
    dependencies = manifest.table_field(package, "devDependencies")
    scripts = manifest.table_field(package, "scripts")
    assert {name: dependencies.get(name) for name in TYPE_CHECKER} == TYPE_CHECKER
    assert dependencies["unrelated"] == "1.0.0"
    assert scripts["typecheck"] == "tsrs --noEmit"
    assert scripts["build"] == "tsc -p tsconfig.build.json"
    assert not [finding for finding in doctor.diagnose(compiler_repository) if finding.id == "doctor.typescript.peer"]
    assert service.apply_init(service.plan_init(compiler_repository), install=False).status == 0
    assert manifest.as_table(parse_json((compiler_repository / "package.json").read_text(encoding="utf-8"))) == package


@pytest.mark.parametrize(
    ("name", "pin"),
    [
        ("tsrs", "0.21.0"),
        ("typescript", "6.0.3"),
        ("typescript", "npm:@typescript/typescript6@^6.0.2"),
        ("typescript", "npm:typescript@6.0.2"),
    ],
)
def test_doctor_rejects_a_different_type_checker_pin(compiler_repository: Path, name: str, pin: str) -> None:
    plan = service.plan_init(compiler_repository, configs=("typescript",), hook_manager="none")
    assert service.apply_init(plan, install=False).status == 0
    package = manifest.as_table(parse_json((compiler_repository / "package.json").read_text(encoding="utf-8")))
    dependencies = manifest.table_field(package, "devDependencies")
    dependencies[name] = pin
    package["devDependencies"] = dependencies
    (compiler_repository / "package.json").write_text(json.dumps(package), encoding="utf-8")

    findings = doctor.diagnose(compiler_repository)

    assert [(finding.where, finding.id) for finding in findings if finding.id == "doctor.typescript.peer"] == [
        (f"package.json: {name}", "doctor.typescript.peer")
    ]


def test_upgrade_retires_the_native_compiler_pair(compiler_repository: Path) -> None:
    setup = service.plan_init(compiler_repository, configs=("typescript",), hook_manager="none")
    assert service.apply_init(setup, install=False).status == 0
    package = manifest.as_table(parse_json((compiler_repository / "package.json").read_text(encoding="utf-8")))
    dependencies = manifest.table_field(package, "devDependencies")
    dependencies["typescript"] = "6.0.3"
    dependencies["@typescript/native"] = "npm:typescript@7.0.2"
    package["devDependencies"] = dependencies
    package["scripts"] = {"typecheck": "tsc --noEmit -p tsconfig.json"}
    (compiler_repository / "package.json").write_text(json.dumps(package), encoding="utf-8")

    assert upgrade.apply(upgrade.build_plan(compiler_repository), install=False) == 0

    package = manifest.as_table(parse_json((compiler_repository / "package.json").read_text(encoding="utf-8")))
    dependencies = manifest.table_field(package, "devDependencies")
    assert {name: dependencies.get(name) for name in TYPE_CHECKER} == TYPE_CHECKER
    assert "@typescript/native" not in dependencies
    assert manifest.table_field(package, "scripts")["typecheck"] == "tsrs --noEmit -p tsconfig.json"
    assert not [finding for finding in doctor.diagnose(compiler_repository) if finding.id == "doctor.typescript.peer"]
