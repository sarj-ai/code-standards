from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_python_lint.rules.conditional_assertion_in_test import ConditionalAssertionInTest
from sarj_python_lint.rules.duplicate_test_body import DuplicateTestBody
from sarj_python_lint.rules.fixture_returns_bare_tuple import FixtureReturnsBareTuple
from sarj_python_lint.rules.inefficient_string_concat_in_loop import (
    InefficientStringConcatInLoop,
)
from sarj_python_lint.rules.interaction_only_test import InteractionOnlyTest
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
from sarj_python_lint.rules.no_file_level_escape_hatch_noqa import NoFileLevelEscapeHatchNoqa
from sarj_python_lint.rules.no_file_level_suppression import NoFileLevelSuppression
from sarj_python_lint.rules.no_first_party_private_import import (
    NoFirstPartyPrivateImport,
)
from sarj_python_lint.rules.no_fstring_in_log import NoFstringInLog
from sarj_python_lint.rules.no_gen_random_uuid_in_sql import NoGenRandomUuidInSql
from sarj_python_lint.rules.no_isinstance_union_chain import NoIsinstanceUnionChain
from sarj_python_lint.rules.no_offset_pagination import NoOffsetPagination
from sarj_python_lint.rules.no_optional_tenant_predicate import (
    NoOptionalTenantPredicate,
)
from sarj_python_lint.rules.no_patching_system_under_test import NoPatchingSystemUnderTest
from sarj_python_lint.rules.no_query_with_many_joins import NoQueryWithManyJoins
from sarj_python_lint.rules.no_raw_sql_in_tests import NoRawSqlInTests
from sarj_python_lint.rules.no_repeated_string_literal import NoRepeatedStringLiteral
from sarj_python_lint.rules.no_restated_comment import NoRestatedComment
from sarj_python_lint.rules.no_secret_in_log import NoSecretInLog
from sarj_python_lint.rules.no_select_star import NoSelectStar
from sarj_python_lint.rules.no_sentinel_return_on_except import NoSentinelReturnOnExcept
from sarj_python_lint.rules.no_sequential_await import NoSequentialAwait
from sarj_python_lint.rules.no_sleep_in_test_body import NoSleepInTestBody
from sarj_python_lint.rules.no_stdlib_logging import NoStdlibLogging
from sarj_python_lint.rules.no_tautological_expect import NoTautologicalExpect
from sarj_python_lint.rules.no_unreachable_after_terminal import (
    NoUnreachableAfterTerminal,
)
from sarj_python_lint.rules.over_mocked_test import OverMockedTest
from sarj_python_lint.rules.parametrize_case_needs_id import ParametrizeCaseNeedsId
from sarj_python_lint.rules.prefer_class_row import PreferClassRow
from sarj_python_lint.rules.prefer_constant_time_secret_compare import (
    PreferConstantTimeSecretCompare,
)
from sarj_python_lint.rules.prefer_fstring_over_concat import PreferFstringOverConcat
from sarj_python_lint.rules.prefer_library_fake import PreferLibraryFake
from sarj_python_lint.rules.prefer_match_assert_never import PreferMatchAssertNever
from sarj_python_lint.rules.prefer_match_pattern_destructuring import PreferMatchPatternDestructuring
from sarj_python_lint.rules.prefer_module_level_constant import (
    PreferModuleLevelConstant,
)
from sarj_python_lint.rules.prefer_namedtuple_over_tuple_return import (
    PreferNamedtupleOverTupleReturn,
)
from sarj_python_lint.rules.prefer_non_nullable_collection import (
    PreferNonNullableCollection,
)
from sarj_python_lint.rules.prefer_or_pattern import PreferOrPattern
from sarj_python_lint.rules.prefer_real_store_in_tests import PreferRealStoreInTests
from sarj_python_lint.rules.prefer_str_enum import PreferStrEnum
from sarj_python_lint.rules.prefer_struct_over_namedtuple import (
    PreferStructOverNamedtuple,
)
from sarj_python_lint.rules.prefer_timedelta_for_durations import (
    PreferTimedeltaForDurations,
)
from sarj_python_lint.rules.primary_export_file_name import (
    PrimaryExportFileName,
)
from sarj_python_lint.rules.pydantic_at_boundaries import PydanticAtBoundaries
from sarj_python_lint.rules.redundant_docstring import RedundantDocstring
from sarj_python_lint.rules.require_port_for_service import RequirePortForService
from sarj_python_lint.rules.primary_export_file_name import (
    PrimaryExportFileName,
)
from sarj_python_lint.rules.single_public_export import SinglePublicExport
from sarj_python_lint.rules.sleep_with_computed_arg_in_test import SleepWithComputedArgInTest
from sarj_python_lint.rules.stepdown import Stepdown
from sarj_python_lint.rules.store_insert_requires_on_conflict import (
    StoreInsertRequiresOnConflict,
)
from sarj_python_lint.rules.tautological_mock_assertion import TautologicalMockAssertion
from sarj_python_lint.rules.test_loops_over_literal_cases import (
    TestLoopsOverLiteralCases,
)
from sarj_python_lint.rules.trailing_value_narration import TrailingValueNarration
from sarj_python_lint.rules.trivially_true_assertion import TriviallyTrueAssertion
from sarj_python_lint.rules.unused_mock_setup import UnusedMockSetup
from sarj_python_lint.rules.xfail_requires_strict import XfailRequiresStrict
from sarj_python_lint.rules.zero_assertion_test import ZeroAssertionTest


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Rule


