import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildPreferValidateCreate } from "../../zod-utils/rule-builders/prefer-validate.mjs";
//#region src/rules/prefer-validate.ts
const preferValidate = createZodPluginRule({
	name: "prefer-validate",
	meta: {
		type: "suggestion",
		hasSuggestions: true,
		docs: { description: "Prefer boolean validation when only the success of parsing is used" },
		messages: {
			preferValidate: "Prefer `{{method}}` when only parse success is used.",
			useValidate: "Replace success-only parsing with `{{method}}`."
		},
		schema: []
	},
	defaultOptions: [],
	create: buildPreferValidateCreate(zodImportScope, "schema-method")
});
//#endregion
export { preferValidate };
