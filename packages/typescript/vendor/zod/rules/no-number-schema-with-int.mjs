import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildPreferTopLevelFactoryCreate } from "../../zod-utils/rule-patterns/prefer-top-level-factory.mjs";
//#region src/rules/no-number-schema-with-int.ts
const noNumberSchemaWithInt = createZodPluginRule({
	name: "no-number-schema-with-int",
	meta: {
		fixable: "code",
		type: "problem",
		docs: { description: "Disallow usage of `z.number().int()` as it is considered legacy" },
		messages: { removeNumber: "`z.number().int()` is considered legacy. Use `z.int()` instead." },
		schema: []
	},
	defaultOptions: [],
	create: buildPreferTopLevelFactoryCreate({
		scope: zodImportScope,
		factoryName: "number",
		replacements: [{
			sourceMethodName: "int",
			replacementMethodName: "int"
		}],
		messageId: "removeNumber"
	})
});
//#endregion
export { noNumberSchemaWithInt };
