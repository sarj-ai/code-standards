"""The immutable bootstrap command supersedes the retired repository script."""

from __future__ import annotations

import pytest

from sarj_standards.libs.adoption import launcher


BOOTSTRAP_COMMAND = "uvx --no-config --isolated --python 3.14 --from sarj-standards-bootstrap==1.0.0 sarj-standards"


def test_repository_wiring_uses_the_exact_immutable_bootstrap() -> None:
    assert launcher.repository_command() == BOOTSTRAP_COMMAND
    assert launcher.repository_command("check", ".") == f"{BOOTSTRAP_COMMAND} check ."


def test_repository_launcher_invocation_is_rewritten_to_bootstrap() -> None:
    legacy = "run: uv run --no-config --no-project --python 3.14 python .sarj/standards check\n"

    rewritten = launcher.rewrite_legacy_repository_invocations(legacy)

    assert rewritten.contents == f"run: {BOOTSTRAP_COMMAND} check\n"
    assert rewritten.replacements == 1


def test_exact_launcher_rejects_noncanonical_version() -> None:
    with pytest.raises(ValueError, match="invalid exact"):
        launcher.argv(version="latest")
