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
/**
 * Detect expression statements like the following:
 *  myArray[1] = 42;
 *  myArray[1] += 42;
 *  myObj.prop1 = 3;
 *  myObj.prop1 += 3;
 */
const MODULE_DECLARATION_NODES = ["ImportDeclaration","ExportNamedDeclaration","ExportDefaultDeclaration","ExportAllDeclaration"];
function isModuleDeclaration(node) {
    return node !== undefined && MODULE_DECLARATION_NODES.includes(node.type);
}
exports.isModuleDeclaration = isModuleDeclaration;
function isFunctionExpression(node) {
    return node !== undefined && node.type === 'FunctionExpression';
}
exports.isFunctionExpression = isFunctionExpression;
function isArrowFunctionExpression(node) {
    return node !== undefined && node.type === 'ArrowFunctionExpression';
}
exports.isArrowFunctionExpression = isArrowFunctionExpression;
function isIdentifier(node, ...values) {
    return (node?.type === 'Identifier' &&
        (values.length === 0 || values.some(value => value === node.name)));
}
exports.isIdentifier = isIdentifier;
function getProgramStatements(program) {
    return program.body.filter((node) => !isModuleDeclaration(node));
}
exports.getProgramStatements = getProgramStatements;
function isIfStatement(node) {
    return node !== undefined && node.type === 'IfStatement';
}
exports.isIfStatement = isIfStatement;
function isLiteral(n) {
    return n != null && n.type === 'Literal';
}
exports.isLiteral = isLiteral;
