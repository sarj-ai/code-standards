import { collectZodSchemaConstraints } from "./collect-zod-schema-constraints.mjs";
import { detectZodSchemaRootNode, isZodSchemaOfType } from "./detect-zod-schema-root-node.mjs";
import { getStaticPropertyName } from "./get-static-property-name.mjs";
import { AST_NODE_TYPES } from "../ast-node-types/index.cjs";
import { findVariable } from "../eslint-utils/index.mjs";
//#region src/track-zod-schema-imports.ts
/**
* Creates a tracker for one file, scoped to `importScope`.
* Rules normally reach it through {@link ZodImportScope.createTracker}.
*/
function trackZodSchemaImports(scope, { kind, sourceCode }) {
	const imports = {
		namespaces: /* @__PURE__ */ new Set(),
		named: /* @__PURE__ */ new Map()
	};
	const zodNamedImportsByOriginal = /* @__PURE__ */ new Map();
	const bindings = [];
	const chainCache = /* @__PURE__ */ new WeakMap();
	function collectZodChainMethods(node) {
		const cached = chainCache.get(node);
		if (cached) return cached;
		const methods = [];
		let current = node;
		while (current.type === AST_NODE_TYPES.CallExpression) {
			const { callee } = current;
			if (callee.type === AST_NODE_TYPES.MemberExpression && !callee.computed && callee.property.type === AST_NODE_TYPES.Identifier) {
				methods.unshift({
					name: callee.property.name,
					node: current
				});
				current = callee.object;
				continue;
			}
			if (callee.type === AST_NODE_TYPES.Identifier) {
				methods.unshift({
					name: callee.name,
					node: current
				});
				break;
			}
			const unwalkable = [];
			chainCache.set(node, unwalkable);
			return unwalkable;
		}
		chainCache.set(node, methods);
		return methods;
	}
	function records(isTypeOnly) {
		return kind === "all" || isTypeOnly === (kind === "type");
	}
	function importDeclarationListener(node) {
		if (!scope.isAllowed(node.source.value)) return;
		const typeDeclaration = node.importKind === "type";
		if (typeDeclaration && !records(true)) return;
		for (const spec of node.specifiers) switch (spec.type) {
			case AST_NODE_TYPES.ImportDefaultSpecifier:
			case AST_NODE_TYPES.ImportNamespaceSpecifier:
				if (!records(typeDeclaration)) break;
				imports.namespaces.add(spec.local.name);
				bindings.push({
					name: "*",
					local: spec.local,
					declaration: node
				});
				break;
			case AST_NODE_TYPES.ImportSpecifier: {
				if (!records(typeDeclaration || spec.importKind === "type")) break;
				const originalName = "name" in spec.imported ? spec.imported.name : spec.local.name;
				if (originalName === "z") imports.namespaces.add(spec.local.name);
				else {
					imports.named.set(spec.local.name, originalName);
					zodNamedImportsByOriginal.set(originalName, spec.local.name);
				}
				bindings.push({
					name: originalName === "z" ? "*" : originalName,
					local: spec.local,
					declaration: node
				});
				break;
			}
		}
	}
	function resolveZodImport(node) {
		if (node.type !== AST_NODE_TYPES.Identifier) return null;
		if (!sourceCode) throw new Error("resolveZodImport needs a tracker created with a `sourceCode`.");
		const definition = findVariable(sourceCode.getScope(node), node.name)?.defs[0];
		if (definition?.type !== "ImportBinding" || definition.node.type === AST_NODE_TYPES.TSImportEqualsDeclaration) return null;
		const { local } = definition.node;
		return bindings.find((item) => item.local === local) ?? null;
	}
	function resolveZodExport(node) {
		if (node.type === AST_NODE_TYPES.Identifier) {
			const found = resolveZodImport(node);
			return found && found.name !== "*" ? found : null;
		}
		if (node.type !== AST_NODE_TYPES.MemberExpression || node.optional) return null;
		const found = resolveZodImport(node.object);
		const name = getStaticPropertyName(node);
		return found?.name === "*" && name ? {
			...found,
			name
		} : null;
	}
	return {
		importDeclarationListener,
		createSchemaVisitor({ schemaType, onSchema }) {
			const allowed = typeof schemaType === "string" ? [schemaType] : schemaType;
			return {
				ImportDeclaration: importDeclarationListener,
				CallExpression(node) {
					const meta = detectZodSchemaRootNode(node, imports);
					if (!meta) return;
					if (allowed && !allowed.includes(meta.schemaType)) return;
					onSchema(node, meta);
				}
			};
		},
		isZodNamespace: (name) => imports.namespaces.has(name),
		getNamedImportOriginal: (localName) => imports.named.get(localName),
		getNamedImportLocal: (originalName) => zodNamedImportsByOriginal.get(originalName),
		detectZodSchemaRootNode: (node) => detectZodSchemaRootNode(node, imports),
		collectZodChainMethods,
		collectZodSchemaConstraints: (node) => collectZodSchemaConstraints({
			methods: collectZodChainMethods(node),
			detectZodSchemaRootNode: (argument) => detectZodSchemaRootNode(argument, imports)
		}),
		isZodSchemaOfType: (node, schemaType) => isZodSchemaOfType(node, schemaType, imports),
		getZodImportBindings: () => bindings,
		resolveZodImport,
		resolveZodExport
	};
}
//#endregion
export { trackZodSchemaImports };
