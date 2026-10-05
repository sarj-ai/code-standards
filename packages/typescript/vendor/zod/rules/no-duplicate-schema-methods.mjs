import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildNoDuplicateSchemaMethodsCreate } from "../../zod-utils/rule-builders/no-duplicate-schema-methods.mjs";
const noDuplicateSchemaMethods = createZodPluginRule({
	name: "no-duplicate-schema-methods",
	meta: {
		hasSuggestions: false,
		type: "problem",
		docs: { description: "Disallow calling the same schema method more than once in a single chain" },
		messages: { noDuplicateSchemaMethod: "Method `.{{method}}()` is called more than once in this schema chain." },
		schema: []
	},
	defaultOptions: [],
	create: buildNoDuplicateSchemaMethodsCreate(zodImportScope, [
		"and",
		"array",
		"check",
		"endsWith",
		"includes",
		"or",
		"overwrite",
		"pipe",
		"refine",
		"regex",
		"register",
		"startsWith",
		"superRefine",
		"transform"
	])
});
//#endregion
export { noDuplicateSchemaMethods };
