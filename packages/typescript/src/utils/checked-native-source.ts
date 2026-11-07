/**
 * @fileoverview checked-native-source — tsrs access for the typed @sarj helpers, and the
 * check that a local implementation is under active native type checking.
 *
 * `nativeTypes` views one file's `tsrsServices` program through the full tsrs checker, program and
 * AST types (`tsrs/ast`, `tsrs/sync`). Syntax kinds, node, type and symbol flags follow TypeScript 7
 * numbering, so always take them from `native.ast` / `native.sync`, never from the `typescript`
 * package.
 *
 * `checkedNativeSource` asks tsrs for the file's syntactic and semantic diagnostics once per
 * program and file, as the original caches them per `ts.Program`.
 */

import type * as TsrsAst from "tsrs/ast";
import type { Checker, NodeHandle, Program, Type } from "tsrs/sync";
import type * as TsrsSync from "tsrs/sync";

import type { Node } from "../types.js";
import { parentOf } from "./ast.js";
import type { TsrsFile } from "./tsrs-services.js";

export type NativeAst = typeof TsrsAst;
export type NativeSync = typeof TsrsSync;
export type TsNode = TsrsAst.Node;

/** One file's tsrs program with the full checker and AST API. */
export interface NativeTypes {
  readonly ast: NativeAst;
  readonly sync: NativeSync;
  readonly file: TsrsFile;
  readonly checker: Checker;
  readonly program: Program;
  readonly source: TsrsAst.SourceFile;
  /** The innermost tsrs node with this ESTree node's range (`TsrsFile.tsNode`). */
  node<T extends TsNode = TsNode>(node: Node): T | undefined;
  /** The outermost tsrs node with this ESTree node's range (`TsrsFile.outerTsNode`): use it for types. */
  outerNode(node: Node): TsNode | undefined;
  /** The innermost ESTree node with this tsrs node's range (`TsrsFile.esTreeNode`). */
  esTreeNode(node: TsNode): Node | undefined;
}

const NATIVE = new WeakMap<TsrsFile, NativeTypes>();

/** The file's tsrs program with the full tsrs types. */
export function nativeTypes(file: TsrsFile): NativeTypes {
  let native = NATIVE.get(file);
  if (native === undefined) {
    native = {
      ast: file.ast,
      sync: file.sync,
      file,
      checker: file.checker as unknown as Checker,
      program: file.program as unknown as Program,
      source: file.sourceFile as unknown as TsrsAst.SourceFile,
      node: <T extends TsNode>(node: Node) => file.tsNode(node) as unknown as T | undefined,
      outerNode: (node: Node) => file.outerTsNode(node) as unknown as TsNode | undefined,
      esTreeNode: (node: TsNode) => file.esTreeNode(node),
    };
    NATIVE.set(file, native);
  }
  return native;
}

/**
 * The tsrs node of a function. typescript-estree maps a method's value function to its
 * MethodDeclaration, whose range starts at the method name, so look that up through the method.
 */
export function functionNode(native: NativeTypes, node: Node): TsNode | undefined {
  const parent = parentOf(node);
  const method = (parent?.type === "MethodDefinition" || parent?.type === "TSAbstractMethodDefinition" ||
    (parent?.type === "Property" && (parent.method || parent.kind !== "init"))) && parent.value === node;
  return native.node(method ? parent : node);
}

/** A union's members, or the type itself. */
export function unionMembers(type: Type): readonly Type[] {
  return type.isUnionType() ? type.getTypes() : [type];
}

/** The declaration node behind a tsrs handle (fetching its file on first use), or undefined. */
export function declarationNode(native: NativeTypes, handle: NodeHandle): TsNode | undefined {
  return handle.resolve(native.program.getProject());
}

