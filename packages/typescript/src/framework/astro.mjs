import { hash } from "node:crypto";
import { basename } from "node:path";
import { API, JsxEmit, ModuleKind } from "typescript-native/unstable/sync";
import { SyntaxKind, ScriptTarget, visitEachChild } from "typescript-native/unstable/ast";
import {
  updateSourceFile,
  updateExpressionStatement,
  createJsxFragment,
  createJsxOpeningFragment,
  createJsxClosingFragment,
  createJsxText,
  updateJsxElement,
  updateJsxFragment,
  createExportDeclaration,
  createNamedExports,
  updateFunctionDeclaration,
} from "typescript-native/unstable/ast/factory";
import { convertToTSX, parse } from "@astrojs/compiler";
import { TraceMap, originalPositionFor } from "@jridgewell/trace-mapping";
import { parseSync } from "oxc-parser";
export { lintAstroFiles, projectAstroPattern } from "./astro-runner.mjs";

function childNodes(node) {
  const children = [];
  node.forEachChild((child) => { children.push(child); });
  return children;
}

function lineOffsets(text) {
  const offsets = [0];
  for (let position = 0; position < text.length; position++) {
    if (text[position] === "\n") offsets.push(position + 1);
  }
  return offsets;
}

function positionAt(offsets, position) {
  let low = 0;
  let high = offsets.length;
  while (low + 1 < high) {
    const middle = (low + high) >>> 1;
    if (offsets[middle] <= position) low = middle;
    else high = middle;
  }
  return { line: low + 1, column: position - offsets[low] };
}

