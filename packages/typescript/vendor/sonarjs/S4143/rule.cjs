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
// https://sonarsource.github.io/rspec/#/rspec/S4143
Object.defineProperty(exports, "__esModule", { value: true });
exports.rule = void 0;
const index_js_1 = require("../helpers/index.cjs");
const meta_js_1 = require("./meta.cjs");
const message = 'Verify this is the index that was intended; "{{index}}" was already set on line {{line}}.';
exports.rule = {
    meta: (0, index_js_1.generateMeta)(meta_js_1.meta, {
        messages: {
            verifyIntendedIndex: message,
        },
    }),
    create(context) {
        return {
            SwitchCase(node) {
                checkStatements(node.consequent);
            },
            BlockStatement(node) {
                checkStatements(node.body);
            },
            Program(node) {
                checkStatements((0, index_js_1.getProgramStatements)(node));
            },
        };
        function checkStatements(statements) {
            const usedKeys = new Map();
            let collection;
            statements.forEach(statement => {
                const keyWriteUsage = getKeyWriteUsage(statement);
                if (keyWriteUsage) {
                    if (collection &&
                        !(0, index_js_1.areEquivalent)(keyWriteUsage.collectionNode, collection, context.sourceCode)) {
                        usedKeys.clear();
                    }
                    const sameKeyWriteUsage = usedKeys.get(keyWriteUsage.indexOrKey);
                    if (sameKeyWriteUsage?.node.loc) {
                        const secondaryLocations = [
                            (0, index_js_1.toSecondaryLocation)(sameKeyWriteUsage.node, 'Original value'),
                        ];
                        (0, index_js_1.report)(context, {
                            node: keyWriteUsage.node,
                            messageId: 'verifyIntendedIndex',
                            message,
                            data: {
                                index: keyWriteUsage.indexOrKey,
                                line: sameKeyWriteUsage.node.loc.start.line,
                            },
                        }, secondaryLocations);
                    }
                    usedKeys.set(keyWriteUsage.indexOrKey, keyWriteUsage);
                    collection = keyWriteUsage.collectionNode;
                }
                else {
                    usedKeys.clear();
                }
            });
        }
        function getKeyWriteUsage(node) {
            if (node.type === 'ExpressionStatement') {
                return arrayKeyWriteUsage(node.expression) || mapOrSetKeyWriteUsage(node.expression);
            }
            return undefined;
        }
        function arrayKeyWriteUsage(node) {
            // a[b] = ...
            if (isSimpleAssignment(node) &&
                node.left.type === 'MemberExpression' &&
                node.left.computed) {
                const { left, right } = node;
                const index = extractIndex(left.property);
                if (index !== undefined && !isUsed(left.object, right)) {
                    return {
                        collectionNode: left.object,
                        indexOrKey: index,
                        node,
                    };
                }
            }
            return undefined;
        }
        function mapOrSetKeyWriteUsage(node) {
            if (node.type === 'CallExpression' &&
                node.callee.type === 'MemberExpression') {
                const propertyAccess = node.callee;
                if ((0, index_js_1.isIdentifier)(propertyAccess.property)) {
                    const methodName = propertyAccess.property.name;
                    const addMethod = methodName === 'add' && node.arguments.length === 1;
                    const setMethod = methodName === 'set' && node.arguments.length === 2;
                    if (addMethod || setMethod) {
                        const key = extractIndex(node.arguments[0]);
                        if (key) {
                            return {
                                collectionNode: propertyAccess.object,
                                indexOrKey: key,
                                node,
                            };
                        }
                    }
                }
            }
            return undefined;
        }
        function extractIndex(node) {
            if ((0, index_js_1.isLiteral)(node)) {
                const { value } = node;
                return typeof value === 'number' || typeof value === 'string' ? String(value) : undefined;
            }
            else if ((0, index_js_1.isIdentifier)(node)) {
                return node.name;
            }
            return undefined;
        }
        function isUsed(value, expression) {
            const valueTokens = context.sourceCode.getTokens(value);
            const expressionTokens = context.sourceCode.getTokens(expression);
            const foundUsage = expressionTokens.find((token, index) => {
                if (eq(token, valueTokens[0])) {
                    for (let expressionIndex = index, valueIndex = 0; expressionIndex < expressionTokens.length && valueIndex < valueTokens.length; expressionIndex++, valueIndex++) {
                        if (!eq(expressionTokens[expressionIndex], valueTokens[valueIndex])) {
                            break;
                        }
                        else if (valueIndex === valueTokens.length - 1) {
                            return true;
                        }
                    }
                }
                return false;
            });
            return foundUsage !== undefined;
        }
    },
};
function eq(token1, token2) {
    return token1.value === token2.value;
}
function isSimpleAssignment(node) {
    return node.type === 'AssignmentExpression' && node.operator === '=';
}
