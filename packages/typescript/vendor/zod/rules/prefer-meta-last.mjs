import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { zodImportScope } from "../../zod-utils/index.mjs";
//#region src/rules/prefer-meta-last.ts
const preferMetaLast = createZodPluginRule({
	name: "prefer-meta-last",
	meta: {
		type: "suggestion",
		docs: { description: "Enforce `.meta()` as last method" },
		fixable: "code",
		messages: { metaNotLast: "The `.meta()` methods should be the last one called" },
		schema: []
	},
	defaultOptions: [],
	create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = zodImportScope.createTracker({ kind: "value" });
		return createSchemaVisitor({ onSchema(node) {
			const chain = collectZodChainMethods(node);
			const metaIndex = chain.findIndex((c) => c.name === "meta");
			if (metaIndex === -1) return;
			if (!chain.slice(metaIndex + 1).some((c) => c.name !== "meta")) return;
			const metaCall = chain[metaIndex].node;
			const metaCallCallee = metaCall.callee;
			context.report({
				node: metaCallCallee.property,
				messageId: "metaNotLast",
				fix(fixer) {
					const source = context.sourceCode;
					const metaCallText = source.getText(metaCall);
					const objectText = source.getText(metaCallCallee.object);
					const onlyMetaSuffix = metaCallText.slice(objectText.length);
					const [, removeStart] = metaCallCallee.object.range;
					const [, removeEnd] = metaCall.range;
					const lastCall = chain[chain.length - 1].node;
					return [fixer.removeRange([removeStart, removeEnd]), fixer.insertTextAfterRange(lastCall.range, onlyMetaSuffix)];
				}
			});
		} });
	}
});
//#endregion
export { preferMetaLast };
