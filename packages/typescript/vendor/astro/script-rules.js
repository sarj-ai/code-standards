import { sourceOrigin } from "../../src/rules/_source-origin.js";
import { READ, ReferenceTracker } from "../eslint-utils/index.mjs";
function createRule(ruleName, rule) {
	return {
		meta: {
			...rule.meta,
			docs: {
				available: () => true,
				...rule.meta.docs,
				url: `https://ota-meshi.github.io/eslint-plugin-astro/rules/${ruleName}/`,
				ruleId: `astro/${ruleName}`,
				ruleName
			}
		},
		create: rule.create
	};
}

var no_deprecated_astro_canonicalurl_default = createRule("no-deprecated-astro-canonicalurl", {
	meta: {
		docs: {
			description: "disallow using deprecated `Astro.canonicalURL`",
			category: "Possible Errors",
			recommended: true
		},
		schema: [],
		messages: { deprecated: "'Astro.canonicalURL' is deprecated. Use 'Astro.url' helper instead." },
		type: "problem"
	},
	create(context) {
		const sourceCode = context.sourceCode;
		if (!sourceOrigin(context).filename.endsWith(".astro")) return {};
		return { "Program:exit"(node) {
			const tracker = new ReferenceTracker(sourceCode.getScope(node));
			for (const { node, path } of tracker.iterateGlobalReferences({ Astro: { canonicalURL: { [READ]: true } } })) context.report({
				node,
				messageId: "deprecated",
				data: { name: path.join(".") }
			});
		} };
	}
});

var no_deprecated_astro_fetchcontent_default = createRule("no-deprecated-astro-fetchcontent", {
	meta: {
		docs: {
			description: "disallow using deprecated `Astro.fetchContent()`",
			category: "Possible Errors",
			recommended: true
		},
		schema: [],
		messages: { deprecated: "'Astro.fetchContent()' is deprecated. Use 'Astro.glob()' instead." },
		type: "problem",
		fixable: "code"
	},
	create(context) {
		const sourceCode = context.sourceCode;
		if (!sourceOrigin(context).filename.endsWith(".astro")) return {};
		return { "Program:exit"(node) {
			const tracker = new ReferenceTracker(sourceCode.getScope(node));
			for (const { node, path } of tracker.iterateGlobalReferences({ Astro: { fetchContent: { [READ]: true } } })) context.report({
				node,
				messageId: "deprecated",
				data: { name: path.join(".") },
				fix(fixer) {
					if (node.type !== "MemberExpression" || node.computed) return null;
					return fixer.replaceText(node.property, "glob");
				}
			});
		} };
	}
});

var no_deprecated_astro_resolve_default = createRule("no-deprecated-astro-resolve", {
	meta: {
		docs: {
			description: "disallow using deprecated `Astro.resolve()`",
			category: "Possible Errors",
			recommended: true
		},
		schema: [],
		messages: { deprecated: "'Astro.resolve()' is deprecated." },
		type: "problem"
	},
	create(context) {
		const sourceCode = context.sourceCode;
		if (!sourceOrigin(context).filename.endsWith(".astro")) return {};
		return { "Program:exit"(node) {
			const tracker = new ReferenceTracker(sourceCode.getScope(node));
			for (const { node, path } of tracker.iterateGlobalReferences({ Astro: { resolve: { [READ]: true } } })) context.report({
				node,
				messageId: "deprecated",
				data: { name: path.join(".") }
			});
		} };
	}
});

var no_deprecated_getentrybyslug_default = createRule("no-deprecated-getentrybyslug", {
	meta: {
		docs: {
			description: "disallow using deprecated `getEntryBySlug()`",
			category: "Possible Errors",
			recommended: true
		},
		schema: [],
		messages: { deprecated: "'getEntryBySlug()' is deprecated. Use 'getEntry()' instead." },
		type: "problem"
	},
	create(context) {
		if (!sourceOrigin(context).filename.endsWith(".astro")) return {};
		return { ImportSpecifier(node) {
			if (node.imported.type === "Identifier" && node.imported.name === "getEntryBySlug" && node.parent?.type === "ImportDeclaration" && node.parent.source.value === "astro:content") context.report({
				node,
				messageId: "deprecated"
			});
		} };
	}
});

