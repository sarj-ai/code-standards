/**
 * @fileoverview index — the plugin's rule registry and its two presets; the historical rename map lives in `rules/_renames.ts`.
 */

import enforceFileStructure from "./rules/enforce-file-structure.js";
import duplicateTestBody from "./rules/duplicate-test-body.js";
import noClientSideDataFetching from "./rules/no-client-side-data-fetching.js";
import noCommentCruft from "./rules/no-comment-cruft.js";
import noCorsWildcardWithCredentials from "./rules/no-cors-wildcard-with-credentials.js";
import noDynamicSql from "./rules/no-dynamic-sql.js";
import noEnum from "./rules/no-enum.js";
import noFatTryBlocks from "./rules/no-fat-try-blocks.js";
import noHandRolledSleep from "./rules/no-hand-rolled-sleep.js";
import noHandRolledSpinner from "./rules/no-hand-rolled-spinner.js";
import noInsecureRandomId from "./rules/no-insecure-random-id.js";
import noJsonStringifyError from "./rules/no-json-stringify-error.js";
import noImpossibleZodLiteralBounds from "./rules/no-impossible-zod-literal-bounds.js";
import noLogOnlyCatch from "./rules/no-log-only-catch.js";
import noLongComment from "./rules/no-long-comment.js";
import noGenericSingleExportModule from "./rules/no-generic-single-export-module.js";
import noOffsetPagination from "./rules/no-offset-pagination.js";
import noPositionalTupleReturn from "./rules/no-positional-tuple-return.js";
import noRawEnv from "./rules/no-raw-env.js";
import noRawFetchOutsideClients from "./rules/no-raw-fetch-outside-clients.js";
import noRestrictedLibraryLoad from "./rules/no-restricted-library-load.js";
import noRepeatedStringLiteral from "./rules/no-repeated-string-literal.js";
import noRestatedComment from "./rules/no-restated-comment.js";
import noRestatedJsdoc from "./rules/no-restated-jsdoc.js";
import noSecretInLog from "./rules/no-secret-in-log.js";
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
import preferConstantTimeSecretCompare from "./rules/prefer-constant-time-secret-compare.js";
import preferDiscriminatedUnion from "./rules/prefer-discriminated-union.js";
import preferInputGroupSearch from "./rules/prefer-input-group-search.js";
import preferImmutableModuleConstant from "./rules/prefer-immutable-module-constant.js";
import preferShadcnPrimitives from "./rules/prefer-shadcn-primitives.js";
import preferModuleLevelConstant from "./rules/prefer-module-level-constant.js";
import preferModuleLevelSchema from "./rules/prefer-module-level-schema.js";
import preferNativeRandomUuid from "./rules/prefer-native-random-uuid.js";
import preferNonNullableCollection from "./rules/prefer-non-nullable-collection.js";
import preferSchemaForApiPayload from "./rules/prefer-schema-for-api-payload.js";
import preferSemanticColors from "./rules/prefer-semantic-colors.js";
import preferServerActions from "./rules/prefer-server-actions.js";
import preferWholeObjectAssertion from "./rules/prefer-whole-object-assertion.js";
import preferZodInfer from "./rules/prefer-zod-infer.js";
import requireAssertNever from "./rules/require-assert-never.js";
import requireFetchTimeout from "./rules/require-fetch-timeout.js";
import requirePortForService from "./rules/require-port-for-service.js";
import requireStaticNextMatcher from "./rules/require-static-next-matcher.js";
import requireZodFormValidation from "./rules/require-zod-form-validation.js";
import storeInsertRequiresOnConflict from "./rules/store-insert-requires-on-conflict.js";
import stepdown from "./rules/stepdown.js";
import zodNamingConvention from "./rules/zod-naming-convention.js";
import { renamedRules } from "./rules/_renames.js";
import { retiredRules } from "./rules/_retired.js";

const rules = {
  "duplicate-test-body": duplicateTestBody,
  "enforce-file-structure": enforceFileStructure,
  "no-client-side-data-fetching": noClientSideDataFetching,
  "no-comment-cruft": noCommentCruft,
  "no-cors-wildcard-with-credentials": noCorsWildcardWithCredentials,
  "no-dynamic-sql": noDynamicSql,
  "no-enum": noEnum,
  "no-fat-try-blocks": noFatTryBlocks,
  "no-hand-rolled-sleep": noHandRolledSleep,
  "no-hand-rolled-spinner": noHandRolledSpinner,
  "no-insecure-random-id": noInsecureRandomId,
  "no-json-stringify-error": noJsonStringifyError,
  "no-impossible-zod-literal-bounds": noImpossibleZodLiteralBounds,
  "no-log-only-catch": noLogOnlyCatch,
  "no-long-comment": noLongComment,
  "no-generic-single-export-module": noGenericSingleExportModule,
  "no-offset-pagination": noOffsetPagination,
  "no-positional-tuple-return": noPositionalTupleReturn,
  "no-raw-env": noRawEnv,
  "no-raw-fetch-outside-clients": noRawFetchOutsideClients,
  "no-restricted-library-load": noRestrictedLibraryLoad,
  "no-repeated-string-literal": noRepeatedStringLiteral,
  "no-restated-comment": noRestatedComment,
  "no-restated-jsdoc": noRestatedJsdoc,
  "no-secret-in-log": noSecretInLog,
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
  "test-loops-over-literal-cases": testLoopsOverLiteralCases,
  "prefer-constant-time-secret-compare": preferConstantTimeSecretCompare,
  "prefer-discriminated-union": preferDiscriminatedUnion,
  "prefer-input-group-search": preferInputGroupSearch,
  "prefer-immutable-module-constant": preferImmutableModuleConstant,
  "prefer-shadcn-primitives": preferShadcnPrimitives,
  "prefer-module-level-constant": preferModuleLevelConstant,
  "prefer-module-level-schema": preferModuleLevelSchema,
  "prefer-native-random-uuid": preferNativeRandomUuid,
  "prefer-non-nullable-collection": preferNonNullableCollection,
  "prefer-schema-for-api-payload": preferSchemaForApiPayload,
  "prefer-semantic-colors": preferSemanticColors,
  "prefer-server-actions": preferServerActions,
  "prefer-whole-object-assertion": preferWholeObjectAssertion,
  "prefer-zod-infer": preferZodInfer,
  "require-assert-never": requireAssertNever,
  "require-fetch-timeout": requireFetchTimeout,
  "require-port-for-service": requirePortForService,
  "require-static-next-matcher": requireStaticNextMatcher,
  "require-zod-form-validation": requireZodFormValidation,
  "store-insert-requires-on-conflict": storeInsertRequiresOnConflict,
  "stepdown": stepdown,
  "zod-naming-convention": zodNamingConvention,
} as const;

