from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from sarj_standards.cli.main import main
from sarj_standards.libs.release.process import (
    ProcessBinaryResult,
    ProcessFailureError,
    ProcessResult,
    run_binary_process,
    run_process,
)
from sarj_standards.libs.repository import rule_changes
from sarj_standards.libs.rules import DefaultLevel


_INVENTORY = Path("packages/standards/src/sarj_standards/configs/rule-inventory.v1.json")
_CATALOG = Path("packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json")


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _rule(rule_id: str, *, level: str = "warning", summary: str = "Summary") -> dict[str, object]:
    return {
        "key": f"python:{rule_id}",
        "engine": "python",
        "id": rule_id,
        "code": "SARJ999",
        "summary": summary,
        "rationale": "Rationale",
        "remediation": "Remediation",
        "category": "correctness",
        "languages": ["python"],
        "defaultLevel": level,
        "autofix": "none",
        "status": "active",
        "aliases": [],
        "limitations": [],
        "filePatterns": ["**/*.py"],
        "messageIds": ["problem"],
        "optionsSchema": None,
        "references": [],
        "since": "1.0.0",
        "source": f"packages/python/src/rules/{rule_id}.py",
        "test": f"packages/python/tests/rules/test_{rule_id.replace('-', '_')}.py",
        "examples": [],
    }


def _write_revision(root: Path, rules: list[dict[str, object]], message: str) -> str:
    inventory_rules = [
        {
            "family": "typescript" if rule["engine"] == "eslint" else rule["engine"],
            "id": rule["id"],
            "code": rule["code"],
            "source": rule["source"],
            "test": rule["test"],
        }
        for rule in rules
    ]
    inventory = {"schemaVersion": 1, "rules": inventory_rules}
    catalog = {"schemaVersion": 1, "rules": rules}
    for path, payload in ((_INVENTORY, inventory), (_CATALOG, catalog)):
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    for rule in rules:
        for field in ("source", "test"):
            destination = root / str(rule[field])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                destination.write_text(f"# {field} for {rule['id']}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Standards test")
    _git(tmp_path, "config", "user.email", "standards@example.invalid")
    return tmp_path


def test_changes_reports_sorted_additions_and_resolved_shas(repository: Path) -> None:
    before = _write_revision(repository, [_rule("existing")], "base")
    after = _write_revision(repository, [_rule("a-new"), _rule("existing"), _rule("z-new")], "candidate")

    result = rule_changes.compare(repository, before=before, after=after)

    assert result["schemaVersion"] == 1
    assert result["beforeSha"] == before
    assert result["afterSha"] == after
    assert [(item["kind"], item["key"]) for item in result["changes"]] == [
        ("added", "python:a-new"),
        ("added", "python:z-new"),
    ]
    added = result["changes"][0]["after"]
    assert added is not None
    assert added["releaseTarget"] == "python"
    assert [item["releaseTarget"] for item in result["changes"]] == ["python", "python"]


def test_added_level_gate_reports_only_rules_outside_required_stage(repository: Path) -> None:
    before = _write_revision(repository, [_rule("existing")], "base")
    after = _write_revision(
        repository,
        [_rule("existing"), _rule("error-first", level="error"), _rule("warning-first")],
        "candidate",
    )

    result = rule_changes.compare(repository, before=before, after=after)

    assert rule_changes.added_rules_at_other_levels(result, required="warning") == ["python:error-first"]


def test_changes_rejects_unknown_catalog_level(repository: Path) -> None:
    before = _write_revision(repository, [_rule("existing")], "base")
    after = _write_revision(repository, [_rule("existing"), _rule("new", level="fatal")], "candidate")

    with pytest.raises(ValueError, match="rule catalog python:new has invalid defaultLevel 'fatal'"):
        rule_changes.compare(repository, before=before, after=after)


def test_changes_accepts_off_catalog_level(repository: Path) -> None:
    before = _write_revision(repository, [], "base")
    after = _write_revision(repository, [_rule("disabled", level="off")], "candidate")

    result = rule_changes.compare(repository, before=before, after=after)

    added = result["changes"][0]["after"]
    assert added is not None
    assert added["defaultLevel"] is DefaultLevel.OFF


def test_changes_routes_removals_without_consumer_side_descriptor_branching(repository: Path) -> None:
    before = _write_revision(repository, [_rule("removed")], "base")
    after = _write_revision(repository, [], "candidate")

    result = rule_changes.compare(repository, before=before, after=after)

    assert result["changes"] == [
        {
            "kind": "removed",
            "key": "python:removed",
            "releaseTarget": "python",
            "before": {
                "key": "python:removed",
                "engine": "python",
                "family": "python",
                "id": "removed",
                "code": "SARJ999",
                "defaultLevel": "warning",
                "releaseTarget": "python",
                "source": "packages/python/src/rules/removed.py",
                "test": "packages/python/tests/rules/test_removed.py",
            },
            "after": None,
        }
    ]


def test_changes_distinguishes_policy_and_implementation_changes(repository: Path) -> None:
    before = _write_revision(repository, [_rule("sample")], "base")
    changed = _rule("sample", level="error", summary="Changed summary")
    after = _write_revision(repository, [changed], "candidate")

    result = rule_changes.compare(repository, before=before, after=after)

    assert [(item["kind"], item["key"]) for item in result["changes"]] == [
        ("implementation-changed", "python:sample"),
        ("policy-changed", "python:sample"),
    ]
    assert result["changedSelectors"] == ["python:sample"]
    identity = {key: value for key, value in result.items() if key != "changeSetDigest"}
    expected_digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert result["changeSetDigest"] == expected_digest


def test_change_set_digest_is_stable_for_repeated_comparisons(repository: Path) -> None:
    before = _write_revision(repository, [_rule("existing")], "base")
    after = _write_revision(repository, [_rule("a-new"), _rule("existing")], "candidate")

    first = rule_changes.compare(repository, before=before, after=after)
    second = rule_changes.compare(repository, before=before, after=after)

    assert first["changeSetDigest"] == second["changeSetDigest"]
    assert len(first["changeSetDigest"]) == 64


