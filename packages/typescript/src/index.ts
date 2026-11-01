import preferDependencyInterface from "./rules/prefer-dependency-interface.js";
import noMutatingInputWithResult from "./rules/no-mutating-input-with-result.js";
import noNegativeOnlyHttpStatusAssertion from "./rules/no-negative-only-http-status-assertion.js";
import preferTestFixtureReuse from "./rules/prefer-test-fixture-reuse.js";
import noReturnDisposedResource from "./rules/no-return-disposed-resource.js";
import requireJwtLifetime from "./rules/require-jwt-lifetime.js";
import noDiscardedValidationResult from "./rules/no-discarded-validation-result.js";
import productionDerivedTestCases from "./rules/production-derived-test-cases.js";
import requireConstrainedSchemaInteger from "./rules/require-constrained-schema-integer.js";
import noGenericJsonParser from "./rules/no-generic-json-parser.js";
import noRedundantLocalAlias from "./rules/no-redundant-local-alias.js";
import noTestComments from "./rules/no-test-comments.js";
import noMutatingContainerTransform from "./rules/no-mutating-container-transform.js";
import noRedundantConsumerUnion from "./rules/no-redundant-consumer-union.js";
import preferMinimalParameterContract from "./rules/prefer-minimal-parameter-contract.js";
import noExcessJsxProps from "./rules/no-excess-jsx-props.js";
import preferNativeFetchInServerActions from "./rules/prefer-native-fetch-in-server-actions.js";
import noCredentialInBrowserStorage from "./rules/no-credential-in-browser-storage.js";
import noNumericSearchParamCoercion from "./rules/no-numeric-search-param-coercion.js";
import packageMetadata from "../package.json" with { type: "json" };
import requireExplicitContractImplementation from "./rules/require-explicit-contract-implementation.js";
import requireExplicitServiceContract from "./rules/require-explicit-service-contract.js";
import noConditionalEmptyObjectSpread from "./rules/no-conditional-empty-object-spread.js";
import preferTypedReflection from "./rules/prefer-typed-reflection.js";
import noBroadReturnType from "./rules/no-broad-return-type.js";
import noReduceAccumulatorCopy from "./rules/no-reduce-accumulator-copy.js";
import noKnownValueWidening from "./rules/no-known-value-widening.js";
import noInvalidTypedMutation from "./rules/no-invalid-typed-mutation.js";
import noContradictoryTypePredicate from "./rules/no-contradictory-type-predicate.js";
import noPartialTypePredicate from "./rules/no-partial-type-predicate.js";
import noBooleanSelectorParameter from "./rules/no-boolean-selector-parameter.js";
import noInvalidZodCustomParse from "./rules/no-invalid-zod-custom-parse.js";
import noContradictoryOverloadReturn from "./rules/no-contradictory-overload-return.js";
/**
 * @fileoverview index — the plugin's rule registry and its two presets; the historical rename map lives in `rules/_renamed-rules.ts`.
 */

