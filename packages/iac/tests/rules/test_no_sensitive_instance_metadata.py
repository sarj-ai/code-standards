from pathlib import Path

from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze
from sarj_iac_lint.rules.no_sensitive_instance_metadata import NoSensitiveInstanceMetadata


def test_documented_examples() -> None:
    verify_native_rule(NoSensitiveInstanceMetadata, analyze)


def test_secret_payload_in_merged_metadata() -> None:
    source = (
        'resource "google_compute_instance" "vm" {\n'
        "  metadata = merge({\n"
        "    tunnel-token = data.google_secret_manager_secret_version.tunnel.secret_data\n"
        "  }, {})\n}\n"
    )
    assert [d.code for d in NoSensitiveInstanceMetadata().check(Path("main.tf"), source)] == ["SARJ226"]
