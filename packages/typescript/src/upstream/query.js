import { definePlugin } from "@oxlint/plugins";
import { rule as exhaustiveDeps } from "../../vendor/query/rules/exhaustive-deps/exhaustive-deps.rule.js";
import { rule as stableQueryClient } from "../../vendor/query/rules/stable-query-client/stable-query-client.rule.js";
import { rule as noRestDestructuring } from "../../vendor/query/rules/no-rest-destructuring/no-rest-destructuring.rule.js";
import { rule as noUnstableDeps } from "../../vendor/query/rules/no-unstable-deps/no-unstable-deps.rule.js";
import { rule as infiniteQueryPropertyOrder } from "../../vendor/query/rules/infinite-query-property-order/infinite-query-property-order.rule.js";
import { rule as noVoidQueryFn } from "../../vendor/query/rules/no-void-query-fn/no-void-query-fn.rule.js";
import { rule as mutationPropertyOrder } from "../../vendor/query/rules/mutation-property-order/mutation-property-order.rule.js";

export default definePlugin({
  meta: { name: "sarj-upstream-query" },
  rules: {
    "exhaustive-deps": exhaustiveDeps,
    "stable-query-client": stableQueryClient,
    "no-rest-destructuring": noRestDestructuring,
    "no-unstable-deps": noUnstableDeps,
    "infinite-query-property-order": infiniteQueryPropertyOrder,
    "no-void-query-fn": noVoidQueryFn,
    "mutation-property-order": mutationPropertyOrder,
  },
});
