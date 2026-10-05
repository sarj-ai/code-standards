import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildNoEmptyCustomSchemaCreate } from "../../zod-utils/rule-builders/no-empty-custom-schema.mjs";
//#region src/rules/no-empty-custom-schema.ts
const noEmptyCustomSchema = createZodPluginRule({
	name: "no-empty-custom-schema",
	meta: {
		hasSuggestions: false,
		type: "suggestion",
		docs: { description: "Disallow usage of `z.custom()` without arguments" },
		messages: { noEmptyCustomSchema: "You should provide a validate function within `z.custom()`" },
		schema: []
	},
	defaultOptions: [],
	create: buildNoEmptyCustomSchemaCreate(zodImportScope)
});
//#endregion
export { noEmptyCustomSchema };