def test_changes_detects_source_only_implementation_change(repository: Path) -> None:
    before = _write_revision(repository, [_rule("sample")], "base")
    source = repository / "packages/python/src/rules/sample.py"
    source.write_text("# changed implementation\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "change implementation")
    after = _git(repository, "rev-parse", "HEAD")

    result = rule_changes.compare(repository, before=before, after=after)

    assert [(item["kind"], item["key"]) for item in result["changes"]] == [("implementation-changed", "python:sample")]


def test_changes_fails_when_inventory_and_catalog_disagree(repository: Path) -> None:
    before = _write_revision(repository, [_rule("existing")], "base")
    after = _write_revision(repository, [_rule("existing"), _rule("new")], "candidate")
    inventory = repository / _INVENTORY
    inventory.write_text('{"schemaVersion":1,"rules":[]}\n', encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "break inventory")
    broken = _git(repository, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="inventory/catalog disagreement"):
        rule_changes.compare(repository, before=before, after=broken)

    assert after != broken


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_changes_rejects_inventory_entries_outside_exact_schema(repository: Path, mutation: str) -> None:
    before = _write_revision(repository, [_rule("existing")], "base")
    inventory_path = repository / _INVENTORY
    first: dict[str, object] = {
        "family": "python",
        "id": "existing",
        "code": "SARJ999",
        "source": "packages/python/src/rules/existing.py",
        "test": "packages/python/tests/rules/test_existing.py",
    }
    if mutation == "extra":
        first["owner"] = "standards"
    else:
        first = {key: value for key, value in first.items() if key != "test"}
    inventory: dict[str, object] = {"schemaVersion": 1, "rules": [first]}
    inventory_path.write_text(json.dumps(inventory, sort_keys=True) + "\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", f"inventory {mutation} field")
    broken = _git(repository, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="inventory entry 1 has unexpected or missing fields"):
        rule_changes.compare(repository, before=before, after=broken)


def test_cli_emits_versioned_json(repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = _write_revision(repository, [], "base")
    after = _write_revision(repository, [_rule("new-rule")], "candidate")

    status = main(
        [
            "--root",
            str(repository),
            "maintain",
            "rules",
            "changes",
            "--before",
            before,
            "--after",
            after,
            "--format",
            "json",
        ]
    )

    assert status == 0
    payload: dict[str, object] = json.loads(capsys.readouterr().out)  # pyright: ignore[reportAny]
    assert payload["schemaVersion"] == 1
    assert payload["changes"]


def test_cli_added_level_gate_prints_warning_stage_command(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = _write_revision(repository, [], "base")
    after = _write_revision(repository, [_rule("error-first", level="error")], "candidate")

    status = main(
        [
            "--root",
            str(repository),
            "maintain",
            "rules",
            "changes",
            "--before",
            before,
            "--after",
            after,
            "--require-added-level",
            "warning",
        ]
    )

    assert status == 1
    stderr = capsys.readouterr().err
    assert "new judgment rules must enter the fleet at warning level" in stderr
    assert "maintain rules stage-warning python:error-first" in stderr


def test_cli_added_level_gate_rejects_unsupported_error_stage(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = _write_revision(repository, [], "base")
    after = _write_revision(repository, [_rule("warning-first")], "candidate")

    with pytest.raises(SystemExit, match="2"):
        main(
            [
                "--root",
                str(repository),
                "maintain",
                "rules",
                "changes",
                "--before",
                before,
                "--after",
                after,
                "--require-added-level",
                "error",
            ]
        )

    error = capsys.readouterr().err
    assert "--require-added-level" in error
    assert "'error'" in error
    assert "'warning'" in error


def test_cli_rejects_missing_revision(repository: Path, capsys: pytest.CaptureFixture[str]) -> None:
    current = _write_revision(repository, [], "base")

    status = main(
        [
            "--root",
            str(repository),
            "maintain",
            "rules",
            "changes",
            "--before",
            "missing",
            "--after",
            current,
        ]
    )

    assert status == 2
    assert "cannot compare rule revisions" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("engine", "rule_id", "level", "expected_status"),
    [
        ("eslint", "no-reduce-accumulator-copy", "error", 0),
        ("eslint", "no-reduce-accumulator-copy", "off", 1),
        ("python", "no-reduce-accumulator-copy", "error", 1),
        ("eslint", "no-reduce-accumulator-copy-extra", "error", 1),
        ("eslint", "no-known-value-widening", "error", 0),
        ("eslint", "no-broad-return-type", "error", 0),
        ("eslint", "no-broad-return-type", "off", 1),
        ("python", "no-broad-return-type", "error", 1),
        ("eslint", "no-broad-return-type-extra", "error", 1),
        ("eslint", "prefer-typed-reflection", "error", 0),
        ("eslint", "prefer-typed-reflection", "off", 1),
        ("python", "prefer-typed-reflection", "error", 1),
        ("eslint", "prefer-typed-reflection-extra", "error", 1),
        ("eslint", "no-conditional-empty-object-spread", "error", 0),
        ("eslint", "no-conditional-empty-object-spread", "off", 1),
        ("python", "no-conditional-empty-object-spread", "error", 1),
        ("eslint", "no-conditional-empty-object-spread-extra", "error", 1),
        ("eslint", "no-known-value-widening", "off", 1),
        ("python", "no-known-value-widening", "error", 1),
        ("eslint", "no-known-value-widening-extra", "error", 1),
        ("python", "no-excessive-cognitive-complexity", "error", 0),
        ("eslint", "no-excessive-cognitive-complexity", "error", 0),
        ("python", "no-excessive-cognitive-complexity", "off", 1),
        ("sql", "no-excessive-cognitive-complexity", "error", 1),
        ("python", "no-excessive-cognitive-complexity-extra", "error", 1),
    ],
)
def test_error_first_approval_is_exact_and_does_not_allow_disabled_rules(
    repository: Path, engine: str, rule_id: str, level: str, expected_status: int
) -> None:
    before = _write_revision(repository, [], "base")
    rule = _rule(rule_id, level=level)
    rule["key"] = f"{engine}:{rule_id}"
    rule["engine"] = engine
    after = _write_revision(repository, [rule], "candidate")
    assert (
        main(
            [
                "--root",
                str(repository),
                "maintain",
                "rules",
                "changes",
                "--before",
                before,
                "--after",
                after,
                "--require-added-level",
                "warning",
            ]
        )
        == expected_status
    )


@pytest.mark.parametrize(
    "selector",
    [
        "iac:no-managed-service-account-key",
        "iac:no-project-basic-privilege",
        "text:cloudbuild-contract",
        "python:no-interpreter-source-arguments",
    ],
)
def test_explicit_devops_error_first_admission_preserves_exact_selector_scope(
    repository: Path, capsys: pytest.CaptureFixture[str], selector: str
) -> None:
    engine, rule_id = selector.split(":", 1)
    approved = {**_rule(rule_id, level="error"), "key": selector, "engine": engine}
    before = _write_revision(repository, [], "base")
    after = _write_revision(repository, [approved], "approved strict DevOps rule")
    arguments = [
        "--root",
        str(repository),
        "maintain",
        "rules",
        "changes",
        "--before",
        before,
        "--after",
        after,
        "--require-added-level",
        "warning",
    ]
    assert main(arguments) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert selector in captured.out

    wrong_engine = "eslint" if engine == "python" else "python"
    foreign_key = f"{wrong_engine}:{rule_id}"
    foreign = {**_rule(rule_id, level="error"), "key": foreign_key, "engine": wrong_engine}
    similarly_named_key = f"{engine}:{rule_id}-heuristic"
    similarly_named = {
        **_rule(f"{rule_id}-heuristic", level="error"),
        "key": similarly_named_key,
        "engine": engine,
    }
    invalid_after = _write_revision(repository, [approved, foreign, similarly_named], "unapproved neighboring rules")
    arguments[arguments.index("--after") + 1] = invalid_after
    assert main(arguments) == 1
    rejected = capsys.readouterr()
    assert "new judgment rules must enter the fleet at warning level" in rejected.err
    suggested = [
        line.removeprefix("Run: code-standards --root . maintain rules stage-warning ")
        for line in rejected.err.splitlines()
        if line.startswith("Run:")
    ]
    assert sorted(suggested) == sorted([foreign_key, similarly_named_key])


@pytest.mark.parametrize(
    "case",
    [
        "parent-init",
        "unrelated-init",
        "module",
        "aliased-module",
        "utf8-bom-module",
        "latin1-module",
        "dotted-module",
        "mutated-type-guard",
        "mutated-import-function",
        "import-function",
        "builtin",
        "relative-module",
        "shadowed",
    ],
)
def test_runtime_import_ownership(repository: Path, case: str) -> None:
    entry = _rule("alpha")
    entry["source"] = "packages/python/src/engine/alpha.py"
    package = repository / "packages/python/src/engine"
    package.mkdir(parents=True)
    initializer = package / "__init__.py"
    initializer.write_text("FLAG=False\n", encoding="utf-8")
    helper = package / "helper.py"
    helper.write_text("def evaluate():\n return False\n", encoding="utf-8")
    (package / "other.py").write_text("VALUE=False\n", encoding="utf-8")
    sources = {
        "parent-init": "import engine.other\nfrom engine import FLAG\ndef check():\n return FLAG\n",
        "unrelated-init": "def check():\n return False\n",
        "module": "import importlib\ndef check():\n return importlib.import_module('engine.helper').evaluate()\n",
        "mutated-type-guard": "import typing\ntyping.TYPE_CHECKING=True\nif typing.TYPE_CHECKING:\n from .helper import evaluate\ndef check():\n return evaluate()\n",
        "mutated-import-function": "import importlib as modules\nmodules.import_module=lambda name:False\ndef check():\n return modules.import_module('engine.helper')\n",
        "dotted-module": "import importlib.util\ndef check():\n return importlib.import_module('engine.helper').evaluate()\n",
        "aliased-module": "import importlib as modules\ndef check():\n return modules.import_module('engine.helper').evaluate()\n",
        "utf8-bom-module": "\ufefffrom .helper import evaluate\ndef check():\n return evaluate()\n",
        "latin1-module": "# coding: latin-1\n# café\nfrom .helper import evaluate\ndef check():\n return evaluate()\n",
        "import-function": "from importlib import import_module as load\ndef check():\n return load('engine.helper').evaluate()\n",
        "builtin": "def check():\n return __import__('engine.helper',fromlist=['evaluate']).evaluate()\n",
        "relative-module": "from importlib import import_module\ndef check():\n return import_module('.helper',package='engine').evaluate()\n",
        "shadowed": "from importlib import import_module as load\ndef load(_name):\n return False\ndef check():\n return load('engine.helper')\n",
    }
    (package / "alpha.py").write_text(sources[case], encoding="latin-1" if case == "latin1-module" else "utf-8")
    other = repository / "packages/python/src/unrelated"
    other.mkdir()
    (other / "__init__.py").write_text("FLAG=False\n", encoding="utf-8")
    before = _write_revision(repository, [entry], "runtime baseline")
    script = repository / "observe.py"
    script.write_text(
        "import sys\nsys.path.insert(0,'packages/python/src')\nfrom engine.alpha import check\nprint(check())\n",
        encoding="utf-8",
    )
    before_output = subprocess.run(
        (sys.executable, str(script)), cwd=repository, check=True, capture_output=True, text=True
    ).stdout
    match case:
        case "parent-init":
            initializer.write_text("FLAG=True\n", encoding="utf-8")
        case "unrelated-init":
            (other / "__init__.py").write_text("FLAG=True\n", encoding="utf-8")
        case _:
            helper.write_text("def evaluate():\n return True\n", encoding="utf-8")
    _git(repository, "add", "packages")
    _git(repository, "commit", "-m", "runtime candidate")
    after = _git(repository, "rev-parse", "HEAD")
    after_output = subprocess.run(
        (sys.executable, str(script)), cwd=repository, check=True, capture_output=True, text=True
    ).stdout
    positive = case not in {"unrelated-init", "shadowed", "mutated-import-function"}
    assert before_output.strip() == "False"
    assert after_output.strip() == ("True" if positive else "False")
    result = rule_changes.compare(repository, before=before, after=after)
    assert result["changedSelectors"] == (["python:alpha"] if positive else [])
    assert rule_changes.compare(repository, before=before, after=after) == result


@pytest.mark.parametrize("case", ["invalid-header", "missing", "truncated", "trailer", "failed-status"])
def test_binary_git_boundary_rejects_invalid_snapshots(repository: Path, case: str) -> None:
    before = _write_revision(repository, [_rule("alpha")], "binary baseline")

    def runner(argv: tuple[str, ...], *, cwd: Path, input_bytes: bytes = b"") -> ProcessBinaryResult:
        result = run_binary_process(argv, cwd=cwd, input_bytes=input_bytes)
        if "cat-file" not in argv:
            return result
        oid = input_bytes.splitlines()[0]
        payloads = {
            "invalid-header": b"invalid\n",
            "missing": oid + b" missing\n",
            "truncated": oid + b" blob 10\nshort\n",
            "trailer": result.stdout + b"unexpected",
            "failed-status": result.stdout,
        }
        return ProcessBinaryResult(7 if case == "failed-status" else 0, payloads[case])

    if case == "failed-status":
        with pytest.raises(ProcessFailureError) as caught:
            rule_changes.compare(repository, before=before, after=before, binary_runner=runner)
        assert caught.value.returncode == 7
    else:
        with pytest.raises(ValueError, match="immutable Git batch"):
            rule_changes.compare(repository, before=before, after=before, binary_runner=runner)


def test_python_only_comparison_does_not_require_node(repository: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = _write_revision(repository, [_rule("alpha")], "python-only baseline")
    # Git stays available through an explicit fixed executable; Node discovery is absent.
    git = shutil.which("git")
    assert git is not None

    def git_only(argv: tuple[str, ...], *, cwd: Path, input_bytes: bytes = b"") -> ProcessBinaryResult:
        return run_binary_process((git, *argv[1:]), cwd=cwd, input_bytes=input_bytes)

    def resolve(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        return run_process((git, *argv[1:]), cwd=cwd, capture_output=capture_output)

    monkeypatch.setenv("PATH", "")
    assert (
        rule_changes.compare(repository, before=before, after=before, runner=resolve, binary_runner=git_only)["changes"]
        == []
    )
    assert shutil.which("node") is None


def test_functional_registry_keeps_called_rule_dependency(repository: Path) -> None:
    alpha = _rule("alpha")
    beta = _rule("beta")
    alpha["source"] = "packages/python/src/engine/alpha.py"
    beta["source"] = "packages/python/src/engine/beta.py"
    package = repository / "packages/python/src/engine"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "alpha.py").write_text(
        "from .registry import OBSERVED\ndef check():\n return OBSERVED\n", encoding="utf-8"
    )
    source = "class Beta:\n id='beta'\n @staticmethod\n def check():\n  return False\n"
    (package / "beta.py").write_text(source, encoding="utf-8")
    (package / "registry.py").write_text(
        "from .beta import Beta\nREGISTRY={Beta.id:Beta}\nOBSERVED=Beta.check()\n", encoding="utf-8"
    )
    before = _write_revision(repository, [alpha, beta], "functional registry baseline")
    script = repository / "observe.py"
    script.write_text(
        "import sys\nsys.path.insert(0,'packages/python/src')\nfrom engine.alpha import check\nprint(check())\n",
        encoding="utf-8",
    )
    assert (
        subprocess.run(
            (sys.executable, str(script)), cwd=repository, capture_output=True, text=True, check=True
        ).stdout.strip()
        == "False"
    )
    (package / "beta.py").write_text(source.replace("False", "True"), encoding="utf-8")
    _git(repository, "add", "packages")
    _git(repository, "commit", "-m", "functional registry candidate")
    after = _git(repository, "rev-parse", "HEAD")
    assert (
        subprocess.run(
            (sys.executable, str(script)), cwd=repository, capture_output=True, text=True, check=True
        ).stdout.strip()
        == "True"
    )
    assert rule_changes.compare(repository, before=before, after=after)["changedSelectors"] == [
        "python:alpha",
        "python:beta",
    ]


@pytest.mark.parametrize("case", ["compiler-runtime", "compiler-package"])
def test_parser_version_pair_rejects_fully_functional_wrong_compiler(repository: Path, case: str) -> None:
    _prepare_rule_comparison_parser_metadata(repository)
    installed = Path(__file__).parents[2] / "typescript/node_modules/typescript/lib/typescript.js"
    compiler = repository / "packages/typescript/node_modules/typescript/lib/typescript.js"
    compiler.parent.mkdir(parents=True)
    pins = _rule_comparison_parser_fixture_pins(repository)
    runtime = "0.0.0" if case == "compiler-runtime" else pins.runtime
    compiler.write_text(
        "const compiler=require("
        + json.dumps(str(installed.resolve()))
        + ");module.exports={...compiler,version:"
        + json.dumps(runtime)
        + "};\n",
        encoding="utf-8",
    )
    (compiler.parent.parent / "package.json").write_text(
        json.dumps(
            {"name": "@typescript/typescript6", "version": "0.0.0" if case == "compiler-package" else pins.package}
        ),
        encoding="utf-8",
    )
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source="packages/typescript/src/alpha.ts",
        test="packages/typescript/tests/alpha.test.ts",
    )
    for field in ("source", "test"):
        path = repository / str(entry[field])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("export const valid=true;\n", encoding="utf-8")
    before = _write_revision(repository, [entry], "compiler-pair baseline")
    with pytest.raises(ValueError, match=r"preinstalled Node.*compiler"):
        rule_changes.compare(repository, before=before, after=before)
    frontend = files("sarj_standards.libs.repository").joinpath("rule_imports.cjs")
    invoked = subprocess.run(
        ("node", str(frontend), str(compiler), pins.node, pins.package, pins.runtime),
        cwd=repository,
        input="{}",
        text=True,
        capture_output=True,
        check=False,
    )
    assert invoked.returncode != 0
    assert "does not match documented preinstalled Node/compiler package/runtime pins" in invoked.stderr


@pytest.mark.parametrize(
    "source",
    [b"# coding: unavailable-encoding\nVALUE = 1\n", b"\xef\xbb\xbf# coding: latin-1\nVALUE = 1\n"],
    ids=("unknown-encoding", "bom-cookie-conflict"),
)
def test_invalid_native_python_encoding_fails_at_the_immutable_boundary(repository: Path, source: bytes) -> None:
    entry = _rule("alpha")
    path = repository / str(entry["source"])
    path.parent.mkdir(parents=True)
    path.write_bytes(source)
    revision = _write_revision(repository, [entry], "invalid encoding fixture")
    native = subprocess.run((sys.executable, str(path)), cwd=repository, check=False, capture_output=True, text=True)
    assert native.returncode != 0
    with pytest.raises(ValueError, match="invalid immutable Python source encoding"):
        rule_changes.compare(repository, before=revision, after=revision)


@pytest.fixture
def installed_rule_comparison_compiler(repository: Path) -> None:
    _prepare_rule_comparison_parser_metadata(repository)
    installed = Path(__file__).parents[2] / "typescript/node_modules/typescript"
    compiler = repository / "packages/typescript/node_modules/typescript"
    compiler.parent.mkdir(parents=True)
    compiler.symlink_to(installed.resolve(), target_is_directory=True)


@pytest.mark.parametrize(
    ("case", "source", "tracks_helper"),
    [
        ("literal", "module.exports=require('./helper.cjs');", True),
        ("nested", "module.exports=(()=>require('./helper.cjs'))();", True),
        (
            "separate-block-shadow",
            "{const require=()=>false;require('./helper.cjs');} module.exports=require('./helper.cjs');",
            True,
        ),
        (
            "separate-parameter-shadow",
            "function local(require){return require('./helper.cjs');} local(()=>false);module.exports=require('./helper.cjs');",
            True,
        ),
        (
            "separate-local-mutation",
            "function local(require){require=()=>false;return require('./helper.cjs');} local(()=>false);module.exports=require('./helper.cjs');",
            True,
        ),
        ("dynamic-with-shadow", "with({require:()=>false}){module.exports=require('./helper.cjs');}", False),
        ("direct-eval-mutation", "eval('require=()=>false');module.exports=require('./helper.cjs');", False),
        ("shadowed-eval", "(eval=>eval('ignored'))(()=>false);module.exports=require('./helper.cjs');", True),
        ("parameter-shadow", "module.exports=(require=>require('./helper.cjs'))(()=>false);", False),
        (
            "destructured-parameter-shadow",
            "module.exports=(({require})=>require('./helper.cjs'))({require:()=>false});",
            False,
        ),
        ("block-shadow", "{const require=()=>false;module.exports=require('./helper.cjs');}", False),
        ("catch-shadow", "try{throw ()=>false;}catch(require){module.exports=require('./helper.cjs');}", False),
        (
            "function-hoisted-var",
            "module.exports=(function(){var require=()=>false;return require('./helper.cjs');})();",
            False,
        ),
        ("function-shadow", "function require(){return false;}module.exports=require('./helper.cjs');", False),
        ("assigned-wrapper", "require=()=>false;module.exports=require('./helper.cjs');", False),
        ("destructured-assignment", "({require}={require:()=>false});module.exports=require('./helper.cjs');", False),
        ("literal-computed-abstention", "const path='./helper.cjs';module.exports=require(path);", False),
        ("comment-lookalike", "// require('./helper.cjs')\nmodule.exports=false;", False),
        ("string-lookalike", "const spelling=\"require('./helper.cjs')\";module.exports=false;", False),
        ("unicode-bom", "\ufeffmodule.exports=require('./helper.cjs');", True),
        ("hashbang", "#!/usr/bin/env node\nmodule.exports=require('./helper.cjs');", True),
    ],
)
@pytest.mark.usefixtures("installed_rule_comparison_compiler")
def test_commonjs_runtime_dependency_ownership(repository: Path, case: str, source: str, tracks_helper: bool) -> None:
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source="packages/typescript/src/alpha.cjs",
        test="packages/typescript/tests/alpha.test.cjs",
    )
    package = repository / "packages/typescript/src"
    package.mkdir(parents=True)
    (package / "alpha.cjs").write_text(source, encoding="utf-8")
    (package / "helper.cjs").write_text("module.exports=false;", encoding="utf-8")
    test = repository / str(entry["test"])
    test.parent.mkdir(parents=True)
    test.write_text("", encoding="utf-8")
    before = _write_revision(repository, [entry], f"CommonJS baseline {case}")
    observe = ("node", "--eval", "console.log(require('./packages/typescript/src/alpha.cjs'))")
    before_output = subprocess.run(observe, cwd=repository, check=True, capture_output=True, text=True).stdout.strip()
    (package / "helper.cjs").write_text("module.exports=true;", encoding="utf-8")
    _git(repository, "add", "packages")
    _git(repository, "commit", "-m", "CommonJS helper counterfactual")
    after = _git(repository, "rev-parse", "HEAD")
    after_output = subprocess.run(observe, cwd=repository, check=True, capture_output=True, text=True).stdout.strip()
    runtime_changes = tracks_helper or case == "literal-computed-abstention"
    assert before_output == "false"
    assert after_output == ("true" if runtime_changes else "false")
    result = rule_changes.compare(repository, before=before, after=after)
    assert result["changedSelectors"] == (["eslint:alpha"] if tracks_helper else [])
    assert rule_changes.compare(repository, before=before, after=after) == result


@pytest.mark.parametrize("suffix", [".cjs", ".mjs"])
@pytest.mark.usefixtures("installed_rule_comparison_compiler")
def test_javascript_extensions_use_native_parser_kind(repository: Path, suffix: str) -> None:
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source=f"packages/typescript/src/alpha{suffix}",
        test="packages/typescript/tests/alpha.test.cjs",
    )
    source = repository / str(entry["source"])
    source.parent.mkdir(parents=True)
    source.write_text("const value = <number>1;", encoding="utf-8")
    test = repository / str(entry["test"])
    test.parent.mkdir(parents=True)
    test.write_text("", encoding="utf-8")
    revision = _write_revision(repository, [entry], "invalid native JavaScript")
    native = subprocess.run(("node", str(source)), cwd=repository, check=False, capture_output=True, text=True)
    assert native.returncode != 0
    with pytest.raises(ValueError, match="Malformed TypeScript source"):
        rule_changes.compare(repository, before=revision, after=revision)


@pytest.mark.parametrize("suffix", [".js", ".mjs", ".cjs"])
@pytest.mark.parametrize(
    ("source_bytes", "native_valid"),
    [
        (b"// \xff\nconsole.log(true);", True),
        (b"const value='\xff';console.log(true);", True),
        (b"\xef\xbb\xbfconsole.log(true);", True),
        ("console.log(true);".encode("utf-16"), False),
    ],
    ids=("replacement-comment", "replacement-string", "utf8-bom", "utf16-rejected"),
)
@pytest.mark.usefixtures("installed_rule_comparison_compiler")
def test_javascript_bytes_match_native_decoding(
    repository: Path, suffix: str, source_bytes: bytes, native_valid: bool
) -> None:
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source=f"packages/typescript/src/alpha{suffix}",
        test="packages/typescript/tests/alpha.test.cjs",
    )
    source = repository / str(entry["source"])
    source.parent.mkdir(parents=True)
    source.write_bytes(source_bytes)
    test = repository / str(entry["test"])
    test.parent.mkdir(parents=True)
    test.write_text("", encoding="utf-8")
    before = _write_revision(repository, [entry], "native JavaScript bytes")
    native = subprocess.run(("node", str(source)), cwd=repository, check=False, capture_output=True, text=True)
    assert (native.returncode == 0) is native_valid
    if not native_valid:
        with pytest.raises(ValueError, match="Malformed TypeScript source"):
            rule_changes.compare(repository, before=before, after=before)
        return
    assert native.stdout.strip() == "true"
    assert rule_changes.compare(repository, before=before, after=before)["changes"] == []
    # Distinct invalid UTF-8 bytes may decode identically; raw Git identity still owns the fingerprint.
    source.write_bytes(
        source_bytes.replace(b"\xff", b"\xfe") if b"\xff" in source_bytes else source_bytes + b"\n// source edit"
    )
    _git(repository, "add", "packages")
    _git(repository, "commit", "-m", "immutable JavaScript byte change")
    after = _git(repository, "rev-parse", "HEAD")
    result = rule_changes.compare(repository, before=before, after=after)
    assert result["changedSelectors"] == ["eslint:alpha"]
    assert rule_changes.compare(repository, before=before, after=after) == result


