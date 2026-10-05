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
exports.report = report;
exports.toSecondaryLocation = toSecondaryLocation;
exports.getMainFunctionTokenLocation = getMainFunctionTokenLocation;
function report(context, descriptor) {
    if ('message' in descriptor && 'messageId' in descriptor) {
        const {message, ...rest} = descriptor;
        context.report(rest);
    } else if ('message' in descriptor && 'data' in descriptor) {
        const {data, ...rest} = descriptor;
        context.report({...rest, message: expandMessage(rest.message, data)});
    } else {
        context.report(descriptor);
    }
}
function expandMessage(message, reportDescriptorData) {
    let expandedMessage = message;
    if (reportDescriptorData !== undefined) {
        for (const [key, value] of Object.entries(reportDescriptorData)) {
            expandedMessage = replaceAll(expandedMessage, `{{${key}}}`, value.toString());
        }
    }
    return expandedMessage;
}
function replaceAll(target, search, replacement) {
    return target.split(search).join(replacement);
}
/**
 * Returns a location of the "main" function token:
 * - function name for a function declaration, method or accessor
 * - "function" keyword for a function expression
 * - "=>" for an arrow function
 */
function getMainFunctionTokenLocation(fn, parent, context) {
    let location;
    if (fn.type === 'FunctionDeclaration') {
        // `fn.id` can be null when it is `export default function` (despite of the @types/TSESTree definition)
        if (fn.id) {
            location = fn.id.loc;
        }
        else {
            const token = getTokenByValue(fn, 'function', context);
            location = token?.loc;
        }
    }
    else if (fn.type === 'FunctionExpression') {
        if (parent && (parent.type === 'MethodDefinition' || parent.type === 'Property')) {
            location = parent.key.loc;
        }
        else {
            const token = getTokenByValue(fn, 'function', context);
            location = token?.loc;
        }
    }
    else if (fn.type === 'ArrowFunctionExpression') {
        const token = context.sourceCode
            .getTokensBefore(fn.body)
            .reverse()
            .find(token => token.value === '=>');
        location = token?.loc;
    }
    return location;
}
function getTokenByValue(node, value, context) {
    return context.sourceCode.getTokens(node).find(token => token.value === value);
}
function getFirstTokenAfter(node, context) {
    return context.sourceCode.getTokenAfter(node);
}
function getFirstToken(node, context) {
    return context.sourceCode.getTokens(node)[0];
}

function toSecondaryLocation(startLoc, endLoc = startLoc, message) {
    if (!startLoc.loc) {
        throw new Error('Invalid secondary location');
    }
    const endLocation = typeof endLoc !== 'string' && endLoc.loc ? endLoc.loc : startLoc.loc;
    return {
        message: typeof endLoc === 'string' ? endLoc : message,
        column: startLoc.loc.start.column,
        line: startLoc.loc.start.line,
        endColumn: endLocation.end.column,
        endLine: endLocation.end.line,
    };
}
/**
 * Wrapper for `context.report`, supporting secondary locations and cost.
 * Encode those extra information in the issue message when rule is executed
 * in Sonar* environment.
 */
