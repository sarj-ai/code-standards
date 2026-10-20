from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import ExclusionOverride, Manifest
from sarj_standards.libs.diagnostics import Completion, TrustMode, baseline
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.external import ProcessOutput, analyze_external, run_process
from sarj_standards.libs.linting.policy import Policy


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


_CONFIG = """[lint]
preview = true
select = ["banned-api"]
[lint.flake8-tidy-imports.banned-api]
"typing.cast".msg = "Prefer discriminated unions or `isinstance` narrowing over `cast`."
"os.getenv".msg = "Use settings."
"""


@pytest.mark.parametrize(
    "source",
    [
        "from typing import cast  # ruff: ignore[banned-api]\nvalue = cast(object, 1)\n",
        "from typing import cast  # noqa: TID251\nvalue = cast(object, 1)\n",
        "from typing import cast  # noqa\nvalue = cast(object, 1)\n",
        "from typing import cast  # ruff: ignore[banned-api] -- external boundary\nvalue = cast(object, 1)\n",
        "# ruff: file-ignore[banned-api]\nfrom typing import cast\nvalue = cast(object, 1)\n",
        "# ruff: noqa: TID251\nfrom typing import cast\nvalue = cast(object, 1)\n",
        "# ruff: disable[banned-api]\nfrom typing import cast\nvalue = cast(object, 1)\n# ruff: enable[banned-api]\n",
        "from typing_extensions import cast as coerce  # ruff: ignore[banned-api]\nvalue = coerce(object, 1)\n",
        "import typing as t\nvalue = t.cast(object, 1)  # ruff: ignore[banned-api]\n",
        "from typing import (\n    cast,  # ruff: ignore[banned-api]\n)\nvalue = cast(object, 1)\n",
        "from typing import cast\nvalue = cast(object, 1)\n",
        "from typing import caſt as coerce  # ruff: ignore[banned-api]\nvalue = coerce(object, 1)\n",
    ],
)
def test_cast_ban_cannot_be_waived_by_source_comments(tmp_path: Path, source: str) -> None:
    path = tmp_path / "app.py"
    path.write_text(source, encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(_CONFIG, encoding="utf-8")

    reports = analyze_external([str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}))

    assert len(reports) == 1
    assert reports[0].completion is Completion.COMPLETE
    findings = tuple(item for item in reports[0].diagnostics if "cast` is banned" in item.message)
    assert len(findings) == 1
    assert "cast` is banned" in findings[0].message
    assert findings[0].source == "ruff"
    assert not baseline.is_baselineable(findings[0])


