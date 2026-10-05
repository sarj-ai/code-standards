import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildDeprecatedSchemaPropertyCreate } from "../../zod-utils/rule-patterns/deprecated-schema-property.mjs";
//#region src/rules/no-number-schema-with-is-int.ts
const noNumberSchemaWithIsInt = createZodPluginRule({
	name: "no-number-schema-with-is-int",
	meta: {
		type: "problem",
		docs: { description: "Disallow using deprecated `isInt` on a Zod number schema; check the `format` property instead." },
		messages: { useFormat: "`isInt` is deprecated. Check the `format` property on the number schema instead (or compare to `\"int\"` or `\"float\"`)." },
		schema: []
	},
	defaultOptions: [],
	create: buildDeprecatedSchemaPropertyCreate({
		scope: zodImportScope,
		schemaType: "number",
		propertyName: "isInt",
		messageId: "useFormat"
	})
});
//#endregion
export { noNumberSchemaWithIsInt };
