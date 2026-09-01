from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from sarj_sql_lint.rules.add_constraint_requires_not_valid import AddConstraintRequiresNotValid
from sarj_sql_lint.rules.enforce_timestamptz import EnforceTimestamptz
from sarj_sql_lint.rules.excessive_commentary import ExcessiveCommentary
from sarj_sql_lint.rules.idempotent_ddl import IdempotentDdl
from sarj_sql_lint.rules.index_concurrently import IndexConcurrently
from sarj_sql_lint.rules.insert_requires_on_conflict import InsertRequiresOnConflict
from sarj_sql_lint.rules.no_comment_cruft import NoCommentCruft
from sarj_sql_lint.rules.no_create_trigger import NoCreateTrigger
from sarj_sql_lint.rules.no_offset_pagination import NoOffsetPagination
from sarj_sql_lint.rules.no_pg_enum import NoPgEnum
from sarj_sql_lint.rules.prefer_jsonb import PreferJsonb
from sarj_sql_lint.rules.prefer_text_over_varchar import PreferTextOverVarchar
from sarj_sql_lint.rules.prefer_uuidv7_default import PreferUuidv7Default
from sarj_sql_lint.rules.require_fk_index import RequireFkIndex
from sarj_sql_lint.rules.require_lock_timeout import RequireLockTimeout


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_sql_lint.rule_base import Rule


REGISTRY: Mapping[str, type[Rule]] = MappingProxyType(
    {
        ExcessiveCommentary.id: ExcessiveCommentary,
        EnforceTimestamptz.id: EnforceTimestamptz,
        IdempotentDdl.id: IdempotentDdl,
        NoPgEnum.id: NoPgEnum,
        PreferTextOverVarchar.id: PreferTextOverVarchar,
        InsertRequiresOnConflict.id: InsertRequiresOnConflict,
        PreferJsonb.id: PreferJsonb,
        NoOffsetPagination.id: NoOffsetPagination,
        IndexConcurrently.id: IndexConcurrently,
        PreferUuidv7Default.id: PreferUuidv7Default,
        RequireLockTimeout.id: RequireLockTimeout,
        AddConstraintRequiresNotValid.id: AddConstraintRequiresNotValid,
        RequireFkIndex.id: RequireFkIndex,
        NoCommentCruft.id: NoCommentCruft,
        NoCreateTrigger.id: NoCreateTrigger,
    }
)
