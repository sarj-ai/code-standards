from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import sarj_standards.cli.main as cli
from sarj_standards.libs.adoption import devops, lifecycle, upgrade
from sarj_standards.libs.adoption.manifest import ALL_CAPABILITIES, MANIFEST_NAME, Manifest, adopted_version, load
from sarj_standards.libs.diagnostics import Completion, Diagnostic, Severity
from sarj_standards.libs.linting.duplicate_code import TEST_GLOBS, analyze_duplicates, parse_jscpd
from sarj_standards.libs.linting.external import ProcessOutput, analyze_external


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sarj_standards.libs.linting.external import ProcessRunner


_BLOCK = "def total(items):\n    paid = [item for item in items if item.paid]\n    return sum(item.amount for item in paid)\n"


def _write(root: Path, name: str, source: str) -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return str(path.resolve())


def _clone(first: str, first_lines: tuple[int, int], second: str, second_lines: tuple[int, int]) -> dict[str, object]:
    return {
        "firstFile": {"name": first, "start": first_lines[0], "end": first_lines[1]},
        "secondFile": {"name": second, "start": second_lines[0], "end": second_lines[1]},
        "format": "python",
        "lines": first_lines[1] - first_lines[0] + 1,
    }


def _report(*clones: dict[str, object]) -> str:
    return json.dumps({"duplicates": list(clones), "statistics": {}})


def _jscpd(report: str | None, *, calls: list[tuple[tuple[str, ...], Path]], version: str = "5.4.0") -> ProcessRunner:
    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        if tuple(argv[1:]) == ("--version",):
            return ProcessOutput(0, f"jscpd {version}\n", "")
        calls.append((tuple(argv), cwd))
        if report is not None:
            output = Path(argv[list(argv).index("--output") + 1])
            (output / "jscpd-report.json").write_text(report)
        return ProcessOutput(0, "", "")

    return runner


def test_every_copy_is_reported_on_its_own_lines_and_names_the_others(tmp_path: Path) -> None:
    orders = _write(tmp_path, "src/orders.py", _BLOCK)
    invoices = _write(tmp_path, "src/invoices.py", "import os\n\n" + _BLOCK)
    refunds = _write(tmp_path, "src/refunds.py", _BLOCK)

    findings = parse_jscpd(
        _report(_clone(orders, (1, 3), invoices, (3, 5)), _clone(orders, (1, 3), refunds, (1, 3))),
        tmp_path,
        allows_path=lambda _path: True,
    )

    by_path = {finding.location.path: finding for finding in findings}
    assert set(by_path) == {"src/orders.py", "src/invoices.py", "src/refunds.py"}
    orders_finding = by_path["src/orders.py"]
    assert orders_finding.severity is Severity.WARNING
    assert f"{orders_finding.source}:{orders_finding.rule_id}" == "jscpd:duplicate-code"
    assert orders_finding.message == ("This 3-line block also appears at src/invoices.py:3-5, src/refunds.py:1-3.")
    assert [item.location.path for item in orders_finding.related] == ["src/invoices.py", "src/refunds.py"]
    region = by_path["src/invoices.py"].location.region
    assert region is not None
    assert (region.start.line, region.end.line) == (2, 4)
    assert region.end.character == len(_BLOCK.splitlines()[-1])


def test_baseline_identity_survives_moving_the_block_and_editing_its_copy(tmp_path: Path) -> None:
    original = _write(tmp_path, "a.py", _BLOCK)
    copy = _write(tmp_path, "b.py", _BLOCK)
    before = parse_jscpd(_report(_clone(original, (1, 3), copy, (1, 3))), tmp_path, allows_path=lambda _path: True)

    moved = _write(tmp_path, "a.py", "import os\n\n\n" + _BLOCK.replace("    ", "        "))
    other_copy = _write(tmp_path, "c.py", _BLOCK)
    after = parse_jscpd(_report(_clone(moved, (4, 6), other_copy, (1, 3))), tmp_path, allows_path=lambda _path: True)

    def fingerprint(findings: Sequence[Diagnostic]) -> str | None:
        return next(item.fingerprint for item in findings if item.location.path == "a.py")

    assert fingerprint(before) == fingerprint(after)


def test_copy_of_an_excluded_file_is_not_reported_on_either_side(tmp_path: Path) -> None:
    source = _write(tmp_path, "src/client.py", _BLOCK)
    generated = _write(tmp_path, "generated/client.py", _BLOCK)

    findings = parse_jscpd(
        _report(_clone(source, (1, 3), generated, (1, 3))),
        tmp_path,
        allows_path=lambda path: not path.startswith("generated/"),
    )

    assert findings == ()


