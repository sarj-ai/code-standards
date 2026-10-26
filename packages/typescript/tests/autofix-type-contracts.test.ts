// vitest: shared-module-graph
import { fileURLToPath } from "node:url";

import ts from "typescript";
import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import { expect, it } from "vitest";

import broadReturn from "../src/rules/no-broad-return-type.js";
import overload from "../src/rules/no-contradictory-overload-return.js";
import contradictoryPredicate from "../src/rules/no-contradictory-type-predicate.js";
import partialPredicate from "../src/rules/no-partial-type-predicate.js";
import contractPrivate from "../src/rules/interface-contract-members-private.js";
import cryptoHash from "../src/rules/prefer-node-crypto-hash.js";
import discriminated from "../src/rules/prefer-discriminated-union.js";
import normalizedCollection from "../src/rules/prefer-non-nullable-collection.js";
import parseOutput from "../src/rules/prefer-zod-parse-output-type.js";
import inferTwin from "../src/rules/prefer-zod-infer.js";
import immutable from "../src/rules/prefer-immutable-module-constant.js";
import knownValue from "../src/rules/no-known-value-widening.js";
import enumRule from "../src/rules/no-enum.js";
import sourceMaps from "../src/rules/no-production-browser-source-maps.js";
import svg from "../src/rules/no-dangerously-allow-svg.js";
import privateMembers from "../src/rules/prefer-ecmascript-private-members.js";
import propertyNames from "../src/rules/require-camelcase-properties.js";
import mockCasting from "../src/rules/no-unsafe-mock-casting.js";
import testDoubleCast from "../src/rules/no-unsafe-test-double-cast.js";
import unionComment from "../src/rules/no-union-in-comment.js";
import namedReturn from "../src/rules/prefer-named-complex-return-type.js";
import namedCallback from "../src/rules/prefer-named-callback-domain.js";
import stringLoop from "../src/rules/no-string-concat-in-loop.js";
import collectionProperty from "../src/rules/no-in-operator-on-built-in-collections.js";
import literalLookup from "../src/rules/prefer-module-level-constant.js";
import declarationOrder from "../src/rules/stepdown.js";
import staticMatcher from "../src/rules/require-static-next-matcher.js";
import repeatedLiteral from "../src/rules/no-repeated-string-literal.js";
import identityReduce from "../src/rules/no-reduce-accumulator-copy.js";
import ownedFetch from "../src/rules/no-detached-global-fetch.js";
import legacyOptional from "../src/rules/no-redundant-optional-array-default.js";

