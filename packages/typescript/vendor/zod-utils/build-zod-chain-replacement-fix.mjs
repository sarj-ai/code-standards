//#region src/build-zod-chain-replacement-fix.ts
/**
* Utility to generate a fixer for replacing a method chain like z.string().uuid() or z.number().int()
* with z.uuid() or z.int(), preserving any intermediate methods.
*
* @param opts Object containing all options for the fixer
* @returns Fixer replaceTextRange call
*/
function buildZodChainReplacementFix(opts) {
	const { sourceCode, fixer, methods, fromIndex, toIndex, toMethodName } = opts;
	const fromNode = methods[fromIndex]?.node;
	const toNode = methods[toIndex]?.node;
	if (!fromNode || !toNode) return null;
	const prefixObj = fromNode.callee.object;
	const prefixText = sourceCode.getText(prefixObj);
	const betweenSuffixes = methods.slice(fromIndex + 1, toIndex).map((m) => {
		const betweenCallee = m.node.callee;
		const objText = sourceCode.getText(betweenCallee.object);
		return sourceCode.getText(m.node).slice(objText.length);
	});
	let replacement = `${prefixText}.${toMethodName}(`;
	if (toNode.arguments.length) {
		const argsText = toNode.arguments.map((arg) => sourceCode.getText(arg)).join(", ");
		replacement += argsText;
	}
	replacement += `)${betweenSuffixes.join("")}`;
	return fixer.replaceTextRange([fromNode.range[0], toNode.range[1]], replacement);
}
//#endregion
export { buildZodChainReplacementFix };
