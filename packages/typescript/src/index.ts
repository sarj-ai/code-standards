import banLooseTypeGuardsInTests from "./rules/ban-loose-type-guards-in-tests.js";
import enforceFileStructure from "./rules/enforce-file-structure.js";
import noClientSideDataFetching from "./rules/no-client-side-data-fetching.js";
import noCommentCruft from "./rules/no-comment-cruft.js";
import noEnum from "./rules/no-enum.js";
import noInsecureRandomId from "./rules/no-insecure-random-id.js";
import noJsonStringifyError from "./rules/no-json-stringify-error.js";
import noLogOnlyCatch from "./rules/no-log-only-catch.js";
import noRawEnv from "./rules/no-raw-env.js";
import noSentinelReturnOnCatch from "./rules/no-sentinel-return-on-catch.js";
import noStringConcatInLoop from "./rules/no-string-concat-in-loop.js";
import noUnnecessaryUseClient from "./rules/no-unnecessary-use-client.js";
import preferDiscriminatedUnion from "./rules/prefer-discriminated-union.js";
import preferSchemaForApiPayload from "./rules/prefer-schema-for-api-payload.js";
import preferSemanticColors from "./rules/prefer-semantic-colors.js";
import preferServerActions from "./rules/prefer-server-actions.js";
import requireAssertNever from "./rules/require-assert-never.js";
import requireZodFormValidation from "./rules/require-zod-form-validation.js";
import zodNamingConvention from "./rules/zod-naming-convention.js";
import noCorsWildcardWithCredentials from "./rules/no-cors-wildcard-with-credentials.js";
import noSilentPromiseCatch from "./rules/no-silent-promise-catch.js";
import requireFetchTimeout from "./rules/require-fetch-timeout.js";
import noFatTryBlocks from "./rules/no-fat-try-blocks.js";
import noSecretInLog from "./rules/no-secret-in-log.js";
import noUnsafeMockCasting from "./rules/no-unsafe-mock-casting.js";
import preferStringLiteralUnion from "./rules/prefer-string-literal-union.js";
import preferZodEnum from "./rules/prefer-zod-enum.js";
import preferZodInfer from "./rules/prefer-zod-infer.js";
import noOffsetPagination from "./rules/no-offset-pagination.js";
import noPositionalTupleReturn from "./rules/no-positional-tuple-return.js";
import noRepeatedStringLiteral from "./rules/no-repeated-string-literal.js";
import noSelectStar from "./rules/no-select-star.js";
import noSleepInTestBody from "./rules/no-sleep-in-test-body.js";
import noConditionalInTest from "./rules/no-conditional-in-test.js";
import preferConstantTimeSecretCompare from "./rules/prefer-constant-time-secret-compare.js";
import storeInsertRequiresOnConflict from "./rules/store-insert-requires-on-conflict.js";
import noDynamicSql from "./rules/no-dynamic-sql.js";
import noRawFetchOutsideClients from "./rules/no-raw-fetch-outside-clients.js";
import noStorageInStatelessModules from "./rules/no-storage-in-stateless-modules.js";
import noZodNativeEnum from "./rules/no-zod-native-enum.js";
import preferModuleLevelConstant from "./rules/prefer-module-level-constant.js";
import jsdocRestatesSignature from "./rules/jsdoc-restates-signature.js";
import noRestatedComment from "./rules/no-restated-comment.js";
import trailingValueNarration from "./rules/trailing-value-narration.js";
import noTypeMemberCommentWall from "./rules/no-type-member-comment-wall.js";
import noTautologicalExpect from "./rules/no-tautological-expect.js";
import requireInterfaceForInjectedService from "./rules/require-interface-for-injected-service.js";
import preferNonNullableCollection from "./rules/prefer-non-nullable-collection.js";
import noImplicitAttributeAccess from "./rules/no-implicit-attribute-access.js";
import strictTestAssertions from "./rules/strict-test-assertions.js";
import noAsyncCallbackInWaitFor from "./rules/no-async-callback-in-waitfor.js";

import noHandRolledSleep from "./rules/no-hand-rolled-sleep.js";
import preferSetupFileMocks from "./rules/prefer-setup-file-mocks.js";