# Retired codes — never reuse these for new rules:
#   SARJ004, SARJ005 (retired before the standards merge),
#   SARJ027, SARJ029, SARJ030 (dropped in 0.11.1 as too noisy),
#   SARJ033 httpx-client-requires-timeout, SARJ035 no-import-time-settings
#   (dropped by user veto after the 0.13.x mined-rules review),
#   SARJ055 no-filler-success-adverb (built and corpus-validated, then dropped
#   — but not for the reason first recorded. The headline "4.7% of Airflow's
#   info/debug logs" is a composition artifact: 237 of those 248 hits are in
#   `providers/` (contributed vendor operators, heavily copy-pasted — the
#   template "%s completed successfully." appears 22 times verbatim). Airflow's
#   maintainer-owned `airflow-core/` sits at 1.15% and Home Assistant at 1.24%,
#   so the real external baseline is ~1.2%, not 4.7%. The rule was re-measured
#   and dropped on a stronger basis: the narrow variant — fire only when the
#   adverb is the sole content beyond a bare verb — has 12 external hits and
#   ZERO internal ones across all six repos, so it would govern nothing we
#   write. The broad rule remains opt-in house style, not a defect check.
#   (Noted for any future revisit: noura-be measures 7.92%, a genuine outlier
#   against every corpus; that, not the narrow variant, is the case to make.),
#   SARJ037 no-trivial-single-use-helper (prototyped and dropped for FP rate;
#   see the 0.13.1 inlining commit for the corpus analysis).
#   SARJ072 unbound-mock-assertion and SARJ073 raises-needs-specific-error
#   (built, corpus-measured and dropped before ever being registered, in the
#   wave that added SARJ058-071). SARJ072 found 0 hits across 16,130 files in
#   9 repos, including 0 against 8,322 real mock-assertion API uses; ruff B018
#   covers its bare-statement shape. SARJ073 was a strict superset of ruff
#   PT011, which this standard already enables — its one real gap,
#   RuntimeError, is closed by `lint.flake8-pytest-style.raises-require-match-for`.
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
    PrimaryExportFileName.id: PrimaryExportFileName,
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
    NoFirstPartyPrivateImport.id: NoFirstPartyPrivateImport,
    NoRestatedComment.id: NoRestatedComment,
    RedundantDocstring.id: RedundantDocstring,
    TrailingValueNarration.id: TrailingValueNarration,
    NoStdlibLogging.id: NoStdlibLogging,
    NoGenRandomUuidInSql.id: NoGenRandomUuidInSql,
    NoFileLevelEscapeHatchNoqa.id: NoFileLevelEscapeHatchNoqa,
    NoOptionalTenantPredicate.id: NoOptionalTenantPredicate,
    NoTautologicalExpect.id: NoTautologicalExpect,
    PreferRealStoreInTests.id: PreferRealStoreInTests,
    PreferLibraryFake.id: PreferLibraryFake,
    TautologicalMockAssertion.id: TautologicalMockAssertion,
    NoPatchingSystemUnderTest.id: NoPatchingSystemUnderTest,
    OverMockedTest.id: OverMockedTest,
    InteractionOnlyTest.id: InteractionOnlyTest,
    TriviallyTrueAssertion.id: TriviallyTrueAssertion,
    ConditionalAssertionInTest.id: ConditionalAssertionInTest,
    DuplicateTestBody.id: DuplicateTestBody,
    UnusedMockSetup.id: UnusedMockSetup,
    PreferFstringOverConcat.id: PreferFstringOverConcat,
    PreferMatchPatternDestructuring.id: PreferMatchPatternDestructuring,
    PreferOrPattern.id: PreferOrPattern,
    RequirePortForService.id: RequirePortForService,
    PreferNonNullableCollection.id: PreferNonNullableCollection,
}

__all__ = ["REGISTRY"]
