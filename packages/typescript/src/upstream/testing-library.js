import { definePlugin } from "@oxlint/plugins";
import rules from "../../vendor/testing-library/rules.js";

export default definePlugin({
  meta: { name: "sarj-upstream-testing-library" },
  rules,
});