@pytest.mark.parametrize("owner", ["source", "test"])
@pytest.mark.usefixtures("installed_rule_comparison_compiler")
def test_commonjs_literal_closure_tracks_transitive_owner(repository: Path, owner: str) -> None:
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source="packages/typescript/src/alpha.cjs",
        test="packages/typescript/tests/alpha.test.cjs",
    )
    for field in ("source", "test"):
        path = repository / str(entry[field])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("module.exports=false;", encoding="utf-8")
    selected = repository / str(entry[owner])
    selected.write_text("module.exports=require('../../shared/src/helper.cjs');", encoding="utf-8")
    helper = repository / "packages/shared/src/helper.cjs"
    helper.parent.mkdir(parents=True)
    helper.write_text("module.exports=require('./leaf.cjs');", encoding="utf-8")
    leaf = helper.with_name("leaf.cjs")
    leaf.write_text("module.exports=false;", encoding="utf-8")
    before = _write_revision(repository, [entry], "transitive CommonJS baseline")
    observe = ("node", "--eval", f"console.log(require('./{entry[owner]}'))")
    assert subprocess.run(observe, cwd=repository, check=True, capture_output=True, text=True).stdout.strip() == "false"
    leaf.write_text("module.exports=true;", encoding="utf-8")
    _git(repository, "add", "packages")
    _git(repository, "commit", "-m", "transitive CommonJS helper change")
    after = _git(repository, "rev-parse", "HEAD")
    assert subprocess.run(observe, cwd=repository, check=True, capture_output=True, text=True).stdout.strip() == "true"
    result = rule_changes.compare(repository, before=before, after=after)
    assert result["changedSelectors"] == ["eslint:alpha"]
    assert rule_changes.compare(repository, before=before, after=after) == result


