/**
 * @fileoverview prefer-input-group-search — search fields should use the shared input-group primitive.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-input-group-search.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "preferInputGroup";
type Options = readonly [];

export const preferInputGroupSearchDocumentation = {
  summary: "Require search icons and shared Input controls in the same visual wrapper to use InputGroup.",
  rationale: "The shared compound control provides consistent spacing, focus behavior, and accessible composition.",
  remediation: "Compose the search icon and field with InputGroup, InputGroupAddon, and InputGroupInput.",
  category: "style",
  limitations: [
    "Only Search and Input bindings imported from the recognized shared modules are paired.",
    "The file must import InputGroup, proving that the repository has adopted that optional primitive.",
  ],
  examples: [
    { id: "grouped-search", title: "Use the shared input group", outcome: "no-match", files: [{ path: "src/search.tsx", source: "import { Search } from 'lucide-react'; import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'; const field = <InputGroup><InputGroupAddon><Search /></InputGroupAddon><InputGroupInput /></InputGroup>;" }], focusPath: "src/search.tsx", expectedCount: 0, public: true },
    { id: "loose-search-input", title: "Do not pair loose search controls", outcome: "match", files: [{ path: "src/search.tsx", source: "import { Search } from 'lucide-react'; import { Input } from '@/components/ui/input'; import { InputGroup } from '@/components/ui/input-group'; const field = <div><Search /><Input /></div>;" }], focusPath: "src/search.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const INPUT_MODULE = /(?:^|\/)components\/ui\/input$/u;
const INPUT_GROUP_MODULE = /(?:^|\/)components\/ui\/input-group$/u;
const MAX_JSX_DISTANCE = 2;
const SEARCH_EXPORTS = ["Search", "SearchIcon", "LucideSearch"] as const;

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

function isActionIcon(
  search: Occurrence,
  wrapper: TSESTree.JSXElement,
): boolean {
  return jsxAncestors(search).some((ancestor) => {
    if (ancestor === wrapper) return false;
    const name = elementName(ancestor.openingElement);
    return name === "a" || name === "button";
  });
}

export default createRule<Options, MessageIds>({
  name: "prefer-input-group-search",
  documentation: preferInputGroupSearchDocumentation,
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
        if (inputGroupNames.size === 0) return;
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
