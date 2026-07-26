from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_python_lint.rules.fixture_returns_bare_tuple import FixtureReturnsBareTuple
from sarj_python_lint.rules.inefficient_string_concat_in_loop import (
    InefficientStringConcatInLoop,
)
from sarj_python_lint.rules.kwarg_heavy_construction_in_test import KwargHeavyConstructionInTest
from sarj_python_lint.rules.kwonly_same_type_params import KwonlySameTypeParams
from sarj_python_lint.rules.mock_without_spec import MockWithoutSpec
from sarj_python_lint.rules.no_aggregation_in_store_query import (
    NoAggregationInStoreQuery,
)
from sarj_python_lint.rules.no_comment_cruft import NoCommentCruft
from sarj_python_lint.rules.no_cors_wildcard_with_credentials import (
    NoCorsWildcardWithCredentials,
)
from sarj_python_lint.rules.no_fat_try_blocks import NoFatTryBlocks
from sarj_python_lint.rules.no_file_level_suppression import NoFileLevelSuppression
from sarj_python_lint.rules.no_fstring_in_log import NoFstringInLog
from sarj_python_lint.rules.no_isinstance_union_chain import NoIsinstanceUnionChain
from sarj_python_lint.rules.no_offset_pagination import NoOffsetPagination
from sarj_python_lint.rules.no_query_with_many_joins import NoQueryWithManyJoins
from sarj_python_lint.rules.no_raw_sql_in_tests import NoRawSqlInTests
from sarj_python_lint.rules.no_repeated_string_literal import NoRepeatedStringLiteral
from sarj_python_lint.rules.no_secret_in_log import NoSecretInLog
from sarj_python_lint.rules.no_select_star import NoSelectStar
from sarj_python_lint.rules.no_sentinel_return_on_except import NoSentinelReturnOnExcept
from sarj_python_lint.rules.no_sequential_await import NoSequentialAwait
from sarj_python_lint.rules.no_sleep_in_test_body import NoSleepInTestBody
from sarj_python_lint.rules.no_unreachable_after_terminal import (
    NoUnreachableAfterTerminal,
)
from sarj_python_lint.rules.parametrize_case_needs_id import ParametrizeCaseNeedsId
from sarj_python_lint.rules.prefer_class_row import PreferClassRow
from sarj_python_lint.rules.prefer_constant_time_secret_compare import (
    PreferConstantTimeSecretCompare,
)
from sarj_python_lint.rules.prefer_match_assert_never import PreferMatchAssertNever
from sarj_python_lint.rules.prefer_module_level_constant import (
    PreferModuleLevelConstant,
)
from sarj_python_lint.rules.prefer_namedtuple_over_tuple_return import (
    PreferNamedtupleOverTupleReturn,
)
from sarj_python_lint.rules.prefer_str_enum import PreferStrEnum
from sarj_python_lint.rules.prefer_struct_over_namedtuple import (
    PreferStructOverNamedtuple,
)
from sarj_python_lint.rules.prefer_timedelta_for_durations import (
    PreferTimedeltaForDurations,
)
from sarj_python_lint.rules.pydantic_at_boundaries import PydanticAtBoundaries
from sarj_python_lint.rules.single_public_export import SinglePublicExport
from sarj_python_lint.rules.sleep_with_computed_arg_in_test import SleepWithComputedArgInTest
from sarj_python_lint.rules.stepdown import Stepdown
from sarj_python_lint.rules.store_insert_requires_on_conflict import (
    StoreInsertRequiresOnConflict,
)
from sarj_python_lint.rules.test_loops_over_literal_cases import (
    TestLoopsOverLiteralCases,
)
from sarj_python_lint.rules.xfail_requires_strict import XfailRequiresStrict
from sarj_python_lint.rules.zero_assertion_test import ZeroAssertionTest


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Rule


# Retired codes — never reuse these for new rules:
#   SARJ004, SARJ005 (retired before the standards merge),
#   SARJ027, SARJ029, SARJ030 (dropped in 0.11.1 as too noisy),
#   SARJ033 httpx-client-requires-timeout, SARJ035 no-import-time-settings
#   (dropped by user veto after the 0.13.x mined-rules review),
#   SARJ037 no-trivial-single-use-helper (prototyped and dropped for FP rate;
#   see the 0.13.1 inlining commit for the corpus analysis).
REGISTRY: dict[str, type[Rule]] = {
    NoSequentialAwait.id: NoSequentialAwait,
    InefficientStringConcatInLoop.id: InefficientStringConcatInLoop,
    PreferClassRow.id: PreferClassRow,
    PreferStrEnum.id: PreferStrEnum,
    NoFatTryBlocks.id: NoFatTryBlocks,
    NoIsinstanceUnionChain.id: NoIsinstanceUnionChain,
    NoOffsetPagination.id: NoOffsetPagination,
    PreferNamedtupleOverTupleReturn.id: PreferNamedtupleOverTupleReturn,
    NoCorsWildcardWithCredentials.id: NoCorsWildcardWithCredentials,
    NoSleepInTestBody.id: NoSleepInTestBody,
    PydanticAtBoundaries.id: PydanticAtBoundaries,
    NoSentinelReturnOnExcept.id: NoSentinelReturnOnExcept,
    NoUnreachableAfterTerminal.id: NoUnreachableAfterTerminal,
    PreferConstantTimeSecretCompare.id: PreferConstantTimeSecretCompare,
    NoSecretInLog.id: NoSecretInLog,
    PreferTimedeltaForDurations.id: PreferTimedeltaForDurations,
    PreferStructOverNamedtuple.id: PreferStructOverNamedtuple,
    NoCommentCruft.id: NoCommentCruft,
    NoFstringInLog.id: NoFstringInLog,
    StoreInsertRequiresOnConflict.id: StoreInsertRequiresOnConflict,
    NoQueryWithManyJoins.id: NoQueryWithManyJoins,
    NoAggregationInStoreQuery.id: NoAggregationInStoreQuery,
    NoSelectStar.id: NoSelectStar,
    SinglePublicExport.id: SinglePublicExport,
    Stepdown.id: Stepdown,
    NoRepeatedStringLiteral.id: NoRepeatedStringLiteral,
    PreferMatchAssertNever.id: PreferMatchAssertNever,
    KwonlySameTypeParams.id: KwonlySameTypeParams,
    NoRawSqlInTests.id: NoRawSqlInTests,
    NoFileLevelSuppression.id: NoFileLevelSuppression,
    PreferModuleLevelConstant.id: PreferModuleLevelConstant,
    MockWithoutSpec.id: MockWithoutSpec,
    TestLoopsOverLiteralCases.id: TestLoopsOverLiteralCases,
    ParametrizeCaseNeedsId.id: ParametrizeCaseNeedsId,
    FixtureReturnsBareTuple.id: FixtureReturnsBareTuple,
    KwargHeavyConstructionInTest.id: KwargHeavyConstructionInTest,
    XfailRequiresStrict.id: XfailRequiresStrict,
    SleepWithComputedArgInTest.id: SleepWithComputedArgInTest,
    ZeroAssertionTest.id: ZeroAssertionTest,
}

__all__ = ["REGISTRY"]
