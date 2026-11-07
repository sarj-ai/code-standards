/**
 * @fileoverview tsrs-services — type information for @sarj rules from tsrs, the Rust TypeScript 7 compiler.
 *
 * Oxlint gives JS plugins no type information, so typed rules get it from one
 * tsrs API process per lint run, with the programs typescript-eslint's project
 * service would build:
 *
 * - one snapshot per nearest `tsconfig.json`, kept for the run. The config is
 *   parsed for the first file under it (rules need its options in `before()`),
 *   but its program is built only when a file first asks for types, so
 *   projects whose files have no candidates cost almost nothing. tsrs's project
 *   system reads referenced projects' sources, as tsserver does;
 * - a one-file synthetic program, with the nearest project's options and
 *   references, for a file on disk outside its project. One snapshot update
 *   creates the programs of a directory's files at once;
 * - a one-file synthetic program over a file-system overlay for text that is
 *   not on disk or differs from it (RuleTester cases, unsaved buffers).
 *
 * Every request is a round trip to the tsrs process, so the API is shaped for
 * batching: collect ESTree nodes during the walk, then resolve them all at once
 * (`typesOf`, `symbolsOf`, `batch`) in `Program:exit`, inside `run`, which
 * builds the project and fetches the remote source file only when called.
 *
 * Type-aware mode is on by default; opt out with Oxlint
 * `settings: { sarj: { typeAware: false } }` or `SARJ_TYPE_AWARE=0`. `tsrs` is
 * loaded from the linted repo first (`context.cwd`), then from the plugin's own
 * dependencies. `tsrsServices` returns null when type-aware mode is off, tsrs is
 * not installed, or the tsrs process broke earlier in the run; typed rules then
 * take their untyped path, as they do under ESLint without type information.
 * Typed work that throws, in tsrs or in the rule, turns tsrs off for that file
 * only while the process still answers, and writes one `@sarj: tsrs request
 * failed` line with the error's stack to stderr. Type flags follow TypeScript 7
 * numbering, so take them from `file.flags` or `file.sync`, never from the
 * `typescript` package.
 */

