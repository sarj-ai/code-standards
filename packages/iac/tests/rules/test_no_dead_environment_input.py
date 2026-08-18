from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_iac_lint.__main__ import main
from sarj_iac_lint.rule_base import is_suppressed
from sarj_iac_lint.rules.no_dead_environment_input import NoDeadEnvironmentInput


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_iac_lint.rule_base import Diagnostic, RuleExample


_PUBLIC_EXAMPLES = NoDeadEnvironmentInput.public_examples()

_DOCUMENTATION = NoDeadEnvironmentInput.documentation
assert _DOCUMENTATION is not None
_EXAMPLES = _DOCUMENTATION.examples

_DECLARED_BOOL = 'variable "pagerduty_enabled" {\n  type    = string\n  default = "true"\n}\n'
_DECLARED_TIER = 'variable "redis_tier" {\n  type = string\n}\n'
_DECLARED_REGION = 'variable "region" {\n  type = string\n}\n'
_REGION_ASSIGNMENT = 'region = "me-central2"\n'
_TFVARS_NAME = "terraform.tfvars"


def _write_root(tmp_path: Path, variables: str, envs: dict[str, str]) -> Path:
    root = tmp_path / "stack"
    root.mkdir()
    _ = (root / "variables.tf").write_text(variables, encoding="utf-8")
    for env, tfvars in envs.items():
        env_dir = root / "env" / env
        env_dir.mkdir(parents=True)
        _ = (env_dir / _TFVARS_NAME).write_text(tfvars, encoding="utf-8")
    return root


def _check_file(path: Path) -> list[Diagnostic]:
    return NoDeadEnvironmentInput().check(path, path.read_text(encoding="utf-8"))


def _check_env(root: Path, env: str) -> list[Diagnostic]:
    return _check_file(root / "env" / env / _TFVARS_NAME)


@pytest.mark.parametrize(
    "example",
    _EXAMPLES,
    ids=tuple(example.example_id for example in _EXAMPLES),
)
def test_documentation_examples_are_executable(example: RuleExample, tmp_path: Path) -> None:
    for file in example.files:
        target = tmp_path / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = target.write_text(file.source, encoding="utf-8")
    focus = tmp_path / example.focus_path

    findings = NoDeadEnvironmentInput().check(focus, example.focus_file.source)

    assert len(findings) == example.expected_count


def test_public_examples_cover_both_outcomes() -> None:
    assert {example.outcome for example in _PUBLIC_EXAMPLES} == {"match", "no-match"}


def test_flags_a_value_constant_in_every_environment(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_BOOL,
        {"dev": 'pagerduty_enabled = "false"\n', "prod": 'pagerduty_enabled = "false"\n'},
    )
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert "constant-everywhere" in diags[0].message
    assert diags[0].code == "SARJ205"
    assert "dev, prod" in diags[0].message


def test_constant_everywhere_reports_in_each_environment_file(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_BOOL,
        {"dev": 'pagerduty_enabled = "false"\n', "prod": 'pagerduty_enabled = "false"\n'},
    )
    for env in ("dev", "prod"):
        diags = _check_env(root, env)
        assert len(diags) == 1
        assert diags[0].path == root / "env" / env / _TFVARS_NAME


def test_divergent_values_are_not_flagged(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_TIER,
        {"dev": 'redis_tier = "BASIC"\n', "prod": 'redis_tier = "STANDARD_HA"\n'},
    )
    assert _check_env(root, "dev") == []
    assert _check_env(root, "prod") == []


def test_a_value_assigned_in_only_some_environments_is_not_constant(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_BOOL,
        {"dev": 'pagerduty_enabled = "false"\n', "prod": "\n", "sandbox": 'pagerduty_enabled = "false"\n'},
    )
    assert _check_env(root, "dev") == []


def test_string_false_and_bare_false_compare_equal(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_BOOL,
        {"dev": "pagerduty_enabled = false\n", "prod": 'pagerduty_enabled = "false"\n'},
    )
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert "constant-everywhere" in diags[0].message


def test_numbers_compare_numerically_across_notations(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "replicas" {\n  type = number\n}\n',
        {"dev": "replicas = 1\n", "prod": "replicas = 1.0\n", "sandbox": 'replicas = "1"\n'},
    )
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert "required-but-constant" in diags[0].message


def test_bool_never_equals_number(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "flag" {\n  type = bool\n}\n',
        {"dev": "flag = true\n", "prod": "flag = 1\n"},
    )
    assert _check_env(root, "dev") == []


