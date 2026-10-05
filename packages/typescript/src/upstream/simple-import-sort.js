import { definePlugin } from "@oxlint/plugins";
import rule0 from "../../vendor/simple-import-sort/imports.cjs";
import rule1 from "../../vendor/simple-import-sort/exports.cjs";
export default definePlugin({
  meta: { name: "sarj-upstream-simple-import-sort" },
  rules: { imports: rule0, exports: rule1 },
});
