//#region src/rule-builders/consistent-import-source.ts
function buildConsistentImportSourceCreate(scope) {
	return function create(context, [{ sources }]) {
		return { ImportDeclaration(node) {
			const sourceValue = node.source.value;
			if (!scope.isAllowed(sourceValue)) return;
			if (sources.includes(sourceValue)) return;
			context.report({
				node,
				messageId: "sourceNotAllowed",
				data: {
					source: sourceValue,
					sources: sources.map((s) => `"${s}"`).join(", ")
				},
				suggest: sources.map((it) => ({
					messageId: "replaceSource",
					data: {
						valid: it,
						invalid: sourceValue
					},
					fix(fixer) {
						return fixer.replaceText(node.source, node.source.raw.replace(sourceValue, it));
					}
				}))
			});
		} };
	};
}
//#endregion
export { buildConsistentImportSourceCreate };
