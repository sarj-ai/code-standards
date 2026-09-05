/**
 * @fileoverview index — the plugin's rule registry and its two presets; the historical rename map lives in `rules/_renames.ts`.
 */

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
import noFatTryBlocks from "./rules/no-fat-try-blocks.js";
import noHandRolledSleep from "./rules/no-hand-rolled-sleep.js";
import noHandRolledSpinner from "./rules/no-hand-rolled-spinner.js";
import noInsecureRandomId from "./rules/no-insecure-random-id.js";
import noJsonStringifyError from "./rules/no-json-stringify-error.js";
import noImpossibleZodLiteralBounds from "./rules/no-impossible-zod-literal-bounds.js";
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
import noSelectStar from "./rules/no-select-star.js";
import noSentinelReturnOnCatch from "./rules/no-sentinel-return-on-catch.js";
import noSilentPromiseCatch from "./rules/no-silent-promise-catch.js";
import noSleepInTestBody from "./rules/no-sleep-in-test-body.js";
import noStorageInStatelessModules from "./rules/no-storage-in-stateless-modules.js";
import noStringConcatInLoop from "./rules/no-string-concat-in-loop.js";
import noTautologicalExpect from "./rules/no-tautological-expect.js";
import noTypedDocSections from "./rules/no-typed-doc-sections.js";
import noTrailingValueNarration from "./rules/no-trailing-value-narration.js";
import noDeclarationCommentWall from "./rules/no-declaration-comment-wall.js";
import noUnionInComment from "./rules/no-union-in-comment.js";
import noTypeMemberCommentWall from "./rules/no-type-member-comment-wall.js";
import noUnnecessaryUseClient from "./rules/no-unnecessary-use-client.js";
import noUnsafeMockCasting from "./rules/no-unsafe-mock-casting.js";
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
import { RENAMED_RULES } from "./rules/_renames.js";
import { RETIRED_RULES } from "./rules/_retired.js";

const RULES = {
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
  "no-fat-try-blocks": noFatTryBlocks,
  "no-hand-rolled-sleep": noHandRolledSleep,
  "no-hand-rolled-spinner": noHandRolledSpinner,
  "no-insecure-random-id": noInsecureRandomId,
  "no-json-stringify-error": noJsonStringifyError,
  "no-impossible-zod-literal-bounds": noImpossibleZodLiteralBounds,
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
  "no-select-star": noSelectStar,
  "no-sentinel-return-on-catch": noSentinelReturnOnCatch,
  "no-silent-promise-catch": noSilentPromiseCatch,
  "no-sleep-in-test-body": noSleepInTestBody,
  "no-storage-in-stateless-modules": noStorageInStatelessModules,
  "no-string-concat-in-loop": noStringConcatInLoop,
  "no-tautological-expect": noTautologicalExpect,
  "no-typed-doc-sections": noTypedDocSections,
  "no-trailing-value-narration": noTrailingValueNarration,
  "no-declaration-comment-wall": noDeclarationCommentWall,
  "no-union-in-comment": noUnionInComment,
  "no-type-member-comment-wall": noTypeMemberCommentWall,
  "no-unnecessary-use-client": noUnnecessaryUseClient,
  "no-unsafe-mock-casting": noUnsafeMockCasting,
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
  version: "15.17.6",
} as const;

/** @deprecated All repositories use one policy; retained for import compatibility. */
const APPLICATION_ONLY_RULES = [] as const;

const LIBRARY_IMPORT_POLICY = ["error", {
  paths: LIBRARY_POLICY.map(({ module, note }) => ({ name: module, message: note })),
  patterns: LIBRARY_POLICY.map(({ module, note }) => ({ group: [`${module}/*`], message: note })),
}] as const;