@pytest.mark.usefixtures("installed_rule_comparison_compiler")
def test_commonjs_missing_literal_dependency_fails_actual_gate(repository: Path) -> None:
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source="packages/typescript/src/alpha.cjs",
        test="packages/typescript/tests/alpha.test.cjs",
    )
    for field in ("source", "test"):
        path = repository / str(entry[field])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    source = repository / str(entry["source"])
    source.write_text("module.exports=require('./missing.cjs');", encoding="utf-8")
    revision = _write_revision(repository, [entry], "missing literal CommonJS dependency")
    native = subprocess.run(("node", str(source)), cwd=repository, check=False, capture_output=True, text=True)
    assert native.returncode != 0
    assert "MODULE_NOT_FOUND" in native.stderr
    with pytest.raises(ValueError, match="missing immutable TypeScript import"):
        rule_changes.compare(repository, before=revision, after=revision)


@pytest.mark.parametrize("changed_suffix", [".js", ".ts"])
@pytest.mark.usefixtures("installed_rule_comparison_compiler")
def test_commonjs_explicit_code_target_uses_runtime_file_not_typescript_substitution(
    repository: Path, changed_suffix: str
) -> None:
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source="packages/typescript/src/alpha.cjs",
        test="packages/typescript/tests/alpha.test.cjs",
    )
    for field in ("source", "test"):
        path = repository / str(entry[field])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    package = repository / "packages/typescript/src"
    (package / "alpha.cjs").write_text("module.exports=require('./helper.js');", encoding="utf-8")
    (package / "helper.js").write_text("module.exports=false;", encoding="utf-8")
    (package / "helper.ts").write_text("export default false;", encoding="utf-8")
    before = _write_revision(repository, [entry], "explicit CommonJS runtime target")
    observe = ("node", "--eval", "console.log(require('./packages/typescript/src/alpha.cjs'))")
    assert subprocess.run(observe, cwd=repository, check=True, capture_output=True, text=True).stdout.strip() == "false"
    helper = package / f"helper{changed_suffix}"
    helper.write_text(helper.read_text().replace("false", "true"), encoding="utf-8")
    _git(repository, "add", "packages")
    _git(repository, "commit", "-m", "runtime file versus unrelated type implementation")
    after = _git(repository, "rev-parse", "HEAD")
    positive = changed_suffix == ".js"
    assert subprocess.run(observe, cwd=repository, check=True, capture_output=True, text=True).stdout.strip() == (
        "true" if positive else "false"
    )
    result = rule_changes.compare(repository, before=before, after=after)
    assert result["changedSelectors"] == (["eslint:alpha"] if positive else [])
    assert rule_changes.compare(repository, before=before, after=after) == result


