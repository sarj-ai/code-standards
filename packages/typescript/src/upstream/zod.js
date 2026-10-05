import { definePlugin } from "@oxlint/plugins";
import { noAnySchema as rule0 } from "../../vendor/zod/rules/no-any-schema.mjs";
import { noCoerceBoolean as rule1 } from "../../vendor/zod/rules/no-coerce-boolean.mjs";
import { noConflictingChecks as rule2 } from "../../vendor/zod/rules/no-conflicting-checks.mjs";
import { noDuplicateSchemaMethods as rule3 } from "../../vendor/zod/rules/no-duplicate-schema-methods.mjs";
import { noThrowInRefine as rule4 } from "../../vendor/zod/rules/no-throw-in-refine.mjs";
import { noTransformInRecordKey as rule5 } from "../../vendor/zod/rules/no-transform-in-record-key.mjs";
import { preferEnumOverLiteralUnion as rule6 } from "../../vendor/zod/rules/prefer-enum-over-literal-union.mjs";
import { preferNullish as rule7 } from "../../vendor/zod/rules/prefer-nullish.mjs";
export default definePlugin({
  meta: { name: "sarj-upstream-zod" },
  rules: {
    "no-any-schema": rule0,
    "no-coerce-boolean": rule1,
    "no-conflicting-checks": rule2,
    "no-duplicate-schema-methods": rule3,
    "no-throw-in-refine": rule4,
    "no-transform-in-record-key": rule5,
    "prefer-enum-over-literal-union": rule6,
    "prefer-nullish": rule7,
  },
});
