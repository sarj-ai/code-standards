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
from sarj_python_lint.rules.no_implicit_attribute_access import NoImplicitAttributeAccess
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
from sarj_python_lint.rules.prefer_match_type_dispatch import PreferMatchTypeDispatch
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
from sarj_python_lint.rules.prefer_pattern_matching import PreferPatternMatching
from sarj_python_lint.rules.prefer_real_store_in_tests import PreferRealStoreInTests
from sarj_python_lint.rules.prefer_self_type_annotation import PreferSelfTypeAnnotation
from sarj_python_lint.rules.prefer_str_enum import PreferStrEnum
from sarj_python_lint.rules.prefer_struct_over_namedtuple import (
    PreferStructOverNamedtuple,
)
from sarj_python_lint.rules.prefer_timedelta_for_durations import (
    PreferTimedeltaForDurations,
)
from sarj_python_lint.rules.prefer_walrus_comprehension_filter import (
    PreferWalrusComprehensionFilter,
)
from sarj_python_lint.rules.prefer_walrus_regex_match import PreferWalrusRegexMatch
from sarj_python_lint.rules.prefer_walrus_stream_loop import PreferWalrusStreamLoop
from sarj_python_lint.rules.primary_export_file_name import (
    PrimaryExportFileName,
)
from sarj_python_lint.rules.pydantic_at_boundaries import PydanticAtBoundaries
from sarj_python_lint.rules.redundant_docstring import RedundantDocstring
from sarj_python_lint.rules.require_port_for_service import RequirePortForService
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

REGISTRY: dict[str, type[Rule]] = {
    NoSequentialAwait.id: NoSequentialAwait,
    InefficientStringConcatInLoop.id: InefficientStringConcatInLoop,
    PreferClassRow.id: PreferClassRow,
    PreferStrEnum.id: PreferStrEnum,
    NoFatTryBlocks.id: NoFatTryBlocks,
    NoIsinstanceUnionChain.id: NoIsinstanceUnionChain,
    NoImplicitAttributeAccess.id: NoImplicitAttributeAccess,
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
    PreferPatternMatching.id: PreferPatternMatching,
    RequirePortForService.id: RequirePortForService,
    PreferNonNullableCollection.id: PreferNonNullableCollection,
    PreferMatchTypeDispatch.id: PreferMatchTypeDispatch,
    PrimaryExportFileName.id: PrimaryExportFileName,
    PreferWalrusRegexMatch.id: PreferWalrusRegexMatch,
    PreferWalrusComprehensionFilter.id: PreferWalrusComprehensionFilter,
    PreferWalrusStreamLoop.id: PreferWalrusStreamLoop,
    PreferSelfTypeAnnotation.id: PreferSelfTypeAnnotation,
}

__all__ = ["REGISTRY"]
