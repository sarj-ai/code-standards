import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import ts from "typescript";
import { expect, it } from "vitest";

import { closedObjectContract } from "../src/rules/_closed-object-contract.js";

it("bounds shared-ancestor validation by the native heritage graph", () => {
  const declarations = ["export {}; interface Base {readonly name: string}", "interface A0 extends Base {} interface B0 extends Base {}"];
  for (let depth = 1; depth <= 16; depth++) {
    declarations.push(`interface A${depth} extends A${depth - 1}, B${depth - 1} {} interface B${depth} extends A${depth - 1}, B${depth - 1} {}`);
  }
  const parsed = tsParser.parseForESLint(declarations.join("\n"), {
    filePath: "proof.tsx",
    projectService: { allowDefaultProject: ["*.tsx"], defaultProject: "tsconfig.json" },
    tsconfigRootDir: join(import.meta.dirname, "fixtures", "minimal-consumer"),
  });
  const program = parsed.services.program;
  const source = parsed.services.esTreeNodeToTSNodeMap.get(parsed.ast);
  if (!program || !source || !ts.isSourceFile(source)) throw new Error("Expected the parser-owned typed project");
  const checker = program.getTypeChecker();
  const root = checker.getSymbolsInScope(source, ts.SymbolFlags.Interface).find((symbol) => symbol.getName() === "A16");
  if (!root) throw new Error("Missing native hierarchy root");
  let indexQueries = 0;
  const observed = new Proxy(checker, {
    get(target, property): unknown {
      if (property === "getIndexInfosOfType") return (type: ts.Type) => {
        indexQueries++;
        return target.getIndexInfosOfType(type);
      };
      const member: unknown = Reflect.get(target, property);
      return typeof member === "function" ? member.bind(target) : member;
    },
  });
  expect(closedObjectContract(checker.getDeclaredTypeOfSymbol(root), observed)).toBe(true);

  expect(indexQueries).toBeLessThanOrEqual(16 * 4 + 3);
  const ordinaryQueries = indexQueries;
  expect(closedObjectContract(checker.getDeclaredTypeOfSymbol(root), observed, true)).toBe(true);
  expect(indexQueries - ordinaryQueries).toBeLessThanOrEqual(16 * 4 + 3);
});
