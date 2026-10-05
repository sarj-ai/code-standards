from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import doctor, manifest, service, upgrade
from sarj_standards.libs.json_boundary import parse_json


if TYPE_CHECKING:
    from pathlib import Path


COMPILER_PINS = {
    "typescript": "7.0.2",
}


@pytest.fixture
def compiler_repository(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "compiler-consumer",
                "private": True,
                "scripts": {"typecheck": "tsc --noEmit"},
                "devDependencies": {"typescript": "6.0.3", "unrelated": "1.0.0"},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.parametrize("package_manager", ["npm@12.1.0", "yarn@4.18.0"])
def test_setup_installs_the_compiler_pin_without_changing_commands(
    compiler_repository: Path, package_manager: str
) -> None:
    package_path = compiler_repository / "package.json"
    package = manifest.as_table(parse_json(package_path.read_text(encoding="utf-8")))
    package["packageManager"] = package_manager
    package_path.write_text(json.dumps(package), encoding="utf-8")

    plan = service.plan_init(compiler_repository, configs=("oxlint",), hook_manager="none")
    assert service.apply_init(plan, install=False).status == 0

    package = manifest.as_table(parse_json(package_path.read_text(encoding="utf-8")))
    dependencies = manifest.table_field(package, "devDependencies")
    assert {name: dependencies.get(name) for name in COMPILER_PINS} == COMPILER_PINS
    assert dependencies["unrelated"] == "1.0.0"
    assert package["scripts"] == {"typecheck": "tsc --noEmit"}
    assert not [finding for finding in doctor.diagnose(compiler_repository) if finding.id == "doctor.oxlint.peer"]
    assert service.apply_init(service.plan_init(compiler_repository), install=False).status == 0
    assert manifest.as_table(parse_json(package_path.read_text(encoding="utf-8"))) == package


@pytest.mark.parametrize(
    ("name", "pin"),
    [
        ("typescript", "6.0.3"),
        ("typescript", "npm:@typescript/typescript6@^6.0.2"),
        ("typescript", "npm:@typescript/typescript6@6.0.1"),
        ("typescript", "npm:typescript@6.0.2"),
    ],
)
def test_doctor_rejects_a_different_compiler_package_or_version(compiler_repository: Path, name: str, pin: str) -> None:
    plan = service.plan_init(compiler_repository, configs=("oxlint",), hook_manager="none")
    assert service.apply_init(plan, install=False).status == 0
    package_path = compiler_repository / "package.json"
    package = manifest.as_table(parse_json(package_path.read_text(encoding="utf-8")))
    dependencies = manifest.table_field(package, "devDependencies")
    dependencies[name] = pin
    package["devDependencies"] = dependencies
    package_path.write_text(json.dumps(package), encoding="utf-8")

    findings = doctor.diagnose(compiler_repository)

    assert [(finding.where, finding.id) for finding in findings if finding.id == "doctor.oxlint.peer"] == [
        (f"package.json: {name}", "doctor.oxlint.peer")
    ]


def test_upgrade_replaces_the_old_compiler_pin_and_preserves_commands(compiler_repository: Path) -> None:
    setup = service.plan_init(compiler_repository, configs=("oxlint",), hook_manager="none")
    assert service.apply_init(setup, install=False).status == 0
    package_path = compiler_repository / "package.json"
    package = manifest.as_table(parse_json(package_path.read_text(encoding="utf-8")))
    dependencies = manifest.table_field(package, "devDependencies")
    dependencies["typescript"] = "6.0.3"
    dependencies.pop("@typescript/native", None)
    package["devDependencies"] = dependencies
    package_path.write_text(json.dumps(package), encoding="utf-8")

    assert upgrade.apply(upgrade.build_plan(compiler_repository), install=False) == 0

    package = manifest.as_table(parse_json(package_path.read_text(encoding="utf-8")))
    dependencies = manifest.table_field(package, "devDependencies")
    assert {name: dependencies.get(name) for name in COMPILER_PINS} == COMPILER_PINS
    assert package["scripts"] == {"typecheck": "tsc --noEmit"}
    assert not [finding for finding in doctor.diagnose(compiler_repository) if finding.id == "doctor.oxlint.peer"]
