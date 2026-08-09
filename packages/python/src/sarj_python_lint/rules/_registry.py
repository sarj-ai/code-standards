from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from sarj_python_lint.rules.conditional_assertion_in_test import ConditionalAssertionInTest
from sarj_python_lint.rules.defect_xfail_requires_strict import DefectXfailRequiresStrict
from sarj_python_lint.rules.docstring_args_restate_signature import (
    DocstringArgsRestateSignature,
)
from sarj_python_lint.rules.docstring_returns_restate_signature import (
    DocstringReturnsRestateSignature,
)
from sarj_python_lint.rules.duplicate_test_body import DuplicateTestBody
from sarj_python_lint.rules.duplicated_override_docstring import (
    DuplicatedOverrideDocstring,
)
from sarj_python_lint.rules.fastapi_openapi_contract import FastapiOpenapiContract
from sarj_python_lint.rules.fixture_returns_bare_tuple import FixtureReturnsBareTuple
from sarj_python_lint.rules.interaction_only_test import InteractionOnlyTest
from sarj_python_lint.rules.invalid_pydantic_field_default import (
    InvalidPydanticFieldDefault,
)
from sarj_python_lint.rules.kwarg_heavy_construction_in_test import KwargHeavyConstructionInTest
from sarj_python_lint.rules.mock_without_spec import MockWithoutSpec
from sarj_python_lint.rules.no_aggregation_in_store_query import (
    NoAggregationInStoreQuery,
)
from sarj_python_lint.rules.no_comment_cruft import NoCommentCruft
from sarj_python_lint.rules.no_cors_wildcard_with_credentials import (
    NoCorsWildcardWithCredentials,
)
from sarj_python_lint.rules.no_duplicate_dunder_all_entry import NoDuplicateDunderAllEntry
from sarj_python_lint.rules.no_file_level_escape_hatch_noqa import NoFileLevelEscapeHatchNoqa
from sarj_python_lint.rules.no_file_level_suppression import NoFileLevelSuppression
from sarj_python_lint.rules.no_first_party_private_import import (
    NoFirstPartyPrivateImport,
)
from sarj_python_lint.rules.no_frozen_after_validator_field_write import (
    NoFrozenAfterValidatorFieldWrite,
)
from sarj_python_lint.rules.no_gen_random_uuid_in_sql import NoGenRandomUuidInSql
from sarj_python_lint.rules.no_generic_single_export_module import NoGenericSingleExportModule
from sarj_python_lint.rules.no_hidden_constructor_fallback import (
    NoHiddenConstructorFallback,
)
from sarj_python_lint.rules.no_isinstance_union_chain import NoIsinstanceUnionChain
from sarj_python_lint.rules.no_long_comment import NoLongComment
from sarj_python_lint.rules.no_offset_pagination import NoOffsetPagination
from sarj_python_lint.rules.no_optional_tenant_predicate import (
    NoOptionalTenantPredicate,
)
from sarj_python_lint.rules.no_query_with_many_joins import NoQueryWithManyJoins
from sarj_python_lint.rules.no_repeated_string_literal import NoRepeatedStringLiteral
from sarj_python_lint.rules.no_restated_comment import NoRestatedComment
from sarj_python_lint.rules.no_secret_in_log import NoSecretInLog
from sarj_python_lint.rules.no_select_star import NoSelectStar
from sarj_python_lint.rules.no_sentinel_return_on_except import NoSentinelReturnOnExcept
from sarj_python_lint.rules.no_stdlib_logging import NoStdlibLogging
from sarj_python_lint.rules.no_string_concat_in_loop import NoStringConcatInLoop
from sarj_python_lint.rules.no_tautological_expect import NoTautologicalExpect
from sarj_python_lint.rules.no_typed_doc_sections import NoTypedDocSections
from sarj_python_lint.rules.opaque_parametrize_case_needs_id import OpaqueParametrizeCaseNeedsId
from sarj_python_lint.rules.over_mocked_test import OverMockedTest
from sarj_python_lint.rules.phase_label_comment import TestPhaseLabelComment
from sarj_python_lint.rules.prefer_class_row import PreferClassRow
from sarj_python_lint.rules.prefer_constant_time_secret_compare import (
    PreferConstantTimeSecretCompare,
)
from sarj_python_lint.rules.prefer_fstring_over_concat import PreferFstringOverConcat
from sarj_python_lint.rules.prefer_immutable_module_constant import (
    PreferImmutableModuleConstant,
)
from sarj_python_lint.rules.prefer_library_fake import PreferLibraryFake
from sarj_python_lint.rules.prefer_match_assert_never import PreferMatchAssertNever
from sarj_python_lint.rules.prefer_match_type_dispatch import PreferMatchTypeDispatch
from sarj_python_lint.rules.prefer_module_level_constant import (
    PreferModuleLevelConstant,
)
from sarj_python_lint.rules.prefer_namedtuple_over_tuple_return import (
    PreferNamedtupleOverTupleReturn,
)
from sarj_python_lint.rules.prefer_nominal_id_types import PreferNominalIdTypes
from sarj_python_lint.rules.prefer_non_nullable_collection import (
    PreferNonNullableCollection,
)
from sarj_python_lint.rules.prefer_or_pattern import PreferOrPattern
from sarj_python_lint.rules.prefer_self_documenting_constant import (
    PreferSelfDocumentingConstant,
)
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
from sarj_python_lint.rules.pydantic_at_boundaries import PydanticAtBoundaries
from sarj_python_lint.rules.redundant_class_docstring import RedundantClassDocstring
from sarj_python_lint.rules.redundant_docstring import RedundantDocstring
from sarj_python_lint.rules.redundant_module_docstring import RedundantModuleDocstring
from sarj_python_lint.rules.require_keyword_only_swap_prone_params import (
    RequireKeywordOnlySwapProneParams,
)
from sarj_python_lint.rules.require_port_for_service import RequirePortForService
from sarj_python_lint.rules.restated_test_docstring import RestatedTestDocstring
from sarj_python_lint.rules.stepdown import Stepdown
from sarj_python_lint.rules.store_insert_requires_on_conflict import (
    StoreInsertRequiresOnConflict,
)
from sarj_python_lint.rules.trailing_value_narration import TrailingValueNarration
from sarj_python_lint.rules.trivially_true_assertion import TriviallyTrueAssertion
from sarj_python_lint.rules.unused_mock_setup import UnusedMockSetup
from sarj_python_lint.rules.zero_assertion_test import ZeroAssertionTest


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint.rule_base import Rule

