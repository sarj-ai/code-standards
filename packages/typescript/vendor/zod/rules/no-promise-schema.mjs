import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildNoPromiseSchemaCreate } from "../../zod-utils/rule-builders/no-promise-schema.mjs";
//#region src/rules/no-promise-schema.ts
const noPromiseSchema = createZodPluginRule({
	name: "no-promise-schema",
	meta: {
		type: "problem",
		docs: { description: "Disallow deprecated `z.promise()` schemas." },
		messages: { noPromiseSchema: "`z.promise()` is deprecated in Zod 4. Await the value before parsing it instead." },
		schema: []
	},
	defaultOptions: [],
	create: buildNoPromiseSchemaCreate(zodImportScope)
});
//#endregion
export { noPromiseSchema };
