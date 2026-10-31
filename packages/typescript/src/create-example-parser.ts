import { basename, dirname, resolve } from "node:path";

import * as parser from "@typescript-eslint/parser";
import ts from "typescript";

const WATCH_DEFAULTS: ts.CompilerOptions = {
  noEmit: true, noUnusedLocals: true, noUnusedParameters: true,
  allowJs: true, allowNonTsExtensions: true, checkJs: true,
};
const MAX_LIBRARY_FILES = 256;
const MAX_LIBRARY_BYTES = 16 * 1024 * 1024;

interface LibraryEntry {
  readonly text: string;
  readonly source: ts.SourceFile;
}

interface ExampleParserStatistics {
  readonly programs: number;
  readonly libraryAcquires: number;
  readonly libraryHits: number;
  readonly nativeFallbacks: number;
  readonly libraryFiles: number;
  readonly libraryBytes: number;
}

interface ExampleParser extends Pick<typeof parser, "meta"> {
  parseForESLint(code: string, options?: parser.ParserOptions): ReturnType<typeof parser.parseForESLint>;
  clear(): void;
  statistics(): ExampleParserStatistics;
}

/** Share only unchanged native library ASTs; every lint pass owns a fresh Program. */
export function createExampleParser(): ExampleParser {
  const libraryRoot = ts.sys.realpath?.(dirname(ts.getDefaultLibFilePath({})));
  const cache = new Map<string, LibraryEntry>();
  const registries = new Map<ts.JSDocParsingMode, ts.DocumentRegistry>();
  const counts = { programs: 0, libraryAcquires: 0, libraryHits: 0, nativeFallbacks: 0 };
  let bytes = 0;

  return {
    meta: parser.meta,
    clear(): void {
      cache.clear();
      registries.clear();
      bytes = 0;
    },
    statistics() {
      return { ...counts, libraryFiles: cache.size, libraryBytes: bytes };
    },
    parseForESLint(code: string, options?: parser.ParserOptions) {
      const fallback = () => {
        counts.nativeFallbacks += 1;
        return parser.parseForESLint(code, options);
      };
      if (!Object.hasOwn(ts, "JSDocParsingMode")) return fallback();
      if (typeof options?.project !== "string" || typeof options.filePath !== "string" ||
          options.programs != null || options.projectService || options.extraFileExtensions?.length || options.debugLevel) {
        return fallback();
      }
      const config = resolve(options.tsconfigRootDir ?? process.cwd(), options.project);
      let unrecoverable = false;
      const parsed = ts.getParsedCommandLineOfConfigFile(config, WATCH_DEFAULTS, {
        ...ts.sys,
        onUnRecoverableConfigFileDiagnostic() { unrecoverable = true; },
      });
      if (unrecoverable || parsed === undefined || parsed.errors.length > 0 || parsed.projectReferences?.length) {
        return fallback();
      }
      const filename = resolve(options.filePath);
      const host = ts.createCompilerHost(parsed.options, true);
      const canonical = (path: string) => host.getCanonicalFileName(resolve(path));
      if (!parsed.fileNames.some((path) => canonical(path) === canonical(filename))) return fallback();
      const mode = options.jsDocParsingMode === "none" ? ts.JSDocParsingMode.ParseNone
        : options.jsDocParsingMode === "type-info" ? ts.JSDocParsingMode.ParseForTypeInfo
          : ts.JSDocParsingMode.ParseAll;
      host.jsDocParsingMode = mode;
      let registry = registries.get(mode);
      if (registry === undefined) {
        registry = ts.createDocumentRegistry(ts.sys.useCaseSensitiveFileNames, process.cwd(), mode);
        registries.set(mode, registry);
      }
      const settingsKey = registry.getKeyForCompilationSettings(parsed.options);
      const read = host.readFile.bind(host);
      host.readFile = (path) => canonical(path) === canonical(filename) ? code : read(path);
      const original = host.getSourceFile.bind(host);
      host.getSourceFile = (path, language, onError, fresh) => {
        if (fresh || libraryRoot === undefined || host.realpath === undefined ||
            canonical(path) === canonical(filename) ||
            dirname(resolve(path)) !== libraryRoot || !/^lib(?:\..+)?\.d\.ts$/u.test(basename(path)) ||
            !host.fileExists(path)) {
          return original(path, language, onError, fresh);
        }
        try {
          if (host.realpath(path) !== resolve(path)) return original(path, language, onError, fresh);
        } catch {
          return original(path, language, onError, fresh);
        }
        const text = read(path);
        if (text === undefined) return original(path, language, onError, fresh);
        const version = typeof language === "number" ? language : language.languageVersion;
        const format = typeof language === "number" ? undefined : language.impliedNodeFormat;
        const key = JSON.stringify([path, settingsKey, version, format, mode]);
        const previous = cache.get(key);
        if (previous?.text === text) {
          counts.libraryHits += 1;
          return previous.source;
        }
        const size = Buffer.byteLength(text);
        if (previous !== undefined || cache.size >= MAX_LIBRARY_FILES || bytes + size > MAX_LIBRARY_BYTES) {
          return original(path, language, onError, fresh);
        }
        const source = registry.acquireDocument(path, parsed.options, ts.ScriptSnapshot.fromString(text),
          "unchanged-native-library", ts.ScriptKind.TS, language);
        cache.set(key, { text, source });
        bytes += size;
        counts.libraryAcquires += 1;
        return source;
      };
      const program = ts.createProgram(parsed.fileNames, parsed.options, host);
      counts.programs += 1;
      if (program.getSourceFile(filename)?.text !== code) {
        throw new Error("The example compiler did not load the current lint source.");
      }
      return parser.parseForESLint(code, {
        ...options, project: false, projectService: false, programs: [program],
        disallowAutomaticSingleRunInference: true,
      });
    },
  };
}
