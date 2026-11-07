/**
 * @fileoverview catalog — every @sarj rule joined with its validated documentation.
 *
 * Kept out of the plugin entrypoint so linting never loads the documentation
 * and examples. Catalog generation and example verification import this.
 */

import { RULE_DOCUMENTATION } from "./docs/index.js";
import { ruleSpec, type NativeRuleSpec, type RuleDocumentation } from "./documentation.js";
import PLUGIN from "./index.js";
import type { SarjRule } from "./types.js";

export { publicDocumentation } from "./documentation.js";
export type * from "./documentation.js";

/** An Oxlint rule carrying its validated documentation. */
export type DocumentedRule = SarjRule & { readonly documentation: NativeRuleSpec };

type RuleName = keyof typeof PLUGIN.rules;

// scripts/oxlint/generate-index.ts writes both indexes from the same names, so every rule has documentation.
export const RULES: Readonly<Record<RuleName, DocumentedRule>> = Object.freeze(Object.fromEntries(
  (Object.keys(PLUGIN.rules) as RuleName[]).map((name) => [name, documented(name, PLUGIN.rules[name], RULE_DOCUMENTATION[name])]),
) as Record<RuleName, DocumentedRule>);

export { RULES as rules };

function documented(name: string, rule: SarjRule, documentation: RuleDocumentation): DocumentedRule {
  return { ...rule, documentation: ruleSpec(name, rule.meta ?? {}, documentation) };
}