def test_lists_compare_structurally_not_textually(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "zones" {\n  type = list(string)\n}\n',
        {"dev": 'zones = ["a", "b"]\n', "prod": 'zones = [ "a" ,"b" , ]\n'},
    )
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert "required-but-constant" in diags[0].message


def test_reordered_list_items_are_a_real_difference(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "zones" {\n  type = list(string)\n}\n',
        {"dev": 'zones = ["a", "b"]\n', "prod": 'zones = ["b", "a"]\n'},
    )
    assert _check_env(root, "dev") == []


def test_maps_compare_by_sorted_keys(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "labels" {\n  type = map(string)\n}\n',
        {"dev": 'labels = { team = "voice", tier = "gold" }\n', "prod": 'labels = { tier = "gold", team = "voice" }\n'},
    )
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert "required-but-constant" in diags[0].message


def test_identical_heredocs_stay_opaque_and_unflagged(tmp_path: Path) -> None:
    tfvars = 'policy = <<-EOT\n  {"rule": "allow"}\nEOT\n'
    root = _write_root(tmp_path, 'variable "policy" {\n  type = string\n}\n', {"dev": tfvars, "prod": tfvars})
    assert _check_env(root, "dev") == []


def test_flags_an_assignment_equal_to_the_declared_default(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "text_llm_enable_thinking" {\n  type    = bool\n  default = true\n}\n',
        {"dev": "text_llm_enable_thinking = true\n", "prod": "text_llm_enable_thinking = true\n"},
    )
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert "equals-default" in diags[0].message


def test_an_overriding_environment_is_never_itself_flagged(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "text_llm_enable_thinking" {\n  type    = bool\n  default = true\n}\n',
        {"dev": "text_llm_enable_thinking = true\n", "prod": "text_llm_enable_thinking = false\n"},
    )
    assert _check_env(root, "prod") == []


def test_an_assignment_differing_from_the_default_is_not_flagged(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "gke_deletion_protection" {\n  type    = bool\n  default = true\n}\n',
        {"dev": "gke_deletion_protection = false\n"},
    )
    assert _check_env(root, "dev") == []


def test_required_but_constant_names_the_missing_default(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "region" {\n  type = string\n}\n',
        {"dev": 'region = "me-central2"\n', "prod": 'region = "me-central2"\n'},
    )
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert "required-but-constant" in diags[0].message
    assert "`region`" in diags[0].message
    assert "dev, prod" in diags[0].message


def test_flags_an_orphaned_key_with_no_declaration(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_TIER,
        {"dev": 'redis_tier = "BASIC"\ngke_enabled = true\n', "prod": 'redis_tier = "STANDARD_HA"\n'},
    )
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert "orphaned-key" in diags[0].message
    assert "`gke_enabled`" in diags[0].message
    assert (diags[0].line, diags[0].col) == (2, 1)


def test_declared_assignments_are_not_orphans(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_TIER,
        {"dev": 'redis_tier = "BASIC"\n', "prod": 'redis_tier = "STANDARD_HA"\n'},
    )
    assert _check_env(root, "dev") == []


def test_never_flags_a_variable_declared_but_never_assigned(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_TIER + 'variable "plumbing_only" {\n  type = string\n}\n',
        {"dev": 'redis_tier = "BASIC"\n', "prod": 'redis_tier = "STANDARD_HA"\n'},
    )
    assert _check_env(root, "dev") == []
    assert _check_env(root, "prod") == []


def test_a_single_environment_root_gets_no_cross_environment_findings(tmp_path: Path) -> None:
    root = _write_root(tmp_path, _DECLARED_TIER, {"dev": 'redis_tier = "BASIC"\n'})
    assert _check_env(root, "dev") == []


def test_a_single_environment_root_still_gets_equals_default_and_orphans(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "tier" {\n  type    = string\n  default = "BASIC"\n}\n',
        {"dev": 'tier = "BASIC"\nghost = 1\n'},
    )
    messages = [diag.message for diag in _check_env(root, "dev")]
    assert len(messages) == 2
    assert any("equals-default" in message for message in messages)
    assert any("orphaned-key" in message for message in messages)


