"""The typed facade remains importable independently of argparse."""

from __future__ import annotations

from sarj_lint_configs import api


def test_every_declared_public_api_resolves() -> None:
    assert api.__all__
    assert all(hasattr(api, name) for name in api.__all__)
    assert len(api.__all__) == len(set(api.__all__))


def test_public_api_exposes_each_business_domain() -> None:
    expected = {
        "diagnose",
        "plan_init",
        "apply_init",
        "plan_sync",
        "apply_sync",
        "plan_upgrade",
        "apply_upgrade",
        "check",
        "check_text",
        "check_library_policy",
        "check_repository",
        "plan_setup",
        "apply_setup",
        "validate_release_tag",
        "verify_package_tarball",
        "run_typescript_release",
    }

    assert expected <= set(api.__all__)
