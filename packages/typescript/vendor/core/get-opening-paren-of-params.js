/**
 * @fileoverview Parameter token utility from ESLint AST utilities.
 * @author Gyandeep Singh
 */

import { isOpeningParenToken } from "../eslint-utils/index.mjs";

/**
 * Gets the `(` token of the given function node.
 * @param {ASTNode} node The function node to get.
 * @param {SourceCode} sourceCode The source code object to get tokens.
 * @returns {Token} `(` token.
 */
export function getOpeningParenOfParams(node, sourceCode) {
	// If the node is an arrow function and doesn't have parens, this returns the identifier of the first param.
	if (node.type === "ArrowFunctionExpression" && node.params.length === 1) {
		const argToken = sourceCode.getFirstToken(node.params[0]);
		const maybeParenToken = sourceCode.getTokenBefore(argToken);

		return isOpeningParenToken(maybeParenToken)
			? maybeParenToken
			: argToken;
	}

	// Otherwise, returns paren.
	return node.id
		? sourceCode.getTokenAfter(node.id, isOpeningParenToken)
		: sourceCode.getFirstToken(node, isOpeningParenToken);
}
