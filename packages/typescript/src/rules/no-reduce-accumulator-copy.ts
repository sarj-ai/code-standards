/**
 * @fileoverview no-reduce-accumulator-copy — review copying of growing collection accumulators.
 *
 * Port of the 18.x `no-reduce-accumulator-copy` rule. Typed: the
 * original needs a program to prove the call resolves to the built-in
 * `Array`/`ReadonlyArray` reduce, and returns no visitors without one. Types
 * come from tsrs only; when `tsrsServices` is null (types off, tsrs missing or
 * failed) `before()` skips the file, as the original does without a program.
 *
 * The walk applies every untyped condition and keeps the calls that pass;
 * `Program:exit` resolves their signatures in one batch, then inspects the
 * callbacks whose signature is the library one, as the original does in the
 * same order per call.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { tsVariable } from "../types.js";
import { forEachAstChild, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { enclosingFunction, stableConstInitializer, typeOnlyReference } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import type { TsrsFile, TsrsNode, TsrsNodeHandle, TsrsRequest, TsrsServices } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";
import { literalIdentityReduceFix, type ReduceFix } from "./_literal-identity-reduce-fix.js";

const NAME = "no-reduce-accumulator-copy";

const COPY_METHODS: ReadonlySet<string> = new Set(["concat", "slice", "toSpliced", "toSorted", "toReversed", "with"]);
const REDUCE_METHODS: ReadonlySet<string> = new Set(["reduce", "reduceRight"]);
const ARRAY_INTERFACES: ReadonlySet<string> = new Set(["Array", "ReadonlyArray"]);
const BOUNDARIES: ReadonlySet<string> = new Set([
  "ArrowFunctionExpression", "FunctionExpression", "FunctionDeclaration", "ClassDeclaration", "ClassExpression",
  "ForStatement", "ForInStatement", "ForOfStatement", "WhileStatement", "DoWhileStatement",
]);

type Callback = ESTree.ArrowFunctionExpression | ESTree.Function;

interface Candidate {
  readonly node: ESTree.CallExpression;
  readonly callback: Callback;
  readonly accumulator: TsVariable;
  readonly arraySeed: boolean;
}

interface ResolvedDeclaration {
  readonly kind: number;
  readonly parent?: { readonly kind: number; readonly name?: { readonly text?: string } } | undefined;
}
interface TsrsSignature {
  readonly declaration?: (TsrsNodeHandle & { readonly index: number; resolve: { gen(): TsrsRequest<ResolvedDeclaration | undefined> } }) | undefined;
}
interface SignatureChecker {
  readonly getResolvedSignature: { gen(node: TsrsNode): TsrsRequest<TsrsSignature | undefined> };
}

// Library declarations do not change during a run: whether one is a member of Array/ReadonlyArray, by path and index.
const ARRAY_MEMBER = new Map<string, boolean>();

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Review copies of the accumulated collection inside a built-in reduce callback.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      copy: "This reduce callback copies its accumulated collection. If it grows each iteration, use a direct transformation or append to a fresh local accumulator; preserve snapshot and callback semantics.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let tsrs: TsrsServices | null = null;
    let candidates: Candidate[] = [];

    /** Which empty collection literal the reduce seed resolves to, if any. */
    function emptySeed(argument: Node | undefined): "array" | "object" | null {
      const seed = argument === undefined ? null : seedValue(argument);
      if (seed?.type === "ArrayExpression") return seed.elements.length === 0 ? "array" : null;
      return seed?.type === "ObjectExpression" && seed.properties.length === 0 ? "object" : null;
    }

    function seedValue(value: Node, seen = new Set<Node>()): Node | null {
      value = unwrapExpression(value);
      if (seen.has(value)) return null;
      seen.add(value);
      if (value.type !== "Identifier") return value;
      const local = stableConstInitializer(sourceCode, value);
      if (local === null || !local.variable.references.every((reference) => reference.init === true ||
        typeOnlyReference(reference) || reference.identifier === value)) return null;
      return seedValue(local.value, seen);
    }

    /** The callback's identifier accumulator parameter, when the callback never reassigns it. */
    function unwrittenAccumulator(callback: Callback): TsVariable | null {
      const parameter = callback.params[0];
      if (parameter?.type !== "Identifier") return null;
      const found = sourceCode.getDeclaredVariables(callback).find((variable) => variable.identifiers.includes(parameter as never));
      return !found || found.references.some((reference) => reference.isWrite()) ? null : tsVariable(found);
    }

    /** Whether each candidate's resolved signature is a default-library Array/ReadonlyArray member. */
    function libraryReduce(file: TsrsFile): boolean[] {
      const checker = file.checker as unknown as SignatureChecker;
      const nodes = candidates.map((candidate) => file.tsNode(candidate.node));
      const present = nodes.filter((node) => node !== undefined);
      const signatures = file.batch(present.map((node) => checker.getResolvedSignature.gen(node)));
      let next = 0;
      const declarations = nodes.map((node) => node === undefined ? undefined : signatures[next++]?.declaration);
      const library = declarations.map((declaration) => declaration !== undefined &&
        file.isDefaultLibrarySymbol({ name: "", flags: 0, declarations: [declaration] }));
      const keyOf = (declaration: NonNullable<TsrsSignature["declaration"]>) => `${declaration.path}#${declaration.index}`;
      const unresolved = [...new Map(declarations.flatMap((declaration, i) =>
        declaration !== undefined && library[i] === true && !ARRAY_MEMBER.has(keyOf(declaration))
          ? [[keyOf(declaration), declaration] as const] : [])).values()];
      const resolved = file.batch(unresolved.map((declaration) => declaration.resolve.gen()));
      const kind = file.ast.SyntaxKind.InterfaceDeclaration;
      unresolved.forEach((declaration, i) => {
        const parent = resolved[i]?.parent;
        ARRAY_MEMBER.set(keyOf(declaration), parent?.kind === kind && ARRAY_INTERFACES.has(parent.name?.text ?? ""));
      });
      return declarations.map((declaration, i) => library[i] === true && ARRAY_MEMBER.get(keyOf(declaration!)) === true);
    }

    function inspectCandidate({ node, callback, accumulator, arraySeed }: Candidate): void {
      const fix: ReduceFix | null = literalIdentityReduceFix(sourceCode, node);
      const referencesAccumulator = (value: Node, seen = new Set<Node>()): boolean => {
        value = unwrapExpression(value);
        if (value.type !== "Identifier" || seen.has(value)) return false;
        seen.add(value);
        if (findVariable(sourceCode.getScope(value), value.name) === accumulator) return true;
        const local = stableConstInitializer(sourceCode, value);
        return local !== null && enclosingFunction(local.declaration) === callback && referencesAccumulator(local.value, seen);
      };
      const inspect = (current: Node): void => {
        if (current !== callback.body && BOUNDARIES.has(current.type)) return;
        if (current.type === "SpreadElement" &&
          current.parent.type === (arraySeed ? "ArrayExpression" : "ObjectExpression") &&
          referencesAccumulator(current.argument)) {
          context.report(fix === null ? { node: current, messageId: "copy" } : { node: current, messageId: "copy", fix });
        }
        if (current.type === "CallExpression") inspectCall(current);
        forEachAstChild(current, sourceCode.visitorKeys, inspect);
      };
      const inspectCall = (current: ESTree.CallExpression): void => {
        if (current.callee.type !== "MemberExpression") return;
        const member = current.callee;
        const name = getPropertyName(member);
        if (arraySeed ? copiesArray(member, name, current.arguments[0]) : assignsObject(member, name, current.arguments)) {
          context.report({ node: current, messageId: "copy" });
        }
      };
      const copiesArray = (member: ESTree.MemberExpression, name: string | null, first: Node | undefined): boolean =>
        (name !== null && COPY_METHODS.has(name) && referencesAccumulator(member.object)) ||
        (name === "from" && globalName(member.object, "Array") && first !== undefined && referencesAccumulator(first));
      const assignsObject = (member: ESTree.MemberExpression, name: string | null, args: readonly Node[]): boolean =>
        name === "assign" && globalName(member.object, "Object") && args[0]?.type === "ObjectExpression" &&
        args.slice(1).some((argument) => referencesAccumulator(argument));
      const globalName = (object: Node, name: string): boolean =>
        object.type === "Identifier" && object.name === name && !findVariable(sourceCode.getScope(object), name)?.defs.length;
      inspect(callback.body!);
    }

    return {
      before() {
        tsrs = null;
        candidates = [];
        sourceCode = context.sourceCode;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      CallExpression(node) {
        if (node.callee.type !== "MemberExpression" || !REDUCE_METHODS.has(getPropertyName(node.callee) ?? "") ||
          node.arguments.length !== 2) return;
        const [callback, argument] = node.arguments;
        const seed = emptySeed(argument);
        if (seed === null || (callback?.type !== "ArrowFunctionExpression" && callback?.type !== "FunctionExpression")) return;
        // The original resolves the signature here; it is pure, so the scope checks may run first.
        const accumulator = unwrittenAccumulator(callback);
        if (accumulator !== null) candidates.push({ node, callback, accumulator, arraySeed: seed === "array" });
      },
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        const library = tsrs.run((file) => libraryReduce(file));
        if (library === null) return;
        candidates.forEach((candidate, i) => {
          if (library[i] === true) inspectCandidate(candidate);
        });
      },
    };
  },
});
