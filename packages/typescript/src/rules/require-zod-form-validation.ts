/**
 * @fileoverview require-zod-form-validation — `formData.get(k)` hands back an attacker-controlled `FormDataEntryValue | null`.
 *
 * Port of the 18.x `require-zod-form-validation` rule. The rule is
 * untyped, so the port covers all of it.
 */

import { defineRule, type ESTree, type Node, type Scope, type TsVariable } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { isZodModule, ZOD_SCHEMA_NAME_RE } from "../utils/zod.js";

const NAME = "require-zod-form-validation";

type Identifier = Extract<Node, { type: "Identifier" }>;

const ZOD_PARSE_METHODS: ReadonlySet<string> = new Set([
  "parse",
  "safeParse",
  "parseAsync",
  "safeParseAsync",
]);
const FORM_VALUE_METHODS: ReadonlySet<string> = new Set(["get", "getAll"]);
const COERCION_FUNCTIONS: ReadonlySet<string> = new Set(["Number", "String", "Boolean"]);
/** Calls and functions past which a form value no longer reaches an enclosing parse unchanged. */
const OPAQUE_FORM_VALUE_BOUNDARIES: ReadonlySet<string> = new Set([
  "CallExpression",
  "NewExpression",
  "TaggedTemplateExpression",
  "ArrowFunctionExpression",
  "FunctionExpression",
  "FunctionDeclaration",
]);
/** Initializers that are provably ordinary values, never Zod schemas. */
const PLAIN_VALUE_INITIALIZERS: ReadonlySet<string> = new Set([
  "ObjectExpression",
  "ArrayExpression",
  "Literal",
  "ArrowFunctionExpression",
  "FunctionExpression",
]);

/** Recognize the supported Zod receiver naming conventions. */
const zodReceiverRoot = (node: Node): Identifier | null => {
  let current: Node = node;
  while (true) {
    if (current.type === "Identifier") {
      return current;
    }
    if (current.type === "CallExpression") {
      current = current.callee;
      continue;
    }
    if (current.type === "MemberExpression") {
      current = current.object;
      continue;
    }
    return null;
  }
};

/** Match an optionally awaited `<x>.formData()` call. */
const isFormDataMethodCall = (node: Node): boolean => {
  let current: Node = node;
  if (current.type === "AwaitExpression") {
    current = current.argument;
  }
  if (current.type !== "CallExpression") return false;
  const callee = unwrapExpression(current.callee);
  return (
    callee.type === "MemberExpression" &&
    getPropertyName(callee) === "formData"
  );
};

