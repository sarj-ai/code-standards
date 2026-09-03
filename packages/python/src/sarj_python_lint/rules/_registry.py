from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from sarj_python_lint.rules.defect_xfail_requires_explicit_strict import DefectXfailRequiresExplicitStrict
from sarj_python_lint.rules.docstring_args_restate_signature import (
    DocstringArgsRestateSignature,
)
from sarj_python_lint.rules.docstring_returns_restate_signature import (
    DocstringReturnsRestateSignature,
)
from sarj_python_lint.rules.excessive_commentary import ExcessiveCommentary
from sarj_python_lint.rules.fakes_in_shared_location import FakesInSharedLocation
from sarj_python_lint.rules.fastapi_explicit_openapi_contract import FastapiExplicitOpenapiContract
from sarj_python_lint.rules.iac_source_coupled_test import IacSourceCoupledTest
from sarj_python_lint.rules.invalid_pydantic_field_default import (
    InvalidPydanticFieldDefault,
)
from sarj_python_lint.rules.mock_without_spec import MockWithoutSpec
from sarj_python_lint.rules.negative_only_http_status_assertion import (
    NegativeOnlyHttpStatusAssertion,
)
from sarj_python_lint.rules.no_analytical_aggregation_in_postgres_store import (
    NoAnalyticalAggregationInPostgresStore,
)
from sarj_python_lint.rules.no_comment_cruft import NoCommentCruft
from sarj_python_lint.rules.no_conftest_test_module_import import NoConftestTestModuleImport
from sarj_python_lint.rules.no_copied_inherited_docstring import NoCopiedInheritedDocstring
from sarj_python_lint.rules.no_cors_wildcard_with_credentials import (
    NoCorsWildcardWithCredentials,
)
from sarj_python_lint.rules.no_duplicate_dunder_all_entry import NoDuplicateDunderAllEntry
from sarj_python_lint.rules.no_fastapi_on_event import NoFastapiOnEvent
from sarj_python_lint.rules.no_file_level_escape_hatch_suppression import (
    NoFileLevelEscapeHatchSuppression,
)
from sarj_python_lint.rules.no_first_party_private_import import (
    NoFirstPartyPrivateImport,
)
from sarj_python_lint.rules.no_frozen_after_validator_field_write import (
    NoFrozenAfterValidatorFieldWrite,
)
from sarj_python_lint.rules.no_generic_single_export_module import NoGenericSingleExportModule
from sarj_python_lint.rules.no_hidden_constructor_fallback import (
    NoHiddenConstructorFallback,
)
from sarj_python_lint.rules.no_nested_pydantic_field_validator import NoNestedPydanticFieldValidator
from sarj_python_lint.rules.no_offset_pagination import NoOffsetPagination
from sarj_python_lint.rules.no_random_uuid_in_sql import NoRandomUuidInSql
from sarj_python_lint.rules.no_raw_connection_in_tests import NoRawConnectionInTests
from sarj_python_lint.rules.no_redundant_literal_description import NoRedundantLiteralDescription
from sarj_python_lint.rules.no_repeated_string_literal import NoRepeatedStringLiteral
from sarj_python_lint.rules.no_repeated_test_body import NoRepeatedTestBody
from sarj_python_lint.rules.no_restated_comment import NoRestatedComment
from sarj_python_lint.rules.no_secret_in_log import NoSecretInLog
from sarj_python_lint.rules.no_select_star import NoSelectStar
from sarj_python_lint.rules.no_sentinel_return_on_except import NoSentinelReturnOnExcept
from sarj_python_lint.rules.no_stdlib_logging import NoStdlibLogging
from sarj_python_lint.rules.no_string_concat_in_loop import NoStringConcatInLoop
from sarj_python_lint.rules.no_tautological_expect import NoTautologicalExpect
from sarj_python_lint.rules.no_typed_doc_sections import NoTypedDocSections
from sarj_python_lint.rules.no_unique_violation_message_match import (
    NoUniqueViolationMessageMatch,
)
from sarj_python_lint.rules.no_unnecessary_docstring import NoUnnecessaryDocstring
from sarj_python_lint.rules.no_vague_suppression_description import (
    NoVagueSuppressionDescription,
)
from sarj_python_lint.rules.opaque_parametrize_case_needs_id import OpaqueParametrizeCaseNeedsId
from sarj_python_lint.rules.over_mocked_test import OverMockedTest
from sarj_python_lint.rules.phase_label_comment import TestPhaseLabelComment
from sarj_python_lint.rules.prefer_class_row import PreferClassRow
from sarj_python_lint.rules.prefer_collection_comprehension import PreferCollectionComprehension
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
from sarj_python_lint.rules.prefer_one_for_required_row import PreferOneForRequiredRow
from sarj_python_lint.rules.prefer_or_pattern import PreferOrPattern
from sarj_python_lint.rules.prefer_self_documenting_constant import (
    PreferSelfDocumentingConstant,
)
from sarj_python_lint.rules.prefer_self_type_annotation import PreferSelfTypeAnnotation
from sarj_python_lint.rules.prefer_set_isdisjoint import PreferSetIsdisjoint
from sarj_python_lint.rules.prefer_str_enum import PreferStrEnum
from sarj_python_lint.rules.prefer_struct_over_namedtuple import (
    PreferStructOverNamedtuple,
)
from sarj_python_lint.rules.prefer_timedelta_for_durations import (
    PreferTimedeltaForDurations,
)
from sarj_python_lint.rules.prefer_walrus_awaited_none_guard import PreferWalrusAwaitedNoneGuard
from sarj_python_lint.rules.prefer_walrus_comprehension_filter import (
    PreferWalrusComprehensionFilter,
)
from sarj_python_lint.rules.prefer_walrus_regex_match import PreferWalrusRegexMatch
from sarj_python_lint.rules.prefer_walrus_stream_loop import PreferWalrusStreamLoop
from sarj_python_lint.rules.preserve_declared_nominal_id import PreserveDeclaredNominalId
from sarj_python_lint.rules.preserve_enum_types import PreserveEnumTypes
from sarj_python_lint.rules.production_derived_test_cases import ProductionDerivedTestCases
from sarj_python_lint.rules.pydantic_at_boundaries import PydanticAtBoundaries
from sarj_python_lint.rules.pytest_fixture_returns_bare_tuple import PytestFixtureReturnsBareTuple
from sarj_python_lint.rules.redundant_class_docstring import RedundantClassDocstring
from sarj_python_lint.rules.redundant_docstring import RedundantDocstring
from sarj_python_lint.rules.redundant_module_docstring import RedundantModuleDocstring
from sarj_python_lint.rules.repeated_kwarg_heavy_call_in_test import RepeatedKwargHeavyCallInTest
from sarj_python_lint.rules.repeated_static_call_cases import RepeatedStaticCallCases
from sarj_python_lint.rules.require_keyword_only_swap_prone_params import (
    RequireKeywordOnlySwapProneParams,
)
from sarj_python_lint.rules.require_nodecode_for_splitting_settings_field import (
    RequireNoDecodeForSplittingSettingsField,
)
from sarj_python_lint.rules.require_port_for_service import RequirePortForService
from sarj_python_lint.rules.require_pydantic_for_external_json import (
    RequirePydanticForExternalJson,
)
from sarj_python_lint.rules.require_pydantic_ordinal_lower_bound import (
    RequirePydanticOrdinalLowerBound,
)
from sarj_python_lint.rules.require_validated_row_factory import RequireValidatedRowFactory
from sarj_python_lint.rules.restated_test_docstring import RestatedTestDocstring
from sarj_python_lint.rules.source_coupled_test import SourceCoupledTest
from sarj_python_lint.rules.sql_requires_injected_pool_owner import SqlRequiresInjectedPoolOwner
from sarj_python_lint.rules.stepdown import Stepdown
from sarj_python_lint.rules.store_get_delegates_to_bulk_read import StoreGetDelegatesToBulkRead
from sarj_python_lint.rules.store_insert_requires_on_conflict import (
    StoreInsertRequiresOnConflict,
)
from sarj_python_lint.rules.timestamp_order_requires_tiebreaker import TimestampOrderRequiresTiebreaker
from sarj_python_lint.rules.trailing_value_narration import TrailingValueNarration
from sarj_python_lint.rules.trivially_true_assertion import TriviallyTrueAssertion
from sarj_python_lint.rules.typed_error_reasons import TypedErrorReasons
from sarj_python_lint.rules.uncontrolled_randomness_in_test import UncontrolledRandomnessInTest
from sarj_python_lint.rules.unused_mock_setup import UnusedMockSetup


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint.rule_base import Rule

