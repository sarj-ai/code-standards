import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildPreferTopLevelFactoryCreate } from "../../zod-utils/rule-patterns/prefer-top-level-factory.mjs";
//#region src/rules/no-number-schema-with-safe.ts
const noNumberSchemaWithSafe = createZodPluginRule({
	name: "no-number-schema-with-safe",
	meta: {
		fixable: "code",
		type: "problem",
		docs: { description: "Disallow deprecated `z.number().safe()`. Use `z.int()`; `.safe()` is now identical to `.int()`." },
		messages: { useInt: "`.safe()` is deprecated; it is identical to `.int()`. Use `z.int()` (or the equivalent) instead of chaining `.safe()` on `z.number()`." },
		schema: []
	},
	defaultOptions: [],
	create: buildPreferTopLevelFactoryCreate({
		scope: zodImportScope,
		factoryName: "number",
		replacements: [{
			sourceMethodName: "safe",
			replacementMethodName: "int"
		}],
		messageId: "useInt"
	})
});
//#endregion
export { noNumberSchemaWithSafe };