@pytest.mark.parametrize("suffix", [".js", ".mjs", ".cjs", ".ts"])
@pytest.mark.usefixtures("installed_rule_comparison_compiler")
def test_commonjs_supported_explicit_code_extensions_track_exact_native_target(repository: Path, suffix: str) -> None:
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source="packages/typescript/src/alpha.cjs",
        test="packages/typescript/tests/alpha.test.cjs",
    )
    for field in ("source", "test"):
        path = repository / str(entry[field])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    package = repository / "packages/typescript/src"
    (package / "alpha.cjs").write_text(
        f"module.exports=require('./helper{suffix}')" + (".default" if suffix == ".mjs" else "") + ";", encoding="utf-8"
    )
    helper = package / f"helper{suffix}"
    helpers = {
        ".js": "module.exports=false;",
        ".cjs": "module.exports=false;",
        ".mjs": "export default false;",
        ".ts": "const value:boolean=false;module.exports=value;",
    }
    helper.write_text(helpers[suffix], encoding="utf-8")
    before = _write_revision(repository, [entry], "native code extension baseline")
    observe = ("node", "--eval", "console.log(require('./packages/typescript/src/alpha.cjs'))")
    assert subprocess.run(observe, cwd=repository, check=True, capture_output=True, text=True).stdout.strip() == "false"
    helper.write_text(helpers[suffix].replace("false", "true"), encoding="utf-8")
    _git(repository, "add", "packages")
    _git(repository, "commit", "-m", "native exact extension helper change")
    after = _git(repository, "rev-parse", "HEAD")
    assert subprocess.run(observe, cwd=repository, check=True, capture_output=True, text=True).stdout.strip() == "true"
    result = rule_changes.compare(repository, before=before, after=after)
    assert result["changedSelectors"] == ["eslint:alpha"]
    assert rule_changes.compare(repository, before=before, after=after) == result


