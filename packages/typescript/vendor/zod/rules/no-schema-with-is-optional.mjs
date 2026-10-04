import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildDeprecatedSchemaMethodCreate } from "../../zod-utils/rule-patterns/deprecated-schema-method.mjs";
//#region src/rules/no-schema-with-is-optional.ts
const noSchemaWithIsOptional = createZodPluginRule({
	name: "no-schema-with-is-optional",
	meta: {
		type: "problem",
		docs: { description: "Disallow deprecated `.isOptional()` on a Zod schema; use `safeParse(undefined).success` instead." },
		messages: { useSafeParse: "`.isOptional()` is deprecated. Try `schema.safeParse(undefined).success` instead." },
		schema: []
	},
	defaultOptions: [],
	create: buildDeprecatedSchemaMethodCreate({
		scope: zodImportScope,
		methodName: "isOptional",
		messageId: "useSafeParse"
	})
});
//#endregion
export { noSchemaWithIsOptional };
