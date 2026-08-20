from __future__ import annotations

import pytest

from sarj_standards.libs.adoption import launcher


BOOTSTRAP_COMMAND = "uvx --no-config --isolated --python 3.14 --from sarj-standards-bootstrap==2.0.0 code-standards"


def test_repository_wiring_uses_the_exact_immutable_bootstrap() -> None:
    assert launcher.repository_command() == BOOTSTRAP_COMMAND
    assert launcher.repository_command("check", ".") == f"{BOOTSTRAP_COMMAND} check ."


@pytest.mark.parametrize(
    "legacy",
    [
        "uv run --no-config --no-project --python 3.14 python .sarj/standards",
        "uvx --no-config --isolated --python 3.14 --from sarj-standards==6.6.0 sarj-standards",
        "uvx --no-config --isolated --python 3.14 --from sarj-standards-bootstrap==1.0.3 sarj-standards",
    ],
)
def test_repository_launcher_invocation_is_rewritten_to_bootstrap(legacy: str) -> None:
    source = f"run: {legacy} check\n"

    rewritten = launcher.rewrite_legacy_repository_invocations(source)

    assert rewritten.contents == f"run: {BOOTSTRAP_COMMAND} check\n"
    assert rewritten.replacements == 1


def test_legacy_bootstrap_python_argv_is_rewritten() -> None:
    source = """        "uvx",
        "--no-config",
        "--isolated",
        "--python",
        "3.14",
        "--from",
        "sarj-standards-bootstrap==1.0.3",
        "sarj-standards",
"""

    rewritten = launcher.rewrite_legacy_repository_invocations(source)

    assert '        "sarj-standards-bootstrap==2.0.0",\n' in rewritten.contents
    assert '        "code-standards",\n' in rewritten.contents
    assert rewritten.replacements == 1


def test_exact_launcher_rejects_noncanonical_version() -> None:
    with pytest.raises(ValueError, match="invalid exact"):
        launcher.argv(version="latest")
