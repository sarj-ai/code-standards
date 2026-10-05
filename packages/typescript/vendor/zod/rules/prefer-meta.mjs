import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
//#region src/rules/prefer-meta.ts
const preferMeta = createZodPluginRule({
	name: "prefer-meta",
	meta: {
		type: "suggestion",
		fixable: "code",
		docs: { description: "Enforce usage of `.meta()` over `.describe()`" },
		messages: { preferMeta: "The `.describe()` method still exists for compatibility with Zod 3, but `.meta()` is now the recommended approach." },
		schema: []
	},
	defaultOptions: [],
	create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = zodImportScope.createTracker({ kind: "value" });
		return createSchemaVisitor({ onSchema(node) {
			const describe = collectZodChainMethods(node).find((it) => it.name === "describe");
			if (!describe) return;
			const { callee, arguments: [describeArg] } = describe.node;
			context.report({
				node,
				messageId: "preferMeta",
				fix(fixer) {
					return [fixer.replaceText(callee.property, "meta"), fixer.replaceText(describeArg, `{ description: ${context.sourceCode.getText(describeArg)} }`)];
				}
			});
		} });
	}
});
//#endregion
export { preferMeta };
