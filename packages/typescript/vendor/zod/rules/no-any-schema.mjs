import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildNoAnySchemaCreate } from "../../zod-utils/rule-builders/no-any-schema.mjs";
//#region src/rules/no-any-schema.ts
const noAnySchema = createZodPluginRule({
	name: "no-any-schema",
	meta: {
		hasSuggestions: true,
		type: "suggestion",
		docs: { description: "Disallow usage of `z.any()` in Zod schemas" },
		messages: {
			noZAny: "Using `z.any()` is not allowed. Please use a more specific schema.",
			useUnknown: "Replace `z.any()` with `z.unknown()`"
		},
		schema: []
	},
	defaultOptions: [],
	create: buildNoAnySchemaCreate(zodImportScope)
});
//#endregion
export { noAnySchema };
