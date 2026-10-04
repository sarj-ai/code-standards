import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { buildNoThrowInRefineCreate } from "../../zod-utils/rule-builders/no-throw-in-refine.mjs";
//#region src/rules/no-throw-in-refine.ts
const noThrowInRefine = createZodPluginRule({
	name: "no-throw-in-refine",
	meta: {
		type: "problem",
		docs: { description: "Disallow throwing errors directly inside Zod refine callbacks" },
		messages: { noThrowInRefine: "Do not throw errors directly inside a z.refine callback." },
		schema: []
	},
	defaultOptions: [],
	create: buildNoThrowInRefineCreate(zodImportScope)
});
//#endregion
export { noThrowInRefine };
