from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules import REGISTRY
from sarj_sql_lint.rules.enforce_timestamptz import EnforceTimestamptz
from sarj_sql_lint.rules.idempotent_ddl import IdempotentDdl
from sarj_sql_lint.rules.no_analytical_queries_in_transactional_db import NoAnalyticalQueriesInTransactionalDb
from sarj_sql_lint.rules.no_application_schema_check import NoApplicationSchemaCheck
from sarj_sql_lint.rules.no_create_trigger import NoCreateTrigger
from sarj_sql_lint.rules.no_database_functions import NoDatabaseFunctions
from sarj_sql_lint.rules.no_offset_pagination import NoOffsetPagination
from sarj_sql_lint.rules.no_pg_enum import NoPgEnum
from sarj_sql_lint.rules.prefer_jsonb import PreferJsonb
from sarj_sql_lint.rules.prefer_text_over_varchar import PreferTextOverVarchar
from sarj_sql_lint.rules.prefer_uuidv7_default import PreferUuidv7Default


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Rule


# One statement per rule, each firing exactly once:
# SARJ103 `CREATE TYPE ... AS ENUM`, SARJ109 `gen_random_uuid()` default,
# SARJ112 unindexed cascading `REFERENCES`, SARJ104 `VARCHAR(n)`, SARJ106 `JSON`,
# SARJ101 `TIMESTAMP`, SARJ108 + SARJ110 the blocking `CREATE INDEX` on a
# table this file does not create, SARJ111 a validating `ADD CONSTRAINT`,
# SARJ105 an `INSERT` with no `ON CONFLICT`, SARJ113 the commented-out
# `DROP TABLE`, SARJ114 `CREATE TRIGGER`, SARJ115 a
# long implementation narrative, SARJ116 the fourth child-table index, and
# SARJ117 one duplicate child-table index shape, and SARJ118 an application-owned
# closed text value set repeated as a database CHECK, and SARJ119 the existing-
# table constraint plus data write mixed with the surrounding expand phase,
# SARJ120 a stored SQL function, and SARJ102 + SARJ121 an unguarded fresh table
# followed by a separately declared primary key.
_LEGACY_UUID_DEFAULT = "gen_random_uuid()"
_ALL_RULES_TEMPLATE = """CREATE TYPE mood AS ENUM ('sad', 'ok');
-- Create the children table used by the application in this database.
-- The table stores each child row used by the application service.
-- The next statement defines identifiers, ownership, names, and timestamps.
-- The final statement creates those columns and their database constraints.

-- DROP TABLE legacy_children;
CREATE TABLE IF NOT EXISTS children (
    id uuid PRIMARY KEY,
    owner_id uuid DEFAULT __LEGACY_UUID_DEFAULT__,
    parent_id uuid REFERENCES parents (id) ON DELETE CASCADE,
    name VARCHAR(50),
    payload JSON,
    status TEXT CHECK (status IN ('queued', 'completed')),
    created_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_orders_total ON orders (total);
CREATE INDEX IF NOT EXISTS children_name_a ON children (name);
CREATE INDEX IF NOT EXISTS children_owner ON children (owner_id);
CREATE INDEX IF NOT EXISTS children_payload ON children (payload);
CREATE INDEX IF NOT EXISTS children_created ON children (created_at);
CREATE INDEX IF NOT EXISTS children_name_b ON children (name);
ALTER TABLE accounts ADD CONSTRAINT chk_name CHECK (name <> '');
INSERT INTO children (id) VALUES ('a');
SELECT * FROM children LIMIT 10 OFFSET 100;
CREATE TRIGGER audit_child AFTER INSERT ON children EXECUTE FUNCTION audit_child();
CREATE FUNCTION audit_child() RETURNS int LANGUAGE SQL AS $$ SELECT 1 $$;
CREATE TABLE inline_contract (id uuid);
ALTER TABLE inline_contract ADD PRIMARY KEY (id);
"""
ALL_RULES = _ALL_RULES_TEMPLATE.replace("__LEGACY_UUID_DEFAULT__", _LEGACY_UUID_DEFAULT)

HAND_WRITTEN = Path("db/migrations/0001_init.sql")

MIGRATION_RULES = tuple(rule_cls for rule_cls in REGISTRY.values() if rule_cls.code not in {"SARJ107", "SARJ122"})
DUMP_EXEMPT = MIGRATION_RULES

