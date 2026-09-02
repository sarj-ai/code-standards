/**
 * @fileoverview prefer-shadcn-primitives — visible application UI should use shared shadcn primitives.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-shadcn-primitives.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join, parse as parsePath, relative, resolve, sep } from "node:path";
import { parse as parseJsonc, type ParseError } from "jsonc-parser";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "preferShadcnPrimitive";
export interface RuleOptions {
  readonly assumeAvailable?: boolean;
  readonly detectProjectPrimitives?: boolean;
}
type Options = readonly [RuleOptions?];

export const PREFER_SHADCN_PRIMITIVES_DOCUMENTATION = {
  summary: "Require visible raw JSX controls to use the corresponding shared shadcn primitive.",
  rationale: "Shared primitives centralize interaction, accessibility, and visual behavior across the product.",
  remediation: "Replace the raw visible control with the corresponding shared shadcn component.",
  category: "style",
  limitations: [
    "Hidden and file inputs, unassociated labels, and non-control semantic elements are excluded.",
    "Tests and the shared components/ui primitive implementation tree are excluded.",
    "Project detection is opt-in and fails closed unless components.json, one unambiguous tsconfig/jsconfig alias, the exact primitive module, and its expected export all exist.",
  ],
  examples: [
    { id: "shared-button", title: "Use a shared button", outcome: "no-match", files: [{ path: "src/form.tsx", source: "import { Button } from '@/components/ui/button'; const action = <Button>Save</Button>;" }], focusPath: "src/form.tsx", expectedCount: 0, public: true },
    { id: "raw-button", title: "Do not use a raw button", outcome: "match", files: [{ path: "src/form.tsx", source: "import { Card } from '@/components/ui/card'; const action = <button>Save</button>;" }], focusPath: "src/form.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const SHADCN_PRIMITIVES = {
  button: "Button",
  dialog: "Dialog or AlertDialog family",
  input: "Input",
  label: "Label",
  progress: "Progress",
  select: "Select family",
  table: "Table family",
  textarea: "Textarea",
} as const;

const SHADCN_EXPORTS = {
  button: "Button",
  dialog: "Dialog",
  input: "Input",
  label: "Label",
  progress: "Progress",
  select: "Select",
  table: "Table",
  textarea: "Textarea",
} as const;

type RawPrimitive = keyof typeof SHADCN_PRIMITIVES;

const LABELABLE_ELEMENTS: ReadonlySet<string> = new Set([
  "button",
  "input",
  "meter",
  "output",
  "progress",
  "select",
  "textarea",
]);

const SHARED_PRIMITIVE_IMPLEMENTATION_RE =
  /(?:^|\/)components\/ui(?:\/|$)/i;
const SHARED_PRIMITIVE_IMPORT_RE =
  /(?:^|\/)components\/ui\/[^/]+$/i;
const AMBIGUOUS_INPUT_TYPES: ReadonlySet<string> = new Set([
  "button",
  "color",
  "image",
  "range",
  "reset",
  "submit",
]);

interface ProjectPrimitives {
  readonly available: ReadonlySet<RawPrimitive>;
  readonly uiRoot: string | null;
}

const PROJECT_PRIMITIVES_CACHE = new Map<string, ProjectPrimitives>();

function detectProjectPrimitives(filename: string): ProjectPrimitives {
  const packageRoot = findPackageRoot(dirname(filename));
  if (packageRoot === null) return { available: new Set(), uiRoot: null };
  const cached = PROJECT_PRIMITIVES_CACHE.get(packageRoot);
  if (cached !== undefined) return cached;

  const manifest = readJsonc(join(packageRoot, "components.json"));
  const alias = stringProperty(manifest, "aliases", "ui");
  const uiRoot = alias === null ? null : resolveAlias(packageRoot, alias);
  if (uiRoot === null || !isWithin(packageRoot, uiRoot)) {
    const missing = { available: new Set<RawPrimitive>(), uiRoot: null } as const;
    PROJECT_PRIMITIVES_CACHE.set(packageRoot, missing);
    return missing;
  }

  const available = new Set<RawPrimitive>();
  for (const primitive of Object.keys(SHADCN_PRIMITIVES) as RawPrimitive[]) {
    const exportName = SHADCN_EXPORTS[primitive];
    const moduleCandidates = ["tsx", "ts", "jsx", "js"].flatMap((extension) => [
      join(uiRoot, `${primitive}.${extension}`),
      join(uiRoot, primitive, `index.${extension}`),
    ]);
    if (
      moduleCandidates.some(
        (candidate) => existsSync(candidate) && exportsPrimitive(candidate, exportName),
      )
    ) {
      available.add(primitive);
    }
  }
  const detected = { available, uiRoot } as const;
  PROJECT_PRIMITIVES_CACHE.set(packageRoot, detected);
  return detected;
}

function isWithin(root: string, candidate: string): boolean {
  const path = relative(root, candidate);
  return path === "" || (!path.startsWith(`..${sep}`) && path !== ".." && !isAbsolute(path));
}

function findPackageRoot(startDir: string): string | null {
  let dir = startDir;
  const filesystemRoot = parsePath(dir).root;
  for (;;) {
    if (existsSync(join(dir, "package.json"))) return dir;
    const parent = dirname(dir);
    if (dir === filesystemRoot || parent === dir) return null;
    dir = parent;
  }
}

function readJsonc(path: string): unknown {
  try {
    const errors: ParseError[] = [];
    const value: unknown = parseJsonc(readFileSync(path, "utf8"), errors, {
      allowTrailingComma: true,
      disallowComments: false,
    });
    return errors.length === 0 ? value : null;
  } catch {
    return null;
  }
}

function stringProperty(value: unknown, ...keys: string[]): string | null {
  let current = value;
  for (const key of keys) {
    if (typeof current !== "object" || current === null || !(key in current)) return null;
    current = (current as Record<string, unknown>)[key];
  }
  return typeof current === "string" && current.trim() !== "" ? current : null;
}

function resolveAlias(packageRoot: string, alias: string): string | null {
  if (isAbsolute(alias)) return null;
  if (alias.startsWith(".")) return resolve(packageRoot, alias);

  const configPath = ["tsconfig.json", "jsconfig.json"]
    .map((name) => join(packageRoot, name))
    .find(existsSync);
  if (configPath === undefined) return null;
  const config = readJsonc(configPath);
  if (typeof config !== "object" || config === null) return null;
  const compilerOptions = (config as Record<string, unknown>)["compilerOptions"];
  if (typeof compilerOptions !== "object" || compilerOptions === null) return null;
  const options = compilerOptions as Record<string, unknown>;
  const baseUrl = typeof options["baseUrl"] === "string" ? options["baseUrl"] : ".";
  const paths = options["paths"];
  if (typeof paths !== "object" || paths === null) return null;

  const matches: string[] = [];
  for (const [pattern, rawTargets] of Object.entries(paths as Record<string, unknown>)) {
    if (!Array.isArray(rawTargets) || rawTargets.length !== 1) {
      continue;
    }
    const [target] = rawTargets as unknown[];
    if (typeof target !== "string") continue;
    const star = pattern.indexOf("*");
    if (star === -1) {
      if (pattern === alias) matches.push(target);
      continue;
    }
    const prefix = pattern.slice(0, star);
    const suffix = pattern.slice(star + 1);
    if (!alias.startsWith(prefix) || !alias.endsWith(suffix)) continue;
    const substitution = alias.slice(prefix.length, alias.length - suffix.length);
    matches.push(target.replace("*", substitution));
  }
  const [match] = matches;
  if (matches.length !== 1 || match === undefined) return null;
  return resolve(packageRoot, baseUrl, match);
}

function exportsPrimitive(path: string, exportName: string): boolean {
  try {
    const source = readFileSync(path, "utf8");
    const escapedName = exportName.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
    return (
      new RegExp(`\\bexport\\s+(?:const|function|class)\\s+${escapedName}\\b`, "u").test(source) ||
      new RegExp(`\\bexport\\s*\\{[^}]*\\b${escapedName}\\b[^}]*\\}`, "u").test(source)
    );
  } catch {
    return false;
  }
}

function rawElementName(
  node: TSESTree.JSXOpeningElement,
): RawPrimitive | null {
  if (node.name.type !== AST_NODE_TYPES.JSXIdentifier) return null;
  const name = node.name.name;
  return Object.hasOwn(SHADCN_PRIMITIVES, name)
    ? (name as RawPrimitive)
    : null;
}

type StaticAttribute =
  | { readonly kind: "known"; readonly value: string }
  | { readonly kind: "missing" }
  | { readonly kind: "unknown" };

function effectiveAttribute(
  node: TSESTree.JSXOpeningElement,
  attributeName: string,
): StaticAttribute {
  for (const attribute of node.attributes.toReversed()) {
    if (attribute.type === AST_NODE_TYPES.JSXSpreadAttribute) {
      return { kind: "unknown" };
    }
    if (
      attribute.name.type !== AST_NODE_TYPES.JSXIdentifier ||
      attribute.name.name !== attributeName
    ) {
      continue;
    }
    const value = staticString(attribute.value);
    return value === null
      ? { kind: "unknown" }
      : { kind: "known", value };
  }
  return { kind: "missing" };
}

function staticString(value: TSESTree.JSXAttribute["value"]): string | null {
  if (value?.type === AST_NODE_TYPES.Literal) {
    return typeof value.value === "string" ? value.value : null;
  }
  if (value?.type !== AST_NODE_TYPES.JSXExpressionContainer) return null;
  return staticExpressionString(value.expression);
}

function staticExpressionString(
  expression: TSESTree.Expression | TSESTree.JSXEmptyExpression,
): string | null {
  if (expression.type === AST_NODE_TYPES.Literal) {
    return typeof expression.value === "string" ? expression.value : null;
  }
  if (expression.type === AST_NODE_TYPES.TemplateLiteral) {
    let value = expression.quasis[0]?.value.cooked ?? "";
    for (const [index, substitution] of expression.expressions.entries()) {
      const staticSubstitution = staticExpressionString(substitution);
      if (staticSubstitution === null) return null;
      value += staticSubstitution;
      value += expression.quasis[index + 1]?.value.cooked ?? "";
    }
    return value;
  }
  if (
    expression.type === AST_NODE_TYPES.TSAsExpression ||
    expression.type === AST_NODE_TYPES.TSNonNullExpression ||
    expression.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    expression.type === AST_NODE_TYPES.TSTypeAssertion
  ) {
    return staticExpressionString(expression.expression);
  }
  return null;
}

function isLabelableElement(node: TSESTree.JSXElement): boolean {
  if (node.openingElement.name.type !== AST_NODE_TYPES.JSXIdentifier) {
    return false;
  }
  const name = node.openingElement.name.name;
  if (!LABELABLE_ELEMENTS.has(name)) return false;
  if (name !== "input") return true;
  const typeAttribute = effectiveAttribute(node.openingElement, "type");
  if (typeAttribute.kind === "unknown") return false;
  return !(
    typeAttribute.kind === "known" &&
    typeAttribute.value.toLowerCase() === "hidden"
  );
}

function containsLabelableElement(
  node: TSESTree.JSXElement | TSESTree.JSXFragment,
): boolean {
  return node.children.some((child) => {
    if (child.type === AST_NODE_TYPES.JSXElement) {
      return isLabelableElement(child) || containsLabelableElement(child);
    }
    if (child.type === AST_NODE_TYPES.JSXFragment) {
      return containsLabelableElement(child);
    }
    return false;
  });
}

function isStaticallyAssociatedLabel(node: TSESTree.JSXOpeningElement): boolean {
  const htmlFor = effectiveAttribute(node, "htmlFor");
  if (htmlFor.kind === "known" && htmlFor.value.trim().length > 0) return true;
  return (
    node.parent.type === AST_NODE_TYPES.JSXElement &&
    containsLabelableElement(node.parent)
  );
}

function replacementFor(
  node: TSESTree.JSXOpeningElement,
  element: RawPrimitive,
): string | null {
  if (element !== "input") return SHADCN_PRIMITIVES[element];
  const typeAttribute = effectiveAttribute(node, "type");
  if (typeAttribute.kind === "unknown") return null;
  const inputType =
    typeAttribute.kind === "known" ? typeAttribute.value.toLowerCase() : "text";
  if (inputType === "hidden" || inputType === "file") return null;
  if (inputType === "checkbox") return "Checkbox";
  if (inputType === "radio") return "RadioGroup family";
  if (AMBIGUOUS_INPUT_TYPES.has(inputType)) return null;
  return "Input";
}

export default createRule<Options, MessageIds>({
  name: "prefer-shadcn-primitives",
  documentation: PREFER_SHADCN_PRIMITIVES_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require visible raw JSX controls to use the corresponding shared shadcn primitive.",
    },
    schema: [
      {
        type: "object",
        properties: {
          assumeAvailable: { type: "boolean" },
          detectProjectPrimitives: { type: "boolean" },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      preferShadcnPrimitive:
        "Use the shared {{ replacement }} shadcn primitive instead of raw <{{ element }}> markup.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    const filename = context.filename.replaceAll("\\", "/");
    const projectPrimitives = options?.detectProjectPrimitives === true
      ? detectProjectPrimitives(context.filename)
      : { available: new Set<RawPrimitive>(), uiRoot: null };
    if (
      isTestFile(filename) ||
      isStoryFile(filename) ||
      isGeneratedFile(filename, context.sourceCode.text) ||
      SHARED_PRIMITIVE_IMPLEMENTATION_RE.test(filename) ||
      (projectPrimitives.uiRoot !== null && isWithin(projectPrimitives.uiRoot, context.filename))
    ) {
      return {};
    }
    // ESLint rules see one file at a time. Require local proof that the
    // repository actually owns a shadcn primitive tree before prescribing it;
    // otherwise every raw control in a non-shadcn project becomes noise.
    let hasSharedPrimitiveImport = options?.assumeAvailable ?? false;
    const candidates: Array<{
      readonly element: RawPrimitive;
      readonly node: TSESTree.JSXOpeningElement;
      readonly replacement: string;
    }> = [];
    return {
      ImportDeclaration(node): void {
        if (
          typeof node.source.value === "string" &&
          SHARED_PRIMITIVE_IMPORT_RE.test(node.source.value)
        ) {
          hasSharedPrimitiveImport = true;
        }
      },
      JSXOpeningElement(node): void {
        const element = rawElementName(node);
        if (element === null) return;
        if (element === "label" && !isStaticallyAssociatedLabel(node)) return;
        const replacement = replacementFor(node, element);
        if (replacement === null) return;
        candidates.push({ element, node, replacement });
      },
      "Program:exit"(): void {
        for (const { element, node, replacement } of candidates) {
          if (
            !hasSharedPrimitiveImport &&
            !projectPrimitives.available.has(element)
          ) {
            continue;
          }
          context.report({
            node,
            messageId: "preferShadcnPrimitive",
            data: { element, replacement },
          });
        }
      },
    };
  },
});
