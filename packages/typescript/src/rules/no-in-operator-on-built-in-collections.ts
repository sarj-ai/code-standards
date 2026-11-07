/**
 * @fileoverview no-in-operator-on-built-in-collections — do not use `in` to test entries in built-in Map and Set collections.
 *
 * Port of the 18.x `no-in-operator-on-built-in-collections` rule. Typed:
 * without tsrs types it reports nothing, as the original returns no visitors
 * without type services. The walk collects `in` expressions; `Program:exit`
 * asks tsrs for their right-hand types in one batched request.
 */

import type { Type } from "tsrs/sync";

import { defineRule, type ESTree } from "../types.js";
import { nativeTypes, type NativeTypes } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";
import { collectionPropertyFix } from "./_collection-property-fix.js";

const NAME = "no-in-operator-on-built-in-collections";

const COLLECTION_NAMES: ReadonlySet<string> = new Set([
  "Map",
  "ReadonlyMap",
  "WeakMap",
  "Set",
  "ReadonlySet",
  "WeakSet",
]);

function isDefaultLibraryCollection(native: NativeTypes, type: Type | undefined): boolean {
  if (type === undefined) return false;
  const flags = native.sync.TypeFlags;
  if ((type.flags & (flags.Any | flags.Unknown | flags.Never | flags.TypeParameter | flags.Union | flags.Intersection)) !== 0) return false;
  const symbol = type.getSymbol();
  if (symbol === undefined || !COLLECTION_NAMES.has(symbol.name)) return false;
  const declarations = symbol.declarations;
  // An interface declaration of the symbol carries the symbol's own name.
  return declarations.length > 0 &&
    declarations.every((declaration) => native.program.getSourceFileMetadataByPath(declaration.path)?.isDefaultLibrary === true) &&
    declarations.some((declaration) => declaration.kind === native.ast.SyntaxKind.InterfaceDeclaration);
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Do not use the `in` operator to test entries in built-in Map and Set collections.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      ambiguousCollectionIn:
        "`in` checks properties on this collection object, not stored entries. Use `.has()` for entry membership or `Reflect.has()` for intentional property lookup.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: ESTree.BinaryExpression[] = [];
    return {
      before() {
        tsrs = null;
        candidates = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      BinaryExpression(node) {
        if (node.operator === "in") candidates.push(node);
      },
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        const found = tsrs.run((file) => {
          const native = nativeTypes(file);
          const types = native.file.typesOf(candidates.map((node) => node.right)) as (Type | undefined)[];
          return types.map((type) => isDefaultLibraryCollection(native, type));
        });
        if (found === null) return;
        candidates.forEach((node, i) => {
          if (found[i] !== true) return;
          const fix = collectionPropertyFix(context.sourceCode, node);
          context.report(fix === null
            ? { node, messageId: "ambiguousCollectionIn" }
            : { node, messageId: "ambiguousCollectionIn", fix });
        });
      },
    };
  },
});
