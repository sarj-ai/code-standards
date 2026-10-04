import { noConflictingClasses } from "./lib/rules/no-conflicting-classes.js";
import { noDuplicateClasses } from "./lib/rules/no-duplicate-classes.js";
import { noDeprecatedClasses } from "./lib/rules/no-deprecated-classes.js";
import { noUnnecessaryWhitespace } from "./lib/rules/no-unnecessary-whitespace.js";
import { enforceShorthandClasses } from "./lib/rules/enforce-shorthand-classes.js";
import { enforceConsistentVariableSyntax } from "./lib/rules/enforce-consistent-variable-syntax.js";

export default {
  meta: { name: "better-tailwindcss" },
  rules: {
    "no-conflicting-classes": noConflictingClasses.rule,
    "no-duplicate-classes": noDuplicateClasses.rule,
    "no-deprecated-classes": noDeprecatedClasses.rule,
    "no-unnecessary-whitespace": noUnnecessaryWhitespace.rule,
    "enforce-shorthand-classes": enforceShorthandClasses.rule,
    "enforce-consistent-variable-syntax": enforceConsistentVariableSyntax.rule,
  },
};