import requireButtonAccessibleName from "./rules/require-button-accessible-name.js";
import requireCamelcaseProperties from "./rules/require-camelcase-properties.js";
import requireSvgAccessibleName from "./rules/require-svg-accessible-name.js";
import preferLogicalTailwindUtilities from "./rules/prefer-logical-tailwind-utilities.js";
import noUnlocalizedToast from "./rules/no-unlocalized-toast.js";
import noUnlocalizedJsxAttributes from "./rules/no-unlocalized-jsx-attributes.js";
import noUnlocalizedJsxText from "./rules/no-unlocalized-jsx-text.js";
import { LIBRARY_POLICY } from "./library-policy.js";
import enforceFileStructure from "./rules/enforce-file-structure.js";
import duplicateTestBody from "./rules/duplicate-test-body.js";
import excessiveCommentary from "./rules/excessive-commentary.js";
import noClientSideDataFetching from "./rules/no-client-side-data-fetching.js";
import noCommentCruft from "./rules/no-comment-cruft.js";
import noCorsWildcardWithCredentials from "./rules/no-cors-wildcard-with-credentials.js";
import noDuplicateLifecycleRefreshListeners from "./rules/no-duplicate-lifecycle-refresh-listeners.js";
import noDangerouslyAllowSvg from "./rules/no-dangerously-allow-svg.js";
import noDynamicSql from "./rules/no-dynamic-sql.js";
import noEnum from "./rules/no-enum.js";
import noExcessiveCognitiveComplexity from "./rules/no-excessive-cognitive-complexity.js";
import noFatTryBlocks from "./rules/no-fat-try-blocks.js";
import noHandRolledSleep from "./rules/no-hand-rolled-sleep.js";
import noHandRolledSpinner from "./rules/no-hand-rolled-spinner.js";
import noInsecureRandomId from "./rules/no-insecure-random-id.js";
import noDetachedGlobalFetch from "./rules/no-detached-global-fetch.js";
import noExceptionTextIn5xxResponse from "./rules/no-exception-text-in-5xx-response.js";
import noJsonStringifyError from "./rules/no-json-stringify-error.js";
import noJsonStringifyObjectEquality from "./rules/no-json-stringify-object-equality.js";
import noImpossibleZodLiteralBounds from "./rules/no-impossible-zod-literal-bounds.js";
import noInOperatorOnBuiltInCollections from "./rules/no-in-operator-on-built-in-collections.js";
import noRedundantOptionalArrayDefault from "./rules/no-redundant-optional-array-default.js";
import interfaceContractMembersPrivate from "./rules/interface-contract-members-private.js";
import noLogOnlyCatch from "./rules/no-log-only-catch.js";
import noBareReturnFromTestCatch from "./rules/no-bare-return-from-test-catch.js";
import noBespokeApiCaseConversion from "./rules/no-bespoke-api-case-conversion.js";
import noLongComment from "./rules/no-long-comment.js";
import noVagueSuppressionDescription from "./rules/no-vague-suppression-description.js";
import noGenericSingleExportModule from "./rules/no-generic-single-export-module.js";
import noOffsetPagination from "./rules/no-offset-pagination.js";
import noPositionalTupleReturn from "./rules/no-positional-tuple-return.js";
import noProductionBrowserSourceMaps from "./rules/no-production-browser-source-maps.js";
import noRawEnv from "./rules/no-raw-env.js";
import noRawFetchOutsideClients from "./rules/no-raw-fetch-outside-clients.js";
import noRestrictedLibraryLoad from "./rules/no-restricted-library-load.js";
import noRouterRefreshPolling from "./rules/no-router-refresh-polling.js";
import noRepeatedStringLiteral from "./rules/no-repeated-string-literal.js";
import noRestatedComment from "./rules/no-restated-comment.js";
import noRestatedJsdoc from "./rules/no-restated-jsdoc.js";
import noSecretInLog from "./rules/no-secret-in-log.js";
import noServerEnvInClientComponent from "./rules/no-server-env-in-client-component.js";
import noServerFileUploads from "./rules/no-server-file-uploads.js";
import noSelectStar from "./rules/no-select-star.js";
import noSentinelReturnOnCatch from "./rules/no-sentinel-return-on-catch.js";
import noSilentPromiseCatch from "./rules/no-silent-promise-catch.js";
import noSleepInTestBody from "./rules/no-sleep-in-test-body.js";
import noStorageInStatelessModules from "./rules/no-storage-in-stateless-modules.js";
import noStringConcatInLoop from "./rules/no-string-concat-in-loop.js";
import noDuplicateTestCase from "./rules/no-duplicate-test-case.js";
import noTautologicalExpect from "./rules/no-tautological-expect.js";
import noTypedDocSections from "./rules/no-typed-doc-sections.js";
import noTrailingValueNarration from "./rules/no-trailing-value-narration.js";
import noDeclarationCommentWall from "./rules/no-declaration-comment-wall.js";
import noUnionInComment from "./rules/no-union-in-comment.js";
import noTypeMemberCommentWall from "./rules/no-type-member-comment-wall.js";
import noUnnecessaryUseClient from "./rules/no-unnecessary-use-client.js";
import noUnsafeMockCasting from "./rules/no-unsafe-mock-casting.js";
import noUnsafeTestDoubleCast from "./rules/no-unsafe-test-double-cast.js";
import noFirstPartyModuleMock from "./rules/no-first-party-module-mock.js";
import noZodNativeEnum from "./rules/no-zod-native-enum.js";
import testLoopsOverLiteralCases from "./rules/test-loops-over-literal-cases.js";
import testPhaseLabelComment from "./rules/test-phase-label-comment.js";
import preferConstantTimeSecretCompare from "./rules/prefer-constant-time-secret-compare.js";
import preferEcmascriptPrivateMembers from "./rules/prefer-ecmascript-private-members.js";
import preferDiscriminatedUnion from "./rules/prefer-discriminated-union.js";
import preferInputGroupSearch from "./rules/prefer-input-group-search.js";
import preferMillisecondControlDurationSchema from "./rules/prefer-millisecond-control-duration-schema.js";
import preferImmutableModuleConstant from "./rules/prefer-immutable-module-constant.js";
import preferShadcnPrimitives from "./rules/prefer-shadcn-primitives.js";
import preferModuleLevelConstant from "./rules/prefer-module-level-constant.js";
import preferModuleLevelSchema from "./rules/prefer-module-level-schema.js";
import preferModuleLevelRefinedSchema from "./rules/prefer-module-level-refined-schema.js";
import preferMultiValueZodLiteral from "./rules/prefer-multi-value-zod-literal.js";
import preferNominalIdTypes from "./rules/prefer-nominal-id-types.js";
import preferNamedCallbackDomain from "./rules/prefer-named-callback-domain.js";
import preferNamedComplexReturnType from "./rules/prefer-named-complex-return-type.js";
import preferNativeRandomUuid from "./rules/prefer-native-random-uuid.js";
import preferNodeCryptoHash from "./rules/prefer-node-crypto-hash.js";
import preferNodeFsPromises from "./rules/prefer-node-fs-promises.js";
import preferNonNullableCollection from "./rules/prefer-non-nullable-collection.js";
import preferNullishFilterPredicate from "./rules/prefer-nullish-filter-predicate.js";
import preferAwaitInAsyncReturn from "./rules/prefer-await-in-async-return.js";
import preferSchemaForApiPayload from "./rules/prefer-schema-for-api-payload.js";
import preferSharedZodEnum from "./rules/prefer-shared-zod-enum.js";
import preferSwitchForRepeatedEquality from "./rules/prefer-switch-for-repeated-equality.js";
import preferSemanticColors from "./rules/prefer-semantic-colors.js";
import preferServerActions from "./rules/prefer-server-actions.js";
import preferWholeObjectAssertion from "./rules/prefer-whole-object-assertion.js";
import repeatedStaticCallCases from "./rules/repeated-static-call-cases.js";
import preferZodInfer from "./rules/prefer-zod-infer.js";
import namedChildSchemaType from "./rules/named-child-schema-type.js";
import preferZodParseOutputType from "./rules/prefer-zod-parse-output-type.js";
import requireAssertNever from "./rules/require-assert-never.js";
import requireFetchTimeout from "./rules/require-fetch-timeout.js";
import requireInterfaceForExportedClass from "./rules/require-interface-for-exported-class.js";
import requirePortForService from "./rules/require-port-for-service.js";
import requireSqlAccessClass from "./rules/require-sql-access-class.js";
import requireStaticNextMatcher from "./rules/require-static-next-matcher.js";
import requireUseFormDefaultValues from "./rules/require-use-form-default-values.js";
import requireUseServerInActionsFile from "./rules/require-use-server-in-actions-file.js";
import requireZodFormValidation from "./rules/require-zod-form-validation.js";
import storeInsertRequiresOnConflict from "./rules/store-insert-requires-on-conflict.js";
import stepdown from "./rules/stepdown.js";
import sourceCoupledTest from "./rules/source-coupled-test.js";
import soleExportMatchesFilename from "./rules/sole-export-matches-filename.js";
import iacSourceCoupledTest from "./rules/iac-source-coupled-test.js";
import requirePascalCaseZodSchemaName from "./rules/require-pascal-case-zod-schema-name.js";
import { RENAMED_RULES } from "./rules/_renamed-rules.js";
import { RETIRED_RULES } from "./rules/_retired-rules.js";

