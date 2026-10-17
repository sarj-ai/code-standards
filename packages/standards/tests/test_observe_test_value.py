from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sarj_standards.api import Standards
from sarj_standards.cli.main import main
from sarj_standards.libs.adoption.manifest import as_table, list_field
from sarj_standards.libs.diagnostics import Severity


def _report(output: str) -> dict[str, object]:
    value: object = json.loads(output)  # pyright: ignore[reportAny] -- narrow JSON at the report boundary.
    return as_table(value)


@pytest.mark.parametrize("paths", [[], ["tests"], ["tests/test_delivery.py"]], ids=["repository", "directory", "file"])
def test_observe_reports_candidates_without_turning_them_into_default_blockers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], paths: list[str]
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_delivery.py").write_text(
        "def test_delivery():\n    deliver()\n"
        "def test_starts_job():\n    job = build_job()\n    job.run()\n    assert job.done\n"
        "def test_stops_job():\n    job = build_job()\n    job.run()\n    assert job.done\n"
        "def test_guard():\n    assert 1\n",
        encoding="utf-8",
    )
    (tests / "fakes").mkdir()
    (tests / "fakes/test_sender.py").write_text("def test_unused():\n    send()\n", encoding="utf-8")
    default = Standards(tmp_path).analyze(["tests/test_delivery.py"])
    assert not any(item.code == "SARJ495" for item in default.diagnostics)
    assert {(item.code, item.severity) for item in default.diagnostics if item.code in {"SARJ057", "SARJ066"}} == {
        ("SARJ057", Severity.ERROR),
        ("SARJ066", Severity.ERROR),
    }

    status = main(["--root", str(tmp_path), "observe", "--test-value", "--format", "json", *paths])
    report = _report(capsys.readouterr().out)
    assert status == 0, report
    assert report["completion"] == "complete"
    findings = [as_table(item) for item in list_field(report, "diagnostics")]
    assert sorted((item["code"], item["severity"]) for item in findings) == [
        ("SARJ057", "warning"),
        ("SARJ066", "warning"),
        ("SARJ495", "warning"),
    ]


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
    assert status == 0, report
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
    ("contract", "independent", "suppressed"),
    [
        pytest.param("await", False, False, id="vacuous-await-evidence"),
        pytest.param("membership", False, False, id="shadowed-membership-oracle"),
        pytest.param("await", True, False, id="positive-await-evidence"),
        pytest.param("membership", True, False, id="independent-membership-oracle"),
        pytest.param("await", False, True, id="suppressed-await-finding"),
        pytest.param("membership", False, True, id="suppressed-membership-finding"),
    ],
)
def test_observe_checks_execution_and_independent_case_oracles(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    contract: str,
    *,
    independent: bool,
    suppressed: bool,
) -> None:
    if contract == "await":
        code = "SARJ456"
        source = (
            "from unittest.mock import AsyncMock\n"
            "async def test_delivery():\n"
            "    send = AsyncMock()\n"
            "    pending = send()\n"
            "    pending.close()\n"
            "    send.assert_called_once()\n"
            f"    assert len(send.await_args_list) {'== 1' if independent else '>= 0'}\n"
        )
        finding_line = 6
    else:
        code = "SARJ409"
        parameter = "" if independent else "ELIGIBLE_MODELS"
        source = (
            "import pytest\n"
            "from app.models import ELIGIBLE_MODELS\n\n"
            f"def test_membership({parameter}):\n"
            "    assert ELIGIBLE_MODELS == ('a', 'b')\n\n"
            "@pytest.mark.parametrize('model', ELIGIBLE_MODELS)\n"
            "def test_model(model):\n"
            "    assert build(model)\n"
        )
        finding_line = 7
    if suppressed:
        lines = source.splitlines()
        lines[finding_line - 1] += f"  # sarj-noqa: {code} -- Intentional scheduling or exhaustiveness contract."
        source = "\n".join(lines) + "\n"
    test = tmp_path / "app/tests/test_delivery.py"
    test.parent.mkdir(parents=True)
    test.write_text(source, encoding="utf-8")

    status = main(["--root", str(tmp_path), "observe", "--test-value", "--format", "json"])
    report = _report(capsys.readouterr().out)
    assert status == 0, report
    assert report["completion"] == "complete"
    assert list_field(report, "issues") == []
    findings = [as_table(item) for item in list_field(report, "diagnostics")]
    assert [
        (item["code"], as_table(as_table(item["location"])["position"])["line"], item["severity"]) for item in findings
    ] == ([] if independent or suppressed else [(code, finding_line - 1, "warning")])


