import { definePlugin } from "@oxlint/plugins";
import noConditionalExpect from "../../vendor/biome-test/no-conditional-expect.js";

export default definePlugin({
  meta: { name: "sarj-upstream-test", version: "2.5.12" },
  rules: { "no-conditional-expect": noConditionalExpect },
});
