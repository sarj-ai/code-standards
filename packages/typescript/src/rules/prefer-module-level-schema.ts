/**
 * @fileoverview prefer-module-level-schema — a Zod schema built inside a function is rebuilt on every call, every request, every render.
 *
 * Port of the 18.x `prefer-module-level-schema` rule. The rule is
 * untyped, so the port covers all of it. The closure checks it shares with
 * prefer-module-level-refined-schema are exported for that rule.
 */

import type { Reference, Variable } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type Scope, type SourceCode } from "../types.js";
import { forEachOwnAstChild, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { getPropertyName } from "../utils/static-string.js";
import { isZodModule } from "../utils/zod.js";

const NAME = "prefer-module-level-schema";

interface Options {
  readonly factories?: readonly string[];
  readonly ignoreTestFiles?: boolean;
  readonly memoCallees?: readonly string[];
  readonly minProperties?: number;
}

const DEFAULT_FACTORIES: readonly string[] = [
  "discriminatedUnion",
  "intersection",
  "looseObject",
  "object",
  "record",
  "strictObject",
  "tuple",
  "union",
];

const DEFAULT_MIN_PROPERTIES = 2;

const CONSTRUCTION_FACTORIES: ReadonlySet<string> = new Set([
  ...DEFAULT_FACTORIES,
  "any", "array", "bigint", "boolean", "custom", "date", "enum", "instanceof",
  "lazy", "literal", "map", "nan", "nativeEnum", "never", "null", "nullable",
  "nullish", "number", "optional", "preprocess", "promise", "set", "string",
  "symbol", "undefined", "unknown", "void",
]);

/** Wrappers that already pay the construction cost exactly once. */
const MEMO_CALLEES: readonly string[] = ["lazy", "memo", "once", "useMemo"];

const TERMINAL_METHODS: ReadonlySet<string> = new Set([
  "isNullable",
  "isOptional",
  "parse",
  "parseAsync",
  "safeParse",
  "safeParseAsync",
  "spa",
]);

const ZOD_COMBINATOR_METHODS: ReadonlySet<string> = new Set([
  "and",
  "array",
  "catch",
  "catchall",
  "default",
  "extend",
  "merge",
  "or",
  "pipe",
  "refine",
  "superRefine",
  "transform",
]);

const I18N_CALLEE_NAMES: ReadonlySet<string> = new Set([
  "$t",
  "defineMessage",
  "gettext",
  "msg",
  "ngettext",
  "t",
  "translate",
]);

/** Receivers whose methods render locale-dependent text (`i18n._`, `intl.formatMessage`). */
const I18N_RECEIVER_NAMES: ReadonlySet<string> = new Set(["$i18n", "i18n", "intl"]);

export const FUNCTION_TYPES: ReadonlySet<string> = new Set([
  "ArrowFunctionExpression",
  "FunctionDeclaration",
  "FunctionExpression",
]);

/**
 * The whole schema EXPRESSION, not just the factory call: climb out through
 * `.refine(...)`, `.superRefine(...)`, `.transform(...)`, `.default(...)` and
 * every other builder method applied to it.
 */
function schemaExpression(node: ESTree.CallExpression): Node {
  let current: Node = node;
  for (;;) {
    const parent = parentOf(current);
    if (parent === null) return current;
    if (
      parent.type === "MemberExpression" &&
      parent.object === current &&
      TERMINAL_METHODS.has(getPropertyName(parent) ?? "")
    ) {
      return current;
    }
    if (
      (parent.type === "MemberExpression" && parent.object === current) ||
      (parent.type === "CallExpression" && parent.callee === current) ||
      (parent.type === "TSAsExpression" && parent.expression === current) ||
      (parent.type === "TSNonNullExpression" && parent.expression === current)
    ) {
      current = parent;
      continue;
    }
    return current;
  }
}

/** Option sets may name `""`, so a missing name must not match. */
function propertyNameIn(member: ESTree.MemberExpression, names: ReadonlySet<string>): boolean {
  const name = getPropertyName(member);
  return name !== null && names.has(name);
}

/** The outermost function ancestor — hoisting targets module scope, not the nearest body. */
export function outermostEnclosingFunction(node: Node): Node | undefined {
  let outermost: Node | undefined;
  let current = parentOf(node);
  while (current !== null) {
    if (FUNCTION_TYPES.has(current.type)) outermost = current;
    current = parentOf(current);
  }
  return outermost;
}

/** Does any node in `root`'s subtree satisfy `predicate`? */
export function subtreeSome(root: Node, predicate: (node: Node) => boolean, skipDeferredFunctions = false): boolean {
  if (skipDeferredFunctions && FUNCTION_TYPES.has(root.type)) return false;
  return predicate(root) || forEachOwnAstChild(root, (child) => subtreeSome(child, predicate, skipDeferredFunctions));
}

/** `this` / `super` / `arguments` anywhere inside pins the schema to its receiver. */
export function readsReceiver(node: Node): boolean {
  return subtreeSome(
    node,
    (inner) =>
      inner.type === "ThisExpression" ||
      inner.type === "Super" ||
      (inner.type === "Identifier" && inner.name === "arguments"),
  );
}

export function buildsLocalizedText(node: Node): boolean {
  return subtreeSome(node, (inner) => {
    if (inner.type === "TaggedTemplateExpression") return true;
    if (inner.type !== "CallExpression") return false;
    const callee = unwrapExpression(inner.callee);
    const calleeReceiver = callee.type === "MemberExpression" ? unwrapExpression(callee.object) : callee;
    if (callee.type === "Identifier") return I18N_CALLEE_NAMES.has(callee.name);
    return (
      callee.type === "MemberExpression" &&
      calleeReceiver.type === "Identifier" &&
      I18N_RECEIVER_NAMES.has(calleeReceiver.name)
    );
  });
}

/**
 * No reference inside the schema resolves to a binding the enclosing function
 * owns, and no imported function is called unless `isZodImport` accepts it.
 */
export function closesOverNothing(
  sourceCode: SourceCode,
  node: Node,
  enclosing: Node,
  isZodImport: (identifier: Reference["identifier"], resolved: Variable) => boolean,
): boolean {
  const references: Reference[] = [];
  collectReferences(sourceCode.getScope(node), references);
  const [schemaStart, schemaEnd] = node.range;
  const [functionStart, functionEnd] = enclosing.range;
  function hasSafeDefinitions(reference: Reference, resolved: Variable): boolean {
    for (const definition of resolved.defs) {
      if (definition.type === "ImportBinding") {
        const parent = parentOf(reference.identifier);
        if (parent?.type === "CallExpression" && parent.callee === reference.identifier && !isZodImport(reference.identifier, resolved)) {
          return false;
        }
        continue;
      }
      const defNode = definition.node;
      if (defNode.type === "VariableDeclarator") {
        const declaration = parentOf(defNode);
        if (declaration?.type === "VariableDeclaration" && declaration.kind !== "const") return false;
      }
      const [defStart, defEnd] = defNode.range;
      if (defStart >= schemaStart && defEnd <= schemaEnd) continue;
      if (defStart >= functionStart && defEnd <= functionEnd) return false;
    }
    return true;
  }

  for (const reference of references) {
    const [identifierStart] = reference.identifier.range;
    if (identifierStart < schemaStart || identifierStart >= schemaEnd) continue;
    const resolved = reference.resolved;
    if (resolved === null) continue;
    if (!hasSafeDefinitions(reference, resolved)) return false;
  }
  return true;
}

function collectReferences(scope: Scope, out: Reference[]): void {
  out.push(...scope.references);
  for (const child of scope.childScopes) collectReferences(child, out);
}

/** How the enclosing function should be named in the message. */
function ownerName(enclosing: Node): string {
  const parent = parentOf(enclosing);
  if (enclosing.type === "FunctionDeclaration" && enclosing.id !== null) return enclosing.id.name;
  if (parent !== null && parent.type === "VariableDeclarator" && parent.id.type === "Identifier") return parent.id.name;
  if (
    parent !== null &&
    (parent.type === "MethodDefinition" || parent.type === "Property") &&
    parent.key.type === "Identifier"
  ) {
    return parent.key.name;
  }
  return "this function";
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "problem",
    docs: {
      description: "Declare a Zod schema at module scope when it closes over nothing in the enclosing function",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        properties: {
          factories: {
            type: "array",
            items: { type: "string" },
            description:
              "Zod factory names to check. Defaults to the object-like composites; add `array` / `enum` to widen.",
          },
          ignoreTestFiles: {
            type: "boolean",
            description: "Skip test files, where a fixture schema belongs next to its assertion.",
          },
          memoCallees: {
            type: "array",
            items: { type: "string" },
            description:
              "Wrappers that construct their callback at most once. Defaults to lazy, memo, once, and useMemo.",
          },
          minProperties: {
            type: "number",
            minimum: 0,
            description: "Minimum key count before an object-like schema is reported.",
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      hoistSchema:
        "Move this `{{factory}}` schema to module scope. It uses nothing from `{{owner}}`, so it is rebuilt on every call for no benefit and cannot be exported, reused, or `z.infer`-ed from where it is.",
    },
  },
  createOnce(context) {
    let factories: ReadonlySet<string> = new Set(DEFAULT_FACTORIES);
    let memoCallees: ReadonlySet<string> = new Set(MEMO_CALLEES);
    let minProperties = DEFAULT_MIN_PROPERTIES;
    const zodNamespaces = new Set<string>();

    function isZodCall(node: Node): boolean {
      if (node.type !== "CallExpression") return false;
      const callee = unwrapExpression(node.callee);
      if (callee.type !== "MemberExpression") return false;
      const receiver = unwrapExpression(callee.object);
      return getPropertyName(callee) !== null && receiver.type === "Identifier" && zodNamespaces.has(receiver.name);
    }

    function isSchemaConstruction(node: ESTree.CallExpression): boolean {
      const callee = unwrapExpression(node.callee);
      if (callee.type !== "MemberExpression") return false;
      const name = getPropertyName(callee);
      if (name === null || TERMINAL_METHODS.has(name)) return false;
      const calleeReceiver = unwrapExpression(callee.object);
      if (calleeReceiver.type === "CallExpression") return isSchemaConstruction(calleeReceiver);
      return isZodCall(node) && CONSTRUCTION_FACTORIES.has(name);
    }

    /** Neither the schema nor the outermost schema composed from it computes eagerly or closes over `enclosing`. */
    function isHoistable(expression: Node, enclosing: Node): boolean {
      if (readsReceiver(expression) || buildsLocalizedText(expression)) return false;
      const outermost = outermostSchemaExpression(expression);
      if (hasEagerComputation(outermost)) return false;
      if (
        outermost !== expression &&
        (readsReceiver(outermost) || buildsLocalizedText(outermost) ||
          !closesOverNothing(context.sourceCode, outermost, enclosing, isZodNamespace))
      ) {
        return false;
      }
      return closesOverNothing(context.sourceCode, expression, enclosing, isZodNamespace);
    }


    function hasEagerComputation(node: Node): boolean {
      return subtreeSome(
        node,
        (inner) =>
          inner.type === "NewExpression" ||
          inner.type === "TaggedTemplateExpression" ||
          (inner.type === "CallExpression" && !isSchemaConstruction(inner)),
        true,
      );
    }

    function isCovered(node: ESTree.CallExpression): boolean {
      let current = parentOf(node);
      while (current !== null) {
        if (
          current !== node &&
          current.type === "CallExpression" &&
          isZodCall(current) &&
          current.callee.type === "MemberExpression" &&
          propertyNameIn(current.callee, factories)
        ) {
          return true;
        }
        if (
          current.type === "CallExpression" &&
          ((current.callee.type === "Identifier" && memoCallees.has(current.callee.name)) ||
            (current.callee.type === "MemberExpression" && propertyNameIn(current.callee, memoCallees)))
        ) {
          return true;
        }
        current = parentOf(current);
      }
      return false;
    }

    function outermostSchemaExpression(expression: Node): Node {
      let confirmed = expression;
      let current = expression;
      for (;;) {
        const parent = parentOf(current);
        if (parent === null) return confirmed;
        if (
          (parent.type === "Property" && parent.value === current) ||
          parent.type === "ObjectExpression" ||
          parent.type === "ArrayExpression"
        ) {
          current = parent;
          continue;
        }
        if (
          parent.type === "CallExpression" &&
          (parent.arguments as readonly Node[]).includes(current) &&
          isSchemaComposition(parent)
        ) {
          current = schemaExpression(parent);
          confirmed = current;
          continue;
        }
        return confirmed;
      }
    }

    /** A `z.*(…)` call, or a Zod combinator method applied to an existing schema. */
    function isSchemaComposition(node: ESTree.CallExpression): boolean {
      const callee = unwrapExpression(node.callee);
      const isCombinator =
        callee.type === "MemberExpression" && ZOD_COMBINATOR_METHODS.has(getPropertyName(callee) ?? "");
      return isCombinator || isZodCall(node);
    }

    const isZodNamespace = (identifier: Reference["identifier"]): boolean => zodNamespaces.has(identifier.name);

    return {
      before() {
        const options = context.options[0] as Options | undefined;
        factories = new Set(options?.factories ?? DEFAULT_FACTORIES);
        const ignoreTestFiles = options?.ignoreTestFiles ?? true;
        memoCallees = new Set(options?.memoCallees ?? MEMO_CALLEES);
        minProperties = options?.minProperties ?? DEFAULT_MIN_PROPERTIES;
        zodNamespaces.clear();
        const file = { filename: context.filename, cwd: context.cwd };
        if (isGeneratedFile(file, context.sourceCode.text)) return false;
        if (ignoreTestFiles && isTestFile(file)) return false;
        return undefined;
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportNamespaceSpecifier" ||
            specifier.type === "ImportDefaultSpecifier" ||
            (specifier.type === "ImportSpecifier" && importSpecifierName(specifier) === "z")
          ) {
            zodNamespaces.add(specifier.local.name);
          }
        }
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (zodNamespaces.size === 0 || !isZodCall(node)) return;
        const callee = unwrapExpression(node.callee) as ESTree.MemberExpression;
        const factory = getPropertyName(callee);
        if (factory === null || !factories.has(factory)) return;
        const enclosing = outermostEnclosingFunction(node);
        if (enclosing === undefined) return;
        if (isCovered(node)) return;
        const shape = node.arguments[0];
        if (shape !== undefined && shape.type === "ObjectExpression" && shape.properties.length < minProperties) return;
        if (!isHoistable(schemaExpression(node), enclosing)) return;
        context.report({
          node,
          messageId: "hoistSchema",
          data: { factory: `z.${factory}`, owner: ownerName(enclosing) },
        });
      },
    };
  },
});