@pytest.mark.parametrize(
    ("body", "directive", "expected", "bulk", "registered"),
    [
        ("test('delivery', () => {deliver();});", "", "vitest/expect-expect", False, True),
        (
            "test.each(['hello'])('delivery %s', () => {try {deliver();} catch {return;} expect(deliver()).toEqual('hello');});",
            "",
            "@sarj/no-bare-return-from-test-catch",
            False,
            True,
        ),
        (
            "function verify(value){expect(value).toEqual('hello');}\ntest('delivery', () => {verify(deliver());});",
            "",
            None,
            False,
            False,
        ),
        (
            "test('delivery', () => {Promise.resolve('hello').then(value => expect(value).toEqual('hello'));});",
            "",
            "vitest/valid-expect-in-promise",
            False,
            True,
        ),
        (
            "test('delivery', () => {return Promise.resolve('hello').then(value => expect(value).toEqual('hello'));});",
            "",
            None,
            False,
            True,
        ),
        (
            "test('delivery', () => {deliver();});",
            "// eslint-disable-next-line vitest/expect-expect\n",
            None,
            False,
            True,
        ),
        ("test('delivery', () => {deliver();});", "", "vitest/expect-expect", True, True),
        ("test('delivery', () => {expect(true).toBe(true);});", "", "@sarj/no-tautological-expect", False, True),
        (
            "test.each([1, 1])('value %s', value => {expect(value).toBe(1);});",
            "",
            "@sarj/no-duplicate-test-case",
            False,
            True,
        ),
        (
            (
                "test('starts', () => {const job=buildJob();job.run();expect(job.done).toBe(true);});\n"
                "test('stops', () => {const job=buildJob();job.run();expect(job.done).toBe(true);});"
            ),
            "",
            "@sarj/duplicate-test-body",
            False,
            True,
        ),
        (
            "test.each([1, 1])('value %s', value => {expect(value).toBe(1);});",
            "",
            "@sarj/no-duplicate-test-case",
            True,
            False,
        ),
        (
            (
                "import {readFileSync} from 'node:fs';\n"
                "test('policy', () => {expect(readFileSync('workflow.yml', 'utf8')).toMatch(/permissions/);});"
            ),
            "",
            "@sarj/source-coupled-test",
            False,
            True,
        ),
        (
            (
                "import {readFileSync} from 'node:fs';\n"
                "test('policy', () => {const policy = JSON.parse(readFileSync('policy.json', 'utf8'));"
                "expect(policy.enabled).toBe(true);});"
            ),
            "",
            None,
            False,
            True,
        ),
        (
            (
                "import {readFileSync} from 'node:fs';\n"
                "// eslint-disable-next-line @sarj/source-coupled-test -- raw representation is the compatibility contract\n"
                "test('policy', () => {expect(readFileSync('workflow.yml', 'utf8')).toMatch(/permissions/);});"
            ),
            "",
            None,
            False,
            True,
        ),
        (
            (
                "import {readFileSync} from 'node:fs';\n"
                "test('policy', () => {expect(readFileSync('main.tf', 'utf8')).toMatch(/prevent_destroy/);});"
            ),
            "",
            "@sarj/iac-source-coupled-test",
            False,
            True,
        ),
        (
            (
                "import {readFileSync} from 'node:fs';\n"
                "test('policy', () => {const config = JSON.parse(readFileSync('main.tf.json', 'utf8'));"
                "expect(config.resource).toEqual({});});"
            ),
            "",
            None,
            False,
            True,
        ),
        (
            (
                "import {readFileSync} from 'node:fs';\n"
                "test('policy', () => {expect(readFileSync('main.tf', 'utf8')).toMatch(/prevent_destroy/);});"
            ),
            "",
            "@sarj/iac-source-coupled-test",
            True,
            False,
        ),
    ],
    ids=[
        "missing-oracle",
        "swallowed-table-failure",
        "asserted",
        "discarded-promise",
        "returned-promise",
        "inline-suppressed",
        "bulk-suppressed",
        "tautology",
        "duplicate-case",
        "duplicate-body",
        "sarj-bulk-suppressed",
        "source-oracle",
        "parsed-source-oracle",
        "source-representation-suppressed",
        "iac-source-oracle",
        "parsed-iac-source-oracle",
        "iac-source-bulk-suppressed",
    ],
)
def test_observe_vitest_oracles_redundancy_and_promise_completion(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    body: str,
    directive: str,
    expected: str | None,
    *,
    bulk: bool,
    registered: bool,
) -> None:
    modules = Path(__file__).resolve().parents[2] / "typescript/node_modules"
    if shutil.which("node") is None or not (modules / "@vitest/eslint-plugin/package.json").is_file():
        pytest.skip("requires the repository's locked TypeScript dependencies")
    plugin = modules.parent / "dist/index.js"
    if not plugin.is_file():
        pytest.skip("requires the built TypeScript plugin")
    installed = tmp_path / "node_modules"
    (installed / "@sarj").mkdir(parents=True)
    for name in ("eslint", "@typescript-eslint", "@vitest", ".bin"):
        (installed / name).symlink_to(modules / name, target_is_directory=True)
    (installed / "@sarj/eslint-plugin").symlink_to(modules.parent, target_is_directory=True)
    configured = "vitest,'@sarj':sarj" if registered else ""
    active = (
        "'@sarj/no-tautological-expect':'error','@sarj/no-duplicate-test-case':'error',"
        "'@sarj/duplicate-test-body':'error',"
        "'@sarj/no-bare-return-from-test-catch':'error',"
        "'@sarj/source-coupled-test':'error','@sarj/iac-source-coupled-test':'error',"
        if registered
        else ""
    )
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    (tmp_path / "eslint.config.mjs").write_text(
        "import parser from '@typescript-eslint/parser';\n"
        "import vitest from '@vitest/eslint-plugin';\n"
        f"import sarj from {json.dumps(plugin.as_uri())};\n"
        "const unrelated={create(){throw new Error('UNRELATED RULE EXECUTED');}};\n"
        "export default [{files:['**/*.ts'],languageOptions:{parser},"
        f"plugins:{{guard:{{rules:{{unrelated}}}}{',' + configured if configured else ''}}},"
        f"rules:{{'guard/unrelated':'error',{active}"
        "'vitest/expect-expect':['off',{assertFunctionNames:['expect','verify']}]}}];\n",
        encoding="utf-8",
    )
    (tmp_path / "delivery.test.ts").write_text(
        "import {test, expect} from 'vitest';\n" + directive + body + "\n",
        encoding="utf-8",
    )
    if bulk:
        (tmp_path / "eslint-suppressions.json").write_text(
            json.dumps({"delivery.test.ts": {expected: {"count": 1}}}), encoding="utf-8"
        )
    status = main(["--root", str(tmp_path), "observe", "--test-value", "--trust-repository-code", "--format", "json"])
    report = _report(capsys.readouterr().out)
    assert status == 0, report
    assert report["completion"] == "complete"
    assert list_field(report, "issues") == []
    findings = [as_table(item) for item in list_field(report, "diagnostics")]
    assert [(item["ruleId"], item["severity"]) for item in findings] == (
        [(expected, "warning")] if expected and not bulk else []
    )

    if expected and expected.startswith("@sarj/") and not bulk and registered:
        policy = Standards(tmp_path).analyze(
            ["delivery.test.ts"], external=True, trust="trusted", rules=["eslint:" + expected.removeprefix("@sarj/")]
        )
        assert [(item.rule_id, item.severity) for item in policy.diagnostics] == [(expected, Severity.ERROR)]