/** Rules staged as non-blocking warnings while corpus adoption evidence accumulates. */
const ADVISORY_RULES = [
  "@sarj/excessive-commentary",
  "@sarj/no-bespoke-api-case-conversion",
  "@sarj/no-restated-comment",
  "@sarj/prefer-millisecond-control-duration-schema",
  "@sarj/prefer-module-level-refined-schema",
  "@sarj/prefer-multi-value-zod-literal",
  "@sarj/prefer-named-callback-domain",
  "@sarj/prefer-named-complex-return-type",
  "@sarj/prefer-node-crypto-hash",
  "@sarj/prefer-node-fs-promises",
  "@sarj/prefer-nullish-filter-predicate",
  "@sarj/prefer-shared-zod-enum",
  "@sarj/prefer-switch-for-repeated-equality",
  "@sarj/require-interface-for-exported-class",
  "@sarj/require-sql-access-class",
  "@sarj/sole-export-matches-filename",
] as const;

const RECOMMENDED_RULES = {
  "no-restricted-imports": LIBRARY_IMPORT_POLICY,
  "@sarj/no-restricted-library-load": ["error", { libraries: LIBRARY_POLICY }],
  "@sarj/prefer-native-random-uuid": "error",
  "@sarj/prefer-shadcn-primitives": "error",
  "@sarj/excessive-commentary": "warn",
  "@sarj/interface-contract-members-private": "error",
  "@sarj/iac-source-coupled-test": "error",
  "@sarj/duplicate-test-body": "error",
  "@sarj/enforce-file-structure": "error",
  "@sarj/no-client-side-data-fetching": "error",
  "@sarj/no-comment-cruft": "error",
  "@sarj/no-cors-wildcard-with-credentials": "error",
  "@sarj/no-dynamic-sql": "error",
  "@sarj/no-fat-try-blocks": ["error", { max: 5 }],
  "@sarj/no-hand-rolled-sleep": "error",
  "@sarj/no-hand-rolled-spinner": "error",
  "@sarj/no-insecure-random-id": "error",
  "@sarj/no-json-stringify-error": "error",
  "@sarj/no-impossible-zod-literal-bounds": "error",
  "@sarj/no-log-only-catch": "error",
  "@sarj/no-bare-return-from-test-catch": "error",
  "@sarj/no-bespoke-api-case-conversion": "warn",
  "@sarj/no-dangerously-allow-svg": "error",
  "@sarj/no-duplicate-lifecycle-refresh-listeners": "error",
  "@sarj/no-long-comment": "error",
  "@sarj/no-vague-suppression-description": "error",
  "@sarj/no-generic-single-export-module": "error",
  "@sarj/no-offset-pagination": "error",
  "@sarj/no-positional-tuple-return": "error",
  "@sarj/no-production-browser-source-maps": "error",
  "@sarj/no-repeated-string-literal": "error",
  "@sarj/no-router-refresh-polling": "error",
  "@sarj/no-restated-comment": "warn",
  "@sarj/no-restated-jsdoc": "error",
  "@sarj/no-secret-in-log": "error",
  "@sarj/no-server-env-in-client-component": "error",
  "@sarj/no-select-star": "error",
  "@sarj/no-sentinel-return-on-catch": "error",
  "@sarj/no-silent-promise-catch": "error",
  "@sarj/no-sleep-in-test-body": "error",
  "@sarj/no-string-concat-in-loop": "error",
  "@sarj/no-tautological-expect": "error",
  "@sarj/no-typed-doc-sections": "error",
  "@sarj/no-trailing-value-narration": "error",
  "@sarj/no-declaration-comment-wall": "error",
  "@sarj/no-union-in-comment": "error",
  "@sarj/no-type-member-comment-wall": "error",
  "@sarj/no-unnecessary-use-client": "error",
  "@sarj/no-unsafe-mock-casting": "error",
  "@sarj/no-zod-native-enum": "error",
  "@sarj/test-loops-over-literal-cases": "error",
  "@sarj/prefer-constant-time-secret-compare": "error",
  "@sarj/prefer-ecmascript-private-members": "error",
  "@sarj/prefer-discriminated-union": "error",
  "@sarj/prefer-input-group-search": "error",
  "@sarj/prefer-millisecond-control-duration-schema": "warn",
  "@sarj/prefer-immutable-module-constant": "error",
  "@sarj/prefer-module-level-constant": "error",
  "@sarj/prefer-module-level-schema": "error",
  "@sarj/prefer-module-level-refined-schema": "warn",
  "@sarj/prefer-multi-value-zod-literal": ["warn", { zodMajorVersion: 4 }],
  "@sarj/prefer-named-callback-domain": "warn",
  "@sarj/prefer-named-complex-return-type": "warn",
  "@sarj/prefer-node-crypto-hash": "warn",
  "@sarj/prefer-node-fs-promises": "warn",
  "@sarj/prefer-non-nullable-collection": "error",
  "@sarj/prefer-nullish-filter-predicate": "warn",
  "@sarj/prefer-await-in-async-return": "error",
  "@sarj/prefer-schema-for-api-payload": "error",
  "@sarj/prefer-shared-zod-enum": "warn",
  "@sarj/prefer-switch-for-repeated-equality": "warn",
  "@sarj/prefer-semantic-colors": ["error", { requireSemanticTokens: true }],
  "@sarj/prefer-server-actions": "error",
  "@sarj/prefer-whole-object-assertion": "error",
  "@sarj/repeated-static-call-cases": "error",
  "@sarj/prefer-zod-infer": "error",
  "@sarj/require-assert-never": "error",
  "@sarj/require-fetch-timeout": "error",
  "@sarj/require-interface-for-exported-class": "warn",
  "@sarj/require-port-for-service": "error",
  "@sarj/require-sql-access-class": "warn",
  "@sarj/require-static-next-matcher": "error",
  "@sarj/require-use-form-default-values": "error",
  "@sarj/require-use-server-in-actions-file": "error",
  "@sarj/require-zod-form-validation": "error",
  "@sarj/store-insert-requires-on-conflict": "error",
  "@sarj/stepdown": "error",
  "@sarj/source-coupled-test": "error",
  "@sarj/sole-export-matches-filename": "warn",
  "@sarj/test-phase-label-comment": "error",
  "@sarj/require-pascal-case-zod-schema-name": "error",
} as const;

