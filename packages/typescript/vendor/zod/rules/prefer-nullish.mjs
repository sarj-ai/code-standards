import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildPreferNullishCreate } from "../../zod-utils/rule-builders/prefer-nullish.mjs";
//#region src/rules/prefer-nullish.ts
const preferNullish = createZodPluginRule({
	name: "prefer-nullish",
	meta: {
		type: "suggestion",
		fixable: "code",
		docs: { description: "Enforce `.nullish()` instead of combining `.optional()` and `.nullable()`" },
		messages: { preferNullish: "Combining `.optional()` and `.nullable()` is redundant. Use `.nullish()` instead." },
		schema: []
	},
	defaultOptions: [],
	create: buildPreferNullishCreate(zodImportScope)
});
//#endregion
export { preferNullish };
