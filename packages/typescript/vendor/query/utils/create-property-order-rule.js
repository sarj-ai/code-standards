import { RuleCreator } from '../../rule-options/RuleCreator.cjs';
import { getDocsUrl } from './get-docs-url.js';
import { detectTanstackQueryImports } from './detect-react-query-imports.js';
import { sortDataByOrder } from './sort-data-by-order.js';
const createRule = RuleCreator(getDocsUrl);
export function createPropertyOrderRule(options, targetFunctions, orderRules) {
    const targetFunctionSet = new Set(targetFunctions);
    function isTargetFunction(node) {
        return targetFunctionSet.has(node);
    }
    return createRule({
        ...options,
        create: detectTanstackQueryImports((context) => {
            return {
                CallExpression(node) {
                    if (node.callee.type !== "Identifier") {
                        return;
                    }
                    const functions = node.callee.name;
                    if (!isTargetFunction(functions)) {
                        return;
                    }
                    const argument = node.arguments[0];
                    if (argument === undefined || argument.type !== 'ObjectExpression') {
                        return;
                    }
                    const allProperties = argument.properties;
                    // no need to sort if there is at max 1 property
                    if (allProperties.length < 2) {
                        return;
                    }
                    const properties = allProperties.flatMap((p, index) => {
                        if (p.type === "Property" &&
                            p.key.type === "Identifier") {
                            return { name: p.key.name, property: p };
                        }
                        else
                            return { name: `_property_${index}`, property: p };
                    });
                    const sortedProperties = sortDataByOrder(properties, orderRules, 'name');
                    if (sortedProperties === null) {
                        return;
                    }
                    context.report({
                        node: argument,
                        data: { function: node.callee.name },
                        messageId: 'invalidOrder',
                        fix(fixer) {
                            const sourceCode = context.sourceCode;
                            const reorderedText = sortedProperties.reduce((sourceText, specifier, index) => {
                                let textBetweenProperties = '';
                                if (index < allProperties.length - 1) {
                                    textBetweenProperties = sourceCode
                                        .getText()
                                        .slice(allProperties[index].range[1], allProperties[index + 1].range[0]);
                                }
                                return (sourceText +
                                    sourceCode.getText(specifier.property) +
                                    textBetweenProperties);
                            }, '');
                            return fixer.replaceTextRange([allProperties[0].range[0], allProperties.at(-1).range[1]], reorderedText);
                        },
                    });
                },
            };
        }),
    });
}
