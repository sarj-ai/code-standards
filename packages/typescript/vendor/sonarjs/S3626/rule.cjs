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
// https://sonarsource.github.io/rspec/#/rspec/S3626
Object.defineProperty(exports, "__esModule", { value: true });
exports.rule = void 0;
const index_js_1 = require("../helpers/index.cjs");
const meta_js_1 = require("./meta.cjs");
const loops = 'WhileStatement, ForStatement, DoWhileStatement, ForInStatement, ForOfStatement';
exports.rule = {
    meta: (0, index_js_1.generateMeta)(meta_js_1.meta, {
        messages: {
            removeRedundantJump: 'Remove this redundant jump.',
            suggestJumpRemoval: 'Remove this redundant jump',
        },
        hasSuggestions: true,
    }),
    create(context) {
        function reportIfLastStatement(node) {
            const withArgument = node.type === 'ContinueStatement' ? !!node.label : !!node.argument;
            if (!withArgument) {
                const block = node.parent;
                if (block.body[block.body.length - 1] === node && block.body.length > 1) {
                    const previousComments = context.sourceCode.getCommentsBefore(node);
                    const previousToken = previousComments.length === 0
                        ? context.sourceCode.getTokenBefore(node)
                        : previousComments[previousComments.length - 1];
                    context.report({
                        messageId: 'removeRedundantJump',
                        node: node,
                        suggest: [
                            {
                                messageId: 'suggestJumpRemoval',
                                fix: fixer => fixer.removeRange([previousToken.range[1], node.range[1]]),
                            },
                        ],
                    });
                }
            }
        }
        function reportIfLastStatementInsideIf(node) {
            const ancestors = context.sourceCode.getAncestors(node);
            const ifStatement = ancestors[ancestors.length - 2];
            const upperBlock = ancestors[ancestors.length - 3];
            if (upperBlock.body[upperBlock.body.length - 1] === ifStatement) {
                reportIfLastStatement(node);
            }
        }
        return {
            [`:matches(${loops}) > BlockStatement > ContinueStatement`]: (node) => {
                reportIfLastStatement(node);
            },
            [`:matches(${loops}) > BlockStatement > IfStatement > BlockStatement > ContinueStatement`]: (node) => {
                reportIfLastStatementInsideIf(node);
            },
            ':function > BlockStatement > ReturnStatement': (node) => {
                reportIfLastStatement(node);
            },
            ':function > BlockStatement > IfStatement > BlockStatement > ReturnStatement': (node) => {
                reportIfLastStatementInsideIf(node);
            },
        };
    },
};
