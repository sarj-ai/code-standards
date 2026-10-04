import { definePlugin, defineRule } from "@oxlint/plugins";
import duplicateArguments from "../../vendor/core/no-dupe-args.js";
import octalLiterals from "../../vendor/core/no-octal.js";
import restrictedSyntax from "../../vendor/core/no-restricted-syntax.js";
import undefinedInitialization from "../../vendor/core/no-undef-init.js";

export default definePlugin({
  meta: { name: "sarj-upstream-core" },
  rules: {
    "no-dupe-args": defineRule(duplicateArguments),
    "no-octal": defineRule(octalLiterals),
    "no-restricted-syntax": defineRule(restrictedSyntax),
    "no-undef-init": defineRule(undefinedInitialization),
  },
});
