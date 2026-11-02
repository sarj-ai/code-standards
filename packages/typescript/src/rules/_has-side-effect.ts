/** @fileoverview _has-side-effect — preserve the pinned side-effect analysis through a visitor-key capability. */
/*!
 * Adapted from @eslint-community/eslint-utils 4.10.1, hasSideEffect.
 * MIT License
 * Copyright (c) 2018 Toru Nagashima
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import { forEachAstChild } from "./_for-each-ast-child.js";
import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";

const BINARY_CONVERSIONS: ReadonlySet<string> = new Set([
  "==", "!=", "<", "<=", ">", ">=", "<<", ">>", ">>>", "+", "-", "*", "/", "%", "|", "^", "&", "in",
]);
const UNARY_CONVERSIONS: ReadonlySet<string> = new Set(["-", "+", "!", "~"]);

interface SideEffectOptions {
  readonly considerGetters?: boolean;
  readonly considerImplicitTypeConversion?: boolean;
}

export function hasSideEffect(
  node: TSESTree.Node,
  sourceCode: { readonly visitorKeys: Readonly<TSESLint.SourceCode.VisitorKeys> },
  options: SideEffectOptions = {},
): boolean {
  const { considerGetters = false, considerImplicitTypeConversion = false } = options;
  const visitorKeys = sourceCode.visitorKeys;
  function visit(current: TSESTree.Node): boolean {
    switch (current.type) {
      case AST_NODE_TYPES.ArrowFunctionExpression:
      case AST_NODE_TYPES.FunctionExpression:
        return false;
      case AST_NODE_TYPES.AssignmentExpression:
      case AST_NODE_TYPES.AwaitExpression:
      case AST_NODE_TYPES.CallExpression:
      case AST_NODE_TYPES.ImportExpression:
      case AST_NODE_TYPES.NewExpression:
      case AST_NODE_TYPES.UpdateExpression:
      case AST_NODE_TYPES.YieldExpression:
        return true;
      case AST_NODE_TYPES.BinaryExpression:
        if (considerImplicitTypeConversion && BINARY_CONVERSIONS.has(current.operator) &&
            (current.left.type !== AST_NODE_TYPES.Literal || current.right.type !== AST_NODE_TYPES.Literal)) return true;
        break;
      case AST_NODE_TYPES.MemberExpression:
        if (considerGetters || considerImplicitTypeConversion && current.computed &&
            current.property.type !== AST_NODE_TYPES.Literal) return true;
        break;
      case AST_NODE_TYPES.MethodDefinition:
      case AST_NODE_TYPES.Property:
      case AST_NODE_TYPES.PropertyDefinition:
        if (considerImplicitTypeConversion && current.computed && current.key.type !== AST_NODE_TYPES.Literal) return true;
        break;
      case AST_NODE_TYPES.UnaryExpression:
        if (current.operator === "delete" || considerImplicitTypeConversion &&
            UNARY_CONVERSIONS.has(current.operator) && current.argument.type !== AST_NODE_TYPES.Literal) return true;
        break;
    }
    if (visitorKeys[current.type] === undefined) {
      return forEachOwnAstChild(current, visit, key =>
        key !== "leadingComments" && key !== "trailingComments" && !key.startsWith("_"));
    }
    return forEachAstChild(current, visitorKeys, visit);
  }
  return visit(node);
}
