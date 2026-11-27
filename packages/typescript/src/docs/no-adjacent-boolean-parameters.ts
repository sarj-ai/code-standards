/** @fileoverview no-adjacent-boolean-parameters — the documentation and executable examples of `@sarj/no-adjacent-boolean-parameters`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_ADJACENT_BOOLEAN_PARAMETERS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Avoid swap-prone positional boolean parameters.",
  rationale: "Callers can reverse two boolean arguments and still type-check. Named fields make each argument's role visible, including when the boolean parameters are separated by other parameters.",
  remediation: "Group independent flags in an options object. Use a literal union with named modes when the flags represent one choice. Update the signature and its callers together.",
  category: "maintainability",
  autofix: "none",
  limitations: [
    "Counts positional identifiers annotated exactly boolean, including optional parameters, and identifier parameters defaulted to true or false. Destructured parameters, rest parameters and the TypeScript this parameter do not count. The rule does not resolve type aliases or infer nonliteral defaults.",
    "Skips generated files, type predicates, setters, direct inline callback arguments and overload implementations whose public signatures have no eligible pair. Public overloads are checked individually.",
    "A function may also trigger @sarj/no-boolean-selector-parameter when a boolean selects between two operations.",
  ],
  examples: [
    {
      id: "positional-flags",
      scenarioId: "named-flags",
      title: "Positional flags can be reversed",
      outcome: "match",
      files: [{
        path: "range.ts",
        source: "declare function checkRange(min: number, excludeMin: boolean, max: number, excludeMax: boolean): void;\ncheckRange(1, false, 4, true);",
      }],
      focusPath: "range.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "named-options",
      scenarioId: "named-flags",
      title: "Name each flag at the call site",
      outcome: "no-match",
      files: [{
        path: "range.ts",
        source: "declare function checkRange(min: number, max: number, options: { excludeMin: boolean; excludeMax: boolean }): void;\ncheckRange(1, 4, { excludeMin: false, excludeMax: true });",
      }],
      focusPath: "range.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
