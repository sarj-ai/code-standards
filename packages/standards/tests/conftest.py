from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_enclosing_git_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep an enclosing Git hook from routing fixture commands to the real repo."""
    for name in tuple(os.environ):  # ruff: ignore[banned-api] -- tests must sanitize inherited hook routing.
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)


def _failure_preview(report: pytest.TestReport) -> str:
    header = f"First failure preview ({report.when}): {report.nodeid}"
    prefix = header.replace("\r", "\\r").replace("\n", "\\n").encode("utf-8", errors="replace")
    full = report.longreprtext
    tail = "\n".join(full.splitlines()[-36:])
    payload = tail.encode("utf-8", errors="replace")
    clipped = len(prefix) > 768 or tail != full or len(payload) > 7168
    marker = "\n[preview truncated]" if clipped else ""
    return (
        f"\n{prefix[:768].decode('utf-8', errors='ignore')}{marker}\n"
        f"{payload[-7168:].decode('utf-8', errors='ignore')}\n"
        "[complete details remain in the final report]"
    )


class _FirstFailurePreview:
    def __init__(self, terminal: pytest.TerminalReporter) -> None:
        self.terminal = terminal
        self.shown = False

    @pytest.hookimpl(trylast=True)
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if self.shown or not report.failed:
            return
        self.shown = True
        self.terminal.write_line(_failure_preview(report))
        self.terminal.flush()


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    terminal = config.pluginmanager.get_plugin("terminalreporter")
    if (
        not isinstance(terminal, pytest.TerminalReporter)
        or hasattr(  # sarj-noqa: SARJ499 -- pytest-xdist adds workerinput only to worker configurations; preserve summary ownership.
            config, "workerinput"
        )
    ):
        return
    if (
        config.getoption("tbstyle", default="auto") == "no"
        or config.getoption("no_summary", default=False)
        or config.get_verbosity() < -1
        or config.get_verbosity(pytest.Config.VERBOSITY_TEST_CASES) < -1
    ):
        return
    config.pluginmanager.register(_FirstFailurePreview(terminal), "sarj-first-failure-preview")
