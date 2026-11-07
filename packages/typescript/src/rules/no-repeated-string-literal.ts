/**
 * @fileoverview no-repeated-string-literal — the same structured literal in two functions drifts the moment one copy is edited.
 *
 * Port of the 18.x `no-repeated-string-literal` rule. The rule is
 * untyped, so the port covers all of it.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { enclosingFunction } from "../utils/stable-value-binding.js";
import { existingStringConstantFix } from "./_existing-string-constant-fix.js";

const NAME = "no-repeated-string-literal";

const MIN_LENGTH = 40;
const MIN_DISTINCT_SCOPES = 2;
const PREVIEW_LENGTH = 40;

/** Case-sensitive on purpose: uppercase keywords mean SQL, lowercase means prose. */
const SQL_KEYWORD_RE =
  /\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|JOIN|VALUES|ON CONFLICT|RETURNING|GROUP BY|ORDER BY)\b/;
const IDENTIFIER_RE = /^[a-z_][a-z0-9_.]*$/;
const URL_PATH_RE =
  /^\/(?=[^\s]*[A-Za-z0-9])[A-Za-z0-9._~!$&'()*+,;=:@%/?#{}\u005B\u005D-]+$/;

/** Recognized query, identifier, or route shapes; equality alone is not intent. */
function isStructured(value: string): boolean {
  return (
    SQL_KEYWORD_RE.test(value) ||
    IDENTIFIER_RE.test(value) ||
    URL_PATH_RE.test(value)
  );
}

function preview(value: string): string {
  const oneLine = value.replaceAll("\n", " ").trim();
  return oneLine.length <= PREVIEW_LENGTH
    ? oneLine
    : `${oneLine.slice(0, PREVIEW_LENGTH)}...`;
}

const SCAFFOLDING_PARENTS: ReadonlySet<string> = new Set([
  "ImportDeclaration", "ImportExpression", "ExportNamedDeclaration", "ExportAllDeclaration",
  "TSImportType", "JSXAttribute", "TSLiteralType",
]);

/**
 * True when the literal is scaffolding rather than a reusable value: an
 * import/`require` source (repeating a module path is the point) or a JSX
 * attribute value (styling strings, handled by the styling rules).
 */
function isScaffolding(node: Node): boolean {
  const parent = node.parent;
  if (parent == null || SCAFFOLDING_PARENTS.has(parent.type)) return true;
  if (parent.type === "Property" || parent.type === "PropertyDefinition" ||
    parent.type === "MethodDefinition" || parent.type === "AccessorProperty") return parent.key === node && !parent.computed;
  if (parent.type === "JSXExpressionContainer") return parent.parent.type === "JSXAttribute";
  return parent.type === "CallExpression" && parent.callee.type === "Identifier" && parent.callee.name === "require";
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Disallow a long structured string literal repeated across functions; the copies drift when one is edited. Extract a module-level constant.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      noRepeatedStringLiteral:
        'Structured string literal "{{preview}}" is repeated across functions (first use on line {{line}}) — extract a module-level constant so the copies cannot drift.',
    },
  },
  createOnce(context) {
    // Each occurrence keeps its enclosing function, or null at module/class scope.
    let occurrences = new Map<string, { readonly node: Node; readonly scope: Node | null }[]>();

    const record = (value: string, node: Node): void => {
      if (
        value.length < MIN_LENGTH ||
        !isStructured(value) ||
        isScaffolding(node)
      ) {
        return;
      }
      const occurrence = { node, scope: enclosingFunction(node) };
      const existing = occurrences.get(value);
      if (existing === undefined) {
        occurrences.set(value, [occurrence]);
      } else {
        existing.push(occurrence);
      }
    };

    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        occurrences = new Map();
        return undefined;
      },
      Literal(node): void {
        if (typeof node.value === "string") {
          record(node.value, node);
        }
      },
      TemplateLiteral(node: ESTree.TemplateLiteral): void {
        // A tagged template (`js`…``, `css`…``, `sql`…``) is a call, not a
        // string value — the tag, not this rule, decides what the text means.
        if (node.parent?.type === "TaggedTemplateExpression") {
          return;
        }
        const [only] = node.quasis;
        if (node.expressions.length === 0 && only !== undefined) {
          record(only.value.cooked ?? only.value.raw, node);
        }
      },
      "Program:exit": (): void => {
        for (const [value, entries] of occurrences) {
          const distinctScopes = new Set(
            entries.map((entry) => entry.scope).filter((scope) => scope !== null),
          );
          if (distinctScopes.size < MIN_DISTINCT_SCOPES) {
            continue;
          }
          const [first, ...repeats] = entries.map((entry) => entry.node) as [Node, ...Node[]];
          for (const node of repeats) {
            const fix = existingStringConstantFix(context.sourceCode, node, value);
            const report = {
              node,
              messageId: "noRepeatedStringLiteral",
              data: {
                preview: preview(value),
                line: String(first.loc.start.line),
              },
            };
            context.report(fix === null ? report : { ...report, fix });
          }
        }
      },
    };
  },
});
