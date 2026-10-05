import { resolveVariable } from '../../../src/rules/_scope.ts';
export function detectTanstackQueryImports(create) {
    return (context, optionsWithDefault) => {
        const tanstackQueryImportSpecifiers = [];
        const helpers = {
            isSpecificTanstackQueryImport(node, source) {
                return !!tanstackQueryImportSpecifiers.find((specifier) => {
                    if (specifier.type === "ImportSpecifier" &&
                        specifier.parent.type ===
                            "ImportDeclaration" &&
                        specifier.parent.source.value === source) {
                        return node.name === specifier.local.name &&
                            resolveVariable(context.sourceCode, node)?.defs.some(definition => definition.node === specifier);
                    }
                    return false;
                });
            },
            isTanstackQueryImport(node) {
                return !!tanstackQueryImportSpecifiers.find((specifier) => {
                    if (specifier.type === "ImportSpecifier") {
                        return node.name === specifier.local.name &&
                            resolveVariable(context.sourceCode, node)?.defs.some(definition => definition.node === specifier);
                    }
                    return false;
                });
            },
        };
        const detectionInstructions = {
            ImportDeclaration(node) {
                if (node.specifiers.length > 0 &&
                    (node.importKind === 'value' || node.importKind === undefined) &&
                    node.source.value.startsWith('@tanstack/') &&
                    node.source.value.endsWith('-query')) {
                    tanstackQueryImportSpecifiers.push(...node.specifiers);
                }
            },
        };
        // Call original rule definition
        const ruleInstructions = create(context, optionsWithDefault, helpers);
        const enhancedRuleInstructions = {};
        const allKeys = new Set(Object.keys(detectionInstructions).concat(Object.keys(ruleInstructions)));
        // Iterate over ALL instructions keys so we can override original rule instructions
        // to prevent their execution if conditions to report errors are not met.
        allKeys.forEach((instruction) => {
            enhancedRuleInstructions[instruction] = (node) => {
                if (instruction in detectionInstructions) {
                    detectionInstructions[instruction]?.(node);
                }
                const ruleInstruction = ruleInstructions[instruction];
                // TODO: canReportErrors()
                if (ruleInstruction) {
                    return ruleInstruction(node);
                }
                return undefined;
            };
        });
        return enhancedRuleInstructions;
    };
}
