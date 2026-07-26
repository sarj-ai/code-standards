import enforceFileStructure from "./rules/enforce-file-structure.js";
import noClientSideDataFetching from "./rules/no-client-side-data-fetching.js";
import noCommentCruft from "./rules/no-comment-cruft.js";
import noEnum from "./rules/no-enum.js";
import noInsecureRandomId from "./rules/no-insecure-random-id.js";
import noJsonStringifyError from "./rules/no-json-stringify-error.js";
import noLogOnlyCatch from "./rules/no-log-only-catch.js";
import noRawEnv from "./rules/no-raw-env.js";
import noSentinelReturnOnCatch from "./rules/no-sentinel-return-on-catch.js";
import noSequentialAwait from "./rules/no-sequential-await.js";
import noStringConcatInLoop from "./rules/no-string-concat-in-loop.js";
import noUnnecessaryUseClient from "./rules/no-unnecessary-use-client.js";
import preferDiscriminatedUnion from "./rules/prefer-discriminated-union.js";
import preferSchemaForApiPayload from "./rules/prefer-schema-for-api-payload.js";
import preferSemanticColors from "./rules/prefer-semantic-colors.js";
import preferServerActions from "./rules/prefer-server-actions.js";
import preferShadcn from "./rules/prefer-shadcn.js";
import requireAssertNever from "./rules/require-assert-never.js";
import requireZodFormValidation from "./rules/require-zod-form-validation.js";
import zodNamingConvention from "./rules/zod-naming-convention.js";
import noCorsWildcardWithCredentials from "./rules/no-cors-wildcard-with-credentials.js";
import noSilentPromiseCatch from "./rules/no-silent-promise-catch.js";
import requireFetchTimeout from "./rules/require-fetch-timeout.js";
import requireSchemaValidateSearch from "./rules/require-schema-validate-search.js";
import noFatTryBlocks from "./rules/no-fat-try-blocks.js";
import noSecretInLog from "./rules/no-secret-in-log.js";
import noUnsafeCast from "./rules/no-unsafe-cast.js";
import preferStringLiteralUnion from "./rules/prefer-string-literal-union.js";
import singlePublicExport from "./rules/single-public-export.js";
import noOffsetPagination from "./rules/no-offset-pagination.js";
import noPositionalTupleReturn from "./rules/no-positional-tuple-return.js";
import noRepeatedStringLiteral from "./rules/no-repeated-string-literal.js";
import noSelectStar from "./rules/no-select-star.js";
import noSleepInTestBody from "./rules/no-sleep-in-test-body.js";
import preferConstantTimeSecretCompare from "./rules/prefer-constant-time-secret-compare.js";
import storeInsertRequiresOnConflict from "./rules/store-insert-requires-on-conflict.js";
import noDynamicSql from "./rules/no-dynamic-sql.js";
import noRawFetchOutsideClients from "./rules/no-raw-fetch-outside-clients.js";
import noStorageInStatelessModules from "./rules/no-storage-in-stateless-modules.js";
import noZodNativeEnum from "./rules/no-zod-native-enum.js";
import preferModuleLevelConstant from "./rules/prefer-module-level-constant.js";

