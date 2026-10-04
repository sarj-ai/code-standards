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
// https://sonarsource.github.io/rspec/#/rspec/S3923
Object.defineProperty(exports, "__esModule", { value: true });
exports.rule = void 0;
const index_js_1 = require("../helpers/index.cjs");
const meta_js_1 = require("./meta.cjs");
exports.rule = {
    meta: (0, index_js_1.generateMeta)(meta_js_1.meta, {
        messages: {
            removeOrEditConditionalStructure: "Remove this conditional structure or edit its code blocks so that they're not all the same.",
            returnsTheSameValue: 'This conditional operation returns the same value whether the condition is "true" or "false".',
        },
    }),
    create(context) {
        return {
            IfStatement(ifStmt) {
                // don't visit `else if` statements
                if (!(0, index_js_1.isIfStatement)(ifStmt.parent)) {
                    const { branches, endsWithElse } = (0, index_js_1.collectIfBranches)(ifStmt);
                    if (endsWithElse && allDuplicated(branches)) {
                        context.report({ messageId: 'removeOrEditConditionalStructure', node: ifStmt });
                    }
                }
            },
            SwitchStatement(switchStmt) {
                const { branches, endsWithDefault } = (0, index_js_1.collectSwitchBranches)(switchStmt);
                if (endsWithDefault && allDuplicated(branches)) {
                    context.report({ messageId: 'removeOrEditConditionalStructure', node: switchStmt });
                }
            },
            ConditionalExpression(conditional) {
                const branches = [conditional.consequent, conditional.alternate];
                if (allDuplicated(branches)) {
                    context.report({ messageId: 'returnsTheSameValue', node: conditional });
                }
            },
        };
        function allDuplicated(branches) {
            return (branches.length > 1 &&
                branches.slice(1).every((branch, index) => {
                    return (0, index_js_1.areEquivalent)(branch, branches[index], context.sourceCode);
                }));
        }
    },
};
