/**
 * @fileoverview no-growing-array-spread-in-loop — review repeated copies of a growing local array in loops.
 *
 * The rule needs a TypeScript program to prove the copied binding and the loop
 * input are arrays. tsrs (`tsrsServices`) provides one when type-aware linting
 * is on; otherwise `before()` skips the file, as the original returns no
 * visitors without `parserServices.program`. The type-aware check comes first,
 * so untyped runs skip the generated-file check and whole-tree `eval` scan the
 * original runs before it (neither can change the result).
 *
 * The walk applies every untyped condition and keeps the assignments that pass;
 * `Program:exit` asks whether both bindings are arrays in one batch, after the
 * original's whole-tree `eval` scan, which only files with candidates now pay
 * for. The original checks are pure, so their order does not change the
 * reports.
 */
import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { enclosingFunction, stableConstInitializer, typeOnlyReference } from "../utils/stable-value-binding.js";
import { findVariable } from "../utils/static-string.js";
import { type TsrsFile, tsrsServices, type TsrsServices } from "../utils/tsrs-services.js";
import { hasIdentifierNamed } from "../utils/unused-private-binding.js";

type Identifier = Extract<Node, { type: "Identifier" }>;

function nearestLoop(node: Node): Node | null {
  const owner = enclosingFunction(node);
  for (let current = parentOf(node); current !== null && current !== owner; current = parentOf(current)) {
    if (current.type === "ForOfStatement" || current.type === "ForInStatement" || current.type === "ForStatement" ||
      current.type === "WhileStatement" || current.type === "DoWhileStatement") return current;
  }
  return null;
}

interface PrefixCopy {
  readonly left: Identifier;
  readonly prefix: ESTree.SpreadElement;
  readonly copied: Identifier;
}

/** `name = [...copied, item, ...]`: one leading spread followed by plain elements. */
function prefixCopy(node: ESTree.AssignmentExpression): PrefixCopy | null {
  if (node.operator !== "=" || node.left.type !== "Identifier") return null;
  const value = unwrapExpression(node.right);
  if (value.type !== "ArrayExpression" || value.elements.length < 2) return null;
  const prefix = value.elements[0];
  if (prefix?.type !== "SpreadElement" ||
    value.elements.slice(1).some((element) => element === null || element.type === "SpreadElement")) return null;
  const copied = unwrapExpression(prefix.argument);
  return copied.type === "Identifier" ? { left: node.left, prefix, copied } : null;
}

/** A private `let name = []` declarator. */
function emptyLetArray(definition: Node | undefined): ESTree.VariableDeclarator | null {
  if (definition?.type !== "VariableDeclarator") return null;
  const declaration = parentOf(definition) as ESTree.VariableDeclaration;
  return definition.id.type === "Identifier" && declaration.kind === "let" &&
    parentOf(declaration)?.type !== "ExportNamedDeclaration" &&
    definition.init?.type === "ArrayExpression" && definition.init.elements.length === 0 ? definition : null;
}

function soleStatement(body: ESTree.Statement): Node | undefined {
  if (body.type !== "BlockStatement") return body;
  return body.body.length === 1 ? body.body[0] : undefined;
}

/** Only the loop writes the array, and it is read only after the loop in the same function. */
function onlyGrownHere(variable: TsVariable, { left, copied }: PrefixCopy, definition: Node, loop: Node): boolean {
  const owner = enclosingFunction(definition);
  return variable.references.every((reference) => {
    if (reference.init === true || typeOnlyReference(reference)) return true;
    if (reference.isWrite()) return reference.identifier === left;
    if (reference.identifier === copied) return true;
    const parent = parentOf(reference.identifier);
    return parent?.type !== "ExportSpecifier" && parent?.type !== "ExportDefaultDeclaration" &&
      reference.identifier.range[0] >= loop.range[1] && enclosingFunction(reference.identifier) === owner;
  });
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Review repeated prefix copies of a growing fresh local array inside a loop.",
      url: docsUrl("no-growing-array-spread-in-loop"),
    },
    schema: [],
    messages: {
      copy: "This loop copies the growing array prefix. Consider appending into its fresh local output; preserve retained snapshots and observations.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let tsrs: TsrsServices | null = null;
    /** Reports that wait for `left` and `right` to be arrays. */
    let candidates: { readonly prefix: Node; readonly left: Node; readonly right: Node }[] = [];

    /** Whether each node's type is an array, in one tsrs batch. */
    function areArrays(file: TsrsFile, nodes: readonly Node[]): boolean[] {
      const types = file.typesOf(nodes);
      const present = types.filter((type) => type !== undefined);
      const arrays = file.batch(present.map((type) => file.checker.isArrayType.gen(type)));
      let next = 0;
      // A node tsrs cannot map has no type, as the checker's error type is no array.
      return types.map((type) => type !== undefined && arrays[next++] === true);
    }

    function check(node: ESTree.AssignmentExpression): void {
      const copy = prefixCopy(node);
      if (copy === null) return;
      const { left, prefix, copied } = copy;
      const variable = findVariable(sourceCode.getScope(left), left.name);
      if (variable === null || variable.defs.length !== 1 || variable.scope.type === "global" ||
        findVariable(sourceCode.getScope(copied), copied.name) !== variable) return;
      const definition = emptyLetArray(variable.defs[0]?.node);
      const loop = definition === null ? null : growthLoop(node, definition);
      if (definition !== null && loop !== null && onlyGrownHere(variable, copy, definition, loop)) {
        candidates.push({ prefix, left, right: loop.right });
      }
    }

    /** The later `for...of` over an input of unknown extent whose only statement is this assignment. */
    function growthLoop(node: ESTree.AssignmentExpression, definition: Node): ESTree.ForOfStatement | null {
      const loop = nearestLoop(node);
      if (loop?.type !== "ForOfStatement" || definition.range[1] >= loop.range[0]) return null;
      const body = soleStatement(loop.body);
      return body?.type === "ExpressionStatement" && body.expression === node && inputHasUnknownExtent(loop.right) &&
        loop.right.type !== "ArrayExpression" ? loop : null;
    }

    function inputHasUnknownExtent(node: Node, seen = new Set<Node>()): boolean {
      if (node.type !== "Identifier" || seen.has(node)) return false;
      seen.add(node);
      const variable = findVariable(sourceCode.getScope(node), node.name);
      if (variable === null || variable.defs.length !== 1) return false;
      const definition = variable.defs[0];
      if (definition?.type === "Parameter" || definition?.type === "ImportBinding") return true;
      const local = stableConstInitializer(sourceCode, node);
      if (local !== null) return inputHasUnknownExtent(local.value, seen);
      return definition?.node.type === "VariableDeclarator" && definition.node.init === null;
    }

    return {
      before(): boolean {
        candidates = [];
        tsrs = tsrsServices(context);
        if (tsrs === null) return false;
        sourceCode = context.sourceCode;
        return !isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text);
      },
      AssignmentExpression: check,
      "Program:exit"() {
        // The original skips files that mention `eval`; only files with candidates need the whole-tree scan.
        if (tsrs === null || candidates.length === 0 || hasIdentifierNamed(sourceCode, "eval")) return;
        const arrays = tsrs.run((file) => areArrays(file, candidates.flatMap((candidate) => [candidate.left, candidate.right])));
        if (arrays === null) return;
        candidates.forEach((candidate, i) => {
          if (arrays[2 * i] === true && arrays[2 * i + 1] === true) context.report({ node: candidate.prefix, messageId: "copy" });
        });
      },
    };
  },
});