const rules = {
  "enforce-file-structure": enforceFileStructure,
  "no-client-side-data-fetching": noClientSideDataFetching,
  "no-comment-cruft": noCommentCruft,
  "no-enum": noEnum,
  "no-insecure-random-id": noInsecureRandomId,
  "no-json-stringify-error": noJsonStringifyError,
  "no-log-only-catch": noLogOnlyCatch,
  "no-raw-env": noRawEnv,
  "no-sentinel-return-on-catch": noSentinelReturnOnCatch,
  "no-sequential-await": noSequentialAwait,
  "no-string-concat-in-loop": noStringConcatInLoop,
  "no-unnecessary-use-client": noUnnecessaryUseClient,
  "prefer-discriminated-union": preferDiscriminatedUnion,
  "prefer-schema-for-api-payload": preferSchemaForApiPayload,
  "prefer-semantic-colors": preferSemanticColors,
  "prefer-server-actions": preferServerActions,
  "prefer-shadcn": preferShadcn,
  "require-assert-never": requireAssertNever,
  "require-zod-form-validation": requireZodFormValidation,
  "zod-naming-convention": zodNamingConvention,
  "no-cors-wildcard-with-credentials": noCorsWildcardWithCredentials,
  "no-fat-try-blocks": noFatTryBlocks,
  "no-secret-in-log": noSecretInLog,
  "no-unsafe-cast": noUnsafeCast,
  "prefer-string-literal-union": preferStringLiteralUnion,
  "single-public-export": singlePublicExport,
  "no-silent-promise-catch": noSilentPromiseCatch,
  "require-fetch-timeout": requireFetchTimeout,
  "require-schema-validate-search": requireSchemaValidateSearch,
  "no-offset-pagination": noOffsetPagination,
  "no-positional-tuple-return": noPositionalTupleReturn,
  "no-repeated-string-literal": noRepeatedStringLiteral,
  "no-select-star": noSelectStar,
  "no-sleep-in-test-body": noSleepInTestBody,
  "prefer-constant-time-secret-compare": preferConstantTimeSecretCompare,
  "store-insert-requires-on-conflict": storeInsertRequiresOnConflict,
  "no-dynamic-sql": noDynamicSql,
  "no-raw-fetch-outside-clients": noRawFetchOutsideClients,
  "no-storage-in-stateless-modules": noStorageInStatelessModules,
  "no-zod-native-enum": noZodNativeEnum,
  "prefer-module-level-constant": preferModuleLevelConstant,
};