const rules = {
  "ban-loose-type-guards-in-tests": banLooseTypeGuardsInTests,
  "enforce-file-structure": enforceFileStructure,
  "no-client-side-data-fetching": noClientSideDataFetching,
  "no-comment-cruft": noCommentCruft,
  "no-enum": noEnum,
  "no-insecure-random-id": noInsecureRandomId,
  "no-json-stringify-error": noJsonStringifyError,
  "no-log-only-catch": noLogOnlyCatch,
  "no-raw-env": noRawEnv,
  "no-sentinel-return-on-catch": noSentinelReturnOnCatch,
  "no-string-concat-in-loop": noStringConcatInLoop,
  "no-unnecessary-use-client": noUnnecessaryUseClient,
  "prefer-discriminated-union": preferDiscriminatedUnion,
  "prefer-schema-for-api-payload": preferSchemaForApiPayload,
  "prefer-semantic-colors": preferSemanticColors,
  "prefer-server-actions": preferServerActions,
  "require-assert-never": requireAssertNever,
  "require-zod-form-validation": requireZodFormValidation,
  "zod-naming-convention": zodNamingConvention,
  "no-cors-wildcard-with-credentials": noCorsWildcardWithCredentials,
  "no-fat-try-blocks": noFatTryBlocks,
  "no-secret-in-log": noSecretInLog,
  "no-unsafe-mock-casting": noUnsafeMockCasting,
  "prefer-string-literal-union": preferStringLiteralUnion,
  "prefer-zod-enum": preferZodEnum,
  "prefer-zod-infer": preferZodInfer,
  "no-silent-promise-catch": noSilentPromiseCatch,
  "require-fetch-timeout": requireFetchTimeout,
  "no-offset-pagination": noOffsetPagination,
  "no-positional-tuple-return": noPositionalTupleReturn,
  "no-repeated-string-literal": noRepeatedStringLiteral,
  "no-select-star": noSelectStar,
  "no-sleep-in-test-body": noSleepInTestBody,
  "no-hand-rolled-sleep": noHandRolledSleep,
  "no-conditional-in-test": noConditionalInTest,
  "prefer-constant-time-secret-compare": preferConstantTimeSecretCompare,
  "store-insert-requires-on-conflict": storeInsertRequiresOnConflict,
  "no-dynamic-sql": noDynamicSql,
  "no-raw-fetch-outside-clients": noRawFetchOutsideClients,
  "no-storage-in-stateless-modules": noStorageInStatelessModules,
  "no-zod-native-enum": noZodNativeEnum,
  "prefer-module-level-constant": preferModuleLevelConstant,
  "jsdoc-restates-signature": jsdocRestatesSignature,
  "no-restated-comment": noRestatedComment,
  "trailing-value-narration": trailingValueNarration,
  "no-type-member-comment-wall": noTypeMemberCommentWall,
  "no-tautological-expect": noTautologicalExpect,
  "require-interface-for-injected-service": requireInterfaceForInjectedService,
  "strict-test-assertions": strictTestAssertions,
  "prefer-non-nullable-collection": preferNonNullableCollection,
  "no-implicit-attribute-access": noImplicitAttributeAccess,
  "no-async-callback-in-waitfor": noAsyncCallbackInWaitFor,
  "prefer-setup-file-mocks": preferSetupFileMocks,
};

