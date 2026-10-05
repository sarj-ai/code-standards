import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildNoNativeEnumCreate } from "../../zod-utils/rule-builders/no-native-enum.mjs";
//#region src/rules/no-native-enum.ts
const noNativeEnum = createZodPluginRule({
	name: "no-native-enum",
	meta: {
		type: "problem",
		fixable: "code",
		docs: { description: "Disallow deprecated `z.nativeEnum()` in favor of `z.enum()`." },
		messages: { useEnum: "`z.nativeEnum()` is deprecated in Zod 4. Use `z.enum()` instead." },
		schema: []
	},
	defaultOptions: [],
	create: buildNoNativeEnumCreate(zodImportScope)
});
//#endregion
export { noNativeEnum };