// eslint-disable-next-line @sarj/prefer-node-fs-promises -- Oxlint calls rule visitors synchronously, so a config lookup made while linting a file cannot await.
import { existsSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

import type * as TsrsAst from "tsrs/ast";
import type * as TsrsSync from "tsrs/sync";

import type { Context, Node, SourceCode } from "../types.js";
import { parentOf } from "./ast.js";

// The subset of tsrs's sync API (`tsrs/sync`, `tsrs/ast`) the backend and its rules use.

/** A request generator: run several in one round trip with `TsrsFile.batch`. */
export type TsrsRequest<T> = Generator<unknown, T, unknown>;
type Batched<Args extends unknown[], Result> = ((...args: Args) => Result) & { gen(...args: Args): TsrsRequest<Result> };

export interface TsrsNode {
  readonly kind: number;
  readonly pos: number;
  readonly end: number;
  readonly parent?: TsrsNode | undefined;
  readonly modifiers?: readonly TsrsNode[] | undefined;
  getStart(sourceFile?: TsrsSourceFile): number;
  getEnd(): number;
  forEachChild<T>(visitor: (node: TsrsNode) => T | undefined): T | undefined;
}

export interface TsrsSourceFile extends TsrsNode {
  readonly text: string;
  readonly fileName: string;
}

export interface TsrsNodeHandle {
  readonly path: string;
}

export interface TsrsSymbol {
  readonly name: string;
  readonly flags: number;
  readonly declarations: readonly TsrsNodeHandle[];
}

export interface TsrsType {
  readonly id: number;
  readonly flags: number;
  readonly objectFlags: number;
  readonly value: string | number | boolean | bigint;
  readonly intrinsicName: string;
  isUnionType(): boolean;
  isIntersectionType(): boolean;
  isStringLiteralType(): boolean;
  isNumberLiteralType(): boolean;
  isBigIntLiteralType(): boolean;
  isBooleanLiteralType(): boolean;
  readonly getTypes: Batched<[], readonly TsrsType[] | undefined>;
  readonly getProperty: Batched<[name: string], TsrsSymbol | undefined>;
}

export interface TsrsChecker {
  readonly getTypeAtLocation: ((nodes: readonly TsrsNode[]) => TsrsType[]) & { gen(nodes: readonly TsrsNode[]): TsrsRequest<TsrsType[]> };
  readonly getSymbolAtLocation: ((nodes: readonly TsrsNode[]) => (TsrsSymbol | undefined)[]) &
    { gen(nodes: readonly TsrsNode[]): TsrsRequest<(TsrsSymbol | undefined)[]> };
  readonly isArrayType: Batched<[type: TsrsType], boolean>;
  readonly typeToString: Batched<[type: TsrsType], string>;
}

export interface TsrsCompilerOptions {
  readonly strict?: boolean | undefined;
  readonly strictNullChecks?: boolean | undefined;
  readonly [option: string]: unknown;
}

export interface TsrsProgram {
  getCompilerOptions(): TsrsCompilerOptions;
  readonly getSourceFile: Batched<[file: string], TsrsSourceFile | undefined>;
  readonly getSourceFileMetadataByPath: Batched<[path: string], { readonly isDefaultLibrary: boolean } | undefined>;
  getProject(): TsrsProject;
}

interface TsrsProject {
  readonly program: TsrsProgram;
  readonly checker: TsrsChecker;
}

interface TsrsParsedCommandLine {
  readonly options: TsrsCompilerOptions;
  readonly raw?: { readonly references?: readonly { readonly path: string }[] } | undefined;
}

interface TsrsSnapshot {
  readonly operation: { readonly createdPrograms?: readonly TsrsProgram[] };
  getConfiguredProject(configFileName: string): TsrsProject | undefined;
  update(params: SnapshotParams): TsrsSnapshot;
  dispose(): void;
}

interface SnapshotParams {
  openProjects?: readonly string[];
  fileSystem?: { kind: "layer"; files: Record<string, string> };
  createPrograms?: readonly { rootFiles: readonly string[]; compilerOptions: TsrsCompilerOptions; options?: { projectReferences?: readonly { path: string }[] } }[];
}

interface TsrsApi {
  parseConfigFile(file: string): TsrsParsedCommandLine;
  parseCommandLine(commandLine: readonly string[]): unknown;
  createSnapshot(params?: SnapshotParams): TsrsSnapshot;
  batch(...requests: readonly TsrsRequest<unknown>[]): unknown[];
}

/** TypeScript 7 `TypeFlags`, as tsrs numbers them. */
export type TsrsTypeFlags = Readonly<Record<
  "Any" | "Unknown" | "String" | "Number" | "Boolean" | "Enum" | "BigInt" | "StringLiteral" | "NumberLiteral" |
  "BooleanLiteral" | "EnumLiteral" | "BigIntLiteral" | "ESSymbol" | "UniqueESSymbol" | "Void" | "Undefined" | "Null" |
  "Never" | "TypeParameter" | "Object" | "Union" | "Intersection" | "Index" | "IndexedAccess" | "Conditional" |
  "Substitution" | "NonPrimitive" | "TemplateLiteral" | "StringMapping" | "Literal" | "StringLike" | "NumberLike" |
  "BigIntLike" | "BooleanLike" | "EnumLike" | "ESSymbolLike" | "VoidLike" | "UnionOrIntersection", number>>;

interface TsrsModules {
  readonly api: TsrsApi;
  readonly ast: typeof TsrsAst;
  readonly sync: typeof TsrsSync;
}

/** One linted file's program in tsrs, with ESTree-to-tsrs node lookup and batched queries. */
export interface TsrsFile {
  /** tsrs's AST module (`tsrs/ast`): TypeScript 7 syntax kinds, node guards, scanner. */
  readonly ast: typeof TsrsAst;
  /** tsrs's API module (`tsrs/sync`): TypeScript 7 type, symbol and object flags. */
  readonly sync: typeof TsrsSync;
  /** TypeScript 7 type flags. */
  readonly flags: TsrsTypeFlags;
  readonly checker: TsrsChecker;
  readonly program: TsrsProgram;
  readonly sourceFile: TsrsSourceFile;
  /** The innermost tsrs node with this ESTree node's range, or undefined when none matches. */
  tsNode(node: Node): TsrsNode | undefined;
  /**
   * The outermost tsrs node with `tsNode(node)`'s range. typescript-estree maps a type to its type
   * node, but the innermost match of a type reference without arguments is its name, and TypeScript 7
   * types inner nodes unlike TypeScript 6: the name Identifier of `value is Text` is `any`, and the
   * string literal of `value is "ready"` widens.
   */
  outerTsNode(node: Node): TsrsNode | undefined;
  /** The innermost ESTree node with this tsrs node's range (the Program for the source file), as typescript-estree's `tsNodeToESTreeNodeMap` finds it. */
  esTreeNode(node: TsrsNode): Node | undefined;
  /** `getTypeAtLocation` for many nodes in one request; undefined where no tsrs node matches. */
  typesOf(nodes: readonly Node[]): (TsrsType | undefined)[];
  /** `getSymbolAtLocation` for many nodes in one request; undefined where no node or symbol matches. */
  symbolsOf(nodes: readonly Node[]): (TsrsSymbol | undefined)[];
  /** Whether every declaration of the symbol is in a default library file (`lib.*.d.ts`). */
  isDefaultLibrarySymbol(symbol: TsrsSymbol | undefined): boolean;
  /** Run request generators (`type.getTypes.gen()`, `checker.isArrayType.gen(type)`...) in one round trip. */
  batch<T>(requests: readonly TsrsRequest<T>[]): T[];
}

export interface TsrsServices {
  /** Options of the program that will type this file (the nearest project's, or `{ strict: true }`). */
  readonly compilerOptions: TsrsCompilerOptions;
  /**
   * Run typed work on the file's program, built on first call. Null when no
   * program can hold the file (a `.mjs` file without `allowJs`, say) or a tsrs
   * request failed; work that throws turns tsrs off for the rest of this file
   * (and of the run when the tsrs process is broken), which then takes the
   * untyped path. Make every request before the first report, so a failure
   * leaves nothing half reported.
   */
  run<T>(work: (file: TsrsFile) => T): T | null;
}

let modules: TsrsModules | null | undefined;
// Disabled for the rest of the run once the tsrs process cannot answer, so every later file takes the untyped path.
let failed = false;

// Every typed rule on one file shares one set of services.
let servicesAst: object | null = null;
let servicesValue: TsrsServices | null = null;

// Standards opts in before loading the plugin. Start the child before Oxlint
// reserves its large per-thread arenas: Linux can reject a later fork with
// ENOMEM even when those arenas mostly consume virtual, rather than real, memory.
// Other callers retain lazy startup and the settings-based opt-out.
// eslint-disable-next-line @sarj/no-raw-env -- Standards sets this explicit type-aware opt-in before plugin loading.
if (process.env["SARJ_TYPE_AWARE"] === "1") {
  try {
    modules = loadTsrs(process.cwd());
  } catch (error) {
    fail(error);
  }
}

/** tsrs type services for the current file, or null when off, unavailable, or failed. */
export function tsrsServices(context: Context): TsrsServices | null {
  if (failed) return null;
  const sourceCode = context.sourceCode;
  if (sourceCode.ast !== servicesAst) {
    servicesAst = sourceCode.ast;
    servicesValue = typeAwareEnabled(context) ? openServices(context) : null;
  }
  return servicesValue;
}

/** Whether type-aware rules may ask for types: on unless `sarj.typeAware` is false or `SARJ_TYPE_AWARE=0`. */
function typeAwareEnabled(context: Context): boolean {
  const settings = context.settings as { sarj?: { typeAware?: unknown } };
  // eslint-disable-next-line @sarj/no-raw-env -- The plugin's one switch is an on/off flag; any value but "0" keeps type-aware rules on.
  return settings.sarj?.typeAware !== false && process.env["SARJ_TYPE_AWARE"] !== "0";
}

function openServices(context: Context): TsrsServices | null {
  try {
    // Null caches "tsrs is not installed", so a missing tsrs is looked up once per run.
    if (modules === undefined) modules = loadTsrs(context.cwd);
    return modules === null ? null : buildServices(modules, context.filename, context.sourceCode);
  } catch (error) {
    return fail(error);
  }
}

function loadTsrs(cwd: string): TsrsModules | null {
  for (const base of [join(cwd, "package.json"), import.meta.url]) {
    let require: NodeJS.Require;
    let sync: typeof TsrsSync;
    try {
      require = createRequire(base);
      sync = require("tsrs/sync") as typeof TsrsSync;
    } catch {
      continue;
    }
    const api = new (sync.API as unknown as new (options: { cwd: string }) => TsrsApi)({ cwd });
    return { api, sync, ast: require("tsrs/ast") as typeof TsrsAst };
  }
  return null;
}

function fail(error: unknown): null {
  if (!failed) {
    failed = true;
    process.stderr.write(`@sarj: tsrs request failed, type-aware rules take their untyped path for the rest of the run: ${describe(error)}\n`);
  }
  return null;
}

/**
 * Typed work that threw, in tsrs or in the rule, turns tsrs off for this file, or for the run when
 * the tsrs process no longer answers. Standards fails `check` on this stderr line.
 */
function requestFailed(tsrs: TsrsModules, filename: string, error: unknown): null {
  if (!answers(tsrs.api)) return fail(error);
  process.stderr.write(`@sarj: tsrs request failed on ${filename}, type-aware rules take their untyped path for this file: ${describe(error)}\n`);
  return null;
}

/** The error with its stack, so a rule bug can be found from the stderr line. */
function describe(error: unknown): string {
  return error instanceof Error && error.stack !== undefined ? error.stack : String(error);
}

/** Whether the tsrs process answers a trivial request; a closed, crashed or desynchronized one cannot. */
function answers(api: TsrsApi): boolean {
  try {
    api.parseCommandLine([]);
    return true;
  } catch {
    return false;
  }
}

// Options for a file no tsconfig.json covers.
const NO_PROJECT_OPTIONS: TsrsCompilerOptions = Object.freeze({ strict: true });

function buildServices(tsrs: TsrsModules, filename: string, sourceCode: SourceCode): TsrsServices {
  const config = nearestConfig(dirname(filename));
  const entry = config === null ? null : configEntry(tsrs.api, config);
  const text = sourceCode.text;
  let file: TsrsFile | null | undefined;
  return {
    compilerOptions: entry?.options ?? NO_PROJECT_OPTIONS,
    run(work) {
      if (failed) return null;
      try {
        if (file === undefined) {
          const opened = openFile(tsrs, filename, text, entry);
          file = opened === null ? null : createFile(tsrs, opened.program, opened.sourceFile, sourceCode);
        }
        return file === null ? null : work(file);
      } catch (error) {
        // Later rules on this file take the untyped path.
        file = null;
        return requestFailed(tsrs, filename, error);
      }
    },
  };
}

// Nearest tsconfig.json per directory, as `ts.findConfigFile` finds it.
const CONFIG_BY_DIR = new Map<string, string | null>();
function nearestConfig(dir: string): string | null {
  let config = CONFIG_BY_DIR.get(dir);
  if (config === undefined) {
    const candidate = join(dir, "tsconfig.json");
    const parent = dirname(dir);
    config = existsSync(candidate) ? candidate : parent === dir ? null : nearestConfig(parent);
    CONFIG_BY_DIR.set(dir, config);
  }
  return config;
}

interface ConfigEntry {
  readonly config: string;
  readonly options: TsrsCompilerOptions;
  readonly references: readonly { path: string }[] | undefined;
}

interface OpenedProject {
  readonly snapshot: TsrsSnapshot;
  readonly project: TsrsProject;
}

// Parsing a tsconfig is cheap; building its program waits until a file needs types (`openProject`).
const CONFIGS = new Map<string, ConfigEntry | null>();
function configEntry(api: TsrsApi, config: string): ConfigEntry | null {
  let entry = CONFIGS.get(config);
  if (entry === undefined) {
    let parsed: TsrsParsedCommandLine | null;
    try {
      parsed = api.parseConfigFile(config);
    } catch {
      // An unreadable config gives no project.
      parsed = null;
    }
    const configDir = dirname(config);
    entry = parsed === null ? null : {
      config,
      options: parsed.options,
      references: parsed.raw?.references?.map((reference) => ({ ...reference, path: join(configDir, reference.path) })),
    };
    CONFIGS.set(config, entry);
  }
  return entry;
}

function openFile(tsrs: TsrsModules, filename: string, text: string, entry: ConfigEntry | null): { program: TsrsProgram; sourceFile: TsrsSourceFile } | null {
  const opened = entry === null ? null : openProject(tsrs.api, entry);
  const inProject = opened?.project.program.getSourceFile(filename);
  if (opened && inProject?.text === text) return { program: opened.project.program, sourceFile: inProject };
  if (inProject === undefined && existsSync(filename)) {
    const program = diskProgram(tsrs.api, filename, entry, opened);
    const sourceFile = program?.getSourceFile(filename);
    if (program !== undefined && sourceFile?.text === text) return { program, sourceFile };
  }
  // Text not on disk, or different from it: a one-file program over an overlay.
  const program = syntheticProgram(tsrs.api, opened?.snapshot, {
    fileSystem: { kind: "layer", files: { [filename]: text } },
    createPrograms: [{ rootFiles: [filename], compilerOptions: { ...(entry?.options ?? NO_PROJECT_OPTIONS), noEmit: true } }],
  });
  const sourceFile = program?.getSourceFile(filename);
  return program !== undefined && sourceFile?.text === text ? { program, sourceFile } : null;
}

// Each project's snapshot, opened on first use; null when tsrs has no project for the config.
// Projects open into one chain of snapshots, so a project reuses the files earlier ones parsed.
const OPENED = new Map<ConfigEntry, OpenedProject | null>();
let projectSnapshot: TsrsSnapshot | null = null;
function openProject(api: TsrsApi, entry: ConfigEntry): OpenedProject | null {
  let opened = OPENED.get(entry);
  if (opened === undefined) {
    const params = { openProjects: [entry.config] };
    const snapshot = projectSnapshot === null ? api.createSnapshot(params) : projectSnapshot.update(params);
    projectSnapshot = snapshot;
    const project = snapshot.getConfiguredProject(entry.config);
    opened = project === undefined ? null : { snapshot, project };
    OPENED.set(entry, opened);
  }
  return opened;
}

// A snapshot update costs more than the one-file program it creates, so the first
// file of a directory outside its project creates the one-file programs of its
// siblings in the same update, and they take theirs when Oxlint reaches them.
// Untaken programs are capped; past the cap a file gets its program alone.
const DISK_BATCH = 64;
const DISK_UNTAKEN = 256;
const SCRIPT_EXTENSION = /\.[cm]?([jt])sx?$/u;
interface DiskBatch {
  readonly snapshot: TsrsSnapshot;
  untaken: number;
}
interface DiskProgram {
  readonly program: TsrsProgram | undefined;
  readonly batch: DiskBatch;
}
const DISK_PROGRAMS = new Map<string, DiskProgram>();
const DISK_TAKEN = new Set<string>();
let diskUntaken = 0;
// A batch whose programs are all taken; disposed on the next request, after the file using its last program.
let retiredBatch: DiskBatch | null = null;

function diskProgram(api: TsrsApi, filename: string, entry: ConfigEntry | null, opened: OpenedProject | null): TsrsProgram | undefined {
  retiredBatch?.snapshot.dispose();
  retiredBatch = null;
  const { program, batch } = DISK_PROGRAMS.get(filename) ?? createDiskBatch(api, filename, entry, opened);
  DISK_PROGRAMS.delete(filename);
  DISK_TAKEN.add(filename);
  diskUntaken--;
  if (--batch.untaken === 0) retiredBatch = batch;
  return program;
}

function createDiskBatch(api: TsrsApi, filename: string, entry: ConfigEntry | null, opened: OpenedProject | null): DiskProgram {
  const size = Math.max(1, Math.min(DISK_BATCH, DISK_UNTAKEN - diskUntaken));
  const files = [filename, ...siblings(filename)].slice(0, size);
  const references = opened ? entry?.references : undefined;
  const compilerOptions = defaultOptions(entry);
  const params: SnapshotParams = {
    createPrograms: files.map((file) => references === undefined
      ? { rootFiles: [file], compilerOptions }
      : { rootFiles: [file], compilerOptions, options: { projectReferences: references } }),
  };
  const snapshot = opened === null ? api.createSnapshot(params) : opened.snapshot.update(params);
  const batch: DiskBatch = { snapshot, untaken: files.length };
  diskUntaken += files.length;
  const programs = snapshot.operation.createdPrograms ?? [];
  for (const [i, file] of files.entries()) DISK_PROGRAMS.set(file, { program: programs[i], batch });
  return { program: programs[0], batch };
}

// Files beside this one of the same language (TypeScript or JavaScript) without a program yet.
function siblings(filename: string): string[] {
  const dir = dirname(filename);
  const language = SCRIPT_EXTENSION.exec(filename)?.[1];
  if (language === undefined) return [];
  return readdirSync(dir)
    .filter((name) => SCRIPT_EXTENSION.exec(name)?.[1] === language)
    .map((name) => join(dir, name))
    .filter((file) => file !== filename && !DISK_PROGRAMS.has(file) && !DISK_TAKEN.has(file));
}

// The last overlay program's snapshot; replaced (and disposed) by the next one.
let syntheticSnapshot: TsrsSnapshot | null = null;
function syntheticProgram(api: TsrsApi, base: TsrsSnapshot | undefined, params: SnapshotParams): TsrsProgram | undefined {
  const snapshot = base === undefined ? api.createSnapshot(params) : base.update(params);
  syntheticSnapshot?.dispose();
  syntheticSnapshot = snapshot;
  return snapshot.operation.createdPrograms?.[0];
}

// Options for a file outside its project: the project's, without emit or build settings.
function defaultOptions(entry: ConfigEntry | null): TsrsCompilerOptions {
  const options: Record<string, unknown> = { ...(entry?.options ?? NO_PROJECT_OPTIONS) };
  delete options["rootDir"];
  delete options["outDir"];
  delete options["tsBuildInfoFile"];
  return { ...options, noEmit: true, composite: false, declaration: false, declarationMap: false, incremental: false };
}

function modifierStarts(tsrs: TsrsModules, source: TsrsSourceFile, node: TsrsNode): readonly number[] | null {
  const modifiers = node.modifiers;
  if (modifiers === undefined || modifiers.length === 0) return null;
  const starts = modifiers.map((modifier) => modifier.getStart(source));
  starts.push(tsrs.ast.skipTrivia(source.text, Math.max(...modifiers.map((modifier) => modifier.end))));
  return starts;
}

// ESTree ranges leave out leading modifiers and decorators that TypeScript ranges
// include, so a match is the same range, or a start after leading modifiers.
function tsNodeAt(tsrs: TsrsModules, source: TsrsSourceFile, start: number, end: number): TsrsNode | undefined {
  let exact: TsrsNode | undefined;
  let modified: TsrsNode | undefined;
  const visit = (node: TsrsNode): undefined => {
    if (node.getEnd() === end) {
      const nodeStart = node.getStart(source);
      if (nodeStart === start) exact = node;
      else if (nodeStart < start && modifierStarts(tsrs, source, node)?.includes(start)) modified = node;
    }
    node.forEachChild((child) => {
      if (child.pos <= start && end <= child.end) visit(child);
      return undefined;
    });
    return undefined;
  };
  visit(source);
  return exact ?? modified;
}

function createFile(tsrs: TsrsModules, program: TsrsProgram, sourceFile: TsrsSourceFile, sourceCode: SourceCode): TsrsFile {
  const checker = program.getProject().checker;
  const toTs = new Map<Node, TsrsNode | undefined>();
  const tsNode = (node: Node): TsrsNode | undefined => {
    if (!toTs.has(node)) {
      // A TSTypeAnnotation's range includes the colon; TypeScript has only the type node.
      const target = node.type === "TSTypeAnnotation" ? (node as { typeAnnotation: Node }).typeAnnotation : node;
      toTs.set(node, node.type === "Program" ? sourceFile : tsNodeAt(tsrs, sourceFile, target.range[0], target.range[1]));
    }
    return toTs.get(node);
  };
  // Query only the nodes that map, then spread the answers back over the input order.
  function query<T>(nodes: readonly Node[], request: (found: TsrsNode[]) => readonly T[]): (T | undefined)[] {
    const mapped = nodes.map(tsNode);
    const found = mapped.filter((node) => node !== undefined);
    const answers = found.length === 0 ? [] : request(found);
    let next = 0;
    return mapped.map((node) => node === undefined ? undefined : answers[next++]);
  }
  return {
    ast: tsrs.ast,
    sync: tsrs.sync,
    flags: tsrs.sync.TypeFlags,
    checker,
    program,
    sourceFile,
    tsNode,
    outerTsNode(node) {
      let found = tsNode(node);
      for (let parent = found?.parent; found !== undefined && parent !== undefined &&
        parent.end === found.end && parent.getStart(sourceFile) === found.getStart(sourceFile); parent = found.parent) found = parent;
      return found;
    },
    esTreeNode(node) {
      if (node === sourceFile) return sourceCode.ast;
      const start = node.getStart(sourceFile);
      const end = node.getEnd();
      let found = sourceCode.getNodeByRangeIndex(start);
      while (found !== null && !(found.range[0] === start && found.range[1] === end)) found = parentOf(found);
      return found ?? undefined;
    },
    typesOf: (nodes) => query(nodes, (found) => checker.getTypeAtLocation(found)),
    symbolsOf: (nodes) => query(nodes, (found) => checker.getSymbolAtLocation(found)),
    // tsrs caches source file metadata on the Program, so each path costs one request per program.
    isDefaultLibrarySymbol(symbol) {
      const declarations = symbol?.declarations ?? [];
      return declarations.length > 0 &&
        declarations.every(({ path }) => program.getSourceFileMetadataByPath(path)?.isDefaultLibrary === true);
    },
    batch: <T>(requests: readonly TsrsRequest<T>[]) => requests.length === 0 ? [] : tsrs.api.batch(...requests) as T[],
  };
}

const NULL_TOLERANT = new WeakMap<object, object>();

/**
 * `file.ast` with every `is*` guard returning false for a missing node, as TypeScript code reads
 * optional children; for helpers that walk remote nodes through loosely typed fields.
 */
export function nullTolerantAst<Ast>(file: TsrsFile): Ast {
  let wrapped = NULL_TOLERANT.get(file.ast);
  if (wrapped === undefined) {
    const guards: Record<string, unknown> = { ...file.ast };
    for (const [key, value] of Object.entries(file.ast)) {
      if (key.startsWith("is") && typeof value === "function") {
        const guard = value as (node: unknown) => boolean;
        guards[key] = (node: unknown) => node !== undefined && node !== null && guard(node);
      }
    }
    wrapped = guards;
    NULL_TOLERANT.set(file.ast, wrapped);
  }
  return wrapped as Ast;
}