const RULES = {
  "no-mutating-input-with-result": noMutatingInputWithResult,
  "no-negative-only-http-status-assertion": noNegativeOnlyHttpStatusAssertion,
  "production-derived-test-cases": productionDerivedTestCases,
  "prefer-test-fixture-reuse": preferTestFixtureReuse,
  "no-return-disposed-resource": noReturnDisposedResource,
  "require-constrained-schema-integer": requireConstrainedSchemaInteger,
  "no-discarded-validation-result": noDiscardedValidationResult,
  "require-jwt-lifetime": requireJwtLifetime,
  "prefer-dependency-interface": preferDependencyInterface,
  "no-generic-json-parser": noGenericJsonParser,
  "no-redundant-local-alias": noRedundantLocalAlias,
  "no-test-comments": noTestComments,
  "no-mutating-container-transform": noMutatingContainerTransform,
  "no-redundant-consumer-union": noRedundantConsumerUnion,
  "prefer-minimal-parameter-contract": preferMinimalParameterContract,
  "no-excess-jsx-props": noExcessJsxProps,
  "prefer-native-fetch-in-server-actions": preferNativeFetchInServerActions,
  "no-credential-in-browser-storage": noCredentialInBrowserStorage,
  "no-numeric-search-param-coercion": noNumericSearchParamCoercion,
  "require-explicit-contract-implementation": requireExplicitContractImplementation,
  "require-explicit-service-contract": requireExplicitServiceContract,
  "no-conditional-empty-object-spread": noConditionalEmptyObjectSpread,
  "prefer-typed-reflection": preferTypedReflection,
  "no-broad-return-type": noBroadReturnType,
  "no-reduce-accumulator-copy": noReduceAccumulatorCopy,
  "no-known-value-widening": noKnownValueWidening,
  "no-invalid-typed-mutation": noInvalidTypedMutation,
  "no-contradictory-type-predicate": noContradictoryTypePredicate,
  "no-partial-type-predicate": noPartialTypePredicate,
  "no-boolean-selector-parameter": noBooleanSelectorParameter,
  "no-invalid-zod-custom-parse": noInvalidZodCustomParse,
  "no-contradictory-overload-return": noContradictoryOverloadReturn,
  "require-button-accessible-name": requireButtonAccessibleName,
  "require-camelcase-properties": requireCamelcaseProperties,
  "require-svg-accessible-name": requireSvgAccessibleName,
  "prefer-logical-tailwind-utilities": preferLogicalTailwindUtilities,
  "no-unlocalized-toast": noUnlocalizedToast,
  "no-unlocalized-jsx-attributes": noUnlocalizedJsxAttributes,
  "no-unlocalized-jsx-text": noUnlocalizedJsxText,
  "excessive-commentary": excessiveCommentary,
  "iac-source-coupled-test": iacSourceCoupledTest,
  "duplicate-test-body": duplicateTestBody,
  "enforce-file-structure": enforceFileStructure,
  "no-client-side-data-fetching": noClientSideDataFetching,
  "no-comment-cruft": noCommentCruft,
  "no-cors-wildcard-with-credentials": noCorsWildcardWithCredentials,
  "no-duplicate-lifecycle-refresh-listeners":
    noDuplicateLifecycleRefreshListeners,
  "no-dangerously-allow-svg": noDangerouslyAllowSvg,
  "no-dynamic-sql": noDynamicSql,
  "no-enum": noEnum,
  "no-excessive-cognitive-complexity": noExcessiveCognitiveComplexity,
  "no-fat-try-blocks": noFatTryBlocks,
  "no-hand-rolled-sleep": noHandRolledSleep,
  "no-hand-rolled-spinner": noHandRolledSpinner,
  "no-insecure-random-id": noInsecureRandomId,
  "no-detached-global-fetch": noDetachedGlobalFetch,
  "no-exception-text-in-5xx-response": noExceptionTextIn5xxResponse,
  "no-json-stringify-error": noJsonStringifyError,
  "no-json-stringify-object-equality": noJsonStringifyObjectEquality,
  "no-impossible-zod-literal-bounds": noImpossibleZodLiteralBounds,
  "no-in-operator-on-built-in-collections": noInOperatorOnBuiltInCollections,
  "no-redundant-optional-array-default": noRedundantOptionalArrayDefault,
  "interface-contract-members-private": interfaceContractMembersPrivate,
  "no-log-only-catch": noLogOnlyCatch,
  "no-bare-return-from-test-catch": noBareReturnFromTestCatch,
  "no-bespoke-api-case-conversion": noBespokeApiCaseConversion,
  "no-long-comment": noLongComment,
  "no-vague-suppression-description": noVagueSuppressionDescription,
  "no-generic-single-export-module": noGenericSingleExportModule,
  "no-offset-pagination": noOffsetPagination,
  "no-positional-tuple-return": noPositionalTupleReturn,
  "no-production-browser-source-maps": noProductionBrowserSourceMaps,
  "no-raw-env": noRawEnv,
  "no-raw-fetch-outside-clients": noRawFetchOutsideClients,
  "no-restricted-library-load": noRestrictedLibraryLoad,
  "no-router-refresh-polling": noRouterRefreshPolling,
  "no-repeated-string-literal": noRepeatedStringLiteral,
  "no-restated-comment": noRestatedComment,
  "no-restated-jsdoc": noRestatedJsdoc,
  "no-secret-in-log": noSecretInLog,
  "no-server-env-in-client-component": noServerEnvInClientComponent,
  "no-server-file-uploads": noServerFileUploads,
  "no-select-star": noSelectStar,
  "no-sentinel-return-on-catch": noSentinelReturnOnCatch,
  "no-silent-promise-catch": noSilentPromiseCatch,
  "no-sleep-in-test-body": noSleepInTestBody,
  "no-storage-in-stateless-modules": noStorageInStatelessModules,
  "no-string-concat-in-loop": noStringConcatInLoop,
  "no-tautological-expect": noTautologicalExpect,
  "no-duplicate-test-case": noDuplicateTestCase,
  "no-typed-doc-sections": noTypedDocSections,
  "no-trailing-value-narration": noTrailingValueNarration,
  "no-declaration-comment-wall": noDeclarationCommentWall,
  "no-union-in-comment": noUnionInComment,
  "no-type-member-comment-wall": noTypeMemberCommentWall,
  "no-unnecessary-use-client": noUnnecessaryUseClient,
  "no-unsafe-mock-casting": noUnsafeMockCasting,
  "no-unsafe-test-double-cast": noUnsafeTestDoubleCast,
  "no-first-party-module-mock": noFirstPartyModuleMock,
  "no-zod-native-enum": noZodNativeEnum,
  "require-use-form-default-values": requireUseFormDefaultValues,
  "require-use-server-in-actions-file": requireUseServerInActionsFile,
  "test-loops-over-literal-cases": testLoopsOverLiteralCases,
  "test-phase-label-comment": testPhaseLabelComment,
  "prefer-constant-time-secret-compare": preferConstantTimeSecretCompare,
  "prefer-ecmascript-private-members": preferEcmascriptPrivateMembers,
  "prefer-discriminated-union": preferDiscriminatedUnion,
  "prefer-input-group-search": preferInputGroupSearch,
  "prefer-millisecond-control-duration-schema": preferMillisecondControlDurationSchema,
  "prefer-immutable-module-constant": preferImmutableModuleConstant,
  "prefer-shadcn-primitives": preferShadcnPrimitives,
  "prefer-module-level-constant": preferModuleLevelConstant,
  "prefer-module-level-schema": preferModuleLevelSchema,
  "prefer-module-level-refined-schema": preferModuleLevelRefinedSchema,
  "prefer-multi-value-zod-literal": preferMultiValueZodLiteral,
  "prefer-named-callback-domain": preferNamedCallbackDomain,
  "prefer-nominal-id-types": preferNominalIdTypes,
  "prefer-named-complex-return-type": preferNamedComplexReturnType,
  "prefer-native-random-uuid": preferNativeRandomUuid,
  "prefer-node-crypto-hash": preferNodeCryptoHash,
  "prefer-node-fs-promises": preferNodeFsPromises,
  "prefer-non-nullable-collection": preferNonNullableCollection,
  "prefer-nullish-filter-predicate": preferNullishFilterPredicate,
  "prefer-await-in-async-return": preferAwaitInAsyncReturn,
  "prefer-schema-for-api-payload": preferSchemaForApiPayload,
  "prefer-shared-zod-enum": preferSharedZodEnum,
  "prefer-switch-for-repeated-equality": preferSwitchForRepeatedEquality,
  "prefer-semantic-colors": preferSemanticColors,
  "prefer-server-actions": preferServerActions,
  "prefer-whole-object-assertion": preferWholeObjectAssertion,
  "repeated-static-call-cases": repeatedStaticCallCases,
  "prefer-zod-infer": preferZodInfer,
  "named-child-schema-type": namedChildSchemaType,
  "prefer-zod-parse-output-type": preferZodParseOutputType,
  "require-assert-never": requireAssertNever,
  "require-fetch-timeout": requireFetchTimeout,
  "require-interface-for-exported-class": requireInterfaceForExportedClass,
  "require-port-for-service": requirePortForService,
  "require-sql-access-class": requireSqlAccessClass,
  "require-static-next-matcher": requireStaticNextMatcher,
  "require-zod-form-validation": requireZodFormValidation,
  "store-insert-requires-on-conflict": storeInsertRequiresOnConflict,
  "stepdown": stepdown,
  "source-coupled-test": sourceCoupledTest,
  "sole-export-matches-filename": soleExportMatchesFilename,
  "require-pascal-case-zod-schema-name": requirePascalCaseZodSchemaName,
} as const;

