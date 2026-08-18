from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules import REGISTRY
from sarj_sql_lint.rules.enforce_timestamptz import EnforceTimestamptz
from sarj_sql_lint.rules.idempotent_ddl import IdempotentDdl
from sarj_sql_lint.rules.no_pg_enum import NoPgEnum
from sarj_sql_lint.rules.prefer_jsonb import PreferJsonb
from sarj_sql_lint.rules.prefer_text_over_varchar import PreferTextOverVarchar
from sarj_sql_lint.rules.prefer_uuidv7_default import PreferUuidv7Default
from sarj_sql_lint.rules.require_fk_index import RequireFkIndex


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Rule


# One statement per rule, each firing exactly once:
# SARJ103 `CREATE TYPE ... AS ENUM`, SARJ109 `gen_random_uuid()` default,
# SARJ112 unindexed `REFERENCES`, SARJ104 `VARCHAR(n)`, SARJ106 `JSON`,
# SARJ101 `TIMESTAMP`, SARJ102 + SARJ108 + SARJ110 the bare `CREATE INDEX` on a
# table this file does not create, SARJ111 a validating `ADD CONSTRAINT`,
# SARJ105 an `INSERT` with no `ON CONFLICT`, SARJ107 `LIMIT ... OFFSET`, and
# SARJ113 the commented-out `DROP TABLE`.
_LEGACY_UUID_DEFAULT = "gen_random_uuid()"
_ALL_TWELVE_TEMPLATE = """CREATE TYPE mood AS ENUM ('sad', 'ok');
-- DROP TABLE legacy_children;
CREATE TABLE IF NOT EXISTS children (
    id uuid PRIMARY KEY,
    owner_id uuid DEFAULT __LEGACY_UUID_DEFAULT__,
    parent_id uuid REFERENCES parents (id),
    name VARCHAR(50),
    payload JSON,
    created_at TIMESTAMP
);
CREATE INDEX idx_orders_total ON orders (total);
ALTER TABLE accounts ADD CONSTRAINT chk_name CHECK (name <> '');
INSERT INTO children (id) VALUES ('a');
SELECT * FROM children LIMIT 10 OFFSET 100;
"""
ALL_TWELVE = _ALL_TWELVE_TEMPLATE.replace("__LEGACY_UUID_DEFAULT__", _LEGACY_UUID_DEFAULT)

HAND_WRITTEN = Path("db/migrations/0001_init.sql")

# A dump exposes the deployed FK/index relationship, so RequireFkIndex remains actionable there.
DUMP_EXEMPT = tuple(cls for cls in REGISTRY.values() if cls is not RequireFkIndex)

MODEL_REDIRECTING = (
    EnforceTimestamptz,
    IdempotentDdl,
    NoPgEnum,
    PreferTextOverVarchar,
    PreferJsonb,
    PreferUuidv7Default,
)


def _ids(classes: tuple[type[Rule], ...]) -> list[str]:
    return [cls.code for cls in classes]


def _total(path: Path, source: str) -> int:
    return sum(len(cls().check(path, source)) for cls in REGISTRY.values())


def test_the_shared_source_fires_every_rule_exactly_once() -> None:
    fired = {cls.code: len(cls().check(HAND_WRITTEN, ALL_TWELVE)) for cls in REGISTRY.values()}
    assert fired == dict.fromkeys(fired, 1)
    assert len(fired) == 13


@pytest.mark.parametrize("rule_cls", DUMP_EXEMPT, ids=_ids(DUMP_EXEMPT))
def test_each_rule_takes_the_dump_exemption(rule_cls: type[Rule]) -> None:
    assert rule_cls().check(HAND_WRITTEN, ALL_TWELVE) != []
    assert rule_cls().check(Path("db/structure.sql"), ALL_TWELVE) == []


def test_require_fk_index_deliberately_declines_the_dump_exemption() -> None:
    assert len(RequireFkIndex().check(Path("db/structure.sql"), ALL_TWELVE)) == 1


def test_the_dump_exemption_is_what_stands_between_thirteen_findings_and_one() -> None:
    assert _total(HAND_WRITTEN, ALL_TWELVE) == 13
    assert _total(Path("db/structure.sql"), ALL_TWELVE) == 1


@pytest.mark.parametrize("name", ["structure.sql", "schema.sql"])
def test_the_dump_filename_set_is_a_dump_signal(name: str) -> None:
    assert _total(Path("db") / name, ALL_TWELVE) == 1


def test_the_dump_sql_suffix_is_a_dump_signal() -> None:
    assert _total(Path("db/prod_dump.sql"), ALL_TWELVE) == 1


def test_a_restore_directory_is_a_dump_signal() -> None:
    assert _total(Path("db/restore/0001.sql"), ALL_TWELVE) == 1


def test_a_hand_written_migration_next_to_those_names_is_still_judged() -> None:
    assert _total(Path("db/migrations/schema_changes.sql"), ALL_TWELVE) == 13


GENERATED = f"--> statement-breakpoint\n{ALL_TWELVE}"


@pytest.mark.parametrize("rule_cls", MODEL_REDIRECTING, ids=_ids(MODEL_REDIRECTING))
def test_each_schema_rule_redirects_a_generated_migration_to_the_model(rule_cls: type[Rule]) -> None:
    plain = rule_cls().check(HAND_WRITTEN, ALL_TWELVE)
    generated = rule_cls().check(Path("drizzle/0000_init.sql"), GENERATED)
    assert len(generated) == len(plain) == 1
    assert "schema.prisma" in generated[0].message
    assert "schema.prisma" not in plain[0].message


@pytest.mark.parametrize("rule_cls", MODEL_REDIRECTING, ids=_ids(MODEL_REDIRECTING))
def test_the_redirect_suppresses_nothing(rule_cls: type[Rule]) -> None:
    generated = rule_cls().check(Path("drizzle/0000_init.sql"), GENERATED)
    assert [d.line for d in generated] == [d.line + 1 for d in rule_cls().check(HAND_WRITTEN, ALL_TWELVE)]