const plugin = {
  meta: {
    name: "@sarj/eslint-plugin",
    version: "4.3.0",
  },
  rules,
  configs: {
    recommended: {
      plugins: ["@sarj"],
      rules: {
        "@sarj/zod-naming-convention": "warn",
        "@sarj/require-assert-never": "error",
        "@sarj/require-zod-form-validation": "error",
        "@sarj/ban-loose-type-guards-in-tests": "error",
        "@sarj/enforce-file-structure": "warn",
        "@sarj/no-client-side-data-fetching": "warn",
        "@sarj/prefer-server-actions": "warn",
        "@sarj/no-unnecessary-use-client": "warn",
        "@sarj/prefer-schema-for-api-payload": "warn",
        // Distilled from sarj-audit skills — warn in recommended, error in strict.
        "@sarj/no-sentinel-return-on-catch": "warn",
        "@sarj/no-log-only-catch": "warn",
        "@sarj/no-insecure-random-id": "warn",
        "@sarj/no-json-stringify-error": "warn",
        "@sarj/no-string-concat-in-loop": "warn",
        "@sarj/prefer-discriminated-union": "warn",
        "@sarj/no-comment-cruft": "warn",
        // Frontend / styling — distilled from frontend PR-review mining.
        "@sarj/prefer-semantic-colors": [
          "warn",
          { requireSemanticTokens: true },
        ],
        // Ported from sarj-python-lint (SARJ), corpus-validated FP~0.
        "@sarj/no-fat-try-blocks": "warn",
        "@sarj/no-cors-wildcard-with-credentials": "warn",
        "@sarj/no-secret-in-log": "warn",
        "@sarj/no-unsafe-mock-casting": "warn",
        "@sarj/prefer-string-literal-union": "warn",
        "@sarj/prefer-zod-enum": "warn",
        // A type hand-written beside the Zod schema it restates drifts the
        // moment the schema gains a field. 30,759-file, 17-repo sweep
        // (2026-07): 5 reports, 5 true positives, all in public repos.
        // `requireIdenticalShape: false` widens it to 8 reports, 1 of them noise.
        "@sarj/prefer-zod-infer": "warn",
        // Mined from 2y of PR review feedback + 5-repo code-smell audit (2026-07).
        "@sarj/require-fetch-timeout": "warn",
        "@sarj/no-silent-promise-catch": "warn",
        // Second SARJ port wave — the TS/Python parity gap. Each targets a
        // defect class seen in production Workers code: timing-leaky secret
        // compares, non-idempotent store writes under queue redelivery,
        // O(N) pagination, implicit row contracts, flaky timed tests.
        "@sarj/prefer-constant-time-secret-compare": "error",
        "@sarj/store-insert-requires-on-conflict": "warn",
        "@sarj/no-offset-pagination": "warn",
        "@sarj/no-select-star": "warn",
        // Uncancellable hand-rolled timers. Verified against the shipped
        // strict config (205 enabled rules) that nothing already reports this
        // position; `unicorn` 72 has no promisified-timer rule at all.
        "@sarj/no-hand-rolled-sleep": "warn",
        "@sarj/no-sleep-in-test-body": "warn",
        "@sarj/no-conditional-in-test": "warn",
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
        // Anti-comment-verbosity family (2026-07), from a 37,918-comment,
        // nine-repo measurement study. Each is a deletion-class finding, so each
        // was validated against pydantic / trio / attrs as well as the maintained
        // repos: `no-restated-comment` 0 hits in the flagship first-party
        // repo and 4 in the three famous
        // corpora combined; `trailing-value-narration` 18 hits, 18 true
        // positives; `jsdoc-restates-signature` 36 hits, 0 measured false
        // positives, and it offers a suggestion rather than a `--fix` because a
        // wrong deletion is silent information loss.
        "@sarj/no-restated-comment": "warn",
        "@sarj/jsdoc-restates-signature": "warn",
        "@sarj/trailing-value-narration": "warn",
        // The VOLUME arm of the same family (2026-07). Its siblings judge one
        // comment at a time and can only condemn one that adds nothing; this
        // one judges a TYPE, so it can report ten rows that each add a word.
        // 33 OSS TS repos / 46,861 files: 22 findings, all read, 0 false; zero
        // across ten first-party repos, where the generated-file sniff alone
        // removed 321 of the 407 raw hits. Measurements and the six false
        // positives that shaped the guards: docs/rules/no-type-member-comment-wall.md
        "@sarj/no-type-member-comment-wall": "warn",
        // The TS half of SARJ057 (2026-07). Python has caught the
        // assertion-FREE test since 0.15.0 (SARJ043) and had no TS
        // counterpart, which is how `expect(true).toBe(true); // placeholder`
        // survived in a first-party repo: the file HAS an assertion.
        // Measured across 5,819 .ts/.tsx files (1,003 of them test files) in
        // six internal repos plus got / hono / swr / trpc: 3 hits, 3 true
        // positives, 0 false positives.
        "@sarj/no-tautological-expect": "warn",
        // Substitutability: an exported service class with injected
        // collaborators and no interface above it can only be tested by
        // mocking. 11-repo sweep: 229 exported classes, 82% already carry a
        // port, 29 fire, 28 of them true positives.
        "@sarj/require-interface-for-injected-service": "warn",
        "@sarj/prefer-non-nullable-collection": "warn",
        "@sarj/no-implicit-attribute-access": "warn",
        "@sarj/no-async-callback-in-waitfor": "warn",
        "@sarj/prefer-setup-file-mocks": "warn",
      },
    },
    strict: {
      plugins: ["@sarj"],
      rules: {
        "@sarj/zod-naming-convention": "error",
        "@sarj/require-assert-never": "error",
        "@sarj/require-zod-form-validation": "error",
        "@sarj/ban-loose-type-guards-in-tests": "error",
        "@sarj/enforce-file-structure": "error",
        "@sarj/no-raw-env": "error",
        "@sarj/no-enum": "error",
        "@sarj/no-client-side-data-fetching": "error",
        "@sarj/prefer-server-actions": "error",
        "@sarj/no-unnecessary-use-client": "error",
        "@sarj/prefer-schema-for-api-payload": "error",
        // Distilled from sarj-audit skills.
        "@sarj/no-sentinel-return-on-catch": "error",
        "@sarj/no-log-only-catch": "error",
        "@sarj/no-insecure-random-id": "error",
        "@sarj/no-json-stringify-error": "error",
        "@sarj/no-string-concat-in-loop": "error",
        "@sarj/prefer-discriminated-union": "error",
        "@sarj/no-comment-cruft": "error",
        // Frontend / styling — distilled from frontend PR-review mining. Stylistic,
        // no autofix → warn (rollout should prove the FP rate before raising it).
        "@sarj/prefer-semantic-colors": [
          "error",
          { requireSemanticTokens: true },
        ],
        // Ported from sarj-python-lint (SARJ), corpus-validated FP~0.
        "@sarj/no-fat-try-blocks": "error",
        "@sarj/no-cors-wildcard-with-credentials": "error",
        "@sarj/no-secret-in-log": "error",
        "@sarj/no-unsafe-mock-casting": "error",
        // Promoted to error 2026-07-25 — strict means strict (user directive).
        "@sarj/prefer-string-literal-union": "error",
        "@sarj/prefer-zod-enum": "error",
        // See the `recommended` block for the measured counts.
        "@sarj/prefer-zod-infer": "error",
        // Mined from 2y of PR review feedback + 5-repo code-smell audit (2026-07).
        "@sarj/require-fetch-timeout": "error",
        "@sarj/no-silent-promise-catch": "error",
        // Second SARJ port wave — the TS/Python parity gap.
        "@sarj/prefer-constant-time-secret-compare": "error",
        "@sarj/store-insert-requires-on-conflict": "error",
        "@sarj/no-offset-pagination": "error",
        "@sarj/no-select-star": "error",
        // Uncancellable hand-rolled timers. Verified against the shipped
        // strict config (205 enabled rules) that nothing already reports this
        // position; `unicorn` 72 has no promisified-timer rule at all.
        "@sarj/no-hand-rolled-sleep": "error",
        "@sarj/no-sleep-in-test-body": "error",
        "@sarj/no-conditional-in-test": "error",
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
        // Anti-comment-verbosity family (2026-07) — see the `recommended` block
        // for the measured hit counts and false-positive rates.
        "@sarj/no-restated-comment": "error",
        "@sarj/jsdoc-restates-signature": "error",
        "@sarj/trailing-value-narration": "error",
        "@sarj/no-type-member-comment-wall": "error",
        // TS half of SARJ057 — see the `recommended` block for the measurement.
        "@sarj/no-tautological-expect": "error",
        // Substitutability: the TS sibling of the Python `prefer-real-store-in-tests`
        // / `prefer-library-fake` wave. The convention already exists in the
        // corpus (175 `implements` clauses vs 29 hits), so strict enforces it.
        "@sarj/require-interface-for-injected-service": "error",
        "@sarj/prefer-non-nullable-collection": "error",
        "@sarj/no-implicit-attribute-access": "error",
        "@sarj/no-async-callback-in-waitfor": "error",
        "@sarj/prefer-setup-file-mocks": "error",
      },
    },
  },
};

export default plugin;
export { rules };
