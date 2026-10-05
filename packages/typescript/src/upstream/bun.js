import { definePlugin } from "@oxlint/plugins";
import preferToBe from "../../vendor/bun/prefer-to-be.cjs";

export default definePlugin({
  meta: { name: "sarj-upstream-bun" },
  rules: { "prefer-to-be": preferToBe.default },
});
