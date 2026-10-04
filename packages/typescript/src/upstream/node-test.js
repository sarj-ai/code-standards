import { definePlugin } from "@oxlint/plugins";
import toRule from "../../vendor/node-test/rules/rule/to-eslint-rule.js";
import rule0 from "../../vendor/node-test/rules/no-assert-throws-async.js";
import rule1 from "../../vendor/node-test/rules/no-assert-throws-multiple-statements.js";
import rule2 from "../../vendor/node-test/rules/no-unneeded-async-rejects-callback.js";
import rule3 from "../../vendor/node-test/rules/no-useless-assertion.js";
export default definePlugin({
  meta: { name: "sarj-upstream-node-test" },
  rules: {
    "no-assert-throws-async": toRule("no-assert-throws-async", rule0),
    "no-assert-throws-multiple-statements": toRule(
      "no-assert-throws-multiple-statements",
      rule1,
    ),
    "no-unneeded-async-rejects-callback": toRule(
      "no-unneeded-async-rejects-callback",
      rule2,
    ),
    "no-useless-assertion": toRule("no-useless-assertion", rule3),
  },
});