REGISTRY: Mapping[str, type[Rule]] = MappingProxyType(
    {
        NoStringConcatInLoop.id: NoStringConcatInLoop,
        PreferClassRow.id: PreferClassRow,
        PreferStrEnum.id: PreferStrEnum,
        NoIsinstanceUnionChain.id: NoIsinstanceUnionChain,
        NoOffsetPagination.id: NoOffsetPagination,
        PreferNamedtupleOverTupleReturn.id: PreferNamedtupleOverTupleReturn,
        NoCorsWildcardWithCredentials.id: NoCorsWildcardWithCredentials,
        PydanticAtBoundaries.id: PydanticAtBoundaries,
        FastapiOpenapiContract.id: FastapiOpenapiContract,
        NoSentinelReturnOnExcept.id: NoSentinelReturnOnExcept,
        PreferConstantTimeSecretCompare.id: PreferConstantTimeSecretCompare,
        NoSecretInLog.id: NoSecretInLog,
        PreferTimedeltaForDurations.id: PreferTimedeltaForDurations,
        PreferStructOverNamedtuple.id: PreferStructOverNamedtuple,
        NoCommentCruft.id: NoCommentCruft,
        StoreInsertRequiresOnConflict.id: StoreInsertRequiresOnConflict,
        NoQueryWithManyJoins.id: NoQueryWithManyJoins,
        NoAggregationInStoreQuery.id: NoAggregationInStoreQuery,
        NoSelectStar.id: NoSelectStar,
        NoGenericSingleExportModule.id: NoGenericSingleExportModule,
        Stepdown.id: Stepdown,
        NoRepeatedStringLiteral.id: NoRepeatedStringLiteral,
        PreferMatchAssertNever.id: PreferMatchAssertNever,
        RequireKeywordOnlySwapProneParams.id: RequireKeywordOnlySwapProneParams,
        NoFileLevelSuppression.id: NoFileLevelSuppression,
        PreferModuleLevelConstant.id: PreferModuleLevelConstant,
        PreferImmutableModuleConstant.id: PreferImmutableModuleConstant,
        MockWithoutSpec.id: MockWithoutSpec,
        OpaqueParametrizeCaseNeedsId.id: OpaqueParametrizeCaseNeedsId,
        FixtureReturnsBareTuple.id: FixtureReturnsBareTuple,
        KwargHeavyConstructionInTest.id: KwargHeavyConstructionInTest,
        DefectXfailRequiresStrict.id: DefectXfailRequiresStrict,
        ZeroAssertionTest.id: ZeroAssertionTest,
        NoFirstPartyPrivateImport.id: NoFirstPartyPrivateImport,
        NoRestatedComment.id: NoRestatedComment,
        RedundantDocstring.id: RedundantDocstring,
        TrailingValueNarration.id: TrailingValueNarration,
        NoStdlibLogging.id: NoStdlibLogging,
        NoGenRandomUuidInSql.id: NoGenRandomUuidInSql,
        NoHiddenConstructorFallback.id: NoHiddenConstructorFallback,
        NoFileLevelEscapeHatchNoqa.id: NoFileLevelEscapeHatchNoqa,
        NoOptionalTenantPredicate.id: NoOptionalTenantPredicate,
        NoTautologicalExpect.id: NoTautologicalExpect,
        PreferLibraryFake.id: PreferLibraryFake,
        OverMockedTest.id: OverMockedTest,
        InteractionOnlyTest.id: InteractionOnlyTest,
        InvalidPydanticFieldDefault.id: InvalidPydanticFieldDefault,
        NoFrozenAfterValidatorFieldWrite.id: NoFrozenAfterValidatorFieldWrite,
        TriviallyTrueAssertion.id: TriviallyTrueAssertion,
        ConditionalAssertionInTest.id: ConditionalAssertionInTest,
        DuplicateTestBody.id: DuplicateTestBody,
        UnusedMockSetup.id: UnusedMockSetup,
        PreferFstringOverConcat.id: PreferFstringOverConcat,
        PreferOrPattern.id: PreferOrPattern,
        RequirePortForService.id: RequirePortForService,
        PreferNonNullableCollection.id: PreferNonNullableCollection,
        PreferMatchTypeDispatch.id: PreferMatchTypeDispatch,
        PreferWalrusRegexMatch.id: PreferWalrusRegexMatch,
        PreferWalrusComprehensionFilter.id: PreferWalrusComprehensionFilter,
        PreferWalrusStreamLoop.id: PreferWalrusStreamLoop,
        PreferSelfTypeAnnotation.id: PreferSelfTypeAnnotation,
        PreferSelfDocumentingConstant.id: PreferSelfDocumentingConstant,
        NoDuplicateDunderAllEntry.id: NoDuplicateDunderAllEntry,
        DuplicatedOverrideDocstring.id: DuplicatedOverrideDocstring,
        RedundantClassDocstring.id: RedundantClassDocstring,
        RedundantModuleDocstring.id: RedundantModuleDocstring,
        DocstringArgsRestateSignature.id: DocstringArgsRestateSignature,
        DocstringReturnsRestateSignature.id: DocstringReturnsRestateSignature,
        RestatedTestDocstring.id: RestatedTestDocstring,
        TestPhaseLabelComment.id: TestPhaseLabelComment,
        NoLongComment.id: NoLongComment,
        NoTypedDocSections.id: NoTypedDocSections,
        PreferNominalIdTypes.id: PreferNominalIdTypes,
    }
)

__all__ = ["REGISTRY"]