@pytest.mark.parametrize("owner", ["source", "test"])
@pytest.mark.parametrize(("suffix", "loader"), [(".cjs", "require"), (".mjs", "static"), (".mjs", "dynamic")])
@pytest.mark.usefixtures("installed_rule_comparison_compiler")
def test_literal_runtime_json_dependency_tracks_immutable_leaf(
    repository: Path, suffix: str, owner: str, loader: str
) -> None:
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source=f"packages/typescript/src/alpha{suffix}",
        test=f"packages/typescript/tests/alpha.test{suffix}",
    )
    for field in ("source", "test"):
        path = repository / str(entry[field])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    source = repository / str(entry[owner])
    loaders = {
        "require": "console.log(require('./helper.json'));",
        "static": "import value from './helper.json' with {type:'json'};console.log(value);",
        "dynamic": "console.log((await import('./helper.json',{with:{type:'json'}})).default);",
    }
    source.write_text(loaders[loader], encoding="utf-8")
    helper = source.with_name("helper.json")
    helper.write_text("false", encoding="utf-8")
    before = _write_revision(repository, [entry], "native JSON dependency baseline")
    observe = ("node", str(source))
    assert subprocess.run(observe, cwd=repository, check=True, capture_output=True, text=True).stdout.strip() == "false"
    helper.write_text("true", encoding="utf-8")
    _git(repository, "add", "packages")
    _git(repository, "commit", "-m", "native JSON dependency counterfactual")
    after = _git(repository, "rev-parse", "HEAD")
    assert subprocess.run(observe, cwd=repository, check=True, capture_output=True, text=True).stdout.strip() == "true"
    result = rule_changes.compare(repository, before=before, after=after)
    assert result["changedSelectors"] == ["eslint:alpha"]
    assert rule_changes.compare(repository, before=before, after=after) == result