const meta = {
  name: "@sarj/eslint-plugin",
  version: packageMetadata.version,
} as const;

/** @deprecated All repositories use one policy; retained for import compatibility. */
const APPLICATION_ONLY_RULES = [] as const;

const LIBRARY_IMPORT_POLICY = ["error", {
  paths: LIBRARY_POLICY.map(({ module, note }) => ({ name: module, message: note })),
  patterns: LIBRARY_POLICY.map(({ module, note }) => ({ group: [`${module}/*`], message: note })),
}] as const;

type PresetMembership = "both" | "strict";
type RuleOptions<Name extends keyof typeof RULES> = NonNullable<(typeof RULES)[Name]["defaultOptions"]>;
type OwnRulePolicy<Options extends readonly unknown[]> =
  | readonly [level: "error" | "warn", membership: PresetMembership]
  | readonly [level: "error" | "warn", membership: PresetMembership, options: () => Options]
  | readonly [level: "error" | "warn", membership: PresetMembership, order: "strict-order", position: number];
type PresetPolicy = {
  readonly [Name in keyof typeof RULES as `@sarj/${Name}`]?: OwnRulePolicy<RuleOptions<Name>>;
} & {
  readonly "no-restricted-imports": readonly ["shared", "both", typeof LIBRARY_IMPORT_POLICY];
};

