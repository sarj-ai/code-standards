from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_sql_lint.rules.add_constraint_not_valid import AddConstraintNotValid
from sarj_sql_lint.rules.enforce_timestamptz import EnforceTimestamptz
from sarj_sql_lint.rules.idempotent_ddl import IdempotentDdl
from sarj_sql_lint.rules.index_concurrently import IndexConcurrently
from sarj_sql_lint.rules.insert_requires_on_conflict import InsertRequiresOnConflict
from sarj_sql_lint.rules.no_limit_offset import NoLimitOffset
from sarj_sql_lint.rules.no_pg_enum import NoPgEnum
from sarj_sql_lint.rules.prefer_jsonb import PreferJsonb
from sarj_sql_lint.rules.prefer_text_over_varchar import PreferTextOverVarchar
from sarj_sql_lint.rules.prefer_uuidv7_default import PreferUuidv7Default
from sarj_sql_lint.rules.require_fk_index import RequireFkIndex
from sarj_sql_lint.rules.require_lock_timeout import RequireLockTimeout


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Rule


REGISTRY: dict[str, type[Rule]] = {
    EnforceTimestamptz.id: EnforceTimestamptz,
    IdempotentDdl.id: IdempotentDdl,
    NoPgEnum.id: NoPgEnum,
    PreferTextOverVarchar.id: PreferTextOverVarchar,
    InsertRequiresOnConflict.id: InsertRequiresOnConflict,
    PreferJsonb.id: PreferJsonb,
    NoLimitOffset.id: NoLimitOffset,
    IndexConcurrently.id: IndexConcurrently,
    PreferUuidv7Default.id: PreferUuidv7Default,
    RequireLockTimeout.id: RequireLockTimeout,
    AddConstraintNotValid.id: AddConstraintNotValid,
    RequireFkIndex.id: RequireFkIndex,
}