@pytest.mark.parametrize("leaf_count", [1, 8])
@pytest.mark.usefixtures("installed_rule_comparison_compiler")
def test_reachable_json_leaves_share_bounded_immutable_batches(repository: Path, leaf_count: int) -> None:
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source="packages/typescript/src/alpha.cjs",
        test="packages/typescript/tests/alpha.test.cjs",
    )
    for field in ("source", "test"):
        path = repository / str(entry[field])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    package = repository / "packages/typescript/src"
    (package / "alpha.cjs").write_text(
        "module.exports=" + "+".join(f"require('./leaf{index}.json')" for index in range(leaf_count)) + ";",
        encoding="utf-8",
    )
    for index in range(leaf_count):
        (package / f"leaf{index}.json").write_text(str(index), encoding="utf-8")
    unowned = package / "unowned.json"
    unowned.write_text("not parsed or loaded as code", encoding="utf-8")
    before = _write_revision(repository, [entry], "bounded JSON leaf baseline")
    observe = ("node", "--eval", "console.log(require('./packages/typescript/src/alpha.cjs'))")
    assert subprocess.run(observe, cwd=repository, check=True, capture_output=True, text=True).stdout.strip() == str(
        sum(range(leaf_count))
    )
    for index in range(leaf_count):
        (package / f"leaf{index}.json").write_text(str(index + 10), encoding="utf-8")
    _git(repository, "add", "packages")
    _git(repository, "commit", "-m", "bounded JSON leaf counterfactual")
    after = _git(repository, "rev-parse", "HEAD")
    assert subprocess.run(observe, cwd=repository, check=True, capture_output=True, text=True).stdout.strip() == str(
        sum(range(leaf_count)) + 10 * leaf_count
    )
    calls: list[tuple[tuple[str, ...], bytes]] = []

    def runner(argv: tuple[str, ...], *, cwd: Path, input_bytes: bytes = b"") -> ProcessBinaryResult:
        calls.append((argv, input_bytes))
        return run_binary_process(argv, cwd=cwd, input_bytes=input_bytes)

    result = rule_changes.compare(repository, before=before, after=after, binary_runner=runner)
    assert result["changedSelectors"] == ["eslint:alpha"]
    assert rule_changes.compare(repository, before=before, after=after) == result
    batches = [payload for argv, payload in calls if "cat-file" in argv]
    assert len(batches) == 3  # One unchanged code/artifact batch, then one data-leaf batch per revision.
    assert [len(payload.splitlines()) for payload in batches[1:]] == [leaf_count, leaf_count]
    unowned_oid = _git(repository, "rev-parse", f"{after}:packages/typescript/src/unowned.json").encode()
    assert all(unowned_oid not in payload.splitlines() for payload in batches)


@pytest.mark.parametrize("case", ["absent", "nonregular", "escaping", "oversized"])
@pytest.mark.usefixtures("installed_rule_comparison_compiler")
def test_exact_json_leaf_preserves_immutable_boundary_failures(repository: Path, case: str) -> None:
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source="packages/typescript/src/alpha.cjs",
        test="packages/typescript/tests/alpha.test.cjs",
    )
    for field in ("source", "test"):
        path = repository / str(entry[field])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    source = repository / str(entry["source"])
    helper = source.with_name("helper.json")
    reference = "./helper.json"
    errors = {
        "absent": "missing/nonregular immutable implementation blob",
        "nonregular": "missing/nonregular immutable implementation blob",
        "escaping": "implementation path must be repository-relative",
        "oversized": "immutable Git blob exceeds byte limit",
    }
    if case == "nonregular":
        helper.with_name("actual.json").write_text("false", encoding="utf-8")
        helper.symlink_to("actual.json")
    elif case == "escaping":
        external = repository.parent / f"outside_{repository.name}.json"
        external.write_text("false", encoding="utf-8")
        reference = f"../../../../{external.name}"
    elif case == "oversized":
        helper.write_bytes(b'"' + b"a" * (8 * 1024 * 1024) + b'"')
    source.write_text(f"console.log(typeof require('{reference}'));", encoding="utf-8")
    revision = _write_revision(repository, [entry], "JSON leaf boundary fixture")
    native = subprocess.run(("node", str(source)), cwd=repository, check=False, capture_output=True, text=True)
    assert (native.returncode == 0) is (case != "absent")
    if case == "absent":
        assert "MODULE_NOT_FOUND" in native.stderr
    with pytest.raises(ValueError, match=errors[case]):
        rule_changes.compare(repository, before=revision, after=revision)


@pytest.mark.usefixtures("installed_rule_comparison_compiler")
def test_json_leaf_requires_actual_immutable_byte_identity(repository: Path) -> None:
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source="packages/typescript/src/alpha.cjs",
        test="packages/typescript/tests/alpha.test.cjs",
    )
    for field in ("source", "test"):
        path = repository / str(entry[field])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    source = repository / str(entry["source"])
    source.write_text("console.log(require('./helper.json'));", encoding="utf-8")
    source.with_name("helper.json").write_text("false", encoding="utf-8")
    revision = _write_revision(repository, [entry], "JSON leaf byte identity fixture")
    assert (
        subprocess.run(("node", str(source)), cwd=repository, check=True, capture_output=True, text=True).stdout.strip()
        == "false"
    )
    leaf_oid = _git(repository, "rev-parse", f"{revision}:packages/typescript/src/helper.json").encode()
    intercepted: list[bytes] = []

    def runner(argv: tuple[str, ...], *, cwd: Path, input_bytes: bytes = b"") -> ProcessBinaryResult:
        result = run_binary_process(argv, cwd=cwd, input_bytes=input_bytes)
        if "cat-file" in argv and leaf_oid in input_bytes.splitlines():
            intercepted.append(result.stdout)
            return ProcessBinaryResult(result.returncode, result.stdout.replace(b"\nfalse\n", b"\ntrue \n"))
        return result

    with pytest.raises(ValueError, match="immutable Git batch blob identity mismatch"):
        rule_changes.compare(repository, before=revision, after=revision, binary_runner=runner)
    assert len(intercepted) == 1


def test_missing_python_module_named_json_keeps_owned_import_failure(repository: Path) -> None:
    entry = _rule("alpha")
    entry["source"] = "packages/python/src/engine/alpha.py"
    package = repository / "packages/python/src/engine"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "alpha.py").write_text("import engine.json", encoding="utf-8")
    revision = _write_revision(repository, [entry], "missing Python module named json")
    native = subprocess.run(
        (sys.executable, "-c", "import engine.alpha"), cwd=package.parent, check=False, capture_output=True, text=True
    )
    assert native.returncode != 0
    assert "ModuleNotFoundError" in native.stderr
    with pytest.raises(ValueError, match=r"missing immutable local import: engine\.json"):
        rule_changes.compare(repository, before=revision, after=revision)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"def broken(:\n", id="syntax"),
        pytest.param(b"# coding: unknown-codec\nvalue = 1\n", id="unknown-cookie"),
        pytest.param(b"\xef\xbb\xbf# coding: latin-1\nvalue = 1\n", id="bom-conflict"),
        pytest.param(b'value = "\xff"\n', id="invalid-utf8"),
    ],
)
@pytest.mark.parametrize("owned", [False, True], ids=["unowned", "owned"])
def test_python_byte_errors_follow_immutable_import_ownership(
    repository: Path,
    payload: bytes,
    *,
    owned: bool,
) -> None:
    rule = _rule("owner")
    source = repository / str(rule["source"])
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("from .helper import value\n" if owned else "value = 1\n", encoding="utf-8")
    helper = source.with_name("helper.py" if owned else "unowned.py")
    helper.write_bytes(b"value = 1\n")
    before = _write_revision(repository, [rule], "base")
    helper.write_bytes(payload)
    after = _write_revision(repository, [rule], "malformed unrelated or owned module")

    if owned:
        with pytest.raises(ValueError, match=r"malformed immutable Python|invalid immutable Python source encoding"):
            rule_changes.compare(repository, before=before, after=after)
    else:
        assert rule_changes.compare(repository, before=before, after=after)["changedSelectors"] == []
    blob = _git(repository, "rev-parse", f"{after}:{helper.relative_to(repository).as_posix()}")
    expected_oid = hashlib.sha1(
        b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload,
        usedforsecurity=False,
    ).hexdigest()
    assert blob == expected_oid