const meta = {
  name: "@sarj/eslint-plugin",
  version: "15.6.1",
} as const;

/** Rules registered for application-profile configs but intentionally absent from general presets. */
const applicationOnlyRules = [
  "no-restricted-library-load",
  "prefer-native-random-uuid",
  "prefer-shadcn-primitives",
] as const;

const recommendedRules = {
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
  "@sarj/no-long-comment": "error",
  "@sarj/no-generic-single-export-module": "error",
  "@sarj/no-offset-pagination": "error",
  "@sarj/no-positional-tuple-return": "error",
  "@sarj/no-repeated-string-literal": "error",
  "@sarj/no-restated-comment": "error",
  "@sarj/no-restated-jsdoc": "error",
  "@sarj/no-secret-in-log": "error",
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
  "@sarj/prefer-discriminated-union": "error",
  "@sarj/prefer-input-group-search": "error",
  "@sarj/prefer-immutable-module-constant": "error",
  "@sarj/prefer-module-level-constant": "error",
  "@sarj/prefer-module-level-schema": "error",
  "@sarj/prefer-non-nullable-collection": "error",
  "@sarj/prefer-schema-for-api-payload": "error",
  "@sarj/prefer-semantic-colors": ["error", { requireSemanticTokens: true }],
  "@sarj/prefer-server-actions": "error",
  "@sarj/prefer-whole-object-assertion": "error",
  "@sarj/prefer-zod-infer": "error",
  "@sarj/require-assert-never": "error",
  "@sarj/require-fetch-timeout": "error",
  "@sarj/require-port-for-service": "error",
  "@sarj/require-static-next-matcher": "error",
  "@sarj/require-zod-form-validation": "error",
  "@sarj/store-insert-requires-on-conflict": "error",
  "@sarj/stepdown": "error",
  "@sarj/zod-naming-convention": "error",
} as const;

const strictRules = {
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
  "@sarj/no-long-comment": "error",
  "@sarj/no-generic-single-export-module": "error",
  "@sarj/no-offset-pagination": "error",
  "@sarj/no-positional-tuple-return": "error",
  "@sarj/no-raw-env": "error",
  "@sarj/no-raw-fetch-outside-clients": "error",
  "@sarj/no-repeated-string-literal": "error",
  "@sarj/no-restated-comment": "error",
  "@sarj/no-restated-jsdoc": "error",
  "@sarj/no-secret-in-log": "error",
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
  "@sarj/prefer-discriminated-union": "error",
  "@sarj/prefer-input-group-search": "error",
  "@sarj/prefer-immutable-module-constant": "error",
  "@sarj/prefer-module-level-constant": "error",
  "@sarj/prefer-module-level-schema": "error",
  "@sarj/prefer-non-nullable-collection": "error",
  "@sarj/prefer-schema-for-api-payload": "error",
  "@sarj/prefer-semantic-colors": ["error", { requireSemanticTokens: true }],
  "@sarj/prefer-server-actions": "error",
  "@sarj/prefer-whole-object-assertion": "error",
  "@sarj/prefer-zod-infer": "error",
  "@sarj/require-assert-never": "error",
  "@sarj/require-fetch-timeout": "error",
  "@sarj/require-port-for-service": "error",
  "@sarj/require-static-next-matcher": "error",
  "@sarj/require-zod-form-validation": "error",
  "@sarj/store-insert-requires-on-conflict": "error",
  "@sarj/stepdown": "error",
  "@sarj/zod-naming-convention": "error",
} as const;

type FlatPreset = {
  readonly name: string;
  readonly plugins: Record<string, unknown>;
  readonly rules: Record<string, unknown>;
};

const plugin = {
  meta,
  rules,
  retiredRules,
  get configs(): { readonly recommended: FlatPreset; readonly strict: FlatPreset } {
    return {
      recommended: {
        name: "@sarj/recommended",
        plugins: { "@sarj": plugin },
        rules: recommendedRules,
      },
      strict: {
        name: "@sarj/strict",
        plugins: { "@sarj": plugin },
        rules: strictRules,
      },
    };
  },
} as const;

export default plugin;
export { publicDocumentation } from "./rules/_docs.js";
export { type RetiredRule, retiredRules } from "./rules/_retired.js";
export { applicationOnlyRules, recommendedRules, renamedRules, rules, strictRules };
