from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.lifecycle_update_requires_state_guard import LifecycleUpdateRequiresStateGuard


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint.rule_base import Diagnostic


_CONFIG = '[python.lifecycle-update-requires-state-guard]\nlifecycle_columns = ["task.status", "call.status"]\n'


def _check(root: Path, sql: str, *, config: str | None = _CONFIG) -> list[Diagnostic]:
    if config is not None:
        (root / ".sarj-standards.toml").write_text(config, encoding="utf-8")
    source = (
        "from psycopg import AsyncCursor\n"
        "class TaskStore:\n"
        "    def __init__(self, cursor: AsyncCursor):\n"
        "        self.cursor = cursor\n"
        "    async def write(self, *args):\n"
        f"        await self.cursor.execute({sql!r}, args)\n"
    )
    return LifecycleUpdateRequiresStateGuard().check(root / "app" / "task_store.py", source)


def test_documented_examples() -> None:
    verify_native_rule(LifecycleUpdateRequiresStateGuard, analyze)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE task SET status = %s WHERE id = ANY(%s)",
        "UPDATE task SET status = %s, updated_at = NOW() WHERE id = ANY(%s) AND type IS DISTINCT FROM %s",
        "UPDATE call SET status = COALESCE(%s, status) WHERE id = %s AND (%s::text IS NULL OR status = %s)",
        "UPDATE task SET status = CASE WHEN status = %s THEN status ELSE %s END WHERE id = %s",
        "UPDATE task SET status = %s",
        "UPDATE public.task AS t SET status = %s WHERE t.id = %s AND o.status = %s",
        "UPDATE task SET status = %s WHERE id IN (SELECT id FROM task WHERE status = %s)",
        "WITH moved AS (UPDATE task SET status = %s WHERE id = %s RETURNING id) SELECT id FROM moved",
    ],
    ids=[
        "keyed-write",
        "unrelated-predicate",
        "optional-guard",
        "set-side-case",
        "no-where",
        "other-relation-column",
        "subquery-only",
        "cte",
    ],
)
def test_unguarded_lifecycle_write_is_reported(tmp_path: Path, sql: str) -> None:
    [finding] = _check(tmp_path, sql)
    assert finding.code == "SARJ598"
    assert ".status" in finding.message


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE task SET status = %s WHERE id = ANY(%s) AND status <> ALL(%s::text[])",
        "UPDATE call SET status = %s, updated_at = NOW() WHERE id = %s AND status = %s",
        "UPDATE task SET status = %s, updated_at = %s WHERE id = %s AND updated_at = %s",
        "UPDATE task AS t SET status = %s WHERE t.id = %s AND (t.status = %s OR t.status IS NULL)",
        "UPDATE task SET message = %s WHERE id = %s",
        "UPDATE batch SET status = %s WHERE id = %s",
        "UPDATE task SET status = %s WHERE {where}",
        "SELECT status FROM task WHERE id = %s",
        "UPDATE task SET status = CASE WHEN status = %s THEN %s ELSE status END WHERE id = %s",
        "UPDATE call SET status = %s WHERE id = (SELECT c.id FROM call c WHERE c.id = %s AND c.status = %s FOR UPDATE)",
    ],
    ids=[
        "terminal-guard",
        "observed-state",
        "compare-and-set",
        "all-branches-guard",
        "non-lifecycle-column",
        "unconfigured-table",
        "unresolved-where",
        "read-only",
        "set-side-compare-and-set",
        "locking-subquery",
    ],
)
def test_guarded_or_unconfigured_write_is_accepted(tmp_path: Path, sql: str) -> None:
    assert _check(tmp_path, sql) == []


_FINISH = (
    "from psycopg import AsyncCursor\n"
    "async def finish(cursor: AsyncCursor, task_id):\n"
    "    await cursor.execute(LOCK, (task_id,))\n"
    "    await cursor.execute('UPDATE task SET status = %s WHERE id = %s', ('done', task_id))\n"
)


@pytest.mark.parametrize(
    ("lock", "expected"),
    [
        ("SELECT status FROM task WHERE id = %s FOR NO KEY UPDATE", 0),
        ("SELECT id FROM task WHERE id = %s AND status = ANY(%s) FOR UPDATE", 0),
        ("SELECT id FROM task WHERE id = %s FOR UPDATE", 1),
        ("SELECT status FROM task WHERE id = %s", 1),
        ("SELECT status FROM call WHERE id = %s FOR UPDATE", 1),
    ],
    ids=["locked-state-read", "locked-state-filter", "lock-without-state", "unlocked-read", "other-relation-lock"],
)
def test_locking_state_read_guards_later_write(tmp_path: Path, lock: str, expected: int) -> None:
    source = _FINISH.replace("LOCK", repr(lock))
    (tmp_path / ".sarj-standards.toml").write_text(_CONFIG, encoding="utf-8")
    assert len(LifecycleUpdateRequiresStateGuard().check(tmp_path / "app" / "task_store.py", source)) == expected


def test_test_fixtures_may_force_state(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(_CONFIG, encoding="utf-8")
    source = (
        "from psycopg import AsyncCursor\n"
        "async def complete(cursor: AsyncCursor, task_id):\n"
        "    await cursor.execute('UPDATE task SET status = %s WHERE id = %s', ('completed', task_id))\n"
    )
    assert LifecycleUpdateRequiresStateGuard().check(tmp_path / "tests" / "fixtures" / "rows.py", source) == []


def test_without_configuration_names_do_not_establish_lifecycle(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert _check(tmp_path, "UPDATE task SET status = %s WHERE id = %s", config=None) == []


def test_exact_suppression_keeps_intentional_overwrite(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(_CONFIG, encoding="utf-8")
    path = tmp_path / "app" / "task_store.py"
    path.parent.mkdir()
    path.write_text(
        "from psycopg import AsyncCursor\n"
        "async def reset(cursor: AsyncCursor, task_id):\n"
        "    await cursor.execute(\n"
        "        'UPDATE task SET status = %s WHERE id = %s',  # sarj-noqa: SARJ598 -- operator reset reopens tasks.\n"
        "        ('pending', task_id),\n"
        "    )\n",
        encoding="utf-8",
    )
    assert analyze([LifecycleUpdateRequiresStateGuard.id], [path]) == []


@pytest.mark.parametrize(
    "config",
    [
        "[python.lifecycle-update-requires-state-guard]\nlifecycle_columns = ['status']\n",
        "[python.lifecycle-update-requires-state-guard]\nlifecycle_columns = 'task.status'\n",
        "[python.lifecycle-update-requires-state-guard]\n",
    ],
)
def test_malformed_configuration_is_rejected(tmp_path: Path, config: str) -> None:
    with pytest.raises(ValueError, match=r"table\.column"):
        _check(tmp_path, "UPDATE task SET status = %s WHERE id = %s", config=config)
