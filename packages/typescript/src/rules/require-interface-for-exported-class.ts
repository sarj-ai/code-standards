/**
 * @fileoverview require-interface-for-exported-class — exported behavior needs an explicit substitutable contract.
 *
 * Port of the 18.x `require-interface-for-exported-class` rule. Same
 * algorithm; the file gates run in `before()`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-interface-for-exported-class.test.ts
 */

import { defineRule, type ESTree } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { existingFactoryContractFix } from "../utils/existing-factory-contract-fix.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "../utils/paths.js";

const NAME = "require-interface-for-exported-class";
const JAVASCRIPT_FILE_RE = /\.(?:js|jsx|mjs|cjs)$/iu;

type ClassLike = ESTree.Class;
type ProgramStatement = ESTree.Program["body"][number];

interface ClassBinding {
  readonly declaration: ClassLike;
  readonly name: string;
}

function isPublicInstanceMember(member: ESTree.MethodDefinition | ESTree.PropertyDefinition): boolean {
  return !member.static && member.accessibility !== "private" && member.accessibility !== "protected" &&
    member.key.type !== "PrivateIdentifier";
}

function hasPublicInstanceBehavior(node: ClassLike): boolean {
  return node.body.body.some((member) => {
    if (member.type === "MethodDefinition") return member.kind !== "constructor" && isPublicInstanceMember(member);
    return member.type === "PropertyDefinition" && isPublicInstanceMember(member) && (
      member.value?.type === "ArrowFunctionExpression" ||
      member.value?.type === "FunctionExpression" ||
      member.typeAnnotation?.typeAnnotation.type === "TSFunctionType"
    );
  });
}

function classBindings(statement: ProgramStatement): readonly ClassBinding[] {
  const declaration = statement.type === "ExportNamedDeclaration" ? statement.declaration : statement;
  if (declaration?.type === "ClassDeclaration") {
    return declaration.id === null ? [] : [{ declaration, name: declaration.id.name }];
  }
  if (declaration?.type !== "VariableDeclaration") return [];
  return declaration.declarations.flatMap((item) =>
    item.id.type === "Identifier" && item.init?.type === "ClassExpression"
      ? [{ declaration: item.init, name: item.id.name }]
      : [],
  );
}

function exportedClasses(program: ESTree.Program, classes: ReadonlyMap<string, ClassLike>): Map<ClassLike, string> {
  const exported = new Map<ClassLike, string>();
  function collectExportedClass(statement: ProgramStatement): void {
    if (statement.type === "ExportNamedDeclaration") {
      for (const binding of classBindings(statement)) {
        exported.set(binding.declaration, binding.name);
      }
      if (statement.source !== null || statement.exportKind === "type") return;
      collectClassSpecifiers(statement);
      return;
    }
    if (statement.type !== "ExportDefaultDeclaration") return;
    if (statement.declaration.type === "ClassDeclaration" || statement.declaration.type === "ClassExpression") {
      exported.set(statement.declaration, statement.declaration.id?.name ?? "default");
    } else if (statement.declaration.type === "Identifier") {
      const candidate = classes.get(statement.declaration.name);
      if (candidate !== undefined) {
        exported.set(candidate, statement.declaration.name);
      }
    }
  }

  function collectClassSpecifiers(statement: ESTree.ExportNamedDeclaration): void {
    for (const specifier of statement.specifiers) {
      if (specifier.exportKind === "type") continue;
      // TS-ESTree reads `local.name`; a string-literal local only occurs with a `source`.
      const candidate = classes.get((specifier.local as { name: string }).name);
      if (candidate === undefined) continue;
      const exportedName = specifier.exported.type === "Identifier" ? specifier.exported.name : specifier.exported.value;
      exported.set(candidate, exportedName);
    }
  }

  for (const statement of program.body) {
    collectExportedClass(statement);
  }

  return exported;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Require exported concrete classes with public behavior to declare a contract.",
      url: docsUrl(NAME),
    },
    schema: [],
    fixable: "code",
    messages: {
      requireContract:
        "Exported class `{{name}}` has public behavior but no declared interface or base contract; add a focused contract and implement it.",
    },
  },
  createOnce(context) {
    return {
      before(): boolean | void {
        const file = { filename: context.filename, cwd: context.cwd };
        if (
          JAVASCRIPT_FILE_RE.test(file.filename) ||
          isTestFile(file) ||
          isStoryFile(file) ||
          isGeneratedFile(file, context.sourceCode.text)
        )
          return false;
      },
      "Program:exit"(program): void {
        const classes = new Map<string, ClassLike>();
        const abstractBases = new Set<string>();
        for (const statement of program.body) {
          for (const binding of classBindings(statement)) {
            classes.set(binding.name, binding.declaration);
            if (binding.declaration.abstract) abstractBases.add(binding.name);
          }
        }

        for (const [declaration, exportedName] of exportedClasses(program, classes)) {
          const extendsLocalAbstractBase =
            declaration.superClass?.type === "Identifier" && abstractBases.has(declaration.superClass.name);
          if (
            declaration.abstract ||
            (declaration.implements?.length ?? 0) > 0 ||
            extendsLocalAbstractBase ||
            !hasPublicInstanceBehavior(declaration)
          )
            continue;
          const fix = existingFactoryContractFix(context.sourceCode, declaration);
          context.report({
            node: declaration.id ?? declaration,
            messageId: "requireContract",
            data: { name: exportedName },
            ...(fix !== null && { fix }),
          });
        }
      },
    };
  },
});