const plugin = {
  meta: {
    name: "@sarj/eslint-plugin",
    version: "2.11.0",
  },
  rules,
  configs: {
    recommended: {
      plugins: ["@sarj"],
      rules: {
        "@sarj/zod-naming-convention": "warn",
        "@sarj/require-assert-never": "error",
        "@sarj/require-zod-form-validation": "error",
        "@sarj/enforce-file-structure": "warn",
        "@sarj/no-client-side-data-fetching": "warn",
        "@sarj/prefer-server-actions": "warn",
        "@sarj/no-unnecessary-use-client": "warn",
        "@sarj/prefer-schema-for-api-payload": "warn",
        // Distilled from sarj-audit skills — warn in recommended, error in strict.
        "@sarj/no-sequential-await": "warn",
        "@sarj/no-sentinel-return-on-catch": "warn",
        "@sarj/no-log-only-catch": "warn",
        "@sarj/no-insecure-random-id": "warn",
        "@sarj/no-json-stringify-error": "warn",
        "@sarj/no-string-concat-in-loop": "warn",
        "@sarj/prefer-discriminated-union": "warn",
        "@sarj/no-comment-cruft": "warn",
        // Frontend / styling — distilled from frontend PR-review mining.
        "@sarj/prefer-semantic-colors": "warn",
        // Ported from sarj-python-lint (SARJ), corpus-validated FP~0.
        "@sarj/no-fat-try-blocks": "warn",
        "@sarj/no-cors-wildcard-with-credentials": "warn",
        "@sarj/no-secret-in-log": "warn",
        "@sarj/no-unsafe-cast": "warn",
        "@sarj/single-public-export": "warn",
        "@sarj/prefer-string-literal-union": "warn",
        // Mined from 2y of PR review feedback + 5-repo code-smell audit (2026-07).
        "@sarj/require-fetch-timeout": "warn",
        "@sarj/no-silent-promise-catch": "warn",
        "@sarj/require-schema-validate-search": "warn",
        // Second SARJ port wave — the TS/Python parity gap. Each targets a
        // defect class seen in production Workers code: timing-leaky secret
        // compares, non-idempotent store writes under queue redelivery,
        // O(N) pagination, implicit row contracts, flaky timed tests.
        "@sarj/prefer-constant-time-secret-compare": "error",
        "@sarj/store-insert-requires-on-conflict": "warn",
        "@sarj/no-offset-pagination": "warn",
        "@sarj/no-select-star": "warn",
        "@sarj/no-sleep-in-test-body": "warn",
        "@sarj/no-repeated-string-literal": "warn",
        "@sarj/no-positional-tuple-return": "warn",
        // Injection guard — low FP, applies to any repo touching SQL.
        "@sarj/no-dynamic-sql": "warn",
        // Mined from two years of PR review (SARJ-928). Schema-layer sibling of
        // `no-enum`; autofixable for inline string-literal objects.
        "@sarj/no-zod-native-enum": "warn",
        // Mined from two years of PR review — the single most frequent uncovered
        // theme (~37 PRs). Measured 17 hits / 1085 real TS files, all true
        // positives, so it is safe to run everywhere.
        "@sarj/prefer-module-level-constant": "warn",
      },
    },
    strict: {
      plugins: ["@sarj"],
      rules: {
        "@sarj/zod-naming-convention": "error",
        "@sarj/require-assert-never": "error",
        "@sarj/require-zod-form-validation": "error",
        "@sarj/enforce-file-structure": "error",
        "@sarj/no-raw-env": "error",
        "@sarj/prefer-shadcn": "error",
        "@sarj/no-enum": "error",
        "@sarj/no-client-side-data-fetching": "error",
        "@sarj/prefer-server-actions": "error",
        "@sarj/no-unnecessary-use-client": "error",
        "@sarj/prefer-schema-for-api-payload": "error",
        // Distilled from sarj-audit skills.
        "@sarj/no-sequential-await": "error",
        "@sarj/no-sentinel-return-on-catch": "error",
        "@sarj/no-log-only-catch": "error",
        "@sarj/no-insecure-random-id": "error",
        "@sarj/no-json-stringify-error": "error",
        "@sarj/no-string-concat-in-loop": "error",
        "@sarj/prefer-discriminated-union": "error",
        "@sarj/no-comment-cruft": "error",
        // Frontend / styling — distilled from frontend PR-review mining. Stylistic,
        // no autofix → warn (rollout should prove the FP rate before raising it).
        "@sarj/prefer-semantic-colors": "error",
        // Ported from sarj-python-lint (SARJ), corpus-validated FP~0.
        "@sarj/no-fat-try-blocks": "error",
        "@sarj/no-cors-wildcard-with-credentials": "error",
        "@sarj/no-secret-in-log": "error",
        "@sarj/no-unsafe-cast": "error",
        "@sarj/single-public-export": "error",
        // Promoted to error 2026-07-25 — strict means strict (user directive).
        "@sarj/prefer-string-literal-union": "error",
        // Mined from 2y of PR review feedback + 5-repo code-smell audit (2026-07).
        "@sarj/require-fetch-timeout": "error",
        "@sarj/no-silent-promise-catch": "error",
        "@sarj/require-schema-validate-search": "error",
        // Second SARJ port wave — the TS/Python parity gap.
        "@sarj/prefer-constant-time-secret-compare": "error",
        "@sarj/store-insert-requires-on-conflict": "error",
        "@sarj/no-offset-pagination": "error",
        "@sarj/no-select-star": "error",
        "@sarj/no-sleep-in-test-body": "error",
        "@sarj/no-repeated-string-literal": "error",
        // API-shape advice rather than a runtime defect — a corpus sweep found its
        // only hits are parser `[value, cursor]` returns, which are conventional.
        // Warn even in strict until a rollout justifies more.
        "@sarj/no-positional-tuple-return": "error",
        "@sarj/no-dynamic-sql": "error",
        // Architectural: both need per-repo config to be meaningful, so they
        // are strict-only. `no-storage-in-stateless-modules` is a no-op until
        // its `modules` option names the directories a team declared stateless;
        // `no-raw-fetch-outside-clients` defaults to the `clients/` convention
        // and takes an `allow` list for repos that lay their client layer out
        // differently.
        "@sarj/no-raw-fetch-outside-clients": "error",
        "@sarj/no-storage-in-stateless-modules": "error",
        // Mined from two years of PR review (SARJ-928).
        "@sarj/no-zod-native-enum": "error",
        "@sarj/prefer-module-level-constant": "error",
      },
    },
  },
};

export default plugin;
export { rules };