def test_root_level_tfvars_layout_is_supported(tmp_path: Path) -> None:
    root = tmp_path / "stack"
    root.mkdir()
    _ = (root / "variables.tf").write_text(_DECLARED_BOOL, encoding="utf-8")
    _ = (root / "dev.tfvars").write_text('pagerduty_enabled = "false"\n', encoding="utf-8")
    _ = (root / "prod.tfvars").write_text('pagerduty_enabled = "false"\n', encoding="utf-8")
    diags = _check_file(root / "dev.tfvars")
    assert len(diags) == 1
    assert "constant-everywhere" in diags[0].message


def test_a_tfvars_without_a_variable_declaring_root_produces_nothing(tmp_path: Path) -> None:
    orphan_dir = tmp_path / "fixtures"
    orphan_dir.mkdir()
    tfvars = orphan_dir / "dev.tfvars"
    _ = tfvars.write_text("anything = true\n", encoding="utf-8")
    assert _check_file(tfvars) == []


def test_non_tfvars_files_are_ignored(tmp_path: Path) -> None:
    tf = tmp_path / "main.tf"
    _ = tf.write_text('variable "x" {\n  default = 1\n}\n', encoding="utf-8")
    assert NoDeadEnvironmentInput().check(tf, tf.read_text(encoding="utf-8")) == []


def test_an_envs_manifest_secret_environment_makes_the_root_blind(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_BOOL,
        {"dev": 'pagerduty_enabled = "false"\n', "preview": 'pagerduty_enabled = "false"\n'},
    )
    manifest = {
        "dev": {"tfvars_secret": "deployment-tfvars"},
        "preview": {"tfvars_secret": "deployment-tfvars"},
        "prod": {"tfvars_secret": "production-tfvars"},
    }
    _ = (root / "envs.json").write_text(json.dumps(manifest), encoding="utf-8")
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert "blind-environment" in diags[0].message
    assert "`prod`" in diags[0].message
    assert "production-tfvars" in diags[0].message
    assert "constant-everywhere: `" not in diags[0].message


def test_the_blind_error_lands_once_on_the_anchor_file(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_BOOL,
        {"dev": 'pagerduty_enabled = "false"\n', "preview": 'pagerduty_enabled = "false"\n'},
    )
    _ = (root / "envs.json").write_text('{"prod": {"tfvars_secret": "production-tfvars"}}', encoding="utf-8")
    dev_diags = _check_env(root, "dev")
    assert len(dev_diags) == 1
    assert (dev_diags[0].line, dev_diags[0].col) == (1, 1)
    assert _check_env(root, "preview") == []


def test_a_sibling_environment_directory_without_tfvars_is_blind(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_BOOL,
        {"dev": 'pagerduty_enabled = "false"\n', "prod": 'pagerduty_enabled = "false"\n'},
    )
    (root / "env" / "staging").mkdir()
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert "blind-environment" in diags[0].message
    assert "staging" in diags[0].message


def test_a_json_tfvars_environment_is_blind_not_half_read(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_BOOL,
        {"dev": 'pagerduty_enabled = "false"\n', "prod": 'pagerduty_enabled = "false"\n'},
    )
    staging = root / "env" / "staging"
    staging.mkdir()
    _ = (staging / "terraform.tfvars.json").write_text('{"pagerduty_enabled": "false"}', encoding="utf-8")
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert "blind-environment" in diags[0].message
    assert "JSON" in diags[0].message


def test_blind_roots_keep_only_the_declaration_based_finding(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "tier" {\n  type    = string\n  default = "BASIC"\n}\n',
        {"dev": 'tier = "BASIC"\nghost = 1\n', "preview": 'tier = "BASIC"\n'},
    )
    _ = (root / "envs.json").write_text('{"prod": {"tfvars_secret": "production-tfvars"}}', encoding="utf-8")
    dev_messages = [diag.message for diag in _check_env(root, "dev")]
    assert len(dev_messages) == 2
    assert any("blind-environment" in message for message in dev_messages)
    assert any("orphaned-key" in message for message in dev_messages)
    assert not any(message.startswith(("equals-default:", "constant-everywhere:")) for message in dev_messages)


def test_an_unparseable_envs_manifest_fails_loud(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_BOOL,
        {"dev": 'pagerduty_enabled = "false"\n', "prod": 'pagerduty_enabled = "false"\n'},
    )
    _ = (root / "envs.json").write_text("{not json", encoding="utf-8")
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert "blind-environment" in diags[0].message
    assert "cannot be parsed" in diags[0].message


