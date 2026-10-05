import { RuleCreator } from '../../rule-options/RuleCreator.cjs'
/**
 * Factory function for creating ESLint rules with consistent structure and
 * documentation.
 *
 * Wraps the RuleCreator to automatically generate documentation
 * URLs for each rule based on its name. All rules created with this function
 * will have their documentation hosted at perfectionist.dev.
 *
 * @see {@link https://typescript-eslint.io/packages/utils/} - TypeScript ESLint
 * Utils documentation
 * @see {@link https://perfectionist.dev/} - Perfectionist plugin documentation
 */
let createEslintRule = RuleCreator(
  ruleName => `https://perfectionist.dev/rules/${ruleName}`,
)
export { createEslintRule }