const RULE_POLICY = {
  "@sarj/no-excess-jsx-props": ["warn", "both"],
  "@sarj/no-redundant-consumer-union": ["warn", "both"],
  "@sarj/prefer-minimal-parameter-contract": ["warn", "both"],
  "@sarj/named-child-schema-type": ["error", "both"],
  "@sarj/no-conditional-empty-object-spread": ["error", "both"],
  "@sarj/prefer-typed-reflection": ["error", "both"],
  "@sarj/no-broad-return-type": ["error", "both"],
  "@sarj/no-reduce-accumulator-copy": ["error", "both"],
  "@sarj/no-known-value-widening": ["error", "both"],
  "@sarj/no-invalid-typed-mutation": ["error", "both"],
  "@sarj/no-contradictory-type-predicate": ["error", "both"],
  "@sarj/no-partial-type-predicate": ["error", "both"],
  "@sarj/no-boolean-selector-parameter": ["warn", "both"],
  "@sarj/no-invalid-zod-custom-parse": ["error", "both"],
  "@sarj/no-contradictory-overload-return": ["error", "both"],
  "@sarj/require-button-accessible-name": ["error", "both"],
  "@sarj/require-camelcase-properties": ["error", "both"],
  "@sarj/require-svg-accessible-name": ["error", "both"],
  "@sarj/prefer-logical-tailwind-utilities": [
    "error",
    "both",
    () => [{ enabled: false }] as const,
  ],
  "@sarj/no-unlocalized-toast": [
    "error",
    "both",
    () => [{ enabled: false }] as const,
  ],
  "@sarj/no-unlocalized-jsx-attributes": [
    "error",
    "both",
    () => [{ enabled: false }] as const,
  ],
  "@sarj/no-unlocalized-jsx-text": [
    "error",
    "both",
    () => [{ enabled: false }] as const,
  ],
  "no-restricted-imports": ["shared", "both", LIBRARY_IMPORT_POLICY],
  "@sarj/no-restricted-library-load": [
    "error",
    "both",
    () => [{ libraries: LIBRARY_POLICY }] as const,
  ],
  "@sarj/no-redundant-local-alias": ["warn", "both", "strict-order", 5],
  "@sarj/prefer-test-fixture-reuse": ["warn", "both", "strict-order", 9],
  "@sarj/no-negative-only-http-status-assertion": ["warn", "both", "strict-order", 4],
  "@sarj/no-mutating-input-with-result": ["warn", "both", "strict-order", 3],
  "@sarj/no-return-disposed-resource": ["warn", "both", "strict-order", 6],
  "@sarj/no-discarded-validation-result": ["warn", "both", "strict-order", 0],
  "@sarj/require-jwt-lifetime": ["warn", "both", "strict-order", 12],
  "@sarj/prefer-dependency-interface": ["warn", "both", "strict-order", 8],
  "@sarj/no-generic-json-parser": ["warn", "both", "strict-order", 1],
  "@sarj/require-constrained-schema-integer": ["warn", "both", "strict-order", 11],
  "@sarj/production-derived-test-cases": ["warn", "both", "strict-order", 10],
  "@sarj/no-test-comments": ["warn", "both", "strict-order", 7],
  "@sarj/no-mutating-container-transform": ["warn", "both", "strict-order", 2],
  "@sarj/prefer-native-random-uuid": ["error", "both"],
  "@sarj/prefer-shadcn-primitives": ["error", "both"],
  "@sarj/excessive-commentary": ["warn", "both"],
  "@sarj/no-excessive-cognitive-complexity": ["error", "both"],
  "@sarj/interface-contract-members-private": ["error", "both"],
  "@sarj/iac-source-coupled-test": ["error", "both"],
  "@sarj/duplicate-test-body": ["error", "both"],
  "@sarj/enforce-file-structure": ["error", "both"],
  "@sarj/no-client-side-data-fetching": ["error", "both"],
  "@sarj/no-comment-cruft": ["error", "both"],
  "@sarj/no-cors-wildcard-with-credentials": ["warn", "both"],
  "@sarj/no-dynamic-sql": ["error", "both"],
  "@sarj/no-enum": ["error", "strict"],
  "@sarj/no-fat-try-blocks": [
    "error",
    "both",
    () => [{ max: 5 }] as const,
  ],
  "@sarj/no-hand-rolled-sleep": ["error", "both"],
  "@sarj/no-hand-rolled-spinner": ["error", "both"],
  "@sarj/no-insecure-random-id": ["error", "both"],
  "@sarj/no-exception-text-in-5xx-response": ["warn", "both"],
  "@sarj/no-json-stringify-error": ["error", "both"],
  "@sarj/no-impossible-zod-literal-bounds": ["error", "both"],
  "@sarj/no-in-operator-on-built-in-collections": ["error", "both"],
  "@sarj/no-log-only-catch": ["error", "both"],
  "@sarj/no-bare-return-from-test-catch": ["error", "both"],
  "@sarj/no-bespoke-api-case-conversion": ["warn", "both"],
  "@sarj/no-detached-global-fetch": ["error", "both"],
  "@sarj/no-json-stringify-object-equality": ["error", "both"],
  "@sarj/no-dangerously-allow-svg": ["error", "both"],
  "@sarj/no-credential-in-browser-storage": ["warn", "both"],
  "@sarj/no-numeric-search-param-coercion": ["warn", "both"],
  "@sarj/prefer-native-fetch-in-server-actions": ["warn", "both"],
  "@sarj/no-duplicate-lifecycle-refresh-listeners": ["error", "both"],
  "@sarj/no-long-comment": ["error", "both"],
  "@sarj/no-vague-suppression-description": ["error", "both"],
  "@sarj/no-generic-single-export-module": ["error", "both"],
  "@sarj/no-offset-pagination": ["error", "both"],
  "@sarj/no-positional-tuple-return": ["error", "both"],
  "@sarj/no-production-browser-source-maps": ["error", "both"],
  "@sarj/no-raw-env": ["error", "strict"],
  "@sarj/no-raw-fetch-outside-clients": ["error", "strict"],
  "@sarj/no-repeated-string-literal": ["error", "both"],
  "@sarj/no-redundant-optional-array-default": ["error", "both"],
  "@sarj/no-router-refresh-polling": ["error", "both"],
  "@sarj/no-restated-comment": ["warn", "both"],
  "@sarj/no-restated-jsdoc": ["warn", "both"],
  "@sarj/no-secret-in-log": ["error", "both"],
  "@sarj/no-server-env-in-client-component": ["error", "both"],
  "@sarj/no-server-file-uploads": ["warn", "both"],
  "@sarj/no-select-star": ["error", "both"],
  "@sarj/no-sentinel-return-on-catch": ["error", "both"],
  "@sarj/no-silent-promise-catch": ["error", "both"],
  "@sarj/no-sleep-in-test-body": ["error", "both"],
  "@sarj/no-storage-in-stateless-modules": ["error", "strict"],
  "@sarj/no-string-concat-in-loop": ["error", "both"],
  "@sarj/no-tautological-expect": ["error", "both"],
  "@sarj/no-duplicate-test-case": ["error", "both"],
  "@sarj/no-typed-doc-sections": ["error", "both"],
  "@sarj/no-trailing-value-narration": ["error", "both"],
  "@sarj/no-declaration-comment-wall": ["error", "both"],
  "@sarj/no-union-in-comment": ["error", "both"],
  "@sarj/no-type-member-comment-wall": ["error", "both"],
  "@sarj/no-unnecessary-use-client": ["error", "both"],
  "@sarj/no-unsafe-mock-casting": ["error", "both"],
  "@sarj/no-unsafe-test-double-cast": ["error", "both"],
  "@sarj/no-first-party-module-mock": ["error", "both"],
  "@sarj/no-zod-native-enum": ["error", "both"],
  "@sarj/test-loops-over-literal-cases": ["error", "both"],
  "@sarj/prefer-constant-time-secret-compare": ["error", "both"],
  "@sarj/prefer-ecmascript-private-members": ["error", "both"],
  "@sarj/prefer-discriminated-union": ["warn", "both"],
  "@sarj/prefer-input-group-search": ["error", "both"],
  "@sarj/prefer-millisecond-control-duration-schema": ["warn", "both"],
  "@sarj/prefer-immutable-module-constant": ["error", "both"],
  "@sarj/prefer-module-level-constant": ["error", "both"],
  "@sarj/prefer-module-level-schema": ["error", "both"],
  "@sarj/prefer-module-level-refined-schema": ["warn", "both"],
  "@sarj/prefer-multi-value-zod-literal": [
    "error",
    "both",
    () => [{ zodMajorVersion: 4 }] as const,
  ],
  "@sarj/prefer-named-callback-domain": ["error", "both"],
  "@sarj/prefer-nominal-id-types": ["error", "both"],
  "@sarj/prefer-named-complex-return-type": ["error", "both"],
  "@sarj/prefer-node-crypto-hash": ["warn", "both"],
  "@sarj/prefer-node-fs-promises": ["warn", "both"],
  "@sarj/prefer-non-nullable-collection": ["error", "both"],
  "@sarj/prefer-nullish-filter-predicate": ["error", "both"],
  "@sarj/prefer-await-in-async-return": ["error", "both"],
  "@sarj/prefer-schema-for-api-payload": ["error", "both"],
  "@sarj/prefer-shared-zod-enum": ["warn", "both"],
  "@sarj/prefer-switch-for-repeated-equality": ["error", "both"],
  "@sarj/prefer-semantic-colors": [
    "error",
    "both",
    () => [{ requireSemanticTokens: true }] as const,
  ],
  "@sarj/prefer-server-actions": ["error", "both"],
  "@sarj/prefer-whole-object-assertion": ["warn", "both"],
  "@sarj/repeated-static-call-cases": ["error", "both"],
  "@sarj/prefer-zod-infer": ["error", "both"],
  "@sarj/prefer-zod-parse-output-type": ["warn", "both"],
  "@sarj/require-assert-never": ["error", "both"],
  "@sarj/require-fetch-timeout": ["error", "both"],
  "@sarj/require-explicit-contract-implementation": ["error", "both"],
  "@sarj/require-explicit-service-contract": ["error", "both"],
  "@sarj/require-interface-for-exported-class": ["error", "both"],
  "@sarj/require-port-for-service": ["error", "both"],
  "@sarj/require-sql-access-class": ["warn", "both"],
  "@sarj/require-static-next-matcher": ["error", "both"],
  "@sarj/require-use-form-default-values": ["error", "both"],
  "@sarj/require-use-server-in-actions-file": ["error", "both"],
  "@sarj/require-zod-form-validation": ["error", "both"],
  "@sarj/store-insert-requires-on-conflict": ["error", "both"],
  "@sarj/stepdown": ["error", "both"],
  "@sarj/source-coupled-test": ["error", "both"],
  "@sarj/sole-export-matches-filename": ["error", "both"],
  "@sarj/test-phase-label-comment": ["error", "both"],
  "@sarj/require-pascal-case-zod-schema-name": ["error", "both"],
} as const satisfies PresetPolicy;

