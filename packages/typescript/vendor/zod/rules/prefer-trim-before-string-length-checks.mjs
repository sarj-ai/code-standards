import { createZodPluginRule } from "../utils/create-plugin-rule.mjs";
import { findParentSchemaMatchingCondition, zodImportScope } from "../../zod-utils/index.mjs";
//#region src/rules/prefer-trim-before-string-length-checks.ts
const LENGTH_CHECK_METHODS = [
	"min",
	"max",
	"length"
];
const preferTrimBeforeStringLengthChecks = createZodPluginRule({
	name: "prefer-trim-before-string-length-checks",
	meta: {
		type: "problem",
		fixable: "code",
		docs: { description: "Enforce `.trim()` is called before string length checks to ensure accurate validation" },
		messages: { trimBeforeLengthCheck: "`.trim()` must be called before length checks (`.min()`, `.max()`, `.length()`) to ensure accurate validation." },
		schema: []
	},
	defaultOptions: [],
	create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = zodImportScope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: "string",
			onSchema(node, zodSchemaMeta) {
				if (findParentSchemaMatchingCondition(node, {
					schemaName: "record",
					condition: (callParent) => callParent.arguments.length > 0 && callParent.arguments[0] === node
				})) return;
				const methods = collectZodChainMethods(node);
				const trimIndex = methods.findIndex((m) => m.name === "trim");
				if (trimIndex === -1) return;
				const firstLengthCheckIndex = methods.findIndex((m) => LENGTH_CHECK_METHODS.includes(m.name));
				if (firstLengthCheckIndex === -1) return;
				if (trimIndex < firstLengthCheckIndex) return;
				context.report({
					node,
					messageId: "trimBeforeLengthCheck",
					fix(fixer) {
						if (zodSchemaMeta.schemaDecl === "named") return null;
						const stringMethodNode = methods[0].node;
						const trimMethodNode = methods[trimIndex].node;
						const trimCallee = trimMethodNode.callee;
						return [fixer.removeRange([trimCallee.object.range[1], trimMethodNode.range[1]]), fixer.insertTextAfter(stringMethodNode, ".trim()")];
					}
				});
			}
		});
	}
});
//#endregion
export { preferTrimBeforeStringLengthChecks };