const STRICT_RULES = {
  "no-restricted-imports": LIBRARY_IMPORT_POLICY,
  "@sarj/no-restricted-library-load": ["error", { libraries: LIBRARY_POLICY }],
  "@sarj/prefer-native-random-uuid": "error",
  "@sarj/prefer-shadcn-primitives": "error",
  "@sarj/excessive-commentary": "warn",
  "@sarj/interface-contract-members-private": "error",
  "@sarj/iac-source-coupled-test": "error",
  "@sarj/duplicate-test-body": "error",
  "@sarj/enforce-file-structure": "error",
  "@sarj/no-client-side-data-fetching": "error",
  "@sarj/no-comment-cruft": "error",
  "@sarj/no-cors-wildcard-with-credentials": "error",
  "@sarj/no-dynamic-sql": "error",
  "@sarj/no-enum": "error",
  "@sarj/no-fat-try-blocks": ["error", { max: 5 }],
  "@sarj/no-hand-rolled-sleep": "error",
  "@sarj/no-hand-rolled-spinner": "error",
  "@sarj/no-insecure-random-id": "error",
  "@sarj/no-json-stringify-error": "error",
  "@sarj/no-impossible-zod-literal-bounds": "error",
  "@sarj/no-log-only-catch": "error",
  "@sarj/no-bare-return-from-test-catch": "error",
  "@sarj/no-bespoke-api-case-conversion": "warn",
  "@sarj/no-dangerously-allow-svg": "error",
  "@sarj/no-duplicate-lifecycle-refresh-listeners": "error",
  "@sarj/no-long-comment": "error",
  "@sarj/no-vague-suppression-description": "error",
  "@sarj/no-generic-single-export-module": "error",
  "@sarj/no-offset-pagination": "error",
  "@sarj/no-positional-tuple-return": "error",
  "@sarj/no-production-browser-source-maps": "error",
  "@sarj/no-raw-env": "error",
  "@sarj/no-raw-fetch-outside-clients": "error",
  "@sarj/no-repeated-string-literal": "error",
  "@sarj/no-router-refresh-polling": "error",
  "@sarj/no-restated-comment": "warn",
  "@sarj/no-restated-jsdoc": "error",
  "@sarj/no-secret-in-log": "error",
  "@sarj/no-server-env-in-client-component": "error",
  "@sarj/no-select-star": "error",
  "@sarj/no-sentinel-return-on-catch": "error",
  "@sarj/no-silent-promise-catch": "error",
  "@sarj/no-sleep-in-test-body": "error",
  "@sarj/no-storage-in-stateless-modules": "error",
  "@sarj/no-string-concat-in-loop": "error",
  "@sarj/no-tautological-expect": "error",
  "@sarj/no-typed-doc-sections": "error",
  "@sarj/no-trailing-value-narration": "error",
  "@sarj/no-declaration-comment-wall": "error",
  "@sarj/no-union-in-comment": "error",
  "@sarj/no-type-member-comment-wall": "error",
  "@sarj/no-unnecessary-use-client": "error",
  "@sarj/no-unsafe-mock-casting": "error",
  "@sarj/no-zod-native-enum": "error",
  "@sarj/test-loops-over-literal-cases": "error",
  "@sarj/prefer-constant-time-secret-compare": "error",
  "@sarj/prefer-ecmascript-private-members": "error",
  "@sarj/prefer-discriminated-union": "error",
  "@sarj/prefer-input-group-search": "error",
  "@sarj/prefer-millisecond-control-duration-schema": "warn",
  "@sarj/prefer-immutable-module-constant": "error",
  "@sarj/prefer-module-level-constant": "error",
  "@sarj/prefer-module-level-schema": "error",
  "@sarj/prefer-module-level-refined-schema": "warn",
  "@sarj/prefer-multi-value-zod-literal": ["warn", { zodMajorVersion: 4 }],
  "@sarj/prefer-named-callback-domain": "warn",
  "@sarj/prefer-named-complex-return-type": "warn",
  "@sarj/prefer-node-crypto-hash": "warn",
  "@sarj/prefer-node-fs-promises": "warn",
  "@sarj/prefer-non-nullable-collection": "error",
  "@sarj/prefer-nullish-filter-predicate": "warn",
  "@sarj/prefer-await-in-async-return": "error",
  "@sarj/prefer-schema-for-api-payload": "error",
  "@sarj/prefer-shared-zod-enum": "warn",
  "@sarj/prefer-switch-for-repeated-equality": "warn",
  "@sarj/prefer-semantic-colors": ["error", { requireSemanticTokens: true }],
  "@sarj/prefer-server-actions": "error",
  "@sarj/prefer-whole-object-assertion": "error",
  "@sarj/repeated-static-call-cases": "error",
  "@sarj/prefer-zod-infer": "error",
  "@sarj/require-assert-never": "error",
  "@sarj/require-fetch-timeout": "error",
  "@sarj/require-interface-for-exported-class": "warn",
  "@sarj/require-port-for-service": "error",
  "@sarj/require-sql-access-class": "warn",
  "@sarj/require-static-next-matcher": "error",
  "@sarj/require-use-form-default-values": "error",
  "@sarj/require-use-server-in-actions-file": "error",
  "@sarj/require-zod-form-validation": "error",
  "@sarj/store-insert-requires-on-conflict": "error",
  "@sarj/stepdown": "error",
  "@sarj/source-coupled-test": "error",
  "@sarj/sole-export-matches-filename": "warn",
  "@sarj/test-phase-label-comment": "error",
  "@sarj/require-pascal-case-zod-schema-name": "error",
} as const;

type FlatPreset = {
  readonly name: string;
  readonly plugins: Record<string, unknown>;
  readonly rules: Record<string, unknown>;
};

const PLUGIN = {
  meta,
  rules: RULES,
  retiredRules: RETIRED_RULES,
  get configs(): {
    readonly recommended: FlatPreset;
    readonly strict: FlatPreset;
  } {
    return {
      recommended: {
        name: "@sarj/recommended",
        plugins: { "@sarj": PLUGIN },
        rules: RECOMMENDED_RULES,
      },
      strict: {
        name: "@sarj/strict",
        plugins: { "@sarj": PLUGIN },
        rules: STRICT_RULES,
      },
    };
  },
} as const;

export default PLUGIN;
export { publicDocumentation } from "./rules/_docs.js";
export {
  type RetiredRule,
  RETIRED_RULES,
  RETIRED_RULES as retiredRules,
} from "./rules/_retired.js";
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