type PolicyName = keyof typeof RULE_POLICY;
type PolicyRow = (typeof RULE_POLICY)[PolicyName];
type RuleSetting<Row extends PolicyRow> =
  Row extends readonly ["shared", "both", infer Shared] ? Shared
    : Row extends readonly [infer Level, PresetMembership, infer Options extends () => readonly unknown[]]
      ? readonly [Level, ...ReturnType<Options>]
      : Row extends readonly [infer Level, PresetMembership, "strict-order", number] ? Level
      : Row extends readonly [infer Level, PresetMembership] ? Level
        : never;
type PresetRules<Preset extends "recommended" | "strict"> = {
  readonly [Name in PolicyName as Preset extends "recommended"
    ? (typeof RULE_POLICY)[Name][1] extends "both" ? Name : never
    : Name]: RuleSetting<(typeof RULE_POLICY)[Name]>;
};
type FlatRuleSetting<Setting> = Setting extends readonly unknown[] ? [...Setting] : Setting;
type FlatPresetRules<Preset extends "recommended" | "strict"> = {
  readonly [Name in keyof PresetRules<Preset>]: FlatRuleSetting<PresetRules<Preset>[Name]>;
};
type AdvisoryRuleName = {
  [Name in PolicyName]: (typeof RULE_POLICY)[Name][0] extends "warn" ? Name : never;
}[PolicyName];