it("compiles the original and fixed private contracts with strict TypeScript and real Zod declarations", () => {
  const rules = [
    broadReturn,
    contractPrivate,
    immutable,
    knownValue,
    enumRule,
    overload,
    contradictoryPredicate,
    partialPredicate,
    inferTwin,
    parseOutput,
    normalizedCollection,
    discriminated,
    cryptoHash,
    privateMembers,
    propertyNames,
    mockCasting,
    testDoubleCast,
    unionComment,
    namedReturn,
    namedCallback,
    stringLoop,
    collectionProperty,
    literalLookup,
    declarationOrder,
    staticMatcher,
    repeatedLiteral,
    identityReduce,
    ownedFetch,
    legacyOptional,
  ];
  const virtual = new Map<string, string>();
  for (const rule of rules) {
    const example = rule.documentation?.examples.find(
      (entry) => entry.id === "safe-autofix",
    );
    expect(example).toBeDefined();
    const original = example?.files[0];
    const fixed = example?.fixedFiles?.[0];
    if (original === undefined || fixed === undefined)
      throw new Error("Missing original or fixed private contract");
    if (
      rule === contradictoryPredicate ||
      rule === partialPredicate ||
      rule === inferTwin ||
      rule === overload ||
      rule === parseOutput ||
      rule === normalizedCollection ||
      rule === discriminated ||
      rule === mockCasting ||
      rule === testDoubleCast ||
      rule === unionComment ||
      rule === namedReturn ||
      rule === namedCallback
    ) {
      const compilerOptions = {
        target: ts.ScriptTarget.ESNext,
        module: ts.ModuleKind.ESNext,
      };
      expect(
        ts.transpileModule(fixed.source, { compilerOptions }).outputText,
      ).toBe(
        ts.transpileModule(original.source, { compilerOptions }).outputText,
      );
    }
    if (rule === overload) {
      const record = overload.documentation?.examples.find(
        (entry) => entry.id === "safe-autofix-record",
      );
      const before = record?.files[0];
      const after = record?.fixedFiles?.[0];
      if (before === undefined || after === undefined)
        throw new Error("Missing flat overload correction");
      virtual.set(
        fileURLToPath(new URL("../autofix-record-before.ts", import.meta.url)),
        before.source,
      );
      virtual.set(
        fileURLToPath(new URL("../autofix-record-after.ts", import.meta.url)),
        after.source,
      );
      const compilerOptions = {
        target: ts.ScriptTarget.ESNext,
        module: ts.ModuleKind.ESNext,
      };
      expect(
        ts.transpileModule(after.source, { compilerOptions }).outputText,
      ).toBe(ts.transpileModule(before.source, { compilerOptions }).outputText);
    }
    const name = rule.documentation?.ruleId;
    const contract = strictContractAssertions(name);
    virtual.set(
      fileURLToPath(
        new URL(`../autofix-before-${String(name)}.ts`, import.meta.url),
      ),
      original.source + contract,
    );
    virtual.set(
      fileURLToPath(
        new URL(`../autofix-after-${String(name)}.ts`, import.meta.url),
      ),
      fixed.source + contract,
    );
  }
  const dependentTypes = [
    "export {}; interface Local { user_id: string; selected: this['user_id'] }",
    "export {}; interface Local { 'userId': number; user_id: string }",
    "export {}; const key = 'userId' as const; interface Local { [key]: number; user_id: string }",
    "export {}; interface Local { [key: `userI${string}`]: number; user_id: string }",
  ];
  const predicateFilename = fileURLToPath(
    new URL("../autofix-inferred-property-predicate.ts", import.meta.url),
  );
  virtual.set(
    predicateFilename,
    "export function hasField(cache: Map<string, object>) { return 'newField' in cache; }",
  );
  for (const [index, original] of dependentTypes.entries()) {
    const filename = fileURLToPath(
      new URL(`../autofix-dependent-${String(index)}.ts`, import.meta.url),
    );
    const fixed = new Linter().verifyAndFix(
      original,
      [
        {
          files: ["**/*.ts"],
          languageOptions: { parser },
          plugins: { sarj: { rules: { property: propertyNames } } },
          rules: { "sarj/property": "error" },
        },
      ],
      { filename },
    );
    expect(fixed.fixed).toBe(false);
    expect(fixed.output).toBe(original);
    virtual.set(filename, fixed.output);
  }
  const policyContracts = [
    {
      rule: sourceMaps,
      source:
        "const config: {productionBrowserSourceMaps:true} = {productionBrowserSourceMaps:true}; export default config;",
    },
    {
      rule: sourceMaps,
      source:
        "export default {productionBrowserSourceMaps:true} satisfies {productionBrowserSourceMaps:true};",
    },
    {
      rule: svg,
      source:
        "const images = {dangerouslyAllowSVG:true} as const; const config: {images:{dangerouslyAllowSVG:true}} = {images}; export default config;",
    },
    {
      rule: svg,
      source:
        "export default {images:{dangerouslyAllowSVG:true}} satisfies {images:{dangerouslyAllowSVG:true}};",
    },
  ];
  for (const [index, entry] of policyContracts.entries()) {
    const filename = fileURLToPath(
      new URL(
        `../autofix-policy-${String(index)}/next.config.ts`,
        import.meta.url,
      ),
    );
    const fixed = new Linter().verifyAndFix(
      entry.source,
      [
        {
          files: ["**/*.ts"],
          languageOptions: { parser },
          plugins: { sarj: { rules: { policy: entry.rule } } },
          rules: { "sarj/policy": "error" },
        },
      ],
      { filename },
    );
    expect(fixed.fixed).toBe(false);
    expect(fixed.output).toBe(entry.source);
    virtual.set(filename, fixed.output);
  }
  const options: ts.CompilerOptions = {
    strict: true,
    noEmit: true,
    types: ["node"],
    skipLibCheck: true,
    target: ts.ScriptTarget.ESNext,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
  };
  const host = ts.createCompilerHost(options);
  const getSourceFile = host.getSourceFile.bind(host);
  const fileExists = host.fileExists.bind(host);
  host.fileExists = (filename) => virtual.has(filename) || fileExists(filename);
  host.getSourceFile = (
    filename,
    languageVersion,
    onError,
    shouldCreateNewSourceFile,
  ) => {
    const source = virtual.get(filename);
    return source === undefined
      ? getSourceFile(
          filename,
          languageVersion,
          onError,
          shouldCreateNewSourceFile,
        )
      : ts.createSourceFile(filename, source, languageVersion, true);
  };
  const program = ts.createProgram([...virtual.keys()], options, host);
  expect(
    ts
      .getPreEmitDiagnostics(program)
      .map(
        (diagnostic) =>
          `${String(diagnostic.file?.fileName)}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n")}`,
      ),
  ).toEqual([]);
  const predicateFile = program.getSourceFile(predicateFilename);
  const predicateFunction = predicateFile?.statements.find(
    ts.isFunctionDeclaration,
  );
  if (predicateFunction === undefined)
    throw new Error("Missing inferred property predicate fixture");
  const checker = program.getTypeChecker();
  const signature = checker.getSignatureFromDeclaration(predicateFunction);
  if (signature === undefined)
    throw new Error("Missing inferred predicate signature");
  expect(checker.getTypePredicateOfSignature(signature)).toBeDefined();
});

function strictContractAssertions(name: string | undefined): string {
  switch (name) {
    case "require-static-next-matcher":
      return "\ntype Equal<A,B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false; type Expect<T extends true> = T; type MatcherContract = Expect<Equal<typeof config.matcher,string>>;";
    case "no-repeated-string-literal":
      return "\ntype Equal<A,B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false; type Expect<T extends true> = T; type FirstContract = Expect<Equal<ReturnType<typeof one>,string>>; type SecondContract = Expect<Equal<ReturnType<typeof two>,ReturnType<typeof current>>>;";
    case "no-reduce-accumulator-copy":
      return "\ntype Equal<A,B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false; type Expect<T extends true> = T; type CollectionContract = Expect<Equal<ReturnType<typeof collect>,string[]>>;";
    case "no-detached-global-fetch":
      return "\ntype Equal<A,B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false; type Expect<T extends true> = T; type RequestContract = Expect<Equal<ReturnType<typeof load>,Promise<Response>>>;";
    default:
      return "";
  }
}