def test_reports_the_assignment_line_and_column(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_BOOL,
        {"dev": '# environment inputs\n\npagerduty_enabled = "false"\n', "prod": 'pagerduty_enabled = "false"\n'},
    )
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert (diags[0].line, diags[0].col) == (3, 1)


def test_diagnostics_are_in_source_order(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "tier" {\n  type    = string\n  default = "BASIC"\n}\n',
        {"dev": 'ghost = 1\ntier = "BASIC"\n', "prod": 'tier = "BASIC"\n'},
    )
    diags = _check_env(root, "dev")
    assert [diag.line for diag in diags] == sorted(diag.line for diag in diags)


def test_a_noqa_on_the_assignment_line_suppresses(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_BOOL,
        {
            "dev": 'pagerduty_enabled = "false"  # sarj-noqa: SARJ205 — fail-closed paging flag\n',
            "prod": 'pagerduty_enabled = "false"\n',
        },
    )
    source = (root / "env" / "dev" / _TFVARS_NAME).read_text(encoding="utf-8")
    diags = _check_env(root, "dev")
    assert len(diags) == 1
    assert is_suppressed(source.splitlines(), diags[0].line, diags[0].code)


def test_cli_run_over_the_whole_root_reports_the_blind_error_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_BOOL,
        {"dev": 'pagerduty_enabled = "false"\n', "preview": 'pagerduty_enabled = "false"\n'},
    )
    _ = (root / "envs.json").write_text('{"prod": {"tfvars_secret": "production-tfvars"}}', encoding="utf-8")

    rc = main(["check", "--rule", "no-dead-environment-input", str(root)])

    out = capsys.readouterr().out
    assert rc == 1
    assert out.count("blind-environment") == 1
    assert "constant-everywhere: `" not in out


def test_cli_noqa_suppresses_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_TIER,
        {"dev": "gke_enabled = true  # sarj-noqa: SARJ205\n", "prod": 'redis_tier = "BASIC"\n'},
    )

    rc = main(["check", "--rule", "no-dead-environment-input", str(root)])

    assert rc == 0
    assert not capsys.readouterr().out


def test_vendored_terraform_directories_are_never_roots(tmp_path: Path) -> None:
    vendored = tmp_path / ".terraform" / "modules" / "x"
    vendored.mkdir(parents=True)
    _ = (vendored / "variables.tf").write_text(_DECLARED_TIER, encoding="utf-8")
    tfvars = vendored / "dev.tfvars"
    _ = tfvars.write_text("ghost = 1\n", encoding="utf-8")
    assert _check_file(tfvars) == []


def test_a_secret_valued_assignment_is_named_but_never_echoed(tmp_path: Path) -> None:
    secret = "correct-horse-battery-staple"
    root = _write_root(
        tmp_path,
        'variable "database_password" {\n  type = string\n}\n',
        {"dev": f'database_password = "{secret}"\n', "prod": f'database_password = "{secret}"\n'},
    )

    findings = _check_env(root, "dev")

    assert len(findings) == 1
    assert "required-but-constant: `database_password`" in findings[0].message
    assert secret not in findings[0].message


def test_a_boolean_value_is_still_shown(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "gke_enabled" {\n  type    = bool\n  default = false\n}\n',
        {"dev": "gke_enabled = true\n", "prod": "gke_enabled = true\n"},
    )

    findings = _check_env(root, "dev")

    assert len(findings) == 1
    assert "(true)" in findings[0].message


def test_a_list_value_is_named_but_never_echoed(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "hosts" {\n  type = list(string)\n}\n',
        {"dev": 'hosts = ["a.internal"]\n', "prod": 'hosts = ["a.internal"]\n'},
    )

    findings = _check_env(root, "dev")

    assert len(findings) == 1
    assert "a.internal" not in findings[0].message


def test_a_backup_tfvars_is_neither_linted_nor_an_environment(tmp_path: Path) -> None:
    root = tmp_path / "stack"
    root.mkdir()
    _ = (root / "variables.tf").write_text(_DECLARED_REGION, encoding="utf-8")
    live = root / "production.tfvars"
    _ = live.write_text(_REGION_ASSIGNMENT, encoding="utf-8")
    backup = root / "backup.tfvars"
    _ = backup.write_text(_REGION_ASSIGNMENT, encoding="utf-8")

    assert _check_file(backup) == []
    assert _check_file(live) == []