/** Rules staged as non-blocking warnings while corpus adoption evidence accumulates. */
const ADVISORY_RULES: readonly AdvisoryRuleName[] = Object.keys(RULE_POLICY)
  .filter(isAdvisoryRuleName)
  .toSorted();
const FLAT_RECOMMENDED_RULES = presetRules("recommended");
const FLAT_STRICT_RULES = presetRules("strict");
// ESLint requires mutable option tuples. Public policy constants expose readonly
// views of those same checked tables, preserving their values and object identity.
const RECOMMENDED_RULES: PresetRules<"recommended"> = FLAT_RECOMMENDED_RULES;
const STRICT_RULES: PresetRules<"strict"> = FLAT_STRICT_RULES;

function isAdvisoryRuleName(name: string): name is AdvisoryRuleName {
  return isPolicyName(name) && RULE_POLICY[name][0] === "warn";
}

function isPolicyName(name: string): name is PolicyName {
  return Object.hasOwn(RULE_POLICY, name);
}

function presetRules<Preset extends "recommended" | "strict">(preset: Preset): FlatPresetRules<Preset> {
  const rows = Object.entries(RULE_POLICY)
    .filter(([, row]) => preset === "strict" || row[1] === "both");
  if (preset === "strict") rows.sort((left, right) => strictOrder(left[1]) - strictOrder(right[1]));
  const entries = rows.map(([name, row]) => [name, policySetting(row)] as const);
  const result = Object.fromEntries(entries);
  const names = Object.keys(result);
  if (names.length !== entries.length || names.some((name, index) => name !== entries[index]?.[0])) {
    throw new Error("Preset projection changed its closed policy key order.");
  }
  // Object.fromEntries cannot retain dependent key/value mapped types. The source
  // table checks each rule's Options, and this closed producer verifies every key.
  return result as FlatPresetRules<Preset>;
}

