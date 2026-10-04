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
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.areEquivalent = areEquivalent;
/**
 * Equivalence is implemented by comparing node types and their tokens.
 * Classic implementation would recursively compare children,
 * but "estree" doesn't provide access to children when node type is unknown
 */
function areEquivalent(first, second, sourceCode) {
    if (Array.isArray(first) && Array.isArray(second)) {
        return (first.length === second.length &&
            first.every((firstNode, index) => areEquivalent(firstNode, second[index], sourceCode)));
    }
    else if (!Array.isArray(first) && !Array.isArray(second)) {
        return (first.type === second.type &&
            compareTokens(sourceCode.getTokens(first), sourceCode.getTokens(second)));
    }
    return false;
}
function compareTokens(firstTokens, secondTokens) {
    return (firstTokens.length === secondTokens.length &&
        firstTokens.every((firstToken, index) => firstToken.value === secondTokens[index].value));
}
