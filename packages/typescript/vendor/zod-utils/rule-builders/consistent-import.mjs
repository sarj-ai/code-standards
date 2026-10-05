import { IMPORT_SYNTAXES, getNamespaceAliasNameFrom, isGroupFirstImportKindValidForSyntax, shouldIdentifierBeRenamed } from "../import-syntax-helpers.mjs";
//#region src/rule-builders/consistent-import.ts
function buildConsistentImportCreate(scope) {
	return function create(context, [options]) {
		const { syntax } = options;
		const { sourceCode } = context;
		const importGroups = {};
		return {
			ImportDeclaration(node) {
				const { source, importKind } = node;
				if (!scope.isAllowed(source.value)) return;
				importGroups[source.value] ??= {
					hasOnlyTypeImports: true,
					nodes: []
				};
				if (importGroups[source.value].hasOnlyTypeImports && importKind === "value") importGroups[source.value].hasOnlyTypeImports = false;
				importGroups[source.value].nodes.push(node);
			},
			"Program:exit": function() {
				let namespaceAliasNameIndex = 0;
				for (const importGroup of Object.values(importGroups)) {
					const { hasOnlyTypeImports, nodes } = importGroup;
					const [firstImportNode, ...othersImportNodes] = nodes;
					/**
					* Variable to track all specifiers that later are used by {@link getDeclaredVariables}
					* to add the namespace prefix
					*/
					const nodesWithVariablesToUpdate = [];
					let namespaceAliasName = null;
					for (const specifier of nodes.flatMap((it) => it.specifiers)) {
						if (!namespaceAliasName) {
							namespaceAliasName = getNamespaceAliasNameFrom(specifier);
							if (namespaceAliasName) continue;
						}
						nodesWithVariablesToUpdate.push(specifier);
					}
					if (!namespaceAliasName) {
						namespaceAliasName = namespaceAliasNameIndex > 0 ? `z${namespaceAliasNameIndex}` : "z";
						namespaceAliasNameIndex += 1;
					}
					if (!isGroupFirstImportKindValidForSyntax(importGroup, syntax)) context.report({
						node: firstImportNode,
						messageId: "changeImportSyntax",
						data: { syntax },
						fix(fixer) {
							const importTypeKeyword = hasOnlyTypeImports ? "type " : "";
							let importSpecifier;
							if (syntax === "named") {
								if (namespaceAliasName === "z") importSpecifier = "{ z }";
								else importSpecifier = `{ z as ${namespaceAliasName} }`;
							} else importSpecifier = `* as ${namespaceAliasName}`;
							const newImportText = `import ${importTypeKeyword}${importSpecifier} from ${firstImportNode.source.raw};`;
							return fixer.replaceText(firstImportNode, newImportText);
						}
					});
					const allReferences = nodesWithVariablesToUpdate.flatMap((it) => sourceCode.getDeclaredVariables(it)).flatMap((it) => it.references);
					for (const ref of allReferences) {
						const { identifier } = ref;
						if (shouldIdentifierBeRenamed(identifier)) context.report({
							node: identifier,
							messageId: "convertUsage",
							data: { syntax },
							fix(fixer) {
								const newId = `${namespaceAliasName}.${identifier.name}`;
								return fixer.replaceText(identifier, newId);
							}
						});
					}
					for (const extraImport of othersImportNodes) context.report({
						node: extraImport,
						messageId: "removeDuplicate",
						fix(fixer) {
							return fixer.removeRange(extraImport.range);
						}
					});
				}
			}
		};
	};
}
//#endregion
export { IMPORT_SYNTAXES, buildConsistentImportCreate };
