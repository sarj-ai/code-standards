import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildPreferEnumOverLiteralUnionCreate } from "../../zod-utils/rule-builders/prefer-enum-over-literal-union.mjs";
//#region src/rules/prefer-enum-over-literal-union.ts
const preferEnumOverLiteralUnion = createZodPluginRule({
	name: "prefer-enum-over-literal-union",
	meta: {
		type: "suggestion",
		fixable: "code",
		docs: { description: "Prefer `z.enum()` over `z.union()` when all members are string literals." },
		messages: { useEnum: "Replace this union of string literals with `z.enum()`." },
		schema: []
	},
	defaultOptions: [],
	create: buildPreferEnumOverLiteralUnionCreate(zodImportScope)
});
//#endregion
export { preferEnumOverLiteralUnion };
