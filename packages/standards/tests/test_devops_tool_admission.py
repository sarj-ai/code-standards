from __future__ import annotations

from contextlib import closing
import hashlib
from http.client import HTTPSConnection
from pathlib import Path
import shutil
import subprocess

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.mobile_tools import semgrep_command
from sarj_standards.libs.release.process import credential_free_environment


_FIXTURES = Path(__file__).parent / "fixtures" / "devops-tool-admission"


def _fetch_rule(source: str) -> bytes:
    assert source.startswith("https://raw.githubusercontent.com/semgrep/semgrep-rules/")
    with closing(HTTPSConnection("raw.githubusercontent.com", timeout=30)) as connection:
        connection.request("GET", source.removeprefix("https://raw.githubusercontent.com"))
        with connection.getresponse() as response:
            assert response.status == 200
            return response.read(65_537)


def test_upstream_compose_rules_fail_versionless_admission(tmp_path: Path) -> None:
    evidence = parse_json((_FIXTURES / "evidence.json").read_text(encoding="utf-8"))
    assert isinstance(evidence, dict)
    rules = evidence["rules"]
    assert isinstance(rules, dict)
    rules_path = tmp_path / "rules"
    rules_path.mkdir()
    for name, item in rules.items():
        assert isinstance(item, dict)
        assert isinstance(item["source"], str)
        payload = _fetch_rule(item["source"])
        assert len(payload) <= 65_536
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]
        (rules_path / f"{name}.yaml").write_bytes(payload)
    environment = credential_free_environment()
    environment.update(
        {
            "SEMGREP_LOG_FILE": str(tmp_path / "semgrep.log"),
            "SEMGREP_SETTINGS_FILE": str(tmp_path / "settings.yml"),
            "SEMGREP_ENABLE_VERSION_CHECK": "0",
        }
    )
    executable = shutil.which("uvx")
    assert executable is not None
    process = subprocess.run(
        (
            executable,
            *semgrep_command(offline=False)[1:],
            "scan",
            "--config",
            str(rules_path),
            "--json",
            "--metrics=off",
            "--disable-version-check",
            "--quiet",
            "--strict",
            "--no-rewrite-rule-ids",
            "--jobs=1",
            str(_FIXTURES / "modern-compose.yaml"),
            str(_FIXTURES / "legacy-compose.yaml"),
        ),
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        # Cold Semgrep startup exceeded 30 seconds during full-suite verification.
        timeout=120,
    )
    assert process.returncode == 0, process.stderr
    report = parse_json(process.stdout)
    assert isinstance(report, dict)
    assert report["version"] == "1.186.0"
    assert report["errors"] == []
    paths = report["paths"]
    assert isinstance(paths, dict)
    scanned = paths["scanned"]
    assert isinstance(scanned, list)
    assert set(scanned) == {
        str(_FIXTURES / "legacy-compose.yaml"),
        str(_FIXTURES / "modern-compose.yaml"),
    }
    results = report["results"]
    assert isinstance(results, list)
    hits: dict[str, set[str]] = {}
    for result in results:
        assert isinstance(result, dict)
        path, rule = result["path"], result["check_id"]
        assert isinstance(path, str)
        assert isinstance(rule, str)
        hits.setdefault(Path(path).name, set()).add(rule)
    assert hits.get("legacy-compose.yaml") == set(rules)
    assert hits.get("modern-compose.yaml", set()) == set()
