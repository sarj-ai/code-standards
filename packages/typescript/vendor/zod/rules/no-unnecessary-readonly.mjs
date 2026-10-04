import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildNoUnnecessaryReadonlyCreate } from "../../zod-utils/rule-builders/no-unnecessary-readonly.mjs";
//#region src/rules/no-unnecessary-readonly.ts
const noUnnecessaryReadonly = createZodPluginRule({
	name: "no-unnecessary-readonly",
	meta: {
		type: "suggestion",
		fixable: "code",
		docs: { description: "Disallow `.readonly()` on schemas whose output is already immutable" },
		messages: { unnecessaryReadonly: "`readonly` has no effect on an already-immutable schema; remove it." },
		schema: []
	},
	defaultOptions: [],
	create: buildNoUnnecessaryReadonlyCreate(zodImportScope)
});
//#endregion
export { noUnnecessaryReadonly };
