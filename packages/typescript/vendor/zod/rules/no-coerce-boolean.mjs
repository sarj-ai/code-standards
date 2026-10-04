import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildNoCoerceBooleanCreate } from "../../zod-utils/rule-builders/no-coerce-boolean.mjs";
//#region src/rules/no-coerce-boolean.ts
const noCoerceBoolean = createZodPluginRule({
	name: "no-coerce-boolean",
	meta: {
		type: "problem",
		hasSuggestions: true,
		docs: { description: "Disallow `z.coerce.boolean()` because it treats any non-empty string as `true`." },
		messages: {
			noCoerceBoolean: "`z.coerce.boolean()` uses `Boolean()`, so any non-empty string (including `\"false\"`) becomes `true`. Use `z.stringbool()` or an explicit string transform such as `z.string().transform((v) => v === \"true\")` instead.",
			useStringbool: "Replace `z.coerce.boolean()` with `z.stringbool()`"
		},
		schema: []
	},
	defaultOptions: [],
	create: buildNoCoerceBooleanCreate(zodImportScope)
});
//#endregion
export { noCoerceBoolean };
