from __future__ import annotations

from dataclasses import replace
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.cli.main import main
from sarj_standards.libs.adoption.manifest import ALL_CAPABILITIES, MANIFEST_NAME, Manifest, Profile
from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode, baseline
from sarj_standards.libs.linting.external import analyze_external


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("profile", ["standard", "application"])
@pytest.mark.parametrize("staged", [False, True])
def test_shell_quotation_errors_block_cli_and_preserve_accepted_warning_debt(
    tmp_path: Path, profile: Profile, *, staged: bool
) -> None:
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    subprocess.run(("git", "config", "user.name", "Standards Test"), cwd=tmp_path, check=True)
    subprocess.run(("git", "config", "user.email", "standards@example.invalid"), cwd=tmp_path, check=True)
    source = "#!/bin/bash\nprintf '%s\\n' \\q\n"
    (tmp_path / "case.sh").write_text(source)
    assert main(["--root", str(tmp_path), "setup", "--config", "shellcheck", "--hooks", "none", "--no-install"]) == 0
    manifest = Manifest(
        version=api.__version__,
        configs=("shellcheck",),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
        profile=profile,
        disabled_capabilities=tuple(name for name in ALL_CAPABILITIES if name != "shellcheck"),
    )
    manifest_path = tmp_path / MANIFEST_NAME
    manifest_path.write_text(manifest.render())
    standards = api.Standards(tmp_path)
    raw = standards.analyze(["case.sh"], external=True, mode=api.AnalysisMode.RAW)
    assert raw.completion is Completion.COMPLETE
    assert raw.exit_code == 1
    [finding] = raw.diagnostics
    assert (finding.rule_id, finding.severity) == ("SC1001", Severity.ERROR)
    assert main(["--root", str(tmp_path), "analyze", "--external", "case.sh"]) == 1
    baseline_path = tmp_path / "diagnostic-baseline.json"
    document = baseline.render(
        (replace(finding, severity=Severity.WARNING),),
        bundle_version=api.__version__,
        consumer_base_sha="0" * 40,
        catalog_digest=baseline.bundled_catalog_digest(),
    )
    baseline_path.write_text(document)
    manifest_path.write_text(replace(manifest, diagnostic_baseline=baseline_path.name).render())
    subprocess.run(("git", "add", "."), cwd=tmp_path, check=True)
    subprocess.run(("git", "commit", "-qm", "accepted warning debt"), cwd=tmp_path, check=True)
    (tmp_path / "case.sh").write_text(source + "# unrelated changed line\n")
    subprocess.run(("git", "add", "case.sh"), cwd=tmp_path, check=True)
    selection = ["--staged"] if staged else ["case.sh"]
    assert main(["--root", str(tmp_path), "check", *selection]) == 0
    (tmp_path / "new_case.sh").write_text(source)
    subprocess.run(("git", "add", "new_case.sh"), cwd=tmp_path, check=True)
    selection = ["--staged"] if staged else ["case.sh", "new_case.sh"]
    assert main(["--root", str(tmp_path), "check", *selection]) == 1
    assert baseline_path.read_text() == document  # sarj-noqa: SARJ402 -- Preserve accepted debt bytes.


@pytest.mark.parametrize("relative", [".github/workflows/checks.yml", "cloudbuild.yaml"])
def test_embedded_quotation_errors_map_to_the_owner_without_actionlint_duplicates(
    tmp_path: Path, relative: str
) -> None:
    program = "printf '%s\\n' \\q\n"
    if relative.startswith(".github/"):
        header = "name: checks\n'on': push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - shell: bash\n        run: |\n"
        indentation = "          "
    else:
        header = "steps:\n  - name: bash\n    script: |\n      #!/bin/bash\n"
        indentation = "      "
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + indentation + program)
    reports = analyze_external(
        (str(path),), root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"shellcheck", "actionlint"})
    )
    assert all(report.completion is Completion.COMPLETE for report in reports)
    findings = [item for report in reports for item in report.diagnostics if item.rule_id == "SC1001"]
    [finding] = findings
    assert (finding.source, finding.severity, finding.location.path) == ("shellcheck", Severity.ERROR, relative)
    assert finding.location.region is not None
    assert finding.location.region.start.byte_offset == path.read_bytes().index(b"\\q")
