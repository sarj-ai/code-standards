from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pytest

from sarj_standards.libs.linting.devops_tools import NativeToolError
from sarj_standards.libs.repository import shell_checks


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("source", "shellcheck", "shfmt"),
    [
        pytest.param('#!/usr/bin/env bash\nprintf "start\\n"\nprintf "done\\n"\n', 0, 0, id="multiple-commands"),
        pytest.param('#!/usr/bin/env bash\nprintf "%s" "hello" > "out"\n', 0, 1, id="formatting"),
        pytest.param('#!/usr/bin/env bash\nprintf "%s\\n" $1\n', 1, 0, id="word-splitting"),
        pytest.param("#!/usr/bin/env bash\nif true; then\n", 1, 1, id="malformed-shell"),
        pytest.param('#!/usr/bin/env bash\npython3 ./job.py\nprintf "done\\n"\n', 0, 0, id="external-python"),
        pytest.param("#!/usr/bin/env bash\ncat <<'DATA'\npython3 -c 'print(1)'\nDATA\n", 0, 0, id="heredoc-data"),
        pytest.param('#!/usr/bin/env bash\nprintf "%s\\n" \'python3 -c "print(1)"\'\n', 0, 0, id="quoted-data"),
    ],
)
def test_native_checks_preserve_shell_diagnostics(tmp_path: Path, source: str, shellcheck: int, shfmt: int) -> None:
    scripts = tmp_path / ".github/scripts"
    scripts.mkdir(parents=True)
    (scripts / "control.sh").write_text(source)
    assert shell_checks.check(tmp_path, tool="shellcheck") == shellcheck
    assert shell_checks.check(tmp_path, tool="shfmt") == shfmt


@pytest.mark.parametrize("tool", ["shellcheck", "shfmt"])
def test_native_dependency_errors_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Literal["shellcheck", "shfmt"]
) -> None:
    scripts = tmp_path / ".github/scripts"
    scripts.mkdir(parents=True)
    (scripts / "control.sh").write_text("#!/usr/bin/env bash\ntrue\n")

    def unavailable(name: str, *, root: Path) -> None:
        message = f"{name} is unavailable in {root}"
        raise NativeToolError(message)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native attestation interception proves the real check command exits 2; injecting another command path would miss this boundary.
        shell_checks, "checked_tool", unavailable
    )
    assert shell_checks.check(tmp_path, tool=tool) == 2