def test_valid_python_encoded_dependency_changes_use_raw_blob_identity(repository: Path) -> None:
    rule = _rule("owner")
    source = repository / str(rule["source"])
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("from .helper import value\n", encoding="utf-8")
    helper = source.with_name("helper.py")
    helper.write_bytes(b"# coding: latin-1\nvalue = 1\n")
    before = _write_revision(repository, [rule], "base")
    helper.write_bytes(b"# coding: latin-1\nvalue = 1  # caf\xe9\n")
    after = _write_revision(repository, [rule], "raw native-valid encoded comment changed")

    assert rule_changes.compare(repository, before=before, after=after)["changedSelectors"] == ["python:owner"]


def _prepare_rule_comparison_parser_metadata(repository: Path) -> None:
    authoring = Path(__file__).parents[3]
    (repository / ".node-version").write_bytes((authoring / ".node-version").read_bytes())
    lock = repository / "packages/typescript/package-lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes((authoring / "packages/typescript/package-lock.json").read_bytes())


@dataclass(frozen=True, slots=True)
class _ParserFixturePins:
    node: str
    package: str
    runtime: str


def _rule_comparison_parser_fixture_pins(repository: Path) -> _ParserFixturePins:
    from sarj_standards.libs.json_boundary import parse_json  # ruff: ignore[import-outside-top-level] -- fixture metadata is used only by native parser controls.
    from sarj_standards.libs.typed_containers import is_object_mapping  # ruff: ignore[import-outside-top-level] -- narrow the actual lock at its test parser boundary.

    node = "v" + (repository / ".node-version").read_text().strip().removeprefix("v")
    locked = parse_json((repository / "packages/typescript/package-lock.json").read_text())
    assert is_object_mapping(locked)
    packages = locked["packages"]
    assert is_object_mapping(packages)
    wrapper = packages["node_modules/typescript"]
    runtime = packages["node_modules/@typescript/old"]
    assert is_object_mapping(wrapper)
    assert is_object_mapping(runtime)
    package_pin, runtime_pin = wrapper["version"], runtime["version"]
    assert isinstance(package_pin, str)
    assert isinstance(runtime_pin, str)
    return _ParserFixturePins(node, package_pin, runtime_pin)


@pytest.mark.usefixtures("installed_rule_comparison_compiler")
@pytest.mark.parametrize(
    "case",
    [
        "matching",
        "node",
        "package",
        "runtime",
        "package-name",
        "runtime-name",
        "missing-node",
        "missing-lock",
        "malformed-lock",
        "duplicate-lock",
        "missing-runtime",
    ],
)
def test_rule_comparison_attests_the_declared_authoring_parser(repository: Path, case: str) -> None:
    entry = _rule("alpha")
    entry.update(
        key="eslint:alpha",
        engine="eslint",
        source="packages/typescript/src/alpha.ts",
        test="packages/typescript/tests/alpha.test.ts",
    )
    for field in ("source", "test"):
        path = repository / str(entry[field])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("export const value=false;\n", encoding="utf-8")
    before = _write_revision(repository, [entry], "declared parser baseline")
    (repository / str(entry["source"])).write_text("export const value=true;\n", encoding="utf-8")
    after = _write_revision(repository, [entry], "declared parser changed owner")
    _change_rule_comparison_parser_metadata(repository, case)
    if case == "matching":
        result = rule_changes.compare(repository, before=before, after=after)
        assert result["changedSelectors"] == ["eslint:alpha"]
        assert rule_changes.compare(repository, before=before, after=after) == result
    else:
        with pytest.raises(ValueError, match="rule comparison requires"):
            rule_changes.compare(repository, before=before, after=after)


def test_python_only_comparison_does_not_require_authoring_parser_metadata(repository: Path) -> None:
    before = _write_revision(repository, [_rule("alpha")], "Python-only baseline without parser setup")
    source = repository / "packages/python/src/rules/alpha.py"
    source.write_text("VALUE = True\n")
    after = _write_revision(repository, [_rule("alpha")], "Python-only changed owner")
    assert not (repository / ".node-version").exists()
    assert not (repository / "packages/typescript/package-lock.json").exists()

    def forbidden_parser(argv: tuple[str, ...], *, cwd: Path, input_text: str) -> ProcessResult:
        pytest.fail(f"Python-only comparison invoked Node: {argv}, cwd={cwd}, source={input_text}")

    result = rule_changes.compare(repository, before=before, after=after, parser_runner=forbidden_parser)
    assert result["changedSelectors"] == ["python:alpha"]


def _change_rule_comparison_parser_metadata(repository: Path, case: str) -> None:
    from sarj_standards.libs.json_boundary import parse_json  # ruff: ignore[import-outside-top-level] -- fixture metadata is used only by native parser controls.
    from sarj_standards.libs.typed_containers import is_object_mapping  # ruff: ignore[import-outside-top-level] -- narrow the actual lock at its test parser boundary.

    node = repository / ".node-version"
    lock = repository / "packages/typescript/package-lock.json"
    match case:
        case "matching":
            return
        case "node":
            node.write_text("0.0.0\n")
        case "missing-node":
            node.unlink()
        case "missing-lock":
            lock.unlink()
        case "malformed-lock":
            lock.write_text("{")
        case "duplicate-lock":
            lock.write_text('{"packages":{},"packages":{}}')
        case _:
            payload = parse_json(lock.read_text())
            assert is_object_mapping(payload)
            packages = payload["packages"]
            assert is_object_mapping(packages)
            if case == "missing-runtime":
                payload["packages"] = {
                    key: value for key, value in packages.items() if key != "node_modules/@typescript/old"
                }
            else:
                cases = {
                    "package": ("node_modules/typescript", "version", "0.0.0"),
                    "runtime": ("node_modules/@typescript/old", "version", "0.0.0"),
                    "package-name": ("node_modules/typescript", "name", "other"),
                    "runtime-name": ("node_modules/@typescript/old", "name", "other"),
                }
                key, field, value = cases[case]
                package = packages[key]
                assert is_object_mapping(package)
                package[field] = value
            lock.write_text(json.dumps(payload))
