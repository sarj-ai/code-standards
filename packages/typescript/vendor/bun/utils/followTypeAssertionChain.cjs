"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.followTypeAssertionChain = void 0;
const isTypeCastExpression = node => node.type === 'TSAsExpression' || node.type === 'TSTypeAssertion';
const followTypeAssertionChain = expression => isTypeCastExpression(expression) ? followTypeAssertionChain(expression.expression) : expression;
exports.followTypeAssertionChain = followTypeAssertionChain;