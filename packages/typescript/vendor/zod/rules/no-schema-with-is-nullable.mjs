import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildDeprecatedSchemaMethodCreate } from "../../zod-utils/rule-patterns/deprecated-schema-method.mjs";
//#region src/rules/no-schema-with-is-nullable.ts
const noSchemaWithIsNullable = createZodPluginRule({
	name: "no-schema-with-is-nullable",
	meta: {
		type: "problem",
		docs: { description: "Disallow deprecated `.isNullable()` on a Zod schema; use `safeParse(null).success` instead." },
		messages: { useSafeParse: "`.isNullable()` is deprecated. Try `schema.safeParse(null).success` instead." },
		schema: []
	},
	defaultOptions: [],
	create: buildDeprecatedSchemaMethodCreate({
		scope: zodImportScope,
		methodName: "isNullable",
		messageId: "useSafeParse"
	})
});
//#endregion
export { noSchemaWithIsNullable };
