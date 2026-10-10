from __future__ import annotations

import pytest

from sarj_standards.libs.adoption import launcher


BOOTSTRAP_COMMAND = "uvx --no-config --isolated --python 3.14 --from sarj-standards-bootstrap code-standards"
NATIVE_BOOTSTRAP = (
    f"uv run --no-config --no-project --python {launcher.TOOL_PYTHON} "
    "--with code-standards==1.2.3 python -m sarj_standards.libs.adoption.native_bootstrap"
)


def test_repository_wiring_uses_unpinned_bootstrap_to_read_pinned_manifest() -> None:
    assert launcher.repository_command() == BOOTSTRAP_COMMAND
    assert launcher.repository_command("check", ".") == f"{BOOTSTRAP_COMMAND} check ."


@pytest.mark.parametrize(
    "legacy",
    [
        "uv run --no-config --no-project --python 3.14 python .sarj/standards",
        "uvx --no-config --isolated --python 3.14 --from sarj-standards==6.6.0 sarj-standards",
        "uvx --no-config --isolated --python 3.14 --from sarj-standards-bootstrap==1.0.3 sarj-standards",
        "uvx --no-config --isolated --python 3.14 --from sarj-standards-bootstrap==2.0.3 code-standards",
        "mise exec pipx:sarj-standards-bootstrap -- code-standards",
    ],
)
def test_repository_launcher_invocation_is_rewritten_to_bootstrap(legacy: str) -> None:
    source = f"run: {legacy} check\n"

    rewritten = launcher.rewrite_legacy_repository_invocations(source)

    assert rewritten.contents == f"run: {BOOTSTRAP_COMMAND} check\n"
    assert rewritten.replacements == 1
    assert launcher.rewrite_legacy_repository_invocations(rewritten.contents).replacements == 0


@pytest.mark.parametrize("command", ["sarj-standards", "code-standards"])
def test_legacy_bootstrap_python_argv_is_rewritten(command: str) -> None:
    source = f"""        "uvx",
        "--no-config",
        "--isolated",
        "--python",
        "3.14",
        "--from",
        "sarj-standards-bootstrap==1.0.3",
        "{command}",
"""

    rewritten = launcher.rewrite_legacy_repository_invocations(source)

    assert '        "sarj-standards-bootstrap",\n' in rewritten.contents
    assert '        "code-standards",\n' in rewritten.contents
    assert rewritten.replacements == 1


def test_exact_launcher_rejects_noncanonical_version() -> None:
    with pytest.raises(ValueError, match="invalid exact"):
        launcher.argv(version="latest")


@pytest.mark.parametrize(
    "source",
    [
        NATIVE_BOOTSTRAP,
        "#!/usr/bin/env bash\nset -euo pipefail\n" + NATIVE_BOOTSTRAP + "\nprintf done\n",
        "NATIVE_METADATA=https://example.test/metadata \\\n  " + NATIVE_BOOTSTRAP,
        NATIVE_BOOTSTRAP.replace("code-standards==1.2.3", "'code-standards==1.2.3'"),
        "# Unicode: λ\n" + NATIVE_BOOTSTRAP,
    ],
    ids=["native", "existing-body", "literal-environment", "quoted-package", "byte-offset"],
)
def test_native_bootstrap_pin_rewrite_preserves_every_other_byte(source: str) -> None:
    expected = source.replace("1.2.3", "1.2.4").encode()
    assert launcher.rewrite_native_bootstrap_pin(source.encode(), version="1.2.4") == expected
    assert launcher.rewrite_native_bootstrap_pin(expected, version="1.2.4") is None


@pytest.mark.parametrize(
    "source",
    [
        "# " + NATIVE_BOOTSTRAP,
        "printf '%s' '" + NATIVE_BOOTSTRAP + "'",
        "DATA='" + NATIVE_BOOTSTRAP + "'",
        "cat <<'DATA'\n" + NATIVE_BOOTSTRAP + "\nDATA\n",
        "python -c '" + NATIVE_BOOTSTRAP + "'",
        NATIVE_BOOTSTRAP.replace("native_bootstrap", "other_module"),
        NATIVE_BOOTSTRAP.replace("uv run", "uvx run"),
        NATIVE_BOOTSTRAP.replace("python -m", "python --with extra -m"),
        NATIVE_BOOTSTRAP.replace("--with code", "python --with code"),
        NATIVE_BOOTSTRAP.replace("code-standards==1.2.3", '"code-standards==$VERSION"'),
        NATIVE_BOOTSTRAP.replace("1.2.3", "1.2.'3'"),
        "alias uv=printf\n" + NATIVE_BOOTSTRAP,
        "PATH=./tool-bin " + NATIVE_BOOTSTRAP,
        "PATH=./tool-bin set -euo pipefail\n" + NATIVE_BOOTSTRAP,
        "uv() { printf '%s' \"$@\"; }\n" + NATIVE_BOOTSTRAP,
        ". ./environment.sh\n" + NATIVE_BOOTSTRAP,
        "eval 'alias uv=printf'\n" + NATIVE_BOOTSTRAP,
        "if true; then " + NATIVE_BOOTSTRAP + "; fi",
        NATIVE_BOOTSTRAP + " &",
        "! " + NATIVE_BOOTSTRAP,
        "INVALID=(\n" + NATIVE_BOOTSTRAP,
    ],
    ids=[
        "comment",
        "argument-data",
        "assignment-data",
        "heredoc-data",
        "interpreter-data",
        "other-module",
        "other-launcher",
        "extra-argument",
        "after-executable",
        "dynamic-pin",
        "split-version",
        "alias",
        "command-search-path",
        "prelude-search-path",
        "function",
        "sourced-state",
        "evaluated-state",
        "conditional",
        "background",
        "negated",
        "malformed",
    ],
)
def test_unproven_bootstrap_pin_ownership_remains_protected(source: str) -> None:
    assert launcher.rewrite_native_bootstrap_pin(source.encode(), version="1.2.4") is None


def test_native_pin_proof_does_not_rewrite_comment_lookalikes() -> None:
    source = (NATIVE_BOOTSTRAP + "\n# " + NATIVE_BOOTSTRAP + "\n").encode()
    assert launcher.rewrite_native_bootstrap_pin(source, version="1.2.4") == source.replace(b"1.2.3", b"1.2.4", 1)