@pytest.mark.parametrize("label", ["backup", "old", "copy", "tmp", "example", "sample", "template", "prod.bak"])
def test_copy_and_specimen_labels_are_not_environments(label: str, tmp_path: Path) -> None:
    root = tmp_path / "stack"
    root.mkdir()
    _ = (root / "variables.tf").write_text(_DECLARED_REGION, encoding="utf-8")
    live = root / "prod.tfvars"
    _ = live.write_text(_REGION_ASSIGNMENT, encoding="utf-8")
    specimen = root / f"{label}.tfvars"
    _ = specimen.write_text(_REGION_ASSIGNMENT, encoding="utf-8")

    assert _check_file(specimen) == []
    assert _check_file(live) == []


def test_an_untyped_variable_is_left_alone(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "flag" {\n  type = any\n}\n',
        {"dev": "flag = false\n", "prod": 'flag = "false"\n'},
    )

    assert _check_env(root, "dev") == []


def test_auto_loaded_files_are_one_environment_not_several(tmp_path: Path) -> None:
    root = tmp_path / "stack"
    root.mkdir()
    _ = (root / "variables.tf").write_text(_DECLARED_REGION, encoding="utf-8")
    first = root / "a.auto.tfvars"
    _ = first.write_text(_REGION_ASSIGNMENT, encoding="utf-8")
    _ = (root / "b.auto.tfvars").write_text('region = "me-central2"\n', encoding="utf-8")

    assert not [d for d in _check_file(first) if d.message.startswith("required-but-constant:")]


def test_a_specimen_word_inside_a_longer_name_is_still_an_environment(tmp_path: Path) -> None:
    root = tmp_path / "stack"
    root.mkdir()
    _ = (root / "variables.tf").write_text(_DECLARED_REGION, encoding="utf-8")
    west = root / "old-west.tfvars"
    _ = west.write_text(_REGION_ASSIGNMENT, encoding="utf-8")
    _ = (root / "prod.tfvars").write_text(_REGION_ASSIGNMENT, encoding="utf-8")

    assert [d for d in _check_file(west) if "old-west, prod" in d.message]


def test_a_json_only_root_reports_that_it_cannot_be_read(tmp_path: Path) -> None:
    root = tmp_path / "stack"
    root.mkdir()
    _ = (root / "variables.tf").write_text(_DECLARED_REGION, encoding="utf-8")
    json_tfvars = root / "dev.tfvars.json"
    _ = json_tfvars.write_text('{"region": "me-central2"}', encoding="utf-8")

    messages = [d.message for d in _check_file(json_tfvars)]

    assert [m for m in messages if m.startswith("blind-environment:") and "JSON" in m]


def test_an_unreadable_environment_reports_on_a_readable_file(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        _DECLARED_REGION,
        {"dev": _REGION_ASSIGNMENT, "prod": _REGION_ASSIGNMENT},
    )
    unreadable = root / "env" / "dev" / _TFVARS_NAME
    unreadable.chmod(0o000)
    try:
        messages = [d.message for d in _check_env(root, "prod")]
    finally:
        unreadable.chmod(0o600)

    assert [m for m in messages if m.startswith("blind-environment:") and "cannot be read" in m]


