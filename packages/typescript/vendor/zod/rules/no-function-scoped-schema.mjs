import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildNoFunctionScopedSchemaCreate } from "../../zod-utils/rule-builders/no-function-scoped-schema.mjs";
//#region src/rules/no-function-scoped-schema.ts
const noFunctionScopedSchema = createZodPluginRule({
	name: "no-function-scoped-schema",
	meta: {
		type: "suggestion",
		docs: { description: "Disallow constructing a Zod schema inside a function body" },
		messages: { functionScopedSchema: "This schema is constructed inside a function and rebuilt on every call. Declare it once at module scope instead." },
		schema: []
	},
	defaultOptions: [],
	create: buildNoFunctionScopedSchemaCreate(zodImportScope)
});
//#endregion
export { noFunctionScopedSchema };
