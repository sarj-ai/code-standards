from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path


def test_comprehension_reuse_advice_stays_out_of_error_baselines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rule = REGISTRY["prefer-walrus-comprehension-filter"]
    example = next(case for case in rule.public_examples() if case.expected_count)
    target = tmp_path / "values.py"
    target.write_text(example.focus_file.source, encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    command = ["check", "--rule", rule.id]
    assert main([*command, str(target)]) == 0
    assert f"{rule.code} warning:" in capsys.readouterr().out
    assert main([*command, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {}


def test_warning_is_excluded_when_baseline_records_a_blocking_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "example.py"
    target.write_text("def render(name: str) -> str: return 'hello ' + name\n\n# ----------------\nerror_value = 2\n")
    baseline = tmp_path / "baseline.json"
    rules = ["check", "--rule", "prefer-fstring-over-concat", "--rule", "no-comment-cruft"]

    assert main([*rules, str(target)]) == 1
    control = capsys.readouterr().out
    assert "SARJ068 " in control
    assert "SARJ016 " in control

    assert main([*rules, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {str(target): {"SARJ016": 1}}
    baseline_output = capsys.readouterr().out
    assert "1 blocking diagnostics over 1 files; 1 warnings excluded" in baseline_output

    assert main([*rules, "--baseline", str(baseline), str(target)]) == 0
    assert "SARJ068 warning:" in capsys.readouterr().out


def test_warning_only_baseline_excludes_the_finding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "example.py"
    target.write_text("def render(name: str) -> str: return 'hello ' + name\n")
    baseline = tmp_path / "baseline.json"

    assert (
        main(
            [
                "check",
                "--rule",
                "prefer-fstring-over-concat",
                "--update-baseline",
                str(baseline),
                str(target),
            ]
        )
        == 0
    )

    assert json.loads(baseline.read_text()) == {}
    assert "0 blocking diagnostics over 0 files; 1 warnings excluded" in capsys.readouterr().out


@pytest.mark.parametrize(
    "rule_id",
    [
        "prefer-or-pattern",
        "prefer-walrus-awaited-none-guard",
        "prefer-walrus-regex-match",
        "prefer-walrus-stream-loop",
        "no-unused-value-marker",
        "require-explicit-contract-implementation",
        "prefer-autospec-for-callable-mock",
        "named-record-at-boundaries",
        "duplicate-adjacent-exception-handler",
        "duplicate-closed-pure-helper",
        "redundant-test-constructor-forwarder",
        "prefer-immutable-module-constant",
        "no-before-validator-input-mutation",
        "prefer-self-type-annotation",
        "require-precise-factory-signature",
        "require-keyword-only-swap-prone-params",
        "prefer-monotonic-for-elapsed-time",
        "prefer-collection-comprehension",
        "prefer-match-value-dispatch",
        "unused-test-factory-option",
        "no-unused-underscored-keyword-parameter",
    ],
)
def test_strict_promotions_block_enter_baselines_and_accept_exact_exceptions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rule_id: str
) -> None:
    rule_type = REGISTRY[rule_id]
    example = next(example for example in rule_type.public_examples() if example.expected_count)
    root = tmp_path.parent / "strict-cli-examples" / rule_id
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'strict-example'\nversion = '1.0'\nrequires-python = '>=3.14'\n"
    )
    for file in example.files:
        path = root / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file.source)
    target = root / example.focus_path
    command = ["check", "--rule", rule_id]
    assert main([*command, str(target)]) == 1
    assert rule_type.code in capsys.readouterr().out
    baseline = root / "baseline.json"
    assert main([*command, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {str(target): {rule_type.code: example.expected_count}}
    capsys.readouterr()
    assert main([*command, "--baseline", str(baseline), str(target)]) == 0
    findings = analyze([rule_id], [target])
    lines = target.read_text().splitlines()
    for line in {finding.line for finding in findings}:
        lines[line - 1] += f"  # sarj-noqa: {rule_type.code} -- deliberate compatibility contract"
    target.write_text("\n".join(lines) + "\n")
    assert main([*command, str(target)]) == 0
    assert rule_type.code not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("rule_id", "source"),
    [
        ("prefer-self-type-annotation", "class Builder:\n    def fluent(self) -> 'Builder': return self\n"),
        (
            "require-precise-factory-signature",
            "from collections.abc import Callable\nclass Result: pass\ndef build(factory: Callable[..., Result]): return factory(size=4)\n",
        ),
        (
            "require-keyword-only-swap-prone-params",
            "def move(source_id: str, target_id: str): return source_id, target_id\n",
        ),
        (
            "prefer-monotonic-for-elapsed-time",
            "import time\ndef measure():\n    start = time.time()\n    work()\n    return time.time() - start\n",
        ),
        (
            "prefer-collection-comprehension",
            "def values(rows):\n    result = {}\n    for row in rows:\n        result[row.key] = row.value\n    return result\n",
        ),
        (
            "prefer-match-value-dispatch",
            "def parse(row):\n    if row.kind == 'json': return json_parser()\n    elif row.kind == 'yaml': return yaml_parser()\n    else: return fallback()\n",
        ),
        (
            "unused-test-factory-option",
            "def _widget(*, size=300):\n    return Widget(size=size)\n_widget()\n_widget(size=300)\n",
        ),
        ("no-unused-underscored-keyword-parameter", "def emit(*, _unused=True): return 'ready'\nemit(_unused=True)\n"),
    ],
)
def test_promoted_rules_keep_unproven_cases_advisory_and_out_of_baselines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rule_id: str, source: str
) -> None:
    root = tmp_path.parent / "advisory-cli-examples" / rule_id
    root.mkdir(parents=True)
    target = root / ("test_widget.py" if rule_id == "unused-test-factory-option" else "service.py")
    target.write_text(source)
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'advisory-example'\nversion = '1.0'\nrequires-python = '>=3.14'\n"
    )
    assert [finding.severity for finding in analyze([rule_id], [target])] == [Severity.WARNING]
    assert main(["check", "--rule", rule_id, str(target)]) == 0
    assert f"{REGISTRY[rule_id].code} warning:" in capsys.readouterr().out
    baseline = root / "baseline.json"
    assert main(["check", "--rule", rule_id, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {}


def test_promoted_repeated_test_body_blocks_and_enters_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "test_examples.py"
    target.write_text(
        "def test_first():\n"
        "    value = build('first')\n"
        "    result = run(value)\n"
        "    assert result is True\n\n"
        "def test_second():\n"
        "    value = build('second')\n"
        "    result = run(value)\n"
        "    assert result is True\n"
    )
    command = ["check", "--rule", "no-repeated-test-body"]

    assert main([*command, str(target)]) == 1
    assert "SARJ066 " in capsys.readouterr().out

    baseline = tmp_path / "baseline.json"
    assert main([*command, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {str(target): {"SARJ066": 1}}


@pytest.mark.parametrize(
    ("rule", "code", "source"),
    [
        ("no-any-mapping-types", "SARJ447", "from typing import Any\ndef details() -> dict[str, Any]: ...\n"),
        (
            "async-cleanup-registered-synchronously",
            "SARJ463",
            "from contextlib import AsyncExitStack\nasync def close():\n    await release()\nasync def run():\n    async with AsyncExitStack() as stack:\n        stack.callback(close)\n",
        ),
        (
            "subprocess-kill-without-reap",
            "SARJ464",
            "import subprocess\ndef run(args):\n    process = subprocess.Popen(args)\n    try:\n        process.communicate(timeout=1)\n    except subprocess.TimeoutExpired:\n        process.kill()\n",
        ),
        (
            "no-impossible-pydantic-field-bounds",
            "SARJ491",
            "from pydantic import BaseModel, Field\nclass Model(BaseModel):\n    value: int = Field(gt=0, lt=1)\n",
        ),
        (
            "no-unknown-pydantic-validator-field",
            "SARJ492",
            "from pydantic import BaseModel, field_validator\nclass Model(BaseModel):\n    value: int\n    @field_validator('missing')\n    @classmethod\n    def check(cls, value: int) -> int: return value\n",
        ),
        (
            "no-conflicting-pydantic-alias-validation",
            "SARJ493",
            "from pydantic import BaseModel, ConfigDict\nclass Model(BaseModel):\n    model_config = ConfigDict(validate_by_alias=False, validate_by_name=False)\n",
        ),
    ],
    ids=(
        "mapping-erasure",
        "dropped-async-cleanup",
        "unreaped-child",
        "empty-field-domain",
        "missing-validator-field",
        "disabled-alias-paths",
    ),
)
def test_typing_campaign_promotions_block_baseline_and_allow_exact_suppression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rule: str, code: str, source: str
) -> None:
    target = tmp_path / "example.py"
    target.write_text(source, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nversion = "1.0"\ndependencies = ["pydantic>=2.11"]\n', encoding="utf-8"
    )
    documentation = REGISTRY[rule].documentation
    assert documentation is not None
    assert documentation.default_level is Severity.ERROR
    findings = analyze([rule], [target])
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    command = ["check", "--rule", rule]
    assert main([*command, str(target)]) == 1
    assert code in capsys.readouterr().out
    baseline = tmp_path / "baseline.json"
    assert main([*command, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {str(target): {code: 1}}
    capsys.readouterr()
    assert main([*command, "--baseline", str(baseline), str(target)]) == 0
    capsys.readouterr()
    lines = source.splitlines()
    lines[findings[0].line - 1] += f"  # sarj-noqa: {code} -- preserve the reviewed compatibility contract"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main([*command, str(target)]) == 0
    assert code not in capsys.readouterr().out


def test_baseline_written_from_absolute_repo_path_is_portable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "src" / "example.py"
    target.parent.mkdir()
    target.write_text("# ----------------\nvalue = 2\n")
    baseline = tmp_path / "baseline.json"
    monkeypatch.chdir(tmp_path)
    command = ["check", "--rule", "no-comment-cruft"]

    assert main([*command, "--update-baseline", str(baseline), str(target.resolve())]) == 0
    assert json.loads(baseline.read_text()) == {"src/example.py": {"SARJ016": 1}}
    assert main([*command, "--baseline", str(baseline), "src/example.py"]) == 0


def test_explicit_missing_input_is_an_operator_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.py"

    assert main(["check", "--rule", "no-comment-cruft", str(missing)]) == 2
    assert f"input does not exist: {missing}" in capsys.readouterr().err


def test_invalid_baseline_is_a_concise_operator_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text("not json", encoding="utf-8")

    status = main(["check", "--rule", "no-comment-cruft", "--baseline", str(baseline), str(source)])

    output = capsys.readouterr()
    assert status == 2
    assert "invalid baseline" in output.err
    assert "Traceback" not in output.err


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("[]", id="array-root"),
        pytest.param("null", id="null-root"),
        pytest.param('{"$TARGET": []}', id="array-count-map"),
        pytest.param('{"$TARGET": {"SARJ016": true}}', id="boolean-allowance"),
        pytest.param('{"$TARGET": {"SARJ016": -1}}', id="negative-allowance"),
        pytest.param('{"$TARGET": {"SARJ016": 1.0}}', id="float-allowance"),
        pytest.param('{"$TARGET": {"SARJ016": "1"}}', id="string-allowance"),
        pytest.param('{"$TARGET": {"SARJ016": null}}', id="null-allowance"),
        pytest.param('{"$TARGET": {"SARJ016": NaN}}', id="non-finite-allowance"),
        pytest.param('{"$TARGET": {"SARJ016": 0, "SARJ016": 1}}', id="duplicate-selector"),
        pytest.param('{"$TARGET": {}, "$TARGET": {"SARJ016": 1}}', id="duplicate-path"),
        pytest.param('{"": {"SARJ016": 1}}', id="empty-path"),
        pytest.param('{"$TARGET": {"": 1}}', id="empty-selector"),
        pytest.param("[" * 2000 + "]" * 2000, id="excessive-nesting"),
    ],
)
def test_malformed_baseline_cannot_suppress_a_blocking_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: str
) -> None:
    source = tmp_path / "example.py"
    source.write_text("# ----------------\nvalue = 2\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(payload.replace('"$TARGET"', json.dumps(str(source))), encoding="utf-8")

    status = main(["check", "--rule", "no-comment-cruft", "--baseline", str(baseline), str(source)])

    output = capsys.readouterr()
    assert status == 2
    assert "invalid baseline" in output.err
    assert "Traceback" not in output.err


def test_baseline_update_requires_an_existing_parent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    baseline = tmp_path / "missing" / "baseline.json"

    status = main(["check", "--rule", "no-comment-cruft", "--update-baseline", str(baseline), str(source)])

    output = capsys.readouterr()
    assert status == 2
    assert "baseline parent does not exist" in output.err
    assert "Traceback" not in output.err


@pytest.mark.parametrize(
    "argv",
    [[], ["check"], ["check", "missing.py"], ["unknown"]],
    ids=("missing-command", "missing-files-and-rule", "missing-rule", "unknown-command"),
)
def test_cli_usage_errors_exit_two(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as failure:
        main(argv)
    assert failure.value.code == 2


@pytest.mark.parametrize(
    "argv",
    [["--help"], ["-h"], ["--version"], ["check", "--help"]],
    ids=("help", "short-help", "version", "check-help"),
)
def test_cli_help_and_version_exit_zero(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 0
    assert "sarj-python-lint" in capsys.readouterr().out


def test_cli_repeated_rules_and_option_like_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "--source.py").write_text("", encoding="utf-8")
    assert main(["check", "--rule", "no-comment-cruft", "--rule", "no-comment-cruft", "--", "--source.py"]) == 0
