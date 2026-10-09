from __future__ import annotations

import hashlib
from importlib.metadata import version
from pathlib import Path
import subprocess
import sys

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


_FIXTURES = Path(__file__).parent / "fixtures" / "devops-tool-admission"


def test_upstream_compose_rules_fail_versionless_admission(tmp_path: Path) -> None:
    assert version("semgrep") == "1.178.0"
    evidence = parse_json((_FIXTURES / "evidence.json").read_text(encoding="utf-8"))
    assert is_object_mapping(evidence)
    rules = evidence["rules"]
    assert is_object_mapping(rules)
    for name, item in rules.items():
        assert isinstance(name, str)
        assert is_object_mapping(item)
        payload = (_FIXTURES / "semgrep" / f"{name}.yaml").read_bytes()
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]
    environment = {
        "PATH": "/usr/bin:/bin",
        "SEMGREP_LOG_FILE": str(tmp_path / "semgrep.log"),
        "SEMGREP_SETTINGS_FILE": str(tmp_path / "settings.yml"),
        "SEMGREP_ENABLE_VERSION_CHECK": "0",
    }
    process = subprocess.run(
        (
            str(Path(sys.executable).parent / "semgrep"),
            "scan",
            "--config",
            str(_FIXTURES / "semgrep"),
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
    assert is_object_mapping(report)
    assert report["errors"] == []
    paths = report["paths"]
    assert is_object_mapping(paths)
    scanned = paths["scanned"]
    assert is_object_list(scanned)
    assert set(scanned) == {
        str(_FIXTURES / "legacy-compose.yaml"),
        str(_FIXTURES / "modern-compose.yaml"),
    }
    results = report["results"]
    assert is_object_list(results)
    hits: dict[str, set[str]] = {}
    for result in results:
        assert is_object_mapping(result)
        path, rule = result["path"], result["check_id"]
        assert isinstance(path, str)
        assert isinstance(rule, str)
        hits.setdefault(Path(path).name, set()).add(rule)
    assert hits.get("legacy-compose.yaml") == set(rules)
    assert hits.get("modern-compose.yaml", set()) == set()
