from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.cancel_owned_task_without_join import CancelOwnedTaskWithoutJoin
from sarj_python_lint.rules.no_unobserved_task_exception import NoUnobservedTaskException


_OWNED = """import asyncio


class Recorder:
    def start(self) -> None:
        self._upload = asyncio.create_task(self._send())

    def stop(self) -> None:
        self._upload.cancel()

    async def _send(self) -> None:
        await asyncio.sleep(1)
"""
_LOCAL = """import asyncio


async def run() -> None:
    task = asyncio.create_task(work())
    try:
        await serve()
    finally:
        task.cancel()
"""
_BACKGROUND = """import asyncio


class Service:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def schedule(self) -> None:
        task = asyncio.create_task(work())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
"""
_CALLBACK = """import asyncio


def start(room) -> None:
    pending: set[asyncio.Task[None]] = set()

    def on_track(track) -> None:
        task = asyncio.create_task(publish(track))
        pending.add(task)
        task.add_done_callback(pending.discard)

    room.on("track_subscribed", on_track)
"""
_LIFESPAN = """import asyncio
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan():
    task = asyncio.create_task(work())
    try:
        yield
    finally:
        task.cancel()
"""

CASES = (
    EvaluationCase("owned-attribute-only-cancelled", Language.PYTHON, _OWNED, ExpectedOutcome.MATCH),
    EvaluationCase("local-only-cancelled", Language.PYTHON, _LOCAL, ExpectedOutcome.MATCH),
    EvaluationCase("set-with-discard-callback", Language.PYTHON, _BACKGROUND, ExpectedOutcome.MATCH),
    EvaluationCase("event-callback-closure-set", Language.PYTHON, _CALLBACK, ExpectedOutcome.MATCH),
    EvaluationCase(
        "factory-alias",
        Language.PYTHON,
        _LOCAL.replace("import asyncio", "from asyncio import create_task as spawn").replace(
            "asyncio.create_task", "spawn"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _LOCAL.replace("import asyncio", "import asyncio as aio").replace("asyncio.", "aio."),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "ensure-future-of-call",
        Language.PYTHON,
        _LOCAL.replace("asyncio.create_task", "asyncio.ensure_future"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "running-loop-task",
        Language.PYTHON,
        _LOCAL.replace(
            "    task = asyncio.create_task(work())",
            "    loop = asyncio.get_running_loop()\n    task = loop.create_task(work())",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "direct-running-loop-task",
        Language.PYTHON,
        _LOCAL.replace("asyncio.create_task(", "asyncio.get_running_loop().create_task("),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "walrus-into-owned-set",
        Language.PYTHON,
        _BACKGROUND.replace(
            "        task = asyncio.create_task(work())\n        self._tasks.add(task)\n",
            "        self._tasks.add(task := asyncio.create_task(work()))\n",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "list-comprehension-only-cancelled",
        Language.PYTHON,
        _LOCAL.replace(
            "task = asyncio.create_task(work())", "tasks = [asyncio.create_task(work()) for _ in range(2)]"
        ).replace("        task.cancel()", "        for task in tasks:\n            task.cancel()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "owned-dict-entry-only-cancelled",
        Language.PYTHON,
        _BACKGROUND.replace("set[asyncio.Task[None]] = set()", "dict[str, asyncio.Task[None]] = {}").replace(
            "        task = asyncio.create_task(work())\n        self._tasks.add(task)\n"
            "        task.add_done_callback(self._tasks.discard)\n",
            "        self._tasks['key'] = asyncio.create_task(work())\n",
        )
        + "\n    def stop(self) -> None:\n        for task in self._tasks.values():\n            task.cancel()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "callback-ignores-task",
        Language.PYTHON,
        _BACKGROUND.replace("task.add_done_callback(self._tasks.discard)", "task.add_done_callback(self._finished)")
        + "\n    def _finished(self, task: asyncio.Task[None]) -> None:\n        self._tasks.discard(task)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "private-module-set",
        Language.PYTHON,
        "import asyncio\n\n_TASKS: set[asyncio.Task[None]] = set()\n\n\ndef schedule() -> None:\n"
        "    task = asyncio.create_task(work())\n    _TASKS.add(task)\n    task.add_done_callback(_TASKS.discard)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "coroutine-reraises",
        Language.PYTHON,
        _BACKGROUND.replace("create_task(work())", "create_task(self._work())")
        + "\n    async def _work(self) -> None:\n        try:\n            await send()\n"
        "        except Exception:\n            log()\n            raise\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "coroutine-catches-narrow-error",
        Language.PYTHON,
        _BACKGROUND.replace("create_task(work())", "create_task(self._work())")
        + "\n    async def _work(self) -> None:\n        try:\n            await send()\n"
        "        except OSError:\n            log()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("awaited-later", Language.PYTHON, _LOCAL + "        await task\n"),
    EvaluationCase(
        "gathered-after-cancel",
        Language.PYTHON,
        _LOCAL + "        await asyncio.gather(task, return_exceptions=True)\n",
    ),
    EvaluationCase("waited-on", Language.PYTHON, _LOCAL + "        await asyncio.wait([task])\n"),
    EvaluationCase("result-read", Language.PYTHON, _LOCAL + "        if task.done():\n            task.result()\n"),
    EvaluationCase(
        "joined-in-aclose",
        Language.PYTHON,
        _OWNED + "\n    async def aclose(self) -> None:\n        self._upload.cancel()\n"
        "        await asyncio.gather(self._upload, return_exceptions=True)\n",
    ),
    EvaluationCase(
        "owned-set-gathered",
        Language.PYTHON,
        _BACKGROUND + "\n    async def aclose(self) -> None:\n"
        "        await asyncio.gather(*self._tasks, return_exceptions=True)\n",
    ),
    EvaluationCase(
        "owned-dict-awaited",
        Language.PYTHON,
        _BACKGROUND.replace("set[asyncio.Task[None]] = set()", "dict[str, asyncio.Task[None]] = {}").replace(
            "        task = asyncio.create_task(work())\n        self._tasks.add(task)\n"
            "        task.add_done_callback(self._tasks.discard)\n",
            "        self._tasks['key'] = asyncio.create_task(work())\n",
        )
        + "\n    async def get(self) -> None:\n        await self._tasks['key']\n",
    ),
    EvaluationCase(
        "callback-logs-exception",
        Language.PYTHON,
        _BACKGROUND.replace("task.add_done_callback(self._tasks.discard)", "task.add_done_callback(self._finished)")
        + "\n    def _finished(self, task: asyncio.Task[None]) -> None:\n        self._tasks.discard(task)\n"
        "        if not task.cancelled() and (error := task.exception()) is not None:\n            log(error)\n",
    ),
    EvaluationCase(
        "lambda-callback-reads-exception",
        Language.PYTHON,
        _BACKGROUND.replace(
            "task.add_done_callback(self._tasks.discard)",
            "task.add_done_callback(lambda done: None if done.cancelled() else done.exception())",
        ),
    ),
    EvaluationCase(
        "imported-callback",
        Language.PYTHON,
        _BACKGROUND.replace("task.add_done_callback(self._tasks.discard)", "task.add_done_callback(log_failure)"),
    ),
    EvaluationCase("returned-to-caller", Language.PYTHON, _LOCAL + "    return task\n"),
    EvaluationCase(
        "returned-directly",
        Language.PYTHON,
        "import asyncio\n\n\ndef start():\n    return asyncio.create_task(work())\n",
    ),
    EvaluationCase(
        "handed-to-joining-owner", Language.PYTHON, _LOCAL.replace("        task.cancel()", "        await drain(task)")
    ),
    EvaluationCase(
        "registered-with-supervisor",
        Language.PYTHON,
        "import asyncio\n\n\ndef start(supervisor) -> None:\n    task = asyncio.create_task(work())\n"
        "    supervisor.add(task)\n",
    ),
    EvaluationCase(
        "comprehension-gathered",
        Language.PYTHON,
        "import asyncio\n\n\nasync def run() -> None:\n    tasks = [asyncio.create_task(work(n)) for n in range(3)]\n"
        "    await asyncio.gather(*tasks)\n",
    ),
    EvaluationCase(
        "task-group",
        Language.PYTHON,
        "import asyncio\n\n\nasync def run() -> None:\n    async with asyncio.TaskGroup() as group:\n"
        "        task = group.create_task(work())\n        task.cancel()\n",
    ),
    EvaluationCase(
        "shadowed-asyncio",
        Language.PYTHON,
        _LOCAL.replace("async def run() -> None:", "async def run(asyncio) -> None:"),
    ),
    EvaluationCase(
        "rebound-asyncio-module",
        Language.PYTHON,
        _LOCAL.replace("import asyncio", "import asyncio\nimport supervisor as asyncio"),
    ),
    EvaluationCase("unknown-loop", Language.PYTHON, _LOCAL.replace("asyncio.create_task(", "loop.create_task(")),
    EvaluationCase(
        "ensure-existing-future",
        Language.PYTHON,
        _LOCAL.replace("asyncio.create_task(work())", "asyncio.ensure_future(future)"),
    ),
    EvaluationCase(
        "discarded-result-owned-by-ruff",
        Language.PYTHON,
        "import asyncio\n\n\nasync def run() -> None:\n    asyncio.create_task(work())\n",
    ),
    EvaluationCase(
        "unread-local-owned-by-ruff",
        Language.PYTHON,
        "import asyncio\n\n\nasync def run() -> None:\n    task = asyncio.create_task(work())\n",
    ),
    EvaluationCase("public-attribute", Language.PYTHON, _OWNED.replace("_upload", "upload")),
    EvaluationCase(
        "attribute-read-by-another-object",
        Language.PYTHON,
        _OWNED + "\n\nasync def shutdown(recorder: Recorder) -> None:\n    await recorder._upload\n",
    ),
    EvaluationCase(
        "reflective-attribute-access",
        Language.PYTHON,
        _OWNED + "\n    async def aclose(self) -> None:\n        await getattr(self, name)\n",
    ),
    EvaluationCase(
        "parameter-container",
        Language.PYTHON,
        "import asyncio\n\n\ndef schedule(tasks: set[asyncio.Task[None]]) -> None:\n"
        "    task = asyncio.create_task(work())\n    tasks.add(task)\n    task.add_done_callback(tasks.discard)\n",
    ),
    EvaluationCase(
        "public-module-set",
        Language.PYTHON,
        "import asyncio\n\nTASKS: set[asyncio.Task[None]] = set()\n\n\ndef schedule() -> None:\n"
        "    task = asyncio.create_task(work())\n    TASKS.add(task)\n    task.add_done_callback(TASKS.discard)\n",
    ),
    EvaluationCase(
        "nonlocal-rebinding",
        Language.PYTHON,
        "import asyncio\n\n\ndef start():\n    task = None\n\n    def begin() -> None:\n        nonlocal task\n"
        "        task = asyncio.create_task(work())\n        task.cancel()\n\n    return begin\n",
    ),
    EvaluationCase(
        "nested-function-awaits-closure",
        Language.PYTHON,
        _CALLBACK
        + "\n    async def close() -> None:\n        await asyncio.gather(*pending, return_exceptions=True)\n\n"
        "    return close\n",
    ),
    EvaluationCase(
        "self-observing-coroutine",
        Language.PYTHON,
        _BACKGROUND.replace("create_task(work())", "create_task(self._work())")
        + "\n    async def _work(self) -> None:\n        try:\n            await send()\n"
        "        except Exception:\n            log()\n",
    ),
    EvaluationCase(
        "self-observing-nested-coroutine",
        Language.PYTHON,
        _BACKGROUND.replace(
            "        task = asyncio.create_task(work())\n",
            "        async def guarded() -> None:\n            try:\n                await send()\n"
            "            except Exception:\n                log()\n\n        task = asyncio.create_task(guarded())\n",
        ),
    ),
    EvaluationCase(
        "suppressed",
        Language.PYTHON,
        _OWNED.replace(
            "asyncio.create_task(self._send())",
            "asyncio.create_task(self._send())  # sarj-noqa: SARJ574 -- supervisor joins every recorder upload",
        ),
    ),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _OWNED),
    EvaluationCase("malformed", Language.PYTHON, "async def run(:\n    asyncio.create_task(work())\n"),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = NoUnobservedTaskException().check(Path("app/tasks.py"), case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(finding.severity is Severity.WARNING and not finding.fixes for finding in findings)


def test_reports_the_creating_call() -> None:
    [finding] = NoUnobservedTaskException().check(Path("app/recorder.py"), _OWNED)
    assert (finding.line, finding.col) == (6, 24)


def test_cancelled_lifespan_task_is_left_to_its_specific_rule(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.py"
    path.write_text(_LIFESPAN)
    findings = analyze([CancelOwnedTaskWithoutJoin.id, NoUnobservedTaskException.id], [path], root=tmp_path)
    assert [finding.code for finding in findings] == [CancelOwnedTaskWithoutJoin.code]


def test_documented_examples() -> None:
    verify_native_rule(NoUnobservedTaskException, analyze)