const ALLOWED_EXPORTS = /* @__PURE__ */ new Set([
	"getStaticPaths",
	"partial",
	"prerender"
]);
var no_exports_from_components_default = createRule("no-exports-from-components", {
	meta: {
		docs: {
			description: "disallow value export",
			category: "Possible Errors",
			recommended: true
		},
		schema: [],
		messages: { disallowExport: "Exporting values from components is not allowed." },
		type: "problem"
	},
	create(context) {
		if (!sourceOrigin(context).filename.endsWith(".astro")) return {};
		/**
		* Verify for export declarations
		*/
		function verifyDeclaration(node) {
			if (!node) return;
			if (node.type.startsWith("TS") && !node.type.endsWith("Expression")) return;
			if (node.type === "FunctionDeclaration" && node.id && ALLOWED_EXPORTS.has(node.id.name) || node.type === "VariableDeclaration" && node.declarations.every((decl) => decl.id.type === "Identifier" && ALLOWED_EXPORTS.has(decl.id.name))) return;
			context.report({
				node,
				messageId: "disallowExport"
			});
		}
		return {
			ExportAllDeclaration(node) {
				if (node.exportKind === "type") return;
				context.report({
					node,
					messageId: "disallowExport"
				});
			},
			ExportDefaultDeclaration(node) {
				if (node.exportKind === "type") return;
				verifyDeclaration(node.declaration);
			},
			ExportNamedDeclaration(node) {
				if (node.exportKind === "type") return;
				verifyDeclaration(node.declaration);
				for (const spec of node.specifiers) {
					if (spec.exportKind === "type" || spec.exported.type !== "Identifier") continue;
					if (ALLOWED_EXPORTS.has(spec.exported.name)) continue;
					context.report({
						node: spec,
						messageId: "disallowExport"
					});
				}
			}
		};
	}
});

const PAGES_DIR_PATTERN = /(?:^|[/\\])pages[/\\]/;
const rule = createRule("no-prerender-export-outside-pages", {
	meta: {
		docs: {
			description: "disallow `prerender` export outside of pages/ directory",
			category: "Possible Errors",
			recommended: true
		},
		schema: [],
		messages: { disallowPrerenderOutsidePages: "'prerender' export is only valid inside a pages/ directory." },
		type: "problem"
	},
	create(context) {
		if (!sourceOrigin(context).filename.endsWith(".astro")) return {};
		const filename = sourceOrigin(context).filename;
		if (PAGES_DIR_PATTERN.test(filename)) return {};
		/**
		* Verify for export declarations
		*/
		function verifyDeclaration(node) {
			if (!node) return;
			if (node.type === "VariableDeclaration" && node.declarations.some((decl) => decl.id.type === "Identifier" && decl.id.name === "prerender")) context.report({
				node,
				messageId: "disallowPrerenderOutsidePages"
			});
		}
		return { ExportNamedDeclaration(node) {
			if (node.exportKind === "type") return;
			verifyDeclaration(node.declaration);
			for (const spec of node.specifiers) {
				if (spec.exportKind === "type") continue;
				if (spec.exported.type === "Identifier" && spec.exported.name === "prerender") context.report({
					node: spec,
					messageId: "disallowPrerenderOutsidePages"
				});
			}
		} };
	}
});

export const rules = {
"no-deprecated-astro-canonicalurl":no_deprecated_astro_canonicalurl_default,"no-deprecated-astro-fetchcontent":no_deprecated_astro_fetchcontent_default,"no-deprecated-astro-resolve":no_deprecated_astro_resolve_default,"no-deprecated-getentrybyslug":no_deprecated_getentrybyslug_default,"no-exports-from-components":no_exports_from_components_default,"no-prerender-export-outside-pages":rule
};
