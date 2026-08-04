/**
 * @fileoverview index — the plugin's rule registry and its two presets; the historical rename map lives in `rules/_renames.ts`.
 */

import enforceFileStructure from "./rules/enforce-file-structure.js";
import noAsyncCallbackInWaitFor from "./rules/no-async-callback-in-wait-for.js";
import noClientSideDataFetching from "./rules/no-client-side-data-fetching.js";
import noCommentCruft from "./rules/no-comment-cruft.js";
import noConditionalInTest from "./rules/no-conditional-in-test.js";
import noCorsWildcardWithCredentials from "./rules/no-cors-wildcard-with-credentials.js";
import noDynamicSql from "./rules/no-dynamic-sql.js";
import noEnum from "./rules/no-enum.js";
import noFatTryBlocks from "./rules/no-fat-try-blocks.js";
import noHandRolledSleep from "./rules/no-hand-rolled-sleep.js";
import noInsecureRandomId from "./rules/no-insecure-random-id.js";
import noJsonStringifyError from "./rules/no-json-stringify-error.js";
import noLogOnlyCatch from "./rules/no-log-only-catch.js";
import noLongComment from "./rules/no-long-comment.js";
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
import preferConstantTimeSecretCompare from "./rules/prefer-constant-time-secret-compare.js";
import preferDiscriminatedUnion from "./rules/prefer-discriminated-union.js";
import preferModuleLevelConstant from "./rules/prefer-module-level-constant.js";
import preferModuleLevelSchema from "./rules/prefer-module-level-schema.js";
import preferNonNullableCollection from "./rules/prefer-non-nullable-collection.js";
import preferNativeRandomUuid from "./rules/prefer-native-random-uuid.js";
import preferSchemaForApiPayload from "./rules/prefer-schema-for-api-payload.js";
import preferSemanticColors from "./rules/prefer-semantic-colors.js";
import preferServerActions from "./rules/prefer-server-actions.js";
import preferSingleSentenceComment from "./rules/prefer-single-sentence-comment.js";
import preferStringLiteralUnion from "./rules/prefer-string-literal-union.js";
import preferWholeObjectAssertion from "./rules/prefer-whole-object-assertion.js";
import preferZodEnum from "./rules/prefer-zod-enum.js";
import preferZodInfer from "./rules/prefer-zod-infer.js";
import requireAssertNever from "./rules/require-assert-never.js";
import requireFetchTimeout from "./rules/require-fetch-timeout.js";
import requireInterfaceForInjectedService from "./rules/require-interface-for-injected-service.js";
import requireZodFormValidation from "./rules/require-zod-form-validation.js";
import storeInsertRequiresOnConflict from "./rules/store-insert-requires-on-conflict.js";
import zodNamingConvention from "./rules/zod-naming-convention.js";
import { renamedRules } from "./rules/_renames.js";
import { retiredRules } from "./rules/_retired.js";

const rules = {
"enforce-file-structure": enforceFileStructure,
  "no-async-callback-in-wait-for": noAsyncCallbackInWaitFor,
  "no-client-side-data-fetching": noClientSideDataFetching,
  "no-comment-cruft": noCommentCruft,
  "no-conditional-in-test": noConditionalInTest,
  "no-cors-wildcard-with-credentials": noCorsWildcardWithCredentials,
  "no-dynamic-sql": noDynamicSql,
  "no-enum": noEnum,
  "no-fat-try-blocks": noFatTryBlocks,
  "no-hand-rolled-sleep": noHandRolledSleep,
  "no-insecure-random-id": noInsecureRandomId,
  "no-json-stringify-error": noJsonStringifyError,
  "no-log-only-catch": noLogOnlyCatch,
  "no-long-comment": noLongComment,
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
  "prefer-constant-time-secret-compare": preferConstantTimeSecretCompare,
  "prefer-discriminated-union": preferDiscriminatedUnion,
  "prefer-module-level-constant": preferModuleLevelConstant,
  "prefer-module-level-schema": preferModuleLevelSchema,
  "prefer-non-nullable-collection": preferNonNullableCollection,
  "prefer-native-random-uuid": preferNativeRandomUuid,
  "prefer-schema-for-api-payload": preferSchemaForApiPayload,
  "prefer-semantic-colors": preferSemanticColors,
  "prefer-server-actions": preferServerActions,
  "prefer-single-sentence-comment": preferSingleSentenceComment,
  "prefer-string-literal-union": preferStringLiteralUnion,
  "prefer-whole-object-assertion": preferWholeObjectAssertion,
  "prefer-zod-enum": preferZodEnum,
  "prefer-zod-infer": preferZodInfer,
  "require-assert-never": requireAssertNever,
  "require-fetch-timeout": requireFetchTimeout,
  "require-interface-for-injected-service": requireInterfaceForInjectedService,
  "require-zod-form-validation": requireZodFormValidation,
  "store-insert-requires-on-conflict": storeInsertRequiresOnConflict,
  "zod-naming-convention": zodNamingConvention,
};

const meta = {
  name: "@sarj/eslint-plugin",
  version: "9.8.0",
} as const;

/** Rules registered for application-profile configs but intentionally absent from general presets. */
const applicationOnlyRules = [
  "no-restricted-library-load",
  "prefer-native-random-uuid",
] as const;

