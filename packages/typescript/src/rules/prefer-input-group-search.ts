/**
 * @fileoverview prefer-input-group-search — search fields should use the shared input-group primitive.
 *
 * Port of the 18.x `prefer-input-group-search` rule. Same algorithm;
 * the per-file import names and occurrences are reset in `before()`.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { findVariable } from "../utils/static-string.js";

const NAME = "prefer-input-group-search";

const INPUT_MODULE = /(?:^|\/)components\/ui\/input$/u;
const INPUT_GROUP_MODULE = /(?:^|\/)components\/ui\/input-group$/u;
const MAX_JSX_DISTANCE = 2;
const SEARCH_EXPORTS = ["Search", "SearchIcon", "LucideSearch"] as const;

interface Occurrence {
  ancestors: readonly Node[];
  node: ESTree.JSXOpeningElement;
}

function localNamedImports(
  node: ESTree.ImportDeclaration,
  importedName: string,
): string[] {
  return node.specifiers
    .filter(
      (specifier) =>
        specifier.type === "ImportSpecifier" &&
        importSpecifierName(specifier) === importedName,
    )
    .map((specifier) => specifier.local.name);
}

function elementName(node: ESTree.JSXOpeningElement): string | null {
  return node.name.type === "JSXIdentifier"
    ? node.name.name
    : null;
}

function jsxAncestors(occurrence: Occurrence): ESTree.JSXElement[] {
  return occurrence.ancestors.filter(
    (ancestor) =>
      ancestor.type === "JSXElement",
  );
}

function isWithinInputGroup(
  occurrence: Occurrence,
  inputGroupNames: ReadonlySet<string>,
): boolean {
  return jsxAncestors(occurrence).some((ancestor) =>
    inputGroupNames.has(elementName(ancestor.openingElement) ?? ""),
  );
}

function nearestEligibleCommonAncestor(
  search: Occurrence,
  input: Occurrence,
  inputGroupNames: ReadonlySet<string>,
): ESTree.JSXElement | null {
  const searchAncestors = jsxAncestors(search);
  const inputAncestorList = jsxAncestors(input);
  const inputAncestors = new Set(inputAncestorList);

  for (let index = searchAncestors.length - 1; index >= 0; index -= 1) {
    const ancestor = searchAncestors[index];
    if (ancestor === undefined) continue;
    if (!inputAncestors.has(ancestor)) continue;

    const searchDistance = searchAncestors.length - index - 1;
    const inputDistance =
      inputAncestorList.length - inputAncestorList.indexOf(ancestor) - 1;
    if (searchDistance > MAX_JSX_DISTANCE || inputDistance > MAX_JSX_DISTANCE) {
      return null;
    }

    if (inputGroupNames.has(elementName(ancestor.openingElement) ?? "")) {
      return null;
    }
    return ancestor;
  }
  return null;
}

function isActionIcon(
  search: Occurrence,
  wrapper: ESTree.JSXElement,
): boolean {
  if (hasInteraction(search.node)) return true;
  return jsxAncestors(search).some((ancestor) => {
    if (ancestor === wrapper) return false;
    const name = elementName(ancestor.openingElement);
    return name === "a" || name === "button" || hasInteraction(ancestor.openingElement);
  });
}

function hasInteraction(node: ESTree.JSXOpeningElement): boolean {
  return node.attributes.some((attribute) =>
    attribute.type === "JSXAttribute" &&
    attribute.name.type === "JSXIdentifier" &&
    /^(?:on[A-Z]|href$)/u.test(attribute.name.name),
  );
}

function mutuallyExclusive(left: Occurrence, right: Occurrence): boolean {
  return left.ancestors.some((ancestor, index) => {
    if (ancestor.type !== "ConditionalExpression") return false;
    const otherIndex = right.ancestors.indexOf(ancestor);
    if (otherIndex < 0) return false;
    const leftBranch = left.ancestors[index + 1];
    const rightBranch = right.ancestors[otherIndex + 1];
    return (leftBranch === ancestor.consequent && rightBranch === ancestor.alternate) ||
      (leftBranch === ancestor.alternate && rightBranch === ancestor.consequent);
  });
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require search icons and shared Input controls in the same visual wrapper to use InputGroup.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      preferInputGroup:
        "Use InputGroup with InputGroupAddon and InputGroupInput for this search field.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let inputNames = new Set<string>();
    let inputGroupNames = new Set<string>();
    let searchNames = new Set<string>();
    let inputs: Occurrence[] = [];
    let searches: Occurrence[] = [];

    return {
      before(): void {
        sourceCode = context.sourceCode;
        inputNames = new Set<string>();
        inputGroupNames = new Set<string>();
        searchNames = new Set<string>();
        inputs = [];
        searches = [];
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (node.importKind === "type") return;
        const source = String(node.source.value);
        if (source === "lucide-react") {
          for (const exported of SEARCH_EXPORTS) {
            localNamedImports(node, exported).forEach((name) =>
              searchNames.add(name),
            );
          }
        } else if (INPUT_MODULE.test(source)) {
          localNamedImports(node, "Input").forEach((name) =>
            inputNames.add(name),
          );
        } else if (INPUT_GROUP_MODULE.test(source)) {
          localNamedImports(node, "InputGroup").forEach((name) =>
            inputGroupNames.add(name),
          );
        }
      },
      JSXOpeningElement(node: ESTree.JSXOpeningElement): void {
        const name = elementName(node);
        if (name === null || !searchNames.has(name) && !inputNames.has(name)) return;
        const binding = findVariable(sourceCode.getScope(node), name);
        if (binding?.defs.length !== 1 ||
          binding.defs[0]?.node.type !== "ImportSpecifier" ||
          binding.defs[0].node.importKind === "type") return;
        const occurrence = {
          ancestors: sourceCode.getAncestors(node) as Node[],
          node,
        };
        if (searchNames.has(name)) searches.push(occurrence);
        if (inputNames.has(name)) inputs.push(occurrence);
      },
      "Program:exit"(): void {
        if (inputGroupNames.size === 0) return;
        const reported = new Set<ESTree.JSXElement>();
        for (const search of searches) {
          if (isWithinInputGroup(search, inputGroupNames)) continue;
          for (const input of inputs) {
            if (mutuallyExclusive(search, input)) continue;
            if (isWithinInputGroup(input, inputGroupNames)) continue;
            const wrapper = nearestEligibleCommonAncestor(
              search,
              input,
              inputGroupNames,
            );
            if (
              wrapper === null ||
              reported.has(wrapper) ||
              isActionIcon(search, wrapper)
            ) {
              continue;
            }
            reported.add(wrapper);
            context.report({
              node: wrapper.openingElement,
              messageId: "preferInputGroup",
            });
            break;
          }
        }
      },
    };
  },
});
