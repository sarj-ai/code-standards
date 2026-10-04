import { definePlugin } from "@oxlint/plugins";
import naming from "../../vendor/typescript/naming-convention.cjs";
import ordering from "../../vendor/typescript/member-ordering.cjs";
export default definePlugin({
  meta: { name: "sarj-upstream-typescript" },
  rules: {
    "naming-convention": naming.default,
    "member-ordering": ordering.default,
  },
});
