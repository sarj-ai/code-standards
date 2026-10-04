import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
import { IMPORT_SYNTAXES, buildConsistentImportCreate } from "../../zod-utils/rule-builders/consistent-import.mjs";
//#region src/rules/consistent-import.ts
const consistentImport = createZodPluginRule({
	name: "consistent-import",
	meta: {
		type: "problem",
		docs: { description: "Enforce a consistent import style for Zod" },
		fixable: "code",
		messages: {
			changeImportSyntax: "Use a {{syntax}} import for Zod.",
			removeDuplicate: "Remove duplicate Zod import; Zod is already imported.",
			convertUsage: "Update Zod usage to match the {{syntax}} import syntax."
		},
		schema: [{
			type: "object",
			properties: { syntax: {
				description: "Specifies the import syntax to use for Zod.",
				type: "string",
				enum: IMPORT_SYNTAXES
			} },
			additionalProperties: false
		}]
	},
	defaultOptions: [{ syntax: "namespace" }],
	create: buildConsistentImportCreate(zodImportScope)
});
//#endregion
export { consistentImport };
