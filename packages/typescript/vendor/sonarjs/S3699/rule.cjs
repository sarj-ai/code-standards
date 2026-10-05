"use strict";
/*
 * SonarQube JavaScript Plugin
 * Copyright (C) 2011-2024 SonarSource SA
 * mailto:info AT sonarsource DOT com
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 3 of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with this program; if not, write to the Free Software Foundation,
 * Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
 */
// https://sonarsource.github.io/rspec/#/rspec/S3699
Object.defineProperty(exports, "__esModule", { value: true });
exports.rule = void 0;
const index_js_1 = require("../helpers/index.cjs");
const meta_js_1 = require("./meta.cjs");
const EMPTY_RETURN_VALUE_KEYWORDS = new Set([
    'TSVoidKeyword',
    'TSNeverKeyword',
    'TSUndefinedKeyword',
]);
function isReturnValueUsed(callExpr) {
    const { parent } = callExpr;
    if (!parent) {
        return false;
    }
    if (parent.type === 'LogicalExpression') {
        return parent.left === callExpr;
    }
    if (parent.type === 'SequenceExpression') {
        return parent.expressions[parent.expressions.length - 1] === callExpr && isReturnValueUsed(parent);
    }
    if (parent.type === 'ConditionalExpression') {
        return parent.test === callExpr;
    }
    return (parent.type !== 'ExpressionStatement' &&
        parent.type !== 'ArrowFunctionExpression' &&
        parent.type !== 'UnaryExpression' &&
        parent.type !== 'AwaitExpression' &&
        parent.type !== 'ReturnStatement' &&
        parent.type !== 'ThrowStatement');
}
exports.rule = {
    meta: (0, index_js_1.generateMeta)(meta_js_1.meta, {
        messages: {
            removeUseOfOutput: 'Remove this use of the output from "{{name}}"; "{{name}}" doesn\'t return anything.',
        },
    }),
    create(context) {
        const callExpressionsToCheck = new Map();
        const functionsWithReturnValue = new Set();
        return {
            CallExpression(node) {
                const callExpr = node;
                if (!isReturnValueUsed(callExpr)) {
                    return;
                }
                const scope = context.sourceCode.getScope(callExpr);
                const reference = scope.references.find(ref => ref.identifier === callExpr.callee);
                if (reference?.resolved) {
                    const variable = reference.resolved;
                    if (variable.defs.length === 1) {
                        const definition = variable.defs[0];
                        if (definition.type === 'FunctionName') {
                            callExpressionsToCheck.set(reference.identifier, definition.node);
                        }
                        else if (definition.type === 'Variable') {
                            const { init } = definition.node;
                            if (init && ((0, index_js_1.isFunctionExpression)(init) || (0, index_js_1.isArrowFunctionExpression)(init))) {
                                callExpressionsToCheck.set(reference.identifier, init);
                            }
                        }
                    }
                }
            },
            ReturnStatement(node) {
                const returnStmt = node;
                if (returnStmt.argument) {
                    const ancestors = [...context.sourceCode.getAncestors(node)].reverse();
                    const functionNode = ancestors.find(node => node.type === 'FunctionExpression' ||
                        node.type === 'FunctionDeclaration' ||
                        node.type === 'ArrowFunctionExpression');
                    functionsWithReturnValue.add(functionNode);
                }
            },
            ArrowFunctionExpression(node) {
                const arrowFunc = node;
                if (arrowFunc.expression) {
                    functionsWithReturnValue.add(arrowFunc);
                }
            },
            ':function'(node) {
                const func = node;
                if (func.async ||
                    func.generator ||
                    (func.body.type === 'BlockStatement' && func.body.body.length === 0)) {
                    functionsWithReturnValue.add(func);
                }
            },
            TSDeclareFunction(node) {
                const declareFunction = node;
                if (declareFunction.returnType?.typeAnnotation.type &&
                    !EMPTY_RETURN_VALUE_KEYWORDS.has(declareFunction.returnType?.typeAnnotation.type)) {
                    functionsWithReturnValue.add(declareFunction);
                }
            },
            'Program:exit'() {
                callExpressionsToCheck.forEach((functionDeclaration, callee) => {
                    if (!functionsWithReturnValue.has(functionDeclaration)) {
                        context.report({
                            messageId: 'removeUseOfOutput',
                            node: callee,
                            data: { name: callee.name },
                        });
                    }
                });
            },
        };
    },
};