def test_existing_import_baseline_cannot_authorize_future_casts(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("from typing import cast  # ruff: ignore[banned-api]\nvalue = cast(object, 1)\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(_CONFIG, encoding="utf-8")
    tools = analyze_external([str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}))
    report = report_from_tools(tmp_path, tools)
    fingerprint = report.diagnostics[0].fingerprint
    assert fingerprint is not None

    active = api._without_baselined_diagnostics(report, {fingerprint: 1})  # ruff: ignore[private-member-access] -- verify the canonical baseline filter.  # pyright: ignore[reportPrivateUsage]

    assert len(active.diagnostics) == 1
    assert '"diagnostics": []' in baseline.render(report.diagnostics)


def test_cast_ban_uses_packaged_policy_despite_consumer_per_file_ignore(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("from typing import cast\nvalue = cast(object, 1)\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(
        _CONFIG + '\n[lint.per-file-ignores]\n"app.py" = ["banned-api"]\n', encoding="utf-8"
    )

    reports = analyze_external([str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}))

    assert reports[0].completion is Completion.COMPLETE
    assert len(reports[0].diagnostics) == 1


@pytest.mark.parametrize(
    "source",
    [
        "import os\nvalue = os.getenv('VENDOR_SETTING')  # ruff: ignore[banned-api] -- vendor boundary\n",
        "def cast(value):\n    return value\nvalue = cast(1)\n",
        "text = 'from typing import cast  # noqa: TID251'\n",
        "# from typing import cast\nvalue = 1\n",
    ],
)
def test_other_api_exceptions_and_non_code_casts_remain_valid(tmp_path: Path, source: str) -> None:
    path = tmp_path / "app.py"
    path.write_text(source, encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(_CONFIG, encoding="utf-8")

    reports = analyze_external([str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}))

    assert reports[0].completion is Completion.COMPLETE
    assert reports[0].diagnostics == ()


def test_cast_policy_execution_failure_is_not_a_clean_result(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("from typing import cast  # ruff: ignore[banned-api]\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(_CONFIG, encoding="utf-8")

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        if "--ignore-noqa" in argv:
            return ProcessOutput(2, "", "cast policy failed")
        return run_process(argv, cwd=cwd)

    reports = analyze_external(
        [str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}), runner=runner
    )

    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].message == "cast policy failed"


@pytest.mark.parametrize(
    "source",
    [
        "from typing import *  # ruff: ignore[wildcard-import]\nvalue = cast(object, 1)\n",
        "from typing_extensions import *  # ruff: ignore[wildcard-import]\nvalue = cast(object, 1)\n",
        'import typing\nvalue = getattr(typing, "cast")(object, 1)  # ruff: ignore[getattr-with-constant]\n',
        'import typing_extensions as t\nvalue = getattr(t, "cast")(object, 1)\n',
        'import typing\nvalue = getattr(typing, "cast", None)(object, 1)\n',
        'import typing\nvalue = getattr(typing, "ca" "st")(object, 1)\n',
        'import typing\nvalue = getattr(typing, "ca" + "st")(object, 1)\n',
        'import typing\nvalue = getattr(typing, f"cast")(object, 1)\n',
        'import typing\nvalue = typing.__dict__["cast"](object, 1)\n',
        'import typing_extensions as t\nvalue = vars(t)["cast"](object, 1)\n',
        'import typing\nvalue = typing.__getattribute__("cast")(object, 1)\n',
    ],
    ids=[
        "wildcard",
        "extensions-wildcard",
        "literal-reflection",
        "extensions-alias",
        "fallback",
        "concatenation",
        "literal-addition",
        "static-fstring",
        "module-dict",
        "module-vars",
        "module-getattribute",
    ],
)
def test_indirect_static_cast_access_cannot_bypass_native_policy(tmp_path: Path, source: str) -> None:
    path = tmp_path / "app.py"
    path.write_text(source, encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(_CONFIG, encoding="utf-8")

    reports = analyze_external([str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}))

    assert reports[0].completion is Completion.COMPLETE
    findings = reports[0].diagnostics
    assert len(findings) == 1
    assert findings[0].rule_id == "banned-api"
    assert "cast`" in findings[0].message
    assert "required-cast-policy" in findings[0].tags
    assert not baseline.is_baselineable(findings[0])


@pytest.mark.parametrize("scoped", [False, True], ids=["global", "per-path"])
def test_rule_exclusions_cannot_waive_cast_but_preserve_other_api_exceptions(tmp_path: Path, scoped: bool) -> None:
    path = tmp_path / "app.py"
    path.write_text("from typing import cast\nimport os\nvalue = os.getenv('VENDOR_SETTING')\n", encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(_CONFIG, encoding="utf-8")
    excluded = ("ruff:banned-api", "ruff:TID251")
    manifest = Manifest(
        version=api.__version__,
        configs=(),
        python_dest=".",
        typescript_dest=".",
        excluded_rules=() if scoped else excluded,
        exclusion_overrides=(ExclusionOverride(("app.py",), excluded, "Vendor boundary"),) if scoped else (),
    )
    reports = analyze_external([str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}))
    assert len(reports[0].diagnostics) == 2

    findings = Policy.from_manifest(tmp_path, manifest).filter_diagnostics(reports[0].diagnostics)

    assert len(findings) == 1
    assert "cast` is banned" in findings[0].message


@pytest.mark.parametrize("statement", ["from typing import *", 'import typing\nvalue = getattr(typing, "cast")'])
def test_cast_evidence_takes_precedence_over_generic_syntax_finding(tmp_path: Path, statement: str) -> None:
    path = tmp_path / "app.py"
    path.write_text(statement + "\n", encoding="utf-8")
    config = _CONFIG.replace(
        'select = ["banned-api"]', 'select = ["banned-api", "wildcard-import", "getattr-with-constant"]'
    )
    (tmp_path / "ruff.toml").write_text(config, encoding="utf-8")

    reports = analyze_external([str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}))

    assert reports[0].completion is Completion.COMPLETE
    assert len(reports[0].diagnostics) == 1
    assert reports[0].diagnostics[0].rule_id == "banned-api"


def test_source_disappearing_after_native_execution_is_incomplete(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text('import typing\nvalue = getattr(typing, "cast")\n', encoding="utf-8")
    (tmp_path / "ruff.toml").write_text(_CONFIG, encoding="utf-8")

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        result = run_process(argv, cwd=cwd)
        if "--ignore-noqa" in argv:
            path.unlink()
        return result

    reports = analyze_external(
        [str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}), runner=runner
    )

    assert reports[0].completion is Completion.FAILED
    assert reports[0].issues[0].kind == "source-proof-failure"


def test_multiline_reflection_keeps_utf16_and_crlf_source_coordinates(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    source = 'import typing\r\ntext = "🎯"; value = getattr(\r\n    typing, "cast"\r\n)\r\n'
    path.write_bytes(source.encode())
    (tmp_path / "ruff.toml").write_text(_CONFIG, encoding="utf-8")

    reports = analyze_external([str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}))

    assert reports[0].completion is Completion.COMPLETE
    finding = reports[0].diagnostics[0]
    region = finding.location.region
    assert region is not None
    assert (region.start.line, region.start.character) == (1, 21)
    assert (region.end.line, region.end.character) == (3, 1)
    assert source.encode()[region.start.byte_offset : region.end.byte_offset].decode().startswith("getattr(")


def test_utf8_bom_does_not_shift_indirect_access_byte_coordinates(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    source = "from typing import *\n".encode("utf-8-sig")
    path.write_bytes(source)
    (tmp_path / "ruff.toml").write_text(_CONFIG, encoding="utf-8")

    reports = analyze_external([str(path)], root=tmp_path, trust=TrustMode.TRUSTED, capabilities=frozenset({"ruff"}))

    assert reports[0].completion is Completion.COMPLETE
    region = reports[0].diagnostics[0].location.region
    assert region is not None
    assert (region.start.line, region.start.character) == (0, 0)
    assert source[region.start.byte_offset : region.end.byte_offset] == b"from typing import *"