REGISTRY: Mapping[str, type[Rule]] = MappingProxyType(
    {
        ExcessiveCommentary.id: ExcessiveCommentary,
        PreferWalrusAwaitedNoneGuard.id: PreferWalrusAwaitedNoneGuard,
        TimestampOrderRequiresTiebreaker.id: TimestampOrderRequiresTiebreaker,
        NoStringConcatInLoop.id: NoStringConcatInLoop,
        PreferClassRow.id: PreferClassRow,
        PreferCollectionComprehension.id: PreferCollectionComprehension,
        PreferStrEnum.id: PreferStrEnum,
        NoOffsetPagination.id: NoOffsetPagination,
        PreferNamedtupleOverTupleReturn.id: PreferNamedtupleOverTupleReturn,
        NoCorsWildcardWithCredentials.id: NoCorsWildcardWithCredentials,
        PydanticAtBoundaries.id: PydanticAtBoundaries,
        FastapiExplicitOpenapiContract.id: FastapiExplicitOpenapiContract,
        FakesInSharedLocation.id: FakesInSharedLocation,
        NoSentinelReturnOnExcept.id: NoSentinelReturnOnExcept,
        PreferConstantTimeSecretCompare.id: PreferConstantTimeSecretCompare,
        NoSecretInLog.id: NoSecretInLog,
        PreferTimedeltaForDurations.id: PreferTimedeltaForDurations,
        PreferStructOverNamedtuple.id: PreferStructOverNamedtuple,
        NoCommentCruft.id: NoCommentCruft,
        NoConftestTestModuleImport.id: NoConftestTestModuleImport,
        StoreInsertRequiresOnConflict.id: StoreInsertRequiresOnConflict,
        SourceCoupledTest.id: SourceCoupledTest,
        IacSourceCoupledTest.id: IacSourceCoupledTest,
        NoRawConnectionInTests.id: NoRawConnectionInTests,
        NoAnalyticalAggregationInPostgresStore.id: NoAnalyticalAggregationInPostgresStore,
        NoSelectStar.id: NoSelectStar,
        NoGenericSingleExportModule.id: NoGenericSingleExportModule,
        Stepdown.id: Stepdown,
        NoRepeatedStringLiteral.id: NoRepeatedStringLiteral,
        PreferMatchAssertNever.id: PreferMatchAssertNever,
        RequireKeywordOnlySwapProneParams.id: RequireKeywordOnlySwapProneParams,
        RequirePydanticForExternalJson.id: RequirePydanticForExternalJson,
        PreferModuleLevelConstant.id: PreferModuleLevelConstant,
        PreferImmutableModuleConstant.id: PreferImmutableModuleConstant,
        MockWithoutSpec.id: MockWithoutSpec,
        OpaqueParametrizeCaseNeedsId.id: OpaqueParametrizeCaseNeedsId,
        PytestFixtureReturnsBareTuple.id: PytestFixtureReturnsBareTuple,
        StoreGetDelegatesToBulkRead.id: StoreGetDelegatesToBulkRead,
        PreferOneForRequiredRow.id: PreferOneForRequiredRow,
        RepeatedKwargHeavyCallInTest.id: RepeatedKwargHeavyCallInTest,
        DefectXfailRequiresExplicitStrict.id: DefectXfailRequiresExplicitStrict,
        NoFirstPartyPrivateImport.id: NoFirstPartyPrivateImport,
        NoRestatedComment.id: NoRestatedComment,
        RedundantDocstring.id: RedundantDocstring,
        TrailingValueNarration.id: TrailingValueNarration,
        NoStdlibLogging.id: NoStdlibLogging,
        NoRandomUuidInSql.id: NoRandomUuidInSql,
        NoHiddenConstructorFallback.id: NoHiddenConstructorFallback,
        NoFileLevelEscapeHatchSuppression.id: NoFileLevelEscapeHatchSuppression,
        NoFastapiOnEvent.id: NoFastapiOnEvent,
        NoTautologicalExpect.id: NoTautologicalExpect,
        PreferLibraryFake.id: PreferLibraryFake,
        OverMockedTest.id: OverMockedTest,
        InvalidPydanticFieldDefault.id: InvalidPydanticFieldDefault,
        NoFrozenAfterValidatorFieldWrite.id: NoFrozenAfterValidatorFieldWrite,
        TriviallyTrueAssertion.id: TriviallyTrueAssertion,
        NoRepeatedTestBody.id: NoRepeatedTestBody,
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
        PreferSetIsdisjoint.id: PreferSetIsdisjoint,
        PreferSelfDocumentingConstant.id: PreferSelfDocumentingConstant,
        NoDuplicateDunderAllEntry.id: NoDuplicateDunderAllEntry,
        NoCopiedInheritedDocstring.id: NoCopiedInheritedDocstring,
        RedundantClassDocstring.id: RedundantClassDocstring,
        RedundantModuleDocstring.id: RedundantModuleDocstring,
        DocstringArgsRestateSignature.id: DocstringArgsRestateSignature,
        DocstringReturnsRestateSignature.id: DocstringReturnsRestateSignature,
        RestatedTestDocstring.id: RestatedTestDocstring,
        TestPhaseLabelComment.id: TestPhaseLabelComment,
        NoNestedPydanticFieldValidator.id: NoNestedPydanticFieldValidator,
        NoRedundantLiteralDescription.id: NoRedundantLiteralDescription,
        NoTypedDocSections.id: NoTypedDocSections,
        NoUnnecessaryDocstring.id: NoUnnecessaryDocstring,
        PreferNominalIdTypes.id: PreferNominalIdTypes,
        NoUniqueViolationMessageMatch.id: NoUniqueViolationMessageMatch,
        NegativeOnlyHttpStatusAssertion.id: NegativeOnlyHttpStatusAssertion,
        ProductionDerivedTestCases.id: ProductionDerivedTestCases,
        UncontrolledRandomnessInTest.id: UncontrolledRandomnessInTest,
        RepeatedStaticCallCases.id: RepeatedStaticCallCases,
        RequireValidatedRowFactory.id: RequireValidatedRowFactory,
        SqlRequiresInjectedPoolOwner.id: SqlRequiresInjectedPoolOwner,
        PreserveDeclaredNominalId.id: PreserveDeclaredNominalId,
        PreserveEnumTypes.id: PreserveEnumTypes,
        RequirePydanticOrdinalLowerBound.id: RequirePydanticOrdinalLowerBound,
        RequireNoDecodeForSplittingSettingsField.id: RequireNoDecodeForSplittingSettingsField,
        NoVagueSuppressionDescription.id: NoVagueSuppressionDescription,
        TypedErrorReasons.id: TypedErrorReasons,
    }
)

__all__ = ["REGISTRY"]