const recommendedRules = {
"@sarj/enforce-file-structure": "warn",
  "@sarj/no-async-callback-in-wait-for": "warn",
  "@sarj/no-client-side-data-fetching": "warn",
  "@sarj/no-comment-cruft": "warn",
  "@sarj/no-conditional-in-test": "warn",
  "@sarj/no-cors-wildcard-with-credentials": "warn",
  "@sarj/no-dynamic-sql": "warn",
  "@sarj/no-fat-try-blocks": "warn",
  "@sarj/no-hand-rolled-sleep": "warn",
  "@sarj/no-insecure-random-id": "warn",
  "@sarj/no-json-stringify-error": "warn",
  "@sarj/no-log-only-catch": "warn",
  "@sarj/no-long-comment": "warn",
  "@sarj/no-offset-pagination": "warn",
  "@sarj/no-positional-tuple-return": "warn",
  "@sarj/no-repeated-string-literal": "warn",
  "@sarj/no-restated-comment": "warn",
  "@sarj/no-restated-jsdoc": "warn",
  "@sarj/no-secret-in-log": "warn",
  "@sarj/no-select-star": "warn",
  "@sarj/no-sentinel-return-on-catch": "warn",
  "@sarj/no-silent-promise-catch": "warn",
  "@sarj/no-sleep-in-test-body": "warn",
  "@sarj/no-string-concat-in-loop": "warn",
  "@sarj/no-tautological-expect": "warn",
  "@sarj/no-typed-doc-sections": "warn",
  "@sarj/no-trailing-value-narration": "warn",
  "@sarj/no-declaration-comment-wall": "warn",
  "@sarj/no-union-in-comment": "warn",
  "@sarj/no-type-member-comment-wall": "warn",
  "@sarj/no-unnecessary-use-client": "warn",
  "@sarj/no-unsafe-mock-casting": "warn",
  "@sarj/no-zod-native-enum": "warn",
  "@sarj/prefer-constant-time-secret-compare": "error",
  "@sarj/prefer-discriminated-union": "warn",
  "@sarj/prefer-module-level-constant": "warn",
  "@sarj/prefer-module-level-schema": "warn",
  "@sarj/prefer-non-nullable-collection": "warn",
  "@sarj/prefer-schema-for-api-payload": "warn",
  "@sarj/prefer-semantic-colors": ["warn", { requireSemanticTokens: true }],
  "@sarj/prefer-server-actions": "warn",
  "@sarj/prefer-single-sentence-comment": "warn",
  "@sarj/prefer-string-literal-union": "warn",
  "@sarj/prefer-whole-object-assertion": "warn",
  "@sarj/prefer-zod-enum": "warn",
  "@sarj/prefer-zod-infer": "warn",
  "@sarj/require-assert-never": "error",
  "@sarj/require-fetch-timeout": "warn",
  "@sarj/require-interface-for-injected-service": "warn",
  "@sarj/require-zod-form-validation": "error",
  "@sarj/store-insert-requires-on-conflict": "warn",
  "@sarj/zod-naming-convention": "warn",
} as const;

const strictRules = {
"@sarj/enforce-file-structure": "error",
  "@sarj/no-async-callback-in-wait-for": "error",
  "@sarj/no-client-side-data-fetching": "error",
  "@sarj/no-comment-cruft": "error",
  "@sarj/no-conditional-in-test": "error",
  "@sarj/no-cors-wildcard-with-credentials": "error",
  "@sarj/no-dynamic-sql": "error",
  "@sarj/no-enum": "error",
  "@sarj/no-fat-try-blocks": "error",
  "@sarj/no-hand-rolled-sleep": "error",
  "@sarj/no-insecure-random-id": "error",
  "@sarj/no-json-stringify-error": "error",
  "@sarj/no-log-only-catch": "error",
  "@sarj/no-long-comment": "error",
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
  "@sarj/prefer-constant-time-secret-compare": "error",
  "@sarj/prefer-discriminated-union": "error",
  "@sarj/prefer-module-level-constant": "error",
  "@sarj/prefer-module-level-schema": "error",
  "@sarj/prefer-non-nullable-collection": "error",
  "@sarj/prefer-schema-for-api-payload": "error",
  "@sarj/prefer-semantic-colors": ["error", { requireSemanticTokens: true }],
  "@sarj/prefer-server-actions": "error",
  "@sarj/prefer-single-sentence-comment": "warn",
  "@sarj/prefer-string-literal-union": "error",
  "@sarj/prefer-whole-object-assertion": "error",
  "@sarj/prefer-zod-enum": "error",
  "@sarj/prefer-zod-infer": "error",
  "@sarj/require-assert-never": "error",
  "@sarj/require-fetch-timeout": "error",
  "@sarj/require-interface-for-injected-service": "error",
  "@sarj/require-zod-form-validation": "error",
  "@sarj/store-insert-requires-on-conflict": "error",
  "@sarj/zod-naming-convention": "error",
} as const;

type FlatPreset = {
  readonly name: string;
  readonly plugins: Record<string, unknown>;
  readonly rules: Record<string, unknown>;
};

/**
 * The presets, as FLAT config objects — `plugins` is the object form, so both go
 * straight into an `eslint.config.mjs` array with no spread. Neither sets
 * `files` or a parser, so they compose with whatever a repo already has.
 */
const plugin = {
  meta,
  rules,
  // Withdrawn names travel WITH the plugin so a consumer's migration script and
  // this repo's gates read one map, not two. See src/rules/_retired.ts.
  retiredRules,
  configs: {
    recommended: {} as FlatPreset,
    strict: {} as FlatPreset,
  },
};

plugin.configs.recommended = {
  name: "@sarj/recommended",
  plugins: { "@sarj": plugin },
  rules: recommendedRules,
};

plugin.configs.strict = {
  name: "@sarj/strict",
  plugins: { "@sarj": plugin },
  rules: strictRules,
};

export default plugin;
export { type RetiredRule, retiredRules } from "./rules/_retired.js";
export { applicationOnlyRules, recommendedRules, renamedRules, rules, strictRules };