def test_a_symlinked_input_is_linted_in_the_root_it_is_linked_into(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    source = external / _TFVARS_NAME
    _ = source.write_text(_REGION_ASSIGNMENT, encoding="utf-8")
    root = tmp_path / "stack"
    root.mkdir()
    _ = (root / "variables.tf").write_text(_DECLARED_REGION, encoding="utf-8")
    env_dir = root / "env" / "dev"
    env_dir.mkdir(parents=True)
    linked = env_dir / _TFVARS_NAME
    linked.symlink_to(source)
    (root / "env" / "staging").mkdir()

    messages = [d.message for d in _check_file(linked)]

    assert [m for m in messages if m.startswith("blind-environment:") and "staging" in m]


def test_a_symlinked_alias_is_not_a_second_environment(tmp_path: Path) -> None:
    root = tmp_path / "stack"
    root.mkdir()
    _ = (root / "variables.tf").write_text(_DECLARED_REGION, encoding="utf-8")
    live = root / "prod.tfvars"
    _ = live.write_text(_REGION_ASSIGNMENT, encoding="utf-8")
    (root / "current.tfvars").symlink_to(live)

    assert _check_file(live) == []


def test_env_directory_of_named_files_is_one_environment_each(tmp_path: Path) -> None:
    root = tmp_path / "stack"
    root.mkdir()
    _ = (root / "variables.tf").write_text(
        'variable "gke_enabled" {\n  type    = bool\n  default = false\n}\n', encoding="utf-8"
    )
    env = root / "env"
    env.mkdir()
    dev = env / "dev.tfvars"
    _ = dev.write_text("gke_enabled = true\n", encoding="utf-8")
    _ = (env / "prod.tfvars").write_text("gke_enabled = true\n", encoding="utf-8")

    messages = [d.message for d in _check_file(dev)]

    assert [m for m in messages if m.startswith("constant-everywhere:") and "dev, prod" in m]


def test_an_auto_loaded_var_file_beside_named_environments_goes_blind(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "gke_enabled" {\n  type    = bool\n  default = false\n}\n',
        {"dev": "gke_enabled = true\n", "prod": "gke_enabled = true\n"},
    )
    _ = (root / "terraform.tfvars").write_text("gke_enabled = true\n", encoding="utf-8")

    messages = [d.message for d in _check_env(root, "dev")]

    assert not [m for m in messages if m.startswith("constant-everywhere:")]


def test_a_duplicate_key_in_one_file_does_not_claim_two_files(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "gke_enabled" {\n  type    = bool\n  default = false\n}\n',
        {"dev": "gke_enabled = true\ngke_enabled = false\n", "prod": "gke_enabled = true\n"},
    )

    messages = [d.message for d in _check_env(root, "dev")]

    assert not [m for m in messages if "more than one file" in m]


def test_an_opaque_sibling_value_counts_as_variation(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "host" {\n  type    = string\n  default = "api.internal"\n}\n',
        {"dev": 'host = "api.internal"\n', "prod": 'host = "api-${var.suffix}.internal"\n'},
    )

    assert _check_env(root, "dev") == []


def test_a_numeric_literal_is_shown_but_a_numeric_string_is_not(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "replicas" {\n  type = number\n}\nvariable "account" {\n  type = string\n}\n',
        {
            "dev": 'replicas = 3\naccount = "123456789012"\n',
            "prod": 'replicas = 3\naccount = "123456789012"\n',
        },
    )

    messages = [d.message for d in _check_env(root, "dev")]

    assert [m for m in messages if m.startswith("required-but-constant: `replicas`") and "(3)" in m]
    assert [m for m in messages if m.startswith("required-but-constant: `account`") and "123456789012" not in m]


def test_default_equal_is_kept_when_a_sibling_environment_differs(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "sql_deletion_protection" {\n  type    = bool\n  default = false\n}\n',
        {"dev": "sql_deletion_protection = false\n", "prod": "sql_deletion_protection = true\n"},
    )

    assert _check_env(root, "dev") == []


def test_default_equal_is_flagged_when_no_environment_differs(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "sql_deletion_protection" {\n  type    = bool\n  default = false\n}\n',
        {"dev": "sql_deletion_protection = false\n", "prod": "sql_deletion_protection = false\n"},
    )

    messages = [d.message for d in _check_env(root, "dev")]

    assert [m for m in messages if m.startswith("equals-default:")]


def test_two_files_disagreeing_about_one_environment_go_blind(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "gke_enabled" {\n  type    = bool\n  default = false\n}\n',
        {"prod": "gke_enabled = true\n", "dev": "gke_enabled = true\n"},
    )
    conflicting = root / "prod.tfvars"
    _ = conflicting.write_text("gke_enabled = false\n", encoding="utf-8")

    across_root = [d.message for d in (*_check_env(root, "dev"), *_check_file(conflicting))]

    assert not [m for m in across_root if m.startswith("constant-everywhere:")]
    assert [m for m in across_root if "blind-environment" in m and "var-file order" in m]


def test_two_files_agreeing_about_one_environment_stay_analyzable(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "gke_enabled" {\n  type    = bool\n  default = false\n}\n',
        {"prod": "gke_enabled = true\n", "dev": "gke_enabled = true\n"},
    )
    _ = (root / "prod.tfvars").write_text("gke_enabled = true\n", encoding="utf-8")

    messages = [d.message for d in _check_env(root, "dev")]

    assert [m for m in messages if "constant-everywhere" in m]


def test_a_real_second_environment_still_reports_constant(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path,
        'variable "gke_enabled" {\n  type    = bool\n  default = false\n}\n',
        {"dev": "gke_enabled = true\n", "staging": "gke_enabled = true\n"},
    )

    findings = _check_env(root, "dev")

    assert len(findings) == 1
    assert "constant-everywhere" in findings[0].message