def test_analysis_scans_the_whole_tree_with_the_pinned_detector(tmp_path: Path) -> None:
    first = _write(tmp_path, "a.py", _BLOCK)
    second = _write(tmp_path, "b.py", _BLOCK)
    calls: list[tuple[tuple[str, ...], Path]] = []

    report = analyze_duplicates(
        root=tmp_path,
        paths=("python", "web"),
        allows_path=lambda _path: True,
        runner=_jscpd(_report(_clone(first, (1, 3), second, (1, 3))), calls=calls),
    )

    assert report.completion is Completion.COMPLETE
    assert report.version == "5.4.0"
    assert len(report.diagnostics) == 2
    ((argv, cwd),) = calls
    assert cwd == tmp_path.resolve()
    assert argv[0] == "jscpd"
    assert argv[-2:] == ("python", "web")
    assert argv[argv.index("--min-tokens") + 1] == "50"
    assert argv[argv.index("--ignore") + 1] == ",".join(TEST_GLOBS)


@pytest.mark.parametrize(
    ("report", "version"),
    [
        (None, "5.4.0"),
        ("{not json", "5.4.0"),
        (json.dumps({"duplicates": [{"firstFile": {}}]}), "5.4.0"),
        (_report(), "5.3.3"),
    ],
    ids=["missing-report", "malformed-json", "incomplete-clone", "unpinned-version"],
)
def test_broken_detector_output_fails_the_analysis(tmp_path: Path, report: str | None, version: str) -> None:
    result = analyze_duplicates(
        root=tmp_path,
        paths=(".",),
        allows_path=lambda _path: True,
        runner=_jscpd(report, calls=[], version=version),
    )

    assert result.completion is Completion.FAILED
    assert result.issues


@pytest.mark.parametrize(
    ("name", "lines"),
    [("../outside.py", (1, 3)), ("a.py", (2, 9)), ("a.py", (3, 1))],
    ids=["outside-repository", "past-end-of-file", "reversed-range"],
)
def test_reported_location_must_exist_in_the_repository(tmp_path: Path, name: str, lines: tuple[int, int]) -> None:
    _write(tmp_path, "a.py", _BLOCK)
    _write(tmp_path.parent, "outside.py", _BLOCK)
    copy = _write(tmp_path, "b.py", _BLOCK)

    with pytest.raises(ValueError, match="jscpd reported"):
        parse_jscpd(
            _report(_clone(str((tmp_path / name).resolve()), lines, copy, (1, 3))),
            tmp_path,
            allows_path=lambda _path: True,
        )


def test_enabled_capability_scans_the_tree_not_the_changed_files(tmp_path: Path) -> None:
    _write(tmp_path, "src/changed.py", _BLOCK)
    calls: list[tuple[tuple[str, ...], Path]] = []

    reports = analyze_external(
        ("src/changed.py",),
        root=tmp_path,
        trust="trusted",
        runner=_jscpd(_report(), calls=calls),
        capabilities=frozenset({"jscpd"}),
    )

    assert [report.name for report in reports] == ["jscpd"]
    assert calls[0][0][-1] == "."


def test_detector_is_opt_in_for_new_and_upgraded_manifests() -> None:
    def manifest(version: str, disabled: tuple[str, ...]) -> Manifest:
        return Manifest(
            version=version, configs=("ruff",), python_dest=".", typescript_dest=".", disabled_capabilities=disabled
        )

    fresh = Manifest(version="8.43.0", configs=("ruff",), python_dest=".", typescript_dest=".")
    assert "jscpd" not in fresh.enabled_capabilities
    assert "jscpd" in manifest("8.43.0", ()).enabled_capabilities
    assert "jscpd" not in manifest("8.42.2", ()).enabled_capabilities


def test_setup_preserves_the_detector_choice(tmp_path: Path) -> None:
    def setup() -> tuple[str, ...]:
        assert cli.main(["--root", str(tmp_path), "setup", "--no-install"]) == 0
        adopted = load(tmp_path)
        assert adopted is not None
        return adopted.disabled_capabilities

    (tmp_path / "package.json").write_text('{"name":"fixture"}\n')
    assert "jscpd" in setup()
    path = tmp_path / MANIFEST_NAME
    path.write_text(path.read_text().replace('  "jscpd",\n', ""))
    assert "jscpd" not in setup()


def test_upgrade_from_an_older_bundle_keeps_the_detector_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    others = [name for name in ALL_CAPABILITIES if name != "jscpd"]
    (tmp_path / MANIFEST_NAME).write_text(
        f'schema = 4\nbundle = "8.42.2"\n[capabilities]\ndisable = {json.dumps(others)}\n[hooks]\nmanager = "none"\n'
    )

    def install(_commands: Iterable[lifecycle.Command]) -> int:
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- skip native tool installation while exercising the real manifest upgrade.
        lifecycle, "execute", install
    )

    assert upgrade.apply(upgrade.build_plan(tmp_path)) == 0

    upgraded = load(tmp_path)
    assert upgraded is not None
    assert upgraded.version == adopted_version()
    assert "jscpd" not in upgraded.enabled_capabilities


def test_setup_installs_the_detector_only_when_enabled(tmp_path: Path) -> None:
    assert devops.required_tools(tmp_path, (), capabilities=("jscpd",)) == ("jscpd",)
    assert devops.required_tools(tmp_path, (), capabilities=("ruff",)) == ()
