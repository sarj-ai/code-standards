import { getZodChainedMethodNames } from "../get-zod-chained-method-names.mjs";
import { buildZodChainReplacementFix } from "../build-zod-chain-replacement-fix.mjs";
//#region src/rule-patterns/prefer-top-level-factory.ts
/**
* Prefers a top-level factory over a deprecated method chained on a general one (`z.uuid()` over `z.string().uuid()`, `z.int()` over `z.number().safe()`).
* The fix rewrites `z.<factory>().<method>(args)` into `z.<replacement>(args)`,
* keeping the methods in between; it bails on named imports, which would need a new import,
* and on a chain the walker cannot name.
*/
function buildPreferTopLevelFactoryCreate(options) {
	const { scope, factoryName, replacements, messageId, ignore = [] } = options;
	const ignored = new Set(ignore);
	const replacementBySource = new Map(replacements.filter(({ sourceMethodName }) => !ignored.has(sourceMethodName)).map(({ sourceMethodName, replacementMethodName }) => [sourceMethodName, replacementMethodName]));
	return function create(context) {
		const { sourceCode } = context;
		const { createSchemaVisitor, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: factoryName,
			onSchema(node, zodSchemaMeta) {
				const methods = collectZodChainMethods(node);
				if (methods.length > 0 && methods[0].name !== factoryName) return;
				const chainedMethod = methods.find((it, index) => index > 0 && replacementBySource.has(it.name));
				const sourceMethodName = chainedMethod?.name ?? getZodChainedMethodNames(zodSchemaMeta).find((name) => replacementBySource.has(name));
				const replacementMethodName = sourceMethodName === void 0 ? void 0 : replacementBySource.get(sourceMethodName);
				if (replacementMethodName === void 0) return;
				context.report({
					node,
					messageId,
					data: {
						sourceMethod: sourceMethodName,
						replacementMethod: replacementMethodName
					},
					fix(fixer) {
						if (!chainedMethod || zodSchemaMeta.schemaDecl === "named") return null;
						return buildZodChainReplacementFix({
							sourceCode,
							fixer,
							methods,
							fromIndex: 0,
							toIndex: methods.indexOf(chainedMethod),
							toMethodName: replacementMethodName
						});
					}
				});
			}
		});
	};
}
//#endregion
export { buildPreferTopLevelFactoryCreate };
