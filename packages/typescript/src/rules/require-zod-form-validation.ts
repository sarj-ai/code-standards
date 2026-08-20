/**
 * @fileoverview require-zod-form-validation — `formData.get(k)` hands back an attacker-controlled `FormDataEntryValue | null`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-zod-form-validation.test.ts
 */

import {
  type TSESTree,
  AST_NODE_TYPES,
  ASTUtils,
} from "@typescript-eslint/utils";
import type { RuleContext, Scope } from "@typescript-eslint/utils/ts-eslint";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { isZodModule, ZOD_SCHEMA_NAME_RE } from "./_zod.js";

type MessageIds = "missingZodValidation";
type Options = readonly [];

export const requireZodFormValidationDocumentation = {
  summary: "Require Zod validation (`Schema.parse(...)` / `Schema.safeParse(...)`) when reading values out of a `FormData` object.",
  rationale: "FormData values are untrusted strings or files and need runtime validation before use.",
  remediation: "Read the value inside a Zod schema's `parse` or `safeParse` input.",
  category: "security",
  limitations: [
    "Tests are excluded; imported schema-shaped names are trusted when their implementation is outside the linted file.",
    "Delayed raw-value use is accepted only after an unconditional successful parse in the same block; safeParse remains valid when the raw binding has no unvalidated consumer.",
  ],
  examples: [
    { id: "validated-form-value", title: "Validate the form value", outcome: "no-match", files: [{ path: "src/action.ts", source: "const input = UserSchema.parse({ name: formData.get('name') });" }], focusPath: "src/action.ts", expectedCount: 0, public: true },
    { id: "raw-form-value", title: "Do not use a raw form value", outcome: "match", files: [{ path: "src/action.ts", source: "const name = formData.get('name');" }], focusPath: "src/action.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

type Ctx = Readonly<RuleContext<MessageIds, Options>>;
const ZOD_PARSE_METHODS: ReadonlySet<string> = new Set([
  "parse",
  "safeParse",
  "parseAsync",
  "safeParseAsync",
]);
const FORM_VALUE_METHODS: ReadonlySet<string> = new Set(["get", "getAll"]);

/** Recognize the supported Zod receiver naming conventions. */
const zodReceiverRoot = (node: TSESTree.Node): TSESTree.Identifier | null => {
  let current: TSESTree.Node = node;
  while (true) {
    if (current.type === AST_NODE_TYPES.Identifier) {
      return current;
    }
    if (current.type === AST_NODE_TYPES.CallExpression) {
      current = current.callee;
      continue;
    }
    if (current.type === AST_NODE_TYPES.MemberExpression) {
      current = current.object;
      continue;
    }
    return null;
  }
};

/** Match an optionally awaited `<x>.formData()` call. */
const isFormDataMethodCall = (node: TSESTree.Node): boolean => {
  let current: TSESTree.Node = node;
  if (current.type === AST_NODE_TYPES.AwaitExpression) {
    current = current.argument;
  }
  if (current.type !== AST_NODE_TYPES.CallExpression) return false;
  const callee = current.callee;
  return (
    callee.type === AST_NODE_TYPES.MemberExpression &&
    !callee.computed &&
    callee.property.type === AST_NODE_TYPES.Identifier &&
    callee.property.name === "formData"
  );
};

export default createRule<Options, MessageIds>({
  name: "require-zod-form-validation",
  documentation: requireZodFormValidationDocumentation,
  meta: {
    type: "problem",
    docs: {
      description:
        "Require Zod validation (`Schema.parse(...)` / `Schema.safeParse(...)`) when reading values out of a `FormData` object.",
    },
    schema: [],
    messages: {
      missingZodValidation:
        "FormData parsing must use Zod schema validation (e.g., Schema.parse() / Schema.safeParse())",
    },
  },
  defaultOptions: [],
  create(context: Ctx) {
    if (isTestFile(context.filename)) {
      return {};
    }

    const zodBindings = new Set<Scope.Variable>();

    const resolvedBinding = (
      identifier: TSESTree.Identifier,
    ): Scope.Variable | null =>
      ASTUtils.findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );

    /** Reject only bindings that are provably ordinary values; imported schemas remain supported. */
    const isProvablyNonZodLocal = (identifier: TSESTree.Identifier): boolean => {
      const binding = resolvedBinding(identifier);
      if (binding === null || zodBindings.has(binding) || binding.defs.length !== 1) {
        return false;
      }
      const definition = binding.defs[0];
      if (
        definition?.type !== "Variable" ||
        definition.node.type !== AST_NODE_TYPES.VariableDeclarator
      ) {
        return false;
      }
      const init = definition.node.init;
      return (
        init?.type === AST_NODE_TYPES.ObjectExpression ||
        init?.type === AST_NODE_TYPES.ArrayExpression ||
        init?.type === AST_NODE_TYPES.Literal ||
        init?.type === AST_NODE_TYPES.ArrowFunctionExpression ||
        init?.type === AST_NODE_TYPES.FunctionExpression
      );
    };

    const isZodParseCall = (node: TSESTree.Node): boolean => {
      if (node.type !== AST_NODE_TYPES.CallExpression) return false;
      const callee = node.callee;
      if (
        callee.type !== AST_NODE_TYPES.MemberExpression ||
        callee.computed ||
        callee.property.type !== AST_NODE_TYPES.Identifier ||
        !ZOD_PARSE_METHODS.has(callee.property.name)
      ) {
        return false;
      }
      const root = zodReceiverRoot(callee.object);
      if (root === null) return false;
      const binding = resolvedBinding(root);
      return (
        (binding !== null && zodBindings.has(binding)) ||
        ((root.name === "z" || ZOD_SCHEMA_NAME_RE.test(root.name)) &&
          !isProvablyNonZodLocal(root))
      );
    };

    // Recognize conventional names and bindings initialized by `.formData()`.
    const isFormSourceIdentifier = (node: TSESTree.Node): boolean => {
      if (node.type !== AST_NODE_TYPES.Identifier) return false;
      const conventionalName = /formdata/i.test(node.name);

      let scope: Scope.Scope | null = context.sourceCode.getScope(node);
      while (scope !== null) {
        const variable = scope.set.get(node.name);
        if (variable !== undefined && variable.defs.length === 1) {
          const def = variable.defs[0];
          if (
            def !== undefined &&
            def.type === "Variable" &&
            def.node.type === AST_NODE_TYPES.VariableDeclarator &&
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

    const isFormDataGetCall = (node: TSESTree.CallExpression): boolean => {
      const callee = node.callee;
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return false;
      if (
        callee.property.type !== AST_NODE_TYPES.Identifier ||
        !FORM_VALUE_METHODS.has(callee.property.name)
      ) {
        return false;
      }
      return isFormSourceIdentifier(callee.object);
    };

    const zodParseAncestor = (
      node: TSESTree.Node,
    ): TSESTree.CallExpression | null => {
      let parent: TSESTree.Node | null | undefined = node.parent;
      while (parent !== null && parent !== undefined) {
        if (isZodParseCall(parent)) return parent as TSESTree.CallExpression;
        parent = parent.parent;
      }
      return null;
    };

    const hasZodParseAncestor = (node: TSESTree.Node): boolean =>
      zodParseAncestor(node) !== null;

    const isInstanceofNarrowing = (node: TSESTree.Node): boolean => {
      const parent: TSESTree.Node | null | undefined = node.parent;
      return (
        parent !== null &&
        parent !== undefined &&
        parent.type === AST_NODE_TYPES.BinaryExpression &&
        parent.operator === "instanceof" &&
        parent.left === node &&
        parent.right.type === AST_NODE_TYPES.Identifier &&
        (parent.right.name === "File" || parent.right.name === "Blob")
      );
    };

    /** The identifier this `.get(...)` call is bound to, or null. */
    const boundDeclarator = (
      node: TSESTree.CallExpression,
    ): TSESTree.VariableDeclarator | null => {
      let current: TSESTree.Node = node;
      let parent = current.parent;
      while (
        (parent.type === AST_NODE_TYPES.TSAsExpression ||
          parent.type === AST_NODE_TYPES.TSSatisfiesExpression ||
          parent.type === AST_NODE_TYPES.TSNonNullExpression ||
          parent.type === AST_NODE_TYPES.ChainExpression) &&
        parent.expression === current
      ) {
        current = parent;
        parent = current.parent;
      }
      if (
        parent.type === AST_NODE_TYPES.VariableDeclarator &&
        parent.init === current &&
        parent.id.type === AST_NODE_TYPES.Identifier
      ) {
        return parent;
      }
      return null;
    };

    const containingStatement = (
      node: TSESTree.Node,
    ): TSESTree.Statement | null => {
      let current = node;
      while (current.parent !== undefined) {
        const parent = current.parent;
        if (
          parent.type === AST_NODE_TYPES.BlockStatement ||
          parent.type === AST_NODE_TYPES.Program
        ) {
          return current as TSESTree.Statement;
        }
        current = parent;
      }
      return null;
    };

    const zodParseMethod = (
      call: TSESTree.CallExpression,
    ): string | null => {
      const callee = call.callee;
      return callee.type === AST_NODE_TYPES.MemberExpression &&
        !callee.computed &&
        callee.property.type === AST_NODE_TYPES.Identifier
        ? callee.property.name
        : null;
    };

    const hasConditionalAncestorBeforeStatement = (
      node: TSESTree.Node,
      statement: TSESTree.Statement,
    ): boolean => {
      let current = node.parent;
      while (current !== undefined && current !== statement) {
        if (
          current.type === AST_NODE_TYPES.LogicalExpression ||
          current.type === AST_NODE_TYPES.ConditionalExpression
        ) {
          return true;
        }
        current = current.parent;
      }
      return false;
    };

    const isAwaitedBeforeStatement = (
      node: TSESTree.Node,
      statement: TSESTree.Statement,
    ): boolean => {
      let current = node.parent;
      while (current !== undefined && current !== statement) {
        if (current.type === AST_NODE_TYPES.AwaitExpression) return true;
        current = current.parent;
      }
      return false;
    };

    /** Return an unconditional, success-guaranteeing validation statement. */
    const guaranteedValidationStatement = (
      declarator: TSESTree.VariableDeclarator,
      reference: TSESTree.Identifier,
    ): TSESTree.Statement | null => {
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
        validationStatement.type !== AST_NODE_TYPES.VariableDeclaration &&
        validationStatement.type !== AST_NODE_TYPES.ExpressionStatement
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

    const isSafePrevalidationInspection = (
      identifier: TSESTree.Identifier,
    ): boolean => {
      const parent = identifier.parent;
      if (
        parent.type === AST_NODE_TYPES.UnaryExpression &&
        parent.operator === "typeof"
      ) {
        return true;
      }
      if (
        parent.type !== AST_NODE_TYPES.BinaryExpression ||
        parent.left !== identifier
      ) {
        return false;
      }
      if (parent.operator === "instanceof") {
        return (
          parent.right.type === AST_NODE_TYPES.Identifier &&
          (parent.right.name === "File" || parent.right.name === "Blob")
        );
      }
      return (
        ["===", "!==", "==", "!="].includes(parent.operator) &&
        ((parent.right.type === AST_NODE_TYPES.Literal &&
          parent.right.value === null) ||
          (parent.right.type === AST_NODE_TYPES.Identifier &&
            parent.right.name === "undefined"))
      );
    };

    const isDescendantOf = (node: TSESTree.Node, ancestor: TSESTree.Node): boolean => {
      let current: TSESTree.Node | null | undefined = node;
      while (current !== undefined && current !== null) {
        if (current === ancestor) return true;
        current = current.parent;
      }
      return false;
    };

    const blockTerminates = (node: TSESTree.Statement): boolean => {
      if (node.type === AST_NODE_TYPES.ReturnStatement || node.type === AST_NODE_TYPES.ThrowStatement) {
        return true;
      }
      if (node.type !== AST_NODE_TYPES.BlockStatement || node.body.length === 0) return false;
      const last = node.body.at(-1);
      return last !== undefined && blockTerminates(last);
    };

    const narrowingIf = (
      identifier: TSESTree.Identifier,
    ): { readonly branch: TSESTree.IfStatement; readonly positive: boolean } | null => {
      const comparison = identifier.parent;
      if (
        comparison?.type !== AST_NODE_TYPES.BinaryExpression ||
        comparison.operator !== "instanceof" ||
        comparison.left !== identifier ||
        comparison.right.type !== AST_NODE_TYPES.Identifier ||
        (comparison.right.name !== "File" && comparison.right.name !== "Blob")
      ) {
        return null;
      }
      const maybeNegation = comparison.parent;
      const negated =
        maybeNegation?.type === AST_NODE_TYPES.UnaryExpression &&
        maybeNegation.operator === "!";
      const test = negated ? maybeNegation : comparison;
      const branch = test.parent;
      return branch?.type === AST_NODE_TYPES.IfStatement && branch.test === test
        ? { branch, positive: !negated }
        : null;
    };

    const useDominatedByNarrowing = (
      use: TSESTree.Identifier,
      narrowings: readonly { readonly branch: TSESTree.IfStatement; readonly positive: boolean }[],
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
      node: TSESTree.Node,
      block: TSESTree.Node,
    ): TSESTree.Statement | null => {
      let current = node;
      while (current.parent !== undefined && current.parent !== block) {
        current = current.parent;
      }
      return current.parent === block ? (current as TSESTree.Statement) : null;
    };

    /** Is every consuming use either validated itself or dominated by a successful parse? */
    const bindingIsValidated = (
      declarator: TSESTree.VariableDeclarator,
    ): boolean => {
      const variable = context.sourceCode.getDeclaredVariables(declarator)[0];
      if (variable === undefined) return false;
      const references = variable.references
        .filter((reference) => !reference.isWriteOnly())
        .map((reference) => reference.identifier)
        .filter(
          (identifier): identifier is TSESTree.Identifier =>
            identifier.type === AST_NODE_TYPES.Identifier,
        );
      if (references.length === 0) return false;
      const narrowings = references
        .map(narrowingIf)
        .filter(
          (value): value is { readonly branch: TSESTree.IfStatement; readonly positive: boolean } =>
            value !== null,
        );
      const validationStatements = references
        .map((reference) => guaranteedValidationStatement(declarator, reference))
        .filter(
          (statement): statement is TSESTree.Statement => statement !== null,
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
      ImportDeclaration(node: TSESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
            (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
              (specifier.imported.type === AST_NODE_TYPES.Identifier
                ? specifier.imported.name === "z"
                : specifier.imported.value === "z"))
          ) {
            const binding = resolvedBinding(specifier.local);
            if (binding !== null) zodBindings.add(binding);
          }
        }
      },
      CallExpression(node: TSESTree.CallExpression): void {
        if (!isFormDataGetCall(node)) return;

        if (hasZodParseAncestor(node) || isInstanceofNarrowing(node)) return;

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