const CHECKED = new WeakMap<Program, Map<string, boolean>>();
const SINGLE_LINE_DIRECTIVE = /^\/\/\/?\s*@(?:ts-expect-error|ts-ignore)/u;
const MULTI_LINE_DIRECTIVE = /^[/*]*\s*@(?:ts-expect-error|ts-ignore)/u;
const SINGLE_LINE_PRAGMA = /^\/\/\/?\s*@([^\s:]+)(?:(?:[^\S\r\n]|:).*)?$/mu;

/** Global diagnostics are separate; this checks this file's complete located diagnostics. */
export function checkedNativeSource(native: NativeTypes, source: TsrsAst.SourceFile): boolean {
  const { program, ast, sync } = native;
  let files = CHECKED.get(program);
  if (!files) {
    files = new Map();
    CHECKED.set(program, files);
  }
  const known = files.get(source.fileName);
  if (known !== undefined) return known;
  const references = (program.getProject() as unknown as { readonly parsedCommandLine?: { readonly projectReferences?: readonly unknown[] } })
    .parsedCommandLine?.projectReferences;
  const error = (diagnostic: { readonly category: number; readonly fileName?: string | undefined }) =>
    diagnostic.category === sync.DiagnosticCategory.Error && diagnostic.fileName === source.fileName;
  const available = !program.getCompilerOptions().noCheck && !source.isDeclarationFile &&
    (source.flags & (ast.NodeFlags.JavaScriptFile | ast.NodeFlags.JsonFile)) === 0 &&
    !references?.length &&
    program.getSourceFile(source.fileName) === source && !program.isSourceFileFromExternalLibrary(source) &&
    !program.isSourceFileDefaultLibrary(source) &&
    !program.getSyntacticDiagnostics(source.fileName).some(error) &&
    !checkingSuppressed(source, ast) &&
    !program.getSemanticDiagnostics(source.fileName).some(error);
  files.set(source.fileName, available);
  return available;
}

function checkingSuppressed(source: TsrsAst.SourceFile, ast: NativeAst): boolean {
  if (!/@ts-/iu.test(source.text)) return false;
  // File pragmas are recognized only in the native leading-comment preamble.
  if (ast.getLeadingCommentRanges(source.text, 0)?.some((comment) => comment.kind === ast.SyntaxKind.SingleLineCommentTrivia &&
    SINGLE_LINE_PRAGMA.exec(source.text.slice(comment.pos, comment.end))?.[1]?.toLowerCase() === "ts-nocheck")) return true;
  const pending: TsNode[] = [source];
  while (pending.length) {
    const node = pending.pop();
    if (!node || ast.isJsxText(node) || ast.isJSDoc(node) || (node.flags & ast.NodeFlags.JSDoc) !== 0) continue;
    if (!ast.isToken(node)) {
      for (const child of node.getChildren(source)) pending.push(child);
      continue;
    }
    if (tokenTriviaSuppressesChecking(node, source, ast)) return true;
  }
  return false;
}

/** Inspect only the real token's preceding trivia, including same-line comments. */
function tokenTriviaSuppressesChecking(node: TsNode, source: TsrsAst.SourceFile, ast: NativeAst): boolean {
  const start = node.getStart(source);
  // Never scan from token.end into following JSX or template literal text.
  for (const comment of [...ast.getLeadingCommentRanges(source.text, node.pos) ?? [], ...ast.getTrailingCommentRanges(source.text, node.pos) ?? []]) {
    if (comment.pos < node.pos || comment.end > start) continue;
    if (commentSuppressesChecking(source.text.slice(comment.pos, comment.end), comment.kind, ast)) return true;
  }
  return false;
}

/** Match the native single-line directive or final line of a multiline comment. */
function commentSuppressesChecking(text: string, kind: number, ast: NativeAst): boolean {
  if (kind === ast.SyntaxKind.SingleLineCommentTrivia) return SINGLE_LINE_DIRECTIVE.test(text);
  let lastLine = text.length;
  while (lastLine > 0 && !ast.isLineBreak(text.charCodeAt(lastLine - 1))) lastLine--;
  return MULTI_LINE_DIRECTIVE.test(text.slice(lastLine).trimStart());
}
