//#region src/rule-patterns/prefer-dedicated-factory.ts
/**
* Prefers a dedicated factory over a general one plus a chained modifier (`z.looseObject()` over `z.object().passthrough()`).
* The fix renames the factory and drops the modifier;
* it bails on named imports (would need a new import) and on a modifier with arguments (nowhere to put them).
*/
function buildPreferDedicatedFactoryCreate(options) {
	const { scope, factoryName, modifierMethods, replacementFactoryName, messageId } = options;
	return function create(context) {
		const { createSchemaVisitor, collectZodChainMethods } = scope.createTracker({ kind: "value" });
		return createSchemaVisitor({
			schemaType: factoryName,
			onSchema(node, zodSchemaMeta) {
				if (!zodSchemaMeta.methods.some((name) => modifierMethods.includes(name))) return;
				const methods = collectZodChainMethods(node);
				const modifierMethod = methods.find((it) => modifierMethods.includes(it.name));
				context.report({
					node: modifierMethod?.node ?? node,
					messageId,
					fix(fixer) {
						if (!modifierMethod || zodSchemaMeta.schemaDecl === "named") return null;
						if (modifierMethod.node.arguments.length !== 0) return null;
						const { sourceCode } = context;
						const [factoryMethod] = methods;
						const factoryCallee = factoryMethod.node.callee;
						const modifierCallee = modifierMethod.node.callee;
						const fixes = [fixer.replaceText(factoryCallee, `${sourceCode.getText(factoryCallee.object)}.${replacementFactoryName}`)];
						const tokenBefore = sourceCode.getTokenBefore(modifierCallee.property);
						if (tokenBefore?.value === ".") fixes.push(fixer.removeRange([tokenBefore.range[0], modifierMethod.node.range[1]]));
						return fixes;
					}
				});
			}
		});
	};
}
//#endregion
export { buildPreferDedicatedFactoryCreate };
