import { definePlugin } from "@oxlint/plugins";
import leaked from "../../vendor/react/lib/rules/jsx-no-leaked-render.js";
import html from "../../vendor/react/lib/rules/no-invalid-html-attribute.js";
export default definePlugin({
  meta: { name: "sarj-upstream-react" },
  rules: { "jsx-no-leaked-render": leaked, "no-invalid-html-attribute": html },
});
