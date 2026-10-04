import { definePlugin } from "@oxlint/plugins";
import rules from "../../vendor/playwright/rules.cjs";

export default definePlugin({
  meta: { name: "sarj-upstream-playwright" },
  rules,
});
