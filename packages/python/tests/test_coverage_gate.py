from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def coverage_project(tmp_path: Path) -> Path:
    project = tmp_path / "packages/python"
    tests = project / "tests"
    tests.mkdir(parents=True)
    shutil.copyfile(Path(__file__).with_name("conftest.py"), tests / "conftest.py")
    (project / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    (tests / "test_probe.py").write_text("def test_probe():\n    pass\n")
    return project


def _pytest(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp={project.parents[1] / 'pytest-runtime'}",
            *arguments,
        ],
        cwd=project,
        env={**os.environ, "PYTEST_ADDOPTS": ""},  # ruff: ignore[banned-api] -- isolate pytest filters, retain runtime.
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_collection_does_not_require_rule_execution(coverage_project: Path) -> None:
    result = _pytest(coverage_project, "--collect-only")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_probe.py::test_probe" in result.stdout
    assert "rules whose tests do not exercise them" not in result.stdout


def test_normal_run_still_requires_both_rule_directions(coverage_project: Path) -> None:
    result = _pytest(coverage_project)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "never makes it report" in result.stdout
    assert "Every rule needs at least one case it flags" in result.stdout


def test_collection_error_still_fails(coverage_project: Path) -> None:
    (coverage_project / "tests/test_probe.py").write_text("def broken(\n")

    result = _pytest(coverage_project, "--collect-only")

    assert result.returncode != 0
    assert "SyntaxError" in result.stdout


@pytest.fixture
def worker_coverage_project(coverage_project: Path) -> Path:
    pytest.importorskip("xdist")
    tests = coverage_project / "tests"
    (tests / "test_probe.py").unlink()
    conftest = tests / "conftest.py"
    conftest.write_text(
        conftest.read_text() + '\nREGISTRY = {"no-loguru-printf-format": REGISTRY["no-loguru-printf-format"]}\n'
    )
    return coverage_project


def _write_worker_probe(project: Path, observations: dict[str, tuple[bool, ...]]) -> None:
    examples = project / "tests/rules/test_no_loguru_printf_format.py"
    examples.parent.mkdir()
    examples.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "from sarj_python_lint.rules.no_loguru_printf_format import NoLoguruPrintfFormat\n"
        f"OBSERVATIONS = {observations!r}\n"
        "def test_rule_probe():\n"
        "    for fires in OBSERVATIONS[os.environ['PYTEST_XDIST_WORKER']]:\n"
        "        template = '%s' if fires else '{}'\n"
        "        source = 'from loguru import logger\\nlogger.info(' + repr(template) + ', 1)\\n'\n"
        "        assert bool(NoLoguruPrintfFormat().check(Path('app/service.py'), source)) == fires\n"
    )


def test_workers_combine_complementary_rule_directions(worker_coverage_project: Path) -> None:
    _write_worker_probe(worker_coverage_project, {"gw0": (True,), "gw1": (False,)})

    result = _pytest(worker_coverage_project, "-n", "2", "--dist=each")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


@pytest.mark.parametrize(("fires", "missing"), [(True, "stay quiet"), (False, "report")])
def test_parallel_run_still_requires_both_rule_directions(
    worker_coverage_project: Path, fires: bool, missing: str
) -> None:
    _write_worker_probe(worker_coverage_project, {"gw0": (fires,), "gw1": (fires,)})

    result = _pytest(worker_coverage_project, "-n", "2", "--dist=each")

    assert result.returncode == 1, result.stdout + result.stderr
    assert f"never makes it {missing}" in result.stdout
    assert "2 passed" in result.stdout


@pytest.mark.parametrize("corruption", ["missing", "malformed"])
def test_parallel_run_rejects_incomplete_worker_reports(worker_coverage_project: Path, corruption: str) -> None:
    _write_worker_probe(worker_coverage_project, {"gw0": (True, False), "gw1": (True, False)})
    mutation = (
        "node.workeroutput.pop('sarj_python_clean')"
        if corruption == "missing"
        else "node.workeroutput['sarj_python_clean'] = None"
    )
    (worker_coverage_project / "transport_failure.py").write_text(
        "import pytest\n"
        "@pytest.hookimpl(tryfirst=True)\n"
        "def pytest_testnodedown(node):\n"
        "    if node.gateway.id == 'gw1':\n"
        f"        {mutation}\n"
    )

    result = _pytest(worker_coverage_project, "-p", "transport_failure", "-n", "2", "--dist=each")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Missing or invalid rule coverage report from a pytest worker." in result.stdout
    assert "never makes it" not in result.stdout
    assert "2 passed" in result.stdout


def test_narrowed_parallel_run_keeps_the_existing_coverage_exemption(worker_coverage_project: Path) -> None:
    _write_worker_probe(worker_coverage_project, {"gw0": (True,), "gw1": (True,)})

    result = _pytest(worker_coverage_project, "-n", "2", "--dist=each", "-k", "test_rule_probe")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "never makes it" not in result.stdout
