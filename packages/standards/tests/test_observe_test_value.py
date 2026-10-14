from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sarj_standards.api import Standards
from sarj_standards.cli.main import main
from sarj_standards.libs.adoption.manifest import as_table, list_field


def _report(output: str) -> dict[str, object]:
    value: object = json.loads(output)  # pyright: ignore[reportAny] -- narrow JSON at the report boundary.
    return as_table(value)


@pytest.mark.parametrize("paths", [[], ["tests"], ["tests/test_delivery.py"]], ids=["repository", "directory", "file"])
def test_observe_reports_candidates_without_turning_them_into_default_blockers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], paths: list[str]
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_delivery.py").write_text("def test_delivery():\n    deliver()\n", encoding="utf-8")
    (tests / "fakes").mkdir()
    (tests / "fakes/test_sender.py").write_text("def test_unused():\n    send()\n", encoding="utf-8")
    default = Standards(tmp_path).analyze(["tests/test_delivery.py"])
    assert not any(item.code == "SARJ495" for item in default.diagnostics)

    status = main(["--root", str(tmp_path), "observe", "--test-value", "--format", "json", *paths])
    report = _report(capsys.readouterr().out)
    assert status == 0
    assert report["completion"] == "complete"
    findings = [as_table(item) for item in list_field(report, "diagnostics")]
    assert [(item["code"], item["severity"]) for item in findings] == [("SARJ495", "warning")]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-c", "user.name=Test Value", "-c", "user.email=test@example.invalid", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


@pytest.mark.parametrize("change", ["empty", "production", "test", "deleted"])
def test_observe_base_scans_only_existing_changed_tests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: str
) -> None:
    _git(tmp_path, "init", "-q")
    target = tmp_path / "test_delivery.py"
    target.write_text("def test_delivery():\n    deliver()\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    match change:
        case "production":
            (tmp_path / "service.py").write_text("def deliver():\n    send()\n", encoding="utf-8")
        case "test":
            target.write_text("def test_delivery():\n    deliver('hello')\n", encoding="utf-8")
        case "deleted":
            target.unlink()
        case _:
            pass
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--allow-empty", "-qm", "change")

    status = main(["--root", str(tmp_path), "observe", "--test-value", "--base", base, "--format", "json"])
    report = _report(capsys.readouterr().out)
    assert status == 0
    assert report["completion"] == "complete"
    codes = [as_table(item)["code"] for item in list_field(report, "diagnostics")]
    assert codes == (["SARJ495"] if change == "test" else [])


@pytest.mark.parametrize(
    "scope",
    [["--base", "missing-ref"], ["missing.py"], ["../escape.py"]],
    ids=["invalid-base", "absent-file", "escape"],
)
def test_observe_invalid_scope_is_an_incomplete_machine_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], scope: list[str]
) -> None:
    status = main(["--root", str(tmp_path), "observe", "--test-value", "--format", "json", *scope])
    report = _report(capsys.readouterr().out)
    assert status == 2
    assert report["conclusion"] == "inconclusive"
    assert list_field(report, "issues")


def test_typescript_analysis_requires_a_trusted_repository_runtime(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "delivery.test.ts").write_text("test('delivery', () => deliver());\n", encoding="utf-8")
    status = main(["--root", str(tmp_path), "observe", "--test-value", "--format", "json"])
    report = _report(capsys.readouterr().out)
    assert status == 2
    assert report["conclusion"] == "inconclusive"
    assert list_field(report, "issues")


@pytest.mark.parametrize(
    ("body", "directive", "expected", "bulk"),
    [
        ("deliver();", "", "vitest/expect-expect", False),
        ("expect(deliver()).toEqual('hello');", "", None, False),
        (
            "Promise.resolve('hello').then(value => expect(value).toEqual('hello'));",
            "",
            "vitest/valid-expect-in-promise",
            False,
        ),
        ("return Promise.resolve('hello').then(value => expect(value).toEqual('hello'));", "", None, False),
        ("deliver();", "// eslint-disable-next-line vitest/expect-expect\n", None, False),
        ("deliver();", "", None, True),
    ],
    ids=["missing-oracle", "asserted", "discarded-promise", "returned-promise", "inline-suppressed", "bulk-suppressed"],
)
def test_observe_vitest_oracles_and_promise_completion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], body: str, directive: str, expected: str | None, *, bulk: bool
) -> None:
    modules = Path(__file__).resolve().parents[2] / "typescript/node_modules"
    if shutil.which("node") is None or not (modules / "@vitest/eslint-plugin/package.json").is_file():
        pytest.skip("requires the repository's locked TypeScript dependencies")
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text(
        "import parser from '@typescript-eslint/parser';\n"
        "import vitest from '@vitest/eslint-plugin';\n"
        "const unrelated={create(){throw new Error('UNRELATED RULE EXECUTED');}};\n"
        "export default [{files:['**/*.ts'],languageOptions:{parser},"
        "plugins:{vitest,'@sarj':{rules:{unrelated}}},rules:{'@sarj/unrelated':'error'}}];\n",
        encoding="utf-8",
    )
    (tmp_path / "delivery.test.ts").write_text(
        "import {test, expect} from 'vitest';\n" + directive + "test('delivery', () => {" + body + "});\n",
        encoding="utf-8",
    )
    if bulk:
        (tmp_path / "eslint-suppressions.json").write_text(
            json.dumps({"delivery.test.ts": {"vitest/expect-expect": {"count": 1}}}), encoding="utf-8"
        )
    status = main(["--root", str(tmp_path), "observe", "--test-value", "--trust-repository-code", "--format", "json"])
    report = _report(capsys.readouterr().out)
    assert status == 0
    assert report["completion"] == "complete"
    assert list_field(report, "issues") == []
    findings = [as_table(item) for item in list_field(report, "diagnostics")]
    assert [(item["ruleId"], item["severity"]) for item in findings] == ([(expected, "warning")] if expected else [])
