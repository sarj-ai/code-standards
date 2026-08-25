from pathlib import Path

from sarj_iac_lint.rules.no_environment_derived_access_grant import NoEnvironmentDerivedAccessGrant


RULE = NoEnvironmentDerivedAccessGrant()


def test_rejects_environment_selected_group_principals() -> None:
    source = """locals {
  product_qa_nonprod_groups = contains(["dev", "preview", "sandbox"], var.environment) ? toset([
    "team-product@sarj.ai",
    "team-qa@sarj.ai",
  ]) : toset([])
}
"""
    diagnostics = RULE.check(Path("iam.tf"), source)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 2
    assert diagnostics[0].code == "SARJ208"


def test_accepts_explicit_capability_input() -> None:
    source = """locals {
  product_qa_nonprod_groups = var.product_qa_nonprod_access_enabled ? toset([
    "team-product@sarj.ai",
  ]) : toset([])
}
"""
    assert RULE.check(Path("iam.tf"), source) == []


def test_ignores_unrelated_environment_derived_compute_group() -> None:
    source = """locals {
  node_groups = var.environment == "dev" ? ["workers"] : []
}
"""
    assert RULE.check(Path("iam.tf"), source) == []


def test_leaves_reference_only_principal_sets_to_the_general_rule() -> None:
    source = """locals {
  access_members = var.environment == "dev" ? var.dev_members : var.other_members
}
"""
    assert RULE.check(Path("iam.tf"), source) == []


def test_documented_examples_are_present() -> None:
    assert RULE.documentation is not None
    outcomes = {example.outcome.value for example in RULE.documentation.examples}
    assert outcomes == {"match", "no-match"}
