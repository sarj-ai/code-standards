import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildDeprecatedSchemaPropertyCreate } from "../../zod-utils/rule-patterns/deprecated-schema-property.mjs";
//#region src/rules/no-number-schema-with-is-finite.ts
const noNumberSchemaWithIsFinite = createZodPluginRule({
	name: "no-number-schema-with-is-finite",
	meta: {
		type: "problem",
		docs: { description: "Disallow using deprecated `isFinite` on a Zod number schema; in v4+ it is always `true`." },
		messages: { deprecated: "`isFinite` is deprecated. Number schemas no longer accept infinite values, so this is always `true` for `z.number()`." },
		schema: []
	},
	defaultOptions: [],
	create: buildDeprecatedSchemaPropertyCreate({
		scope: zodImportScope,
		schemaType: "number",
		propertyName: "isFinite",
		messageId: "deprecated"
	})
});
//#endregion
export { noNumberSchemaWithIsFinite };
