/**
 * @fileoverview prefer-input-group-search — search fields should use the shared input-group primitive.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-input-group-search.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";

type MessageIds = "preferInputGroup";
type Options = readonly [];

const INPUT_MODULE = /(?:^|\/)components\/ui\/input$/u;
const INPUT_GROUP_MODULE = /(?:^|\/)components\/ui\/input-group$/u;
const MAX_JSX_DISTANCE = 2;

interface Occurrence {
  ancestors: readonly TSESTree.Node[];
  node: TSESTree.JSXOpeningElement;
}

function localNamedImports(
  node: TSESTree.ImportDeclaration,
  importedName: string,
): string[] {
  return node.specifiers
    .filter(
      (specifier): specifier is TSESTree.ImportSpecifier =>
        specifier.type === AST_NODE_TYPES.ImportSpecifier &&
        (specifier.imported.type === AST_NODE_TYPES.Identifier
          ? specifier.imported.name
          : specifier.imported.value) === importedName,
    )
    .map((specifier) => specifier.local.name);
}

function elementName(node: TSESTree.JSXOpeningElement): string | null {
  return node.name.type === AST_NODE_TYPES.JSXIdentifier
    ? node.name.name
    : null;
}

function jsxAncestors(occurrence: Occurrence): TSESTree.JSXElement[] {
  return occurrence.ancestors.filter(
    (ancestor): ancestor is TSESTree.JSXElement =>
      ancestor.type === AST_NODE_TYPES.JSXElement,
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
): TSESTree.JSXElement | null {
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

export default createRule<Options, MessageIds>({
  name: "prefer-input-group-search",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require search icons and shared Input controls in the same visual wrapper to use InputGroup.",
    },
    schema: [],
    messages: {
      preferInputGroup:
        "Use InputGroup with InputGroupAddon and InputGroupInput for this search field.",
    },
  },
  defaultOptions: [],
  create(context) {
    const inputNames = new Set<string>();
    const inputGroupNames = new Set<string>();
    const searchNames = new Set<string>();
    const inputs: Occurrence[] = [];
    const searches: Occurrence[] = [];

    return {
      ImportDeclaration(node): void {
        const source = String(node.source.value);
        if (source === "lucide-react") {
          localNamedImports(node, "Search").forEach((name) =>
            searchNames.add(name),
          );
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
      JSXOpeningElement(node): void {
        const name = elementName(node);
        if (name === null) return;
        const occurrence = {
          ancestors: context.sourceCode.getAncestors(node),
          node,
        };
        if (searchNames.has(name)) searches.push(occurrence);
        if (inputNames.has(name)) inputs.push(occurrence);
      },
      "Program:exit"(): void {
        const reported = new Set<TSESTree.JSXElement>();
        for (const search of searches) {
          if (isWithinInputGroup(search, inputGroupNames)) continue;
          for (const input of inputs) {
            if (isWithinInputGroup(input, inputGroupNames)) continue;
            const wrapper = nearestEligibleCommonAncestor(
              search,
              input,
              inputGroupNames,
            );
            if (wrapper === null || reported.has(wrapper)) continue;
            reported.add(wrapper);
            context.report({
              node: wrapper.openingElement,
              messageId: "preferInputGroup",
            });
          }
        }
      },
    };
  },
});
