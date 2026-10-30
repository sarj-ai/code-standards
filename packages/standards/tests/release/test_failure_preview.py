from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from sarj_standards.libs.release.process import credential_free_environment


_TEST_SOURCE = r"""
SUCCESS = __SUCCESS__
MESSAGE = "UNICODE_HEAD\n" + "\n".join(
    f"private-line-{number}: " + "é雪🙂" * 24 for number in range(90)
) + "\nUNICODE_TAIL"

def test_first():
    print("PRIVATE_CAPTURE_SENTINEL")
    if not SUCCESS:
        raise RuntimeError(MESSAGE)

def test_second():
    if not SUCCESS:
        raise ValueError("SECOND_FAILURE_SENTINEL")

def test_last():
    pass
"""


@pytest.mark.parametrize(
    ("success", "options", "preview"),
    [
        (False, (), True),
        (True, (), False),
        (False, ("--tb=no",), False),
        (False, ("--no-summary",), False),
        (False, ("-qq",), False),
        (False, ("-p", "no:terminal"), False),
    ],
    ids=("enabled", "success", "no-traceback", "no-summary", "extra-quiet", "no-terminal"),
)
def test_first_failure_preview(tmp_path: Path, success: bool, options: tuple[str, ...], preview: bool) -> None:
    conftest = Path(__file__).parents[1] / "conftest.py"
    (tmp_path / "conftest.py").write_bytes(conftest.read_bytes())
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_private.py").write_text(_TEST_SOURCE.replace("__SUCCESS__", repr(success)))
    environment = credential_free_environment()
    environment.pop("PYTEST_ADDOPTS", None)
    arguments = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(tmp_path / "pytest.ini"),
        "--rootdir",
        str(tmp_path),
        "--confcutdir",
        str(tmp_path),
        "--basetemp",
        str(tmp_path / "pytest-tmp"),
    ]
    if "no:terminal" not in options:
        arguments.extend(("-q", "--color=no"))
    completed = subprocess.run(
        [*arguments, *options, "test_private.py"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
        check=False,
        timeout=15,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == (0 if success else 1)
    header = "First failure preview ("
    footer = "[complete details remain in the final report]"
    assert output.count(header) == output.count(footer) == int(preview)
    if success:
        assert "3 passed" in output
        assert "PRIVATE_CAPTURE_SENTINEL" not in output
    if not preview:
        return
    start = output.index(header)
    end = output.index(footer, start) + len(footer)
    block = output[start:end]
    assert "preview (call): test_private.py::test_first" in block
    assert "[preview truncated]" in block
    assert "UNICODE_TAIL" in block
    assert "雪" in block
    assert len(block.encode("utf-8")) + 3 < 8192
    assert len(block.splitlines()) + 2 < 42
    assert "SECOND_FAILURE_SENTINEL" not in block
    assert "PRIVATE_CAPTURE_SENTINEL" not in block
    final = output[end:]
    assert all(marker in final for marker in ("UNICODE_HEAD", "private-line-45:", "UNICODE_TAIL"))
    assert all(f"private-line-{number}:" in final for number in range(90))
    assert "SECOND_FAILURE_SENTINEL" in final
    assert "PRIVATE_CAPTURE_SENTINEL" in final
    assert "2 failed, 1 passed" in final
    assert len(final.encode("utf-8")) > 8192
