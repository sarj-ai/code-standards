from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules import REGISTRY
from sarj_sql_lint.rules.enforce_timestamptz import EnforceTimestamptz
from sarj_sql_lint.rules.idempotent_ddl import IdempotentDdl
from sarj_sql_lint.rules.no_create_trigger import NoCreateTrigger
from sarj_sql_lint.rules.no_pg_enum import NoPgEnum
from sarj_sql_lint.rules.prefer_jsonb import PreferJsonb
from sarj_sql_lint.rules.prefer_text_over_varchar import PreferTextOverVarchar
from sarj_sql_lint.rules.prefer_uuidv7_default import PreferUuidv7Default


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Rule


# One statement per rule, each firing exactly once:
# SARJ103 `CREATE TYPE ... AS ENUM`, SARJ109 `gen_random_uuid()` default,
# SARJ112 unindexed cascading `REFERENCES`, SARJ104 `VARCHAR(n)`, SARJ106 `JSON`,
# SARJ101 `TIMESTAMP`, SARJ102 + SARJ108 + SARJ110 the bare `CREATE INDEX` on a
# table this file does not create, SARJ111 a validating `ADD CONSTRAINT`,
# SARJ105 an `INSERT` with no `ON CONFLICT`, SARJ107 `LIMIT ... OFFSET`, and
# SARJ113 the commented-out `DROP TABLE`, SARJ114 `CREATE TRIGGER`, SARJ115 a
# long implementation narrative, SARJ116 the fourth child-table index, and
# SARJ117 one duplicate child-table index shape.
_LEGACY_UUID_DEFAULT = "gen_random_uuid()"
_ALL_RULES_TEMPLATE = """CREATE TYPE mood AS ENUM ('sad', 'ok');
-- This paragraph explains the first ordinary implementation step in detail.
-- It then narrates a second ordinary step already expressed by the schema.
-- It continues describing local behavior without recording a durable rule.
-- The final sentence repeats the nearby implementation instead of clarifying intent.

-- DROP TABLE legacy_children;
CREATE TABLE IF NOT EXISTS children (
    id uuid PRIMARY KEY,
    owner_id uuid DEFAULT __LEGACY_UUID_DEFAULT__,
    parent_id uuid REFERENCES parents (id) ON DELETE CASCADE,
    name VARCHAR(50),
    payload JSON,
    created_at TIMESTAMP
);
CREATE INDEX idx_orders_total ON orders (total);
CREATE INDEX IF NOT EXISTS children_name_a ON children (name);
CREATE INDEX IF NOT EXISTS children_name_b ON children (name);
CREATE INDEX IF NOT EXISTS children_payload ON children (payload);
CREATE INDEX IF NOT EXISTS children_created ON children (created_at);
ALTER TABLE accounts ADD CONSTRAINT chk_name CHECK (name <> '');
INSERT INTO children (id) VALUES ('a');
SELECT * FROM children LIMIT 10 OFFSET 100;
CREATE TRIGGER audit_child AFTER INSERT ON children EXECUTE FUNCTION audit_child();
"""
ALL_RULES = _ALL_RULES_TEMPLATE.replace("__LEGACY_UUID_DEFAULT__", _LEGACY_UUID_DEFAULT)

HAND_WRITTEN = Path("db/migrations/0001_init.sql")

DUMP_EXEMPT = tuple(REGISTRY.values())

MODEL_REDIRECTING = (
    EnforceTimestamptz,
    IdempotentDdl,
    NoPgEnum,
    PreferTextOverVarchar,
    PreferJsonb,
    PreferUuidv7Default,
    NoCreateTrigger,
)


def _ids(classes: tuple[type[Rule], ...]) -> list[str]:
    return [cls.code for cls in classes]


def _total(path: Path, source: str) -> int:
    return sum(len(cls().check(path, source)) for cls in REGISTRY.values())


def test_the_shared_source_fires_every_rule_exactly_once() -> None:
    fired = {cls.code: len(cls().check(HAND_WRITTEN, ALL_RULES)) for cls in REGISTRY.values()}
    assert fired == dict.fromkeys(fired, 1)
    assert len(fired) == 17


@pytest.mark.parametrize("rule_cls", DUMP_EXEMPT, ids=_ids(DUMP_EXEMPT))
def test_each_rule_takes_the_dump_exemption(rule_cls: type[Rule]) -> None:
    assert rule_cls().check(HAND_WRITTEN, ALL_RULES) != []
    assert rule_cls().check(Path("db/structure.sql"), ALL_RULES) == []


def test_the_dump_exemption_suppresses_all_seventeen_findings() -> None:
    assert _total(HAND_WRITTEN, ALL_RULES) == 17
    assert _total(Path("db/structure.sql"), ALL_RULES) == 0


@pytest.mark.parametrize("name", ["structure.sql", "schema.sql"])
def test_the_dump_filename_set_is_a_dump_signal(name: str) -> None:
    assert _total(Path("db") / name, ALL_RULES) == 0


def test_the_dump_sql_suffix_is_a_dump_signal() -> None:
    assert _total(Path("db/prod_dump.sql"), ALL_RULES) == 0


def test_a_restore_directory_is_a_dump_signal() -> None:
    assert _total(Path("db/restore/0001.sql"), ALL_RULES) == 0


def test_a_hand_written_migration_next_to_those_names_is_still_judged() -> None:
    assert _total(Path("db/migrations/schema_changes.sql"), ALL_RULES) == 17


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
