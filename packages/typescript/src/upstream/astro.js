import { definePlugin } from "@oxlint/plugins";
import { astroFrameworkRules } from "./astro-framework-rules.js";
import { rules } from "../../vendor/astro/script-rules.js";
import { sourceOrigin } from "../rules/_source-origin.js";
const componentRules = Object.fromEntries(Object.entries({ ...rules, ...astroFrameworkRules }).map(([name, rule]) => [name, {
  ...rule,
  create(context) { return sourceOrigin(context).region === "client-script" ? {} : rule.create(context); },
}]));
export default definePlugin({ meta: { name: "sarj-upstream-astro" }, rules: componentRules });
export { getStaticValue, getPropertyName } from "../../vendor/eslint-utils/index.mjs";