/** Owns one public compiler process per invocation, with no type-checker emulation. */
export function createAstroCompiler({ cwd = process.cwd() } = {}) {
  const api = new API({ cwd });
  return {
    close() { api.close(); },
    async compile(source, filename) {
      // Astro's public parser reports UTF-8 offsets; native source documents
      // and TypeScript nodes use UTF-16 positions.
      const sourceOffsets = new Map([[0, 0]]);
      let bytePosition = 0;
      let textPosition = 0;
      for (const character of source) {
        bytePosition += Buffer.byteLength(character);
        textPosition += character.length;
        sourceOffsets.set(bytePosition, textPosition);
      }
      function sourceOffset(position) {
        if (position === undefined) return undefined;
        const offset = sourceOffsets.get(position);
        if (offset === undefined) throw new Error("Astro source position is not a UTF-8 character boundary");
        return offset;
      }
      // The parser omits some ends and can report expression ends past EOF.
      // Such optional facts cannot own an exact range; genuine compiler spans
      // still own diagnostics and edits.
      function sourceEndOffset(position) {
        return position === undefined ? undefined : sourceOffsets.get(position);
      }
      const parsedAstro = await parse(source, { position: true });
      const converted = await convertToTSX(source, {
        filename: basename(filename),
        sourcemap: "external",
        includeScripts: false,
        includeStyles: true,
      });
      const errors = [...parsedAstro.diagnostics, ...converted.diagnostics]
        .filter((diagnostic) => diagnostic.severity === 1);
      if (errors.length) throw new Error(errors.map((error) => error.text).join("\n"));
      const originalTree = api.createSourceFile(`${filename}.tsx`, converted.code);
      const regions = [converted.metaRanges.frontmatter, converted.metaRanges.body];
      const sourceMap = new TraceMap(converted.map);
      const compiledLines = lineOffsets(converted.code);
      const authoredLines = lineOffsets(source);
      const expressionContainers = [];
      function omitCommentContainers(node) {
        const container = authoredExpressionContainer(node);
        if (container) expressionContainers.push(container);
        if (node.kind === SyntaxKind.JsxExpression && !node.expression) return undefined;
        if (node.kind === SyntaxKind.JsxText) {
          const end = authoredOffset(node.end);
          // The public Astro compiler can duplicate closing markup after a
          // string escape. Its duplicate has no position inside the source.
          if (end !== null && end > source.length) return undefined;
        }
        const visited = visitEachChild(node, omitCommentContainers);
        if (visited.kind !== SyntaxKind.JsxElement && visited.kind !== SyntaxKind.JsxFragment) return visited;
        // Removing a comment container makes adjacent genuine text children
        // contiguous. The public printer/parser represents them as one child.
        const children = [];
        for (const child of visited.children) {
          const previous = children.at(-1);
          if (child.kind === SyntaxKind.JsxText && previous?.kind === SyntaxKind.JsxText) {
            children[children.length - 1] = createJsxText(previous.text + child.text, false);
          } else children.push(child);
        }
        if (visited.kind === SyntaxKind.JsxFragment) return updateJsxFragment(visited, visited.openingFragment, children, visited.closingFragment);
        if (visited.openingElement.tagName.kind === SyntaxKind.Identifier && visited.openingElement.tagName.text === "Fragment") {
          const tag = node.openingElement.tagName;
          const start = authoredOffset(tag.getStart(originalTree));
          const end = authoredOffset(tag.end);
          if (start === null || end === null || source.slice(start, end) !== "Fragment" || source[start - 1] !== "<") {
            return createJsxFragment(createJsxOpeningFragment(), children, createJsxClosingFragment());
          }
        }
        return updateJsxElement(visited, visited.openingElement, children, visited.closingElement);
      }
      function authoredExpressionContainer(node) {
        if (node.kind !== SyntaxKind.JsxExpression) return null;
        const start = node.getStart(originalTree);
        const authoredStart = authoredOffset(start);
        const authoredEnd = authoredOffset(node.end);
        if (authoredStart !== null && authoredEnd !== null && authoredEnd > authoredStart &&
          source.slice(authoredStart, authoredEnd) === converted.code.slice(start, node.end)) {
          return { start: authoredStart, end: authoredEnd, omittedExpression: !node.expression };
        }
        return null;
      }
      const statements = originalTree.statements
        .filter((node) => regions.some((region) =>
          node.end > region.start && node.getStart(originalTree) < region.end))
        .map((originalNode) => {
          const node = omitCommentContainers(originalNode);
          // The wrapper is compiler-owned; authored Fragment elements remain intact.
          if (node.kind !== SyntaxKind.ExpressionStatement ||
            node.expression.kind !== SyntaxKind.JsxElement ||
            originalNode.getStart(originalTree) < converted.metaRanges.frontmatter.end ||
            node.expression.openingElement.tagName.kind !== SyntaxKind.Identifier ||
            node.expression.openingElement.tagName.text !== "Fragment" ||
            originalNode.getStart(originalTree) >= converted.metaRanges.body.start) return node;
          return updateExpressionStatement(node, createJsxFragment(
            createJsxOpeningFragment(), node.expression.children, createJsxClosingFragment(),
          ));
        });
      // Astro is an ES module even when its authored code has no imports or
      // exports. Retain that semantic boundary after removing compiler helpers.
      statements.push(createExportDeclaration(undefined, false, createNamedExports([]), undefined, undefined));
      const transformed = updateSourceFile(originalTree, statements, originalTree.endOfFileToken);
      const printOptions = {
        preserveSourceNewlines: true,
        neverAsciiEscape: true,
      };
      // Printing real statement nodes omits trivia. Original source providers
      // own comments and directives; compiler-generated pragma comments cannot
      // participate in policy or move a directive across a declaration.
      const text = statements.map((statement) => api.printer.printNode(statement, printOptions)).join("\n");
      const printedTree = api.createSourceFile(`${filename}.printed.tsx`, text);
      const spans = [{ virtual: [0, text.length], original: [0, source.length], exact: false }];
      const expressionRegions = [];
      const openingRanges = [];
      function authoredOffset(position) {
        const original = originalPositionFor(sourceMap, positionAt(compiledLines, position));
        return original.line === null ? null : authoredLines[original.line - 1] + original.column;
      }
      function pair(original, printed) {
        // The genuine printer can add parentheses, for example around a
        // non-null assertion used as a member-access receiver.
        if (original.kind !== SyntaxKind.ParenthesizedExpression && printed.kind === SyntaxKind.ParenthesizedExpression) {
          pair(original, printed.expression);
          return;
        }
        if (original.kind !== printed.kind) throw new Error("Astro compiler changed a node kind during printing");
        const oldChildren = childNodes(original);
        const newChildren = childNodes(printed);
        if (oldChildren.length !== newChildren.length) {
          throw new Error("Astro compiler changed a node's children during printing");
        }
        for (let index = 0; index < oldChildren.length; index++) pair(oldChildren[index], newChildren[index]);
        if (original.pos < 0 || original.end <= original.pos || original.kind === SyntaxKind.SourceFile) return;
        const start = original.getStart(originalTree);
        const end = original.end;
        if (!regions.some((region) => start >= region.start && end <= region.end)) return;
        const authoredStart = authoredOffset(start);
        const authoredEnd = authoredOffset(end);
        if (authoredStart === null || authoredEnd === null || authoredEnd < authoredStart) return;
        if (original.kind === SyntaxKind.JsxOpeningElement) openingRanges.push({ start: authoredStart, end: authoredEnd });
        const printedStart = printed.getStart(printedTree);
        let exact = converted.code.slice(start, end) === text.slice(printedStart, printed.end) &&
          source.slice(authoredStart, authoredEnd) === converted.code.slice(start, end);
        if (exact) {
          for (let position = start; position <= end; position++) {
            if (authoredOffset(position) !== authoredStart + position - start) { exact = false; break; }
          }
        }
        spans.push({ virtual: [printedStart, printed.end], original: [authoredStart, authoredEnd], exact });
      }
      pair(transformed, printedTree);
      function collectExpressions(node) {
        if (node.kind === SyntaxKind.JsxExpression && !node.expression) {
          const start = authoredOffset(node.getStart(originalTree));
          const end = authoredOffset(node.end);
          if (start !== null && end !== null && end > start &&
            source.slice(start, end) === converted.code.slice(node.getStart(originalTree), node.end) &&
            source[start] === "{" && source[end - 1] === "}") {
            expressionRegions.push({ text: source.slice(start + 1, end - 1), start: start + 1 });
          }
          return;
        }
        if (node.kind === SyntaxKind.JsxExpression && node.expression &&
          node.getStart(originalTree) >= converted.metaRanges.body.start) {
          const start = authoredOffset(node.expression.getStart(originalTree));
          const end = authoredOffset(node.expression.end);
          if (start !== null && end !== null && end >= start &&
            source.slice(start, end) === converted.code.slice(node.expression.getStart(originalTree), node.expression.end)) {
            expressionRegions.push({ text: source.slice(start, end), start, expression: true });
            return;
          }
        }
        for (const child of childNodes(node)) collectExpressions(child);
      }
      collectExpressions(originalTree);
      const elements = [];
      const originalComments = [];
      const scripts = [];
      function visit(node) {
        if (node.type === "comment") originalComments.push({
          start: sourceOffset(node.position.start.offset), end: sourceOffset(node.position.end.offset), value: node.value, kind: "html",
        });
        if (node.attributes) elements.push({
          name: node.name,
          start: sourceOffset(node.position.start.offset),
          end: sourceEndOffset(node.position.end?.offset),
          openingEnd: openingRanges.find((range) => range.start === sourceOffset(node.position.start.offset))?.end,
          attributes: node.attributes.map((attribute) => ({
            name: attribute.name, kind: attribute.kind, value: attribute.value,
            start: sourceOffset(attribute.position.start.offset),
          })),
          children: (node.children ?? []).map((child) => {
            const content = child.type === "expression" && child.children?.[0];
            const contentStart = content && sourceOffset(content.position.start.offset);
            // Astro's parser may omit an expression end. The genuine compiler
            // JSX node and its source map still own the comment container span.
            // Compiler traversal is preorder, so the last containing range is
            // the innermost genuine JSX expression at this source position.
            const expression = content && expressionContainers.findLast((range) =>
              range.start < contentStart && range.end > contentStart);
            return {
              type: child.type, value: child.value,
              start: expression?.start ?? sourceOffset(child.position.start.offset),
              end: expression?.end ?? sourceEndOffset(child.position.end?.offset),
              ...(expression?.omittedExpression && { omittedExpression: true }),
            };
          }),
        });
        if (node.name === "script" && node.children?.length === 1 && node.children[0].type === "text" &&
          !node.attributes.some((attribute) => attribute.name === "src")) {
          const child = node.children[0];
          const start = sourceOffset(child.position.start.offset);
          if (source.slice(start, start + child.value.length) !== child.value) {
            throw new Error("Astro client script does not match its original source span");
          }
          scripts.push({ text: child.value, start,
            language: node.attributes.find((attribute) => attribute.name === "lang")?.value === "js" ? "jsx" : "tsx",
          });
        }
        for (const child of node.children ?? []) visit(child);
      }
      visit(parsedAstro.ast);
      const frontmatter = parsedAstro.ast.children.find((node) => node.type === "frontmatter");
      const rawRegions = [
        ...(frontmatter ? [{ text: frontmatter.value, start: sourceOffset(frontmatter.position.start.offset) + 3 }] : []),
        ...expressionRegions,
      ];
      for (const region of rawRegions) {
        if (source.slice(region.start, region.start + region.text.length) !== region.text) {
          throw new Error("Astro source region does not match its original document");
        }
        const parsed = parseSync("source.tsx", region.expression ? `(${region.text});` : region.text);
        const prefix = region.expression ? 1 : 0;
        for (const comment of parsed.comments) {
          originalComments.push({
            start: region.start + comment.start - prefix, end: region.start + comment.end - prefix,
            value: comment.value, kind: comment.type,
          });
        }
      }
      const javascript = api.transpileModule(text, {
        fileName: `${filename}.tsx`,
        compilerOptions: { jsx: JsxEmit.Preserve, target: ScriptTarget.ESNext, module: ModuleKind.ESNext, sourceMap: true, removeComments: true },
      });
      const component = originalTree.statements.find((node) => node.kind === SyntaxKind.FunctionDeclaration &&
        node.getStart(originalTree) >= converted.metaRanges.body.end);
      const bindingsText = component && /\bAstro\b/u.test(source)
        ? `${text}\n${api.printer.printNode(updateFunctionDeclaration(component, component.modifiers,
          component.asteriskToken, undefined, component.typeParameters, component.parameters, component.type, component.body), printOptions)}` : text;
      return {
        text,
        bindingsText,
        origin: {
          filename, text: source, spans,
          virtualHash: hash("sha256", text),
          elements, originalComments,
        },
        frontmatter: frontmatter && { text: frontmatter.value, start: sourceOffset(frontmatter.position.start.offset) + 3 },
        rawRegions,
        scripts,
        javascript,
      };
    },
  };
}

/** A finding can own a structural span; an edit needs an exact span. */
export function mapAstroRange(origin, range, { exact = false } = {}) {
  const span = origin.spans
    .filter((candidate) => candidate.virtual[0] <= range[0] && candidate.virtual[1] >= range[1] &&
      (!exact || candidate.exact))
    .sort((left, right) => left.virtual[1] - left.virtual[0] - (right.virtual[1] - right.virtual[0]))[0];
  if (!span) return null;
  return span.exact
    ? [span.original[0] + range[0] - span.virtual[0], span.original[0] + range[1] - span.virtual[0]]
    : span.original;
}
