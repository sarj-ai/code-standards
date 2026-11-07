/** @fileoverview has-side-effect — side-effect analysis through a visitor-key capability. */
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

import type { Node } from "../types.js";
import { forEachAstChild, forEachOwnAstChild, type VisitorKeys } from "./ast.js";

const BINARY_CONVERSIONS: ReadonlySet<string> = new Set([
  "==", "!=", "<", "<=", ">", ">=", "<<", ">>", ">>>", "+", "-", "*", "/", "%", "|", "^", "&", "in",
]);
const UNARY_CONVERSIONS: ReadonlySet<string> = new Set(["-", "+", "!", "~"]);

interface SideEffectOptions {
  readonly considerGetters?: boolean;
  readonly considerImplicitTypeConversion?: boolean;
}

export function hasSideEffect(
  node: Node,
  sourceCode: { readonly visitorKeys: VisitorKeys },
  options: SideEffectOptions = {},
): boolean {
  const { considerGetters = false, considerImplicitTypeConversion = false } = options;
  const visitorKeys = sourceCode.visitorKeys;
  function visit(current: Node): boolean {
    switch (current.type) {
      case "ArrowFunctionExpression":
      case "FunctionExpression":
        return false;
      case "AssignmentExpression":
      case "AwaitExpression":
      case "CallExpression":
      case "ImportExpression":
      case "NewExpression":
      case "UpdateExpression":
      case "YieldExpression":
        return true;
      case "BinaryExpression":
        if (considerImplicitTypeConversion && BINARY_CONVERSIONS.has(current.operator) &&
            (current.left.type !== "Literal" || current.right.type !== "Literal")) return true;
        break;
      case "MemberExpression":
        if (considerGetters || considerImplicitTypeConversion && current.computed &&
            current.property.type !== "Literal") return true;
        break;
      case "MethodDefinition":
      case "Property":
      case "PropertyDefinition":
        if (considerImplicitTypeConversion && current.computed && current.key.type !== "Literal") return true;
        break;
      case "UnaryExpression":
        if (current.operator === "delete" || considerImplicitTypeConversion &&
            UNARY_CONVERSIONS.has(current.operator) && current.argument.type !== "Literal") return true;
        break;
    }
    if (visitorKeys[current.type] === undefined) {
      return forEachOwnAstChild(current, visit, (key) =>
        key !== "leadingComments" && key !== "trailingComments" && !key.startsWith("_"));
    }
    return forEachAstChild(current, visitorKeys, visit);
  }
  return visit(node);
}
