/**
 * @fileoverview no-restricted-library-load — configured library restrictions also cover runtime loads.
 *
 * Port of the 18.x `no-restricted-library-load` rule. The rule is
 * untyped, so the port covers all of it.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { findVariable, staticString } from "../utils/static-string.js";

type IdentifierNode = Extract<Node, { type: "Identifier" }>;

const NAME = "no-restricted-library-load";

export interface RestrictedLibrary {
  readonly id: string;
  readonly module: string;
  readonly replacement: string;
  readonly note?: string;
}

interface Options {
  readonly libraries: readonly RestrictedLibrary[];
}

function matchesModule(source: string, module: string): boolean {
  return source === module || source.startsWith(`${module}/`);
}

function staticMemberName(node: ESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === "Identifier") return node.property.name;
  return node.computed && node.property.type === "Literal" && typeof node.property.value === "string"
    ? node.property.value
    : null;
}

export default defineRule({
  meta: {
    defaultOptions: [{ libraries: [] }],
    type: "problem",
    docs: {
      description:
        "Apply configured library restrictions to literal runtime loads and CommonJS resolution references.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        required: ["libraries"],
        properties: {
          libraries: {
            description: "Library import and module-load restrictions.",
            type: "array",
            items: {
              type: "object",
              additionalProperties: false,
              required: ["id", "module", "replacement"],
              properties: {
                id: { type: "string", minLength: 1 },
                module: { type: "string", minLength: 1 },
                replacement: { type: "string", minLength: 1 },
                note: { type: "string", minLength: 1 },
              },
            },
          },
        },
      },
    ],
    messages: {
      restrictedLibraryLoad:
        "{{id}}: Replace this runtime dependency reference to {{module}} with {{replacement}}.{{note}}",
    },
  },
  createOnce(context) {
    let restrictions: readonly RestrictedLibrary[] = [];

    function report(node: Node, source: string): void {
      const restriction = restrictions.find((entry) => matchesModule(source, entry.module));
      if (restriction === undefined) return;
      context.report({
        node,
        messageId: "restrictedLibraryLoad",
        data: {
          id: restriction.id,
          module: restriction.module,
          replacement: restriction.replacement,
          note: restriction.note === undefined ? "" : ` ${restriction.note}`,
        },
      });
    }

    function isUnshadowedRequire(node: IdentifierNode): boolean {
      const variable = findVariable(context.sourceCode.getScope(node), node.name);
      return variable === null || variable.defs.length === 0;
    }

    return {
      before() {
        restrictions = (context.options[0] as Options | undefined)?.libraries ?? [];
        // No restriction can match, so no file can report.
        if (restrictions.length === 0) return false;
        return undefined;
      },
      ImportExpression(node: ESTree.ImportExpression): void {
        const source = staticString(node.source);
        if (source !== null) report(node.source, source);
      },
      CallExpression(node: ESTree.CallExpression): void {
        const callee = unwrapExpression(node.callee);
        let requireIdentifier: IdentifierNode | null = null;
        if (callee.type === "Identifier" && callee.name === "require") {
          requireIdentifier = callee;
        } else if (
          callee.type === "MemberExpression" &&
          callee.object.type === "Identifier" &&
          callee.object.name === "require" &&
          staticMemberName(callee) === "resolve"
        ) {
          requireIdentifier = callee.object;
        }
        if (requireIdentifier === null || !isUnshadowedRequire(requireIdentifier)) return;
        const argument = node.arguments[0];
        const source = staticString(argument);
        if (source !== null && argument !== undefined) report(argument, source);
      },
      TSImportEqualsDeclaration(node: ESTree.TSImportEqualsDeclaration): void {
        if (node.importKind === "type") return;
        if (node.moduleReference.type !== "TSExternalModuleReference") return;
        const source = staticString(node.moduleReference.expression);
        if (source !== null) report(node.moduleReference.expression, source);
      },
    };
  },
});