/** `node instanceof File` or `node instanceof Blob`. */
function fileInstanceofTest(node: Node): ESTree.BinaryExpression | null {
  const parent = parentOf(node);
  return parent?.type === "BinaryExpression" && parent.operator === "instanceof" && parent.left === node &&
    parent.right.type === "Identifier" && (parent.right.name === "File" || parent.right.name === "Blob")
    ? parent
    : null;
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Require Zod validation (`Schema.parse(...)` / `Schema.safeParse(...)`) when reading values out of a `FormData` object.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      missingZodValidation:
        "FormData parsing must use Zod schema validation (e.g., Schema.parse() / Schema.safeParse())",
    },
  },
  createOnce(context) {
    let zodBindings = new Set<TsVariable>();

    const resolvedBinding = (
      identifier: Identifier,
    ): TsVariable | null =>
      findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );

    const isFormDataGetCall = (node: ESTree.CallExpression): boolean => {
      const callee = unwrapExpression(node.callee);
      if (callee.type !== "MemberExpression" || !FORM_VALUE_METHODS.has(getPropertyName(callee) ?? "")) return false;
      return isFormSourceIdentifier(callee.object);
    };

    // Recognize conventional names and bindings initialized by `.formData()`.
    const isFormSourceIdentifier = (node: Node): boolean => {
      node = unwrapExpression(node);
      if (node.type !== "Identifier") return false;
      const conventionalName = /formdata/i.test(node.name);

      let scope: Scope | null = context.sourceCode.getScope(node);
      while (scope !== null) {
        const variable = scope.set.get(node.name);
        if (variable !== undefined && variable.defs.length === 1) {
          const def = variable.defs[0];
          if (
            def !== undefined &&
            def.type === "Variable" &&
            def.node.type === "VariableDeclarator" &&
            def.node.init !== null
          ) {
            return isFormDataMethodCall(def.node.init);
          }
          return def?.type === "Parameter" && conventionalName;
        }
        scope = scope.upper;
      }
      return conventionalName;
    };

    const zodParseAncestor = (
      node: Node,
    ): ESTree.CallExpression | null => {
      for (let parent = parentOf(node); parent !== null; parent = parentOf(parent)) {
        if (isZodParseCall(parent)) return parent as ESTree.CallExpression;
        if (isFormValueConversion(parent)) continue;
        if (OPAQUE_FORM_VALUE_BOUNDARIES.has(parent.type)) return null;
      }
      return null;
    };

    /** `Number(value)` and `Object.fromEntries(formData)` on the global bindings keep the form value flowing to a parse. */
    const isFormValueConversion = (node: Node): boolean => {
      if (node.type !== "CallExpression") return false;
      const { callee } = node;
      if (callee.type === "Identifier") {
        return COERCION_FUNCTIONS.has(callee.name) && node.arguments.length === 1 && isGlobal(callee);
      }
      return callee.type === "MemberExpression" && callee.object.type === "Identifier" && callee.object.name === "Object" &&
        getPropertyName(callee) === "fromEntries" && isGlobal(callee.object);
    };

    const isGlobal = (identifier: Identifier): boolean => (resolvedBinding(identifier)?.defs.length ?? 0) === 0;

    const isZodParseCall = (node: Node): boolean => {
      if (node.type !== "CallExpression") return false;
      const callee = unwrapExpression(node.callee);
      if (callee.type !== "MemberExpression" || !ZOD_PARSE_METHODS.has(getPropertyName(callee) ?? "")) return false;
      const root = zodReceiverRoot(unwrapExpression(callee.object));
      if (root === null) return false;
      const binding = resolvedBinding(root);
      return (
        (binding !== null && zodBindings.has(binding)) ||
        ((root.name === "z" || ZOD_SCHEMA_NAME_RE.test(root.name)) &&
          !isProvablyNonZodLocal(root))
      );
    };

    /** Reject only bindings that are provably ordinary values; imported schemas remain supported. */
    const isProvablyNonZodLocal = (identifier: Identifier): boolean => {
      const binding = resolvedBinding(identifier);
      if (binding === null || zodBindings.has(binding) || binding.defs.length !== 1) {
        return false;
      }
      const definition = binding.defs[0];
      if (
        definition?.type !== "Variable" ||
        definition.node.type !== "VariableDeclarator"
      ) {
        return false;
      }
      const init = definition.node.init;
      return init !== null && PLAIN_VALUE_INITIALIZERS.has(init.type);
    };


    /** The identifier this `.get(...)` call is bound to, or null. */
    const boundDeclarator = (
      node: ESTree.CallExpression,
    ): ESTree.VariableDeclarator | null => {
      let current: Node = node;
      let parent = current.parent;
      while (
        (parent.type === "TSAsExpression" ||
          parent.type === "TSSatisfiesExpression" ||
          parent.type === "TSNonNullExpression" ||
          parent.type === "ChainExpression") &&
        parent.expression === current
      ) {
        current = parent;
        parent = current.parent;
      }
      if (
        parent.type === "VariableDeclarator" &&
        parent.init === current &&
        parent.id.type === "Identifier"
      ) {
        return parent;
      }
      return null;
    };

    const containingStatement = (
      node: Node,
    ): ESTree.Statement | null => {
      let current = node;
      for (let parent = parentOf(current); parent !== null; parent = parentOf(current)) {
        if (parent.type === "BlockStatement" || parent.type === "Program") return current as ESTree.Statement;
        current = parent;
      }
      return null;
    };

    /** Return an unconditional, success-guaranteeing validation statement. */
    const guaranteedValidationStatement = (
      declarator: ESTree.VariableDeclarator,
      reference: Identifier,
    ): ESTree.Statement | null => {
      const parse = zodParseAncestor(reference);
      if (parse === null) return null;
      const declarationStatement = containingStatement(declarator);
      const validationStatement = containingStatement(parse);
      if (
        declarationStatement === null ||
        validationStatement === null ||
        declarationStatement.parent !== validationStatement.parent ||
        validationStatement.range[0] <= declarationStatement.range[1] ||
        hasConditionalAncestorBeforeStatement(parse, validationStatement)
      ) {
        return null;
      }
      if (
        validationStatement.type !== "VariableDeclaration" &&
        validationStatement.type !== "ExpressionStatement"
      ) {
        return null;
      }
      const method = zodParseMethod(parse);
      if (method === "parse") return validationStatement;
      if (
        method === "parseAsync" &&
        isAwaitedBeforeStatement(parse, validationStatement)
      ) {
        return validationStatement;
      }
      return null;
    };

    const isAwaitedBeforeStatement = (
      node: Node,
      statement: ESTree.Statement,
    ): boolean => {
      for (let current = parentOf(node); current !== null && current !== statement; current = parentOf(current)) {
        if (current.type === "AwaitExpression") return true;
      }
      return false;
    };

    const hasConditionalAncestorBeforeStatement = (
      node: Node,
      statement: ESTree.Statement,
    ): boolean => {
      for (let current = parentOf(node); current !== null && current !== statement; current = parentOf(current)) {
        if (current.type === "LogicalExpression" || current.type === "ConditionalExpression") return true;
      }
      return false;
    };

    const zodParseMethod = (
      call: ESTree.CallExpression,
    ): string | null => {
      const callee = unwrapExpression(call.callee);
      return callee.type === "MemberExpression" ? getPropertyName(callee) : null;
    };

    const isSafePrevalidationInspection = (
      identifier: Identifier,
    ): boolean => {
      const parent = identifier.parent;
      if (
        parent.type === "UnaryExpression" &&
        parent.operator === "typeof"
      ) {
        return true;
      }
      if (
        parent.type !== "BinaryExpression" ||
        parent.left !== identifier
      ) {
        return false;
      }
      if (parent.operator === "instanceof") return fileInstanceofTest(identifier) !== null;
      return (
        ["===", "!==", "==", "!="].includes(parent.operator) &&
        ((parent.right.type === "Literal" &&
          parent.right.value === null) ||
          (parent.right.type === "Identifier" &&
            parent.right.name === "undefined"))
      );
    };

    const isDescendantOf = (node: Node, ancestor: Node): boolean => {
      for (let current: Node | null = node; current !== null; current = parentOf(current)) {
        if (current === ancestor) return true;
      }
      return false;
    };

    const blockTerminates = (node: ESTree.Statement): boolean => {
      if (node.type === "ReturnStatement" || node.type === "ThrowStatement") {
        return true;
      }
      if (node.type !== "BlockStatement" || node.body.length === 0) return false;
      const last = node.body.at(-1);
      return last !== undefined && blockTerminates(last);
    };

    const narrowingIf = (
      identifier: Identifier,
    ): { readonly branch: ESTree.IfStatement; readonly positive: boolean } | null => {
      const comparison = fileInstanceofTest(identifier);
      if (comparison === null) return null;
      const maybeNegation = comparison.parent;
      const negated =
        maybeNegation.type === "UnaryExpression" &&
        maybeNegation.operator === "!";
      const test = negated ? maybeNegation : comparison;
      const branch = test.parent;
      return branch.type === "IfStatement" && branch.test === test
        ? { branch, positive: !negated }
        : null;
    };

    const useDominatedByNarrowing = (
      use: Identifier,
      narrowings: readonly { readonly branch: ESTree.IfStatement; readonly positive: boolean }[],
    ): boolean =>
      narrowings.some(({ branch, positive }) => {
        if (positive) return isDescendantOf(use, branch.consequent);
        if (!blockTerminates(branch.consequent)) return false;
        const branchStatement = containingStatement(branch);
        const useStatement = containingStatement(use);
        return (
          branchStatement !== null &&
          useStatement !== null &&
          branchStatement.parent === useStatement.parent &&
          branchStatement.range[1] < useStatement.range[0]
        );
      });

    /** Find the statement directly owned by `block` that contains `node`. */
    const statementWithinBlock = (
      node: Node,
      block: Node,
    ): ESTree.Statement | null => {
      let current = node;
      for (let parent = parentOf(current); parent !== null; parent = parentOf(current)) {
        if (parent === block) return current as ESTree.Statement;
        current = parent;
      }
      return null;
    };

    /** Is every consuming use either validated itself or dominated by a successful parse? */
    const bindingIsValidated = (
      declarator: ESTree.VariableDeclarator,
    ): boolean => {
      const variable = context.sourceCode.getDeclaredVariables(declarator)[0];
      if (variable === undefined) return false;
      const references = variable.references
        .filter((reference) => !reference.isWriteOnly())
        .map((reference) => reference.identifier)
        .filter(
          (identifier) =>
            identifier.type === "Identifier",
        );
      if (references.length === 0) return false;
      const narrowings = references
        .map(narrowingIf)
        .filter(
          (value) =>
            value !== null,
        );
      const validationStatements = references
        .map((reference) => guaranteedValidationStatement(declarator, reference))
        .filter(
          (statement) => statement !== null,
        );
      const declarationStatement = containingStatement(declarator);
      const declarationBlock = declarationStatement?.parent;
      return references.every((reference) => {
        if (
          zodParseAncestor(reference) !== null ||
          isSafePrevalidationInspection(reference) ||
          useDominatedByNarrowing(reference, narrowings)
        ) {
          return true;
        }
        if (declarationBlock === undefined) return false;
        const useStatement = statementWithinBlock(reference, declarationBlock);
        return (
          useStatement !== null &&
          validationStatements.some(
            (statement) => statement.range[1] < useStatement.range[0],
          )
        );
      });
    };

    return {
      before() {
        if (isTestFile({ filename: context.filename, cwd: context.cwd })) return false;
        zodBindings = new Set<TsVariable>();
        return undefined;
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportNamespaceSpecifier" ||
            specifier.type === "ImportDefaultSpecifier" ||
            (specifier.type === "ImportSpecifier" &&
              importSpecifierName(specifier) === "z")
          ) {
            const binding = resolvedBinding(specifier.local);
            if (binding !== null) zodBindings.add(binding);
          }
        }
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (!isFormDataGetCall(node)) return;

        if (zodParseAncestor(node) !== null || fileInstanceofTest(node) !== null) return;

        const declarator = boundDeclarator(node);
        if (declarator !== null && bindingIsValidated(declarator)) return;

        context.report({
          node,
          messageId: "missingZodValidation",
        });
      },
    };
  },
});
