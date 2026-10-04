import { getRuleURL } from "../meta.mjs";
import { RuleCreator } from "../../rule-options/RuleCreator.cjs";
//#region src/utils/create-plugin-rule.ts
const createZodPluginRule = RuleCreator(getRuleURL);
//#endregion
export { createZodPluginRule };