MODEL_REDIRECTING = (
    EnforceTimestamptz,
    IdempotentDdl,
    NoPgEnum,
    PreferTextOverVarchar,
    PreferJsonb,
    PreferUuidv7Default,
    NoCreateTrigger,
    NoDatabaseFunctions,
    NoApplicationSchemaCheck,
)


def _ids(classes: tuple[type[Rule], ...]) -> list[str]:
    return [cls.code for cls in classes]


def _total(path: Path, source: str) -> int:
    return sum(len(cls().check(path, source)) for cls in REGISTRY.values())


def test_the_shared_source_fires_every_migration_rule_exactly_once() -> None:
    fired = {cls.code: len(cls().check(HAND_WRITTEN, ALL_RULES)) for cls in MIGRATION_RULES}
    assert fired == dict.fromkeys(fired, 1)
    assert len(fired) == 20


@pytest.mark.parametrize("rule_cls", DUMP_EXEMPT, ids=_ids(DUMP_EXEMPT))
def test_each_rule_takes_the_dump_exemption(rule_cls: type[Rule]) -> None:
    assert rule_cls().check(HAND_WRITTEN, ALL_RULES) != []
    assert rule_cls().check(Path("db/structure.sql"), ALL_RULES) == []


def test_the_dump_exemption_suppresses_all_migration_findings() -> None:
    assert _total(HAND_WRITTEN, ALL_RULES) == 20
    assert _total(Path("db/structure.sql"), ALL_RULES) == 0


@pytest.mark.parametrize(
    ("rule_cls", "query"),
    [
        (NoOffsetPagination, "SELECT id FROM event ORDER BY id LIMIT $1 OFFSET $2;"),
        (NoAnalyticalQueriesInTransactionalDb, "SELECT COUNT(*) FROM event;"),
    ],
)
def test_query_policies_enforce_authored_queries_and_exempt_dump_content(rule_cls: type[Rule], query: str) -> None:
    path = Path("queries/events.sql")
    assert len(rule_cls().check(path, query)) == 1
    assert rule_cls().check(path, f"-- PostgreSQL database dump\n{query}") == []


@pytest.mark.parametrize("path", ["db/schema.sql", "db/structure.sql", "db/restore/001.sql", "db/migrations/001.sql"])
def test_analytical_query_policy_checks_authored_sql_at_dump_like_paths(path: str) -> None:
    assert len(NoAnalyticalQueriesInTransactionalDb().check(Path(path), "SELECT COUNT(*) FROM event;")) == 1


@pytest.mark.parametrize("name", ["structure.sql", "schema.sql"])
def test_the_dump_filename_set_is_a_dump_signal(name: str) -> None:
    assert _total(Path("db") / name, ALL_RULES) == 0


def test_the_dump_sql_suffix_is_a_dump_signal() -> None:
    assert _total(Path("db/prod_dump.sql"), ALL_RULES) == 0


def test_a_restore_directory_is_a_dump_signal() -> None:
    assert _total(Path("db/restore/0001.sql"), ALL_RULES) == 0


def test_a_hand_written_migration_next_to_those_names_is_still_judged() -> None:
    assert _total(Path("db/migrations/schema_changes.sql"), ALL_RULES) == 20


GENERATED = f"--> statement-breakpoint\n{ALL_RULES}"


@pytest.mark.parametrize("rule_cls", MODEL_REDIRECTING, ids=_ids(MODEL_REDIRECTING))
def test_each_schema_rule_redirects_a_generated_migration_to_the_model(rule_cls: type[Rule]) -> None:
    plain = rule_cls().check(HAND_WRITTEN, ALL_RULES)
    generated = rule_cls().check(Path("drizzle/0000_init.sql"), GENERATED)
    assert len(generated) == len(plain) == 1
    assert "schema.prisma" in generated[0].message
    assert "schema.prisma" not in plain[0].message


@pytest.mark.parametrize("rule_cls", MODEL_REDIRECTING, ids=_ids(MODEL_REDIRECTING))
def test_the_redirect_suppresses_nothing(rule_cls: type[Rule]) -> None:
    generated = rule_cls().check(Path("drizzle/0000_init.sql"), GENERATED)
    assert [d.line for d in generated] == [d.line + 1 for d in rule_cls().check(HAND_WRITTEN, ALL_RULES)]