function strictOrder(row: PolicyRow): number {
  return row.length === 4 ? row[3] : Number.MAX_SAFE_INTEGER;
}

function policySetting(row: PolicyRow): RuleSetting<PolicyRow> {
  if (row[0] === "shared") return row[2];
  if (row.length !== 3) return row[0];
  return [row[0], ...row[2]()] as const;
}

type FlatPreset<Settings> = {
  readonly name: string;
  readonly plugins: { readonly "@sarj": PluginDefinition };
  readonly rules: Settings;
};

interface PluginDefinition {
  readonly meta: typeof meta;
  readonly rules: typeof RULES;
  readonly retiredRules: typeof RETIRED_RULES;
  /** TSESLint.ESLint accepts these typed callbacks while running the native ESLint engine. */
  readonly configs: {
    readonly recommended: FlatPreset<typeof FLAT_RECOMMENDED_RULES>;
    readonly strict: FlatPreset<typeof FLAT_STRICT_RULES>;
  };
}

const PLUGIN: PluginDefinition = {
  meta,
  rules: RULES,
  retiredRules: RETIRED_RULES,
  get configs(): PluginDefinition["configs"] {
    return {
      recommended: {
        name: "@sarj/recommended",
        plugins: { "@sarj": PLUGIN },
        rules: FLAT_RECOMMENDED_RULES,
      },
      strict: {
        name: "@sarj/strict",
        plugins: { "@sarj": PLUGIN },
        rules: FLAT_STRICT_RULES,
      },
    };
  },
} as const;

export default PLUGIN;
export { type DocumentedRule, publicDocumentation } from "./rules/_docs.js";
export {
  type RetiredRule,
  RETIRED_RULES,
  RETIRED_RULES as retiredRules,
} from "./rules/_retired-rules.js";
export {
  ADVISORY_RULES,
  APPLICATION_ONLY_RULES,
  RECOMMENDED_RULES,
  RENAMED_RULES,
  RULES,
  STRICT_RULES,
};
export {
  ADVISORY_RULES as advisoryRules,
  APPLICATION_ONLY_RULES as applicationOnlyRules,
  RECOMMENDED_RULES as recommendedRules,
  RENAMED_RULES as renamedRules,
  RULES as rules,
  STRICT_RULES as strictRules,
};
