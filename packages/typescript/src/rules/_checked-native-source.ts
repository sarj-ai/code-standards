/** @fileoverview _checked-native-source — require active native checking of a local implementation. */
import type { ParserServicesWithTypeInformation, TSESLint } from "@typescript-eslint/utils";
import ts from "typescript";

const CHECKED = new WeakMap<ts.Program, WeakMap<ts.SourceFile, boolean>>();
const SINGLE_LINE_DIRECTIVE = /^\/\/\/?\s*@(?:ts-expect-error|ts-ignore)/u;
const MULTI_LINE_DIRECTIVE = /^[/*]*\s*@(?:ts-expect-error|ts-ignore)/u;
const SINGLE_LINE_PRAGMA = /^\/\/\/?\s*@([^\s:]+)(?:(?:[^\S\r\n]|:).*)?$/mu;

/** Current text is context-specific, including when a supplied Program is reused after a fix. */
export function currentNativeSource(sourceCode: Readonly<TSESLint.SourceCode>, services: ParserServicesWithTypeInformation): ts.SourceFile | null {
  const source = services.esTreeNodeToTSNodeMap.get(sourceCode.ast);
  return ts.isSourceFile(source) && services.program.getSourceFile(source.fileName) === source && source.text === sourceCode.text ? source : null;
}

/** Global diagnostics are separate; this checks this file's complete located diagnostics. */
export function checkedNativeSource(program: ts.Program, source: ts.SourceFile): boolean {
  let files = CHECKED.get(program);
  if (!files) { files = new WeakMap(); CHECKED.set(program, files); }
  const known = files.get(source);
  if (known !== undefined) return known;
  const available = !program.getCompilerOptions().noCheck && !source.isDeclarationFile &&
    (source.flags & (ts.NodeFlags.JavaScriptFile | ts.NodeFlags.JsonFile)) === 0 &&
    !program.getProjectReferences()?.length && !program.getResolvedProjectReferences()?.length &&
    program.getSourceFile(source.fileName) === source && !program.isSourceFileFromExternalLibrary(source) &&
    !program.isSourceFileDefaultLibrary(source) &&
    !program.getSyntacticDiagnostics(source).some((diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error && diagnostic.file === source) &&
    !checkingSuppressed(source) &&
    !program.getSemanticDiagnostics(source).some((diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error && diagnostic.file === source);
  // A full file query completes native deferred checks. No program-wide health
  // result or unlocated/global error state is cached as proof of this file.
  files.set(source, available);
  return available;
}

function checkingSuppressed(source: ts.SourceFile): boolean {
  if (!/@ts-/iu.test(source.text)) return false;
  // File pragmas are recognized only in the native leading-comment preamble.
  if (ts.getLeadingCommentRanges(source.text, 0)?.some((comment) => comment.kind === ts.SyntaxKind.SingleLineCommentTrivia &&
    SINGLE_LINE_PRAGMA.exec(source.text.slice(comment.pos, comment.end))?.[1]?.toLowerCase() === "ts-nocheck")) return true;
  const pending: ts.Node[] = [source];
  while (pending.length) {
    const node = pending.pop();
    if (!node || ts.isJsxText(node) || ts.isJSDoc(node) || (node.flags & ts.NodeFlags.JSDoc) !== 0) continue;
    if (!ts.isToken(node)) { for (const child of node.getChildren(source)) pending.push(child); continue; }
    if (tokenTriviaSuppressesChecking(node, source)) return true;
  }
  return false;
}

/** Inspect only the real token's preceding trivia, including same-line comments. */
function tokenTriviaSuppressesChecking(node: ts.Node, source: ts.SourceFile): boolean {
  const start = node.getStart(source);
  // Never scan from token.end into following JSX or template literal text.
  for (const comment of [...ts.getLeadingCommentRanges(source.text, node.pos) ?? [], ...ts.getTrailingCommentRanges(source.text, node.pos) ?? []]) {
    if (comment.pos < node.pos || comment.end > start) continue;
    if (commentSuppressesChecking(source.text.slice(comment.pos, comment.end), comment.kind)) return true;
  }
  return false;
}

/** Match the native single-line directive or final line of a multiline comment. */
function commentSuppressesChecking(text: string, kind: ts.CommentKind): boolean {
  if (kind === ts.SyntaxKind.SingleLineCommentTrivia) return SINGLE_LINE_DIRECTIVE.test(text);
  let lastLine = text.length;
  while (lastLine > 0 && !ts.isLineBreak(text.charCodeAt(lastLine - 1))) lastLine--;
  return MULTI_LINE_DIRECTIVE.test(text.slice(lastLine).trimStart());
}
