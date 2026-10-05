import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildNoUnknownSchemaCreate } from "../../zod-utils/rule-builders/no-unknown-schema.mjs";
//#region src/rules/no-unknown-schema.ts
const noUnknownSchema = createZodPluginRule({
	name: "no-unknown-schema",
	meta: {
		type: "suggestion",
		docs: { description: "Disallow usage of `z.unknown()` in Zod schemas" },
		messages: { noZUnknown: "Using `z.unknown()` is not allowed. Please use a more specific schema." },
		schema: []
	},
	defaultOptions: [],
	create: buildNoUnknownSchemaCreate(zodImportScope)
});
//#endregion
export { noUnknownSchema };
