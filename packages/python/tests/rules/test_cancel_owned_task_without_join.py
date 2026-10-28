from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.cancel_owned_task_without_join import CancelOwnedTaskWithoutJoin


_BASE = "import asyncio\nfrom contextlib import asynccontextmanager\n\n@asynccontextmanager\nasync def lifespan():\n    task = asyncio.create_task(work())\n    try:\n        yield\n    finally:\n        task.cancel()\n"
CASES = (
    EvaluationCase("cancel-without-join", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "additional-finalizer", Language.PYTHON, _BASE + "        release_resources()\n", ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _BASE.replace("import asyncio", "import asyncio as aio").replace("asyncio.", "aio."),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "task-factory-alias",
        Language.PYTHON,
        _BASE.replace("import asyncio", "from asyncio import create_task as spawn").replace(
            "asyncio.create_task", "spawn"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "decorator-alias",
        Language.PYTHON,
        _BASE.replace("from contextlib import asynccontextmanager", "import contextlib as ctx").replace(
            "@asynccontextmanager", "@ctx.asynccontextmanager"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("await-after-cancel", Language.PYTHON, _BASE + "        await task\n"),
    EvaluationCase(
        "gather-after-cancel", Language.PYTHON, _BASE + "        await asyncio.gather(task, return_exceptions=True)\n"
    ),
    EvaluationCase("wait-after-cancel", Language.PYTHON, _BASE + "        await asyncio.wait([task])\n"),
    EvaluationCase("joined-before-cancel", Language.PYTHON, _BASE.replace("    try:", "    await task\n    try:")),
    EvaluationCase(
        "observed-done",
        Language.PYTHON,
        _BASE.replace("        task.cancel()", "        if not task.done():\n            task.cancel()"),
    ),
    EvaluationCase("cleanup-helper", Language.PYTHON, _BASE + "        await finish_task(task)\n"),
    EvaluationCase(
        "registered-supervision", Language.PYTHON, _BASE.replace("    try:", "    supervisor.add(task)\n    try:")
    ),
    EvaluationCase(
        "done-callback", Language.PYTHON, _BASE.replace("    try:", "    task.add_done_callback(cleanup)\n    try:")
    ),
    EvaluationCase("alias-escape", Language.PYTHON, _BASE.replace("    try:", "    alias = task\n    try:")),
    EvaluationCase(
        "external-task",
        Language.PYTHON,
        _BASE.replace("lifespan()", "lifespan(task)").replace("    task = asyncio.create_task(work())\n", ""),
    ),
    EvaluationCase(
        "ensure-existing-future",
        Language.PYTHON,
        _BASE.replace("asyncio.create_task(work())", "asyncio.ensure_future(existing)"),
    ),
    EvaluationCase("unknown-factory", Language.PYTHON, _BASE.replace("asyncio.create_task(work())", "spawn(work())")),
    EvaluationCase("undecorated", Language.PYTHON, _BASE.replace("@asynccontextmanager\n", "")),
    EvaluationCase("other-decorator", Language.PYTHON, _BASE.replace("@asynccontextmanager", "@custom_contextmanager")),
    EvaluationCase(
        "multiple-decorators", Language.PYTHON, _BASE.replace("@asynccontextmanager", "@custom\n@asynccontextmanager")
    ),
    EvaluationCase("rebound-task", Language.PYTHON, _BASE.replace("    try:", "    task = other\n    try:")),
    EvaluationCase(
        "conditional-owner", Language.PYTHON, _BASE.replace("    task =", "    if enabled:\n        task =")
    ),
    EvaluationCase(
        "custom-task-factory", Language.PYTHON, _BASE.replace("    try:", "    loop.set_task_factory(custom)\n    try:")
    ),
    EvaluationCase("mutated-cancel", Language.PYTHON, _BASE.replace("    try:", "    task.cancel = custom\n    try:")),
    EvaluationCase(
        "namespace-mutation",
        Language.PYTHON,
        _BASE.replace("@asynccontextmanager", "asyncio.create_task = custom\n\n@asynccontextmanager"),
    ),
    EvaluationCase(
        "factory-namespace-alias",
        Language.PYTHON,
        _BASE.replace(
            "@asynccontextmanager",
            "from asyncio import create_task as spawn\nspawn.custom = True\n\n@asynccontextmanager",
        ),
    ),
    EvaluationCase(
        "nested-callback",
        Language.PYTHON,
        _BASE.replace("    try:", "    def callback():\n        task.cancel()\n    try:"),
    ),
    EvaluationCase("no-yield", Language.PYTHON, _BASE.replace("        yield", "        await work()")),
    EvaluationCase("invalid-factory-call", Language.PYTHON, _BASE.replace("create_task(work())", "create_task()")),
    EvaluationCase(
        "eager-task", Language.PYTHON, _BASE.replace("create_task(work())", "create_task(work(), eager_start=True)")
    ),
    EvaluationCase(
        "dynamic-eager-task",
        Language.PYTHON,
        _BASE.replace("create_task(work())", "create_task(work(), eager_start=policy)"),
    ),
    EvaluationCase(
        "opaque-task-keywords", Language.PYTHON, _BASE.replace("create_task(work())", "create_task(work(), **options)")
    ),
    EvaluationCase(
        "suppressed",
        Language.PYTHON,
        _BASE.replace("task.cancel()", "task.cancel()  # sarj-noqa: SARJ536 -- supervisor settles at process boundary"),
    ),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase(
        "reflection",
        Language.PYTHON,
        _BASE.replace("@asynccontextmanager", "globals()['asyncio'] = custom\n\n@asynccontextmanager"),
    ),
    EvaluationCase("malformed", Language.PYTHON, "async def lifespan(:"),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = CancelOwnedTaskWithoutJoin().check(Path("app/lifecycle.py"), case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(finding.severity is Severity.WARNING and not finding.fixes for finding in findings)


def test_ensure_future_requires_a_new_local_coroutine() -> None:
    source = _BASE.replace(
        "@asynccontextmanager", "async def work():\n    await asyncio.sleep(1)\n\n@asynccontextmanager"
    ).replace("asyncio.create_task", "asyncio.ensure_future")
    assert len(CancelOwnedTaskWithoutJoin().check(Path("app/lifecycle.py"), source)) == 1


def test_repeated_cancel_reports_the_owned_task_once() -> None:
    assert len(CancelOwnedTaskWithoutJoin().check(Path("app/lifecycle.py"), _BASE + "        task.cancel()\n")) == 1


def test_documented_examples() -> None:
    verify_native_rule(CancelOwnedTaskWithoutJoin, analyze)
